"""DRE pessoal e dados de apoio ao Imposto de Renda."""
from datetime import date

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.core.visibility import visible_clause
from app.modules.autenticacao.models import User
from app.modules.contas.models import Account, Category
from app.modules.contas.service import Scope, account_visible_clause
from app.modules.dividas.models import Debt
from app.modules.financiamentos.models import Financing
from app.modules.financiamentos.routes import schedule
from app.modules.investimentos.models import Investment
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import clamp_day, tx_filter

EXPENSE_KINDS = ("gasto", "fora_escopo", "divida", "lazer")
NOT_RESULT_KINDS = ("investimento", "guardado")
UNCATEGORIZED = "Sem categoria"


def _root_names(db: Session) -> dict[int, str]:
    rows = db.scalars(select(Category)).all()
    by_id = {c.id: c for c in rows}
    result = {}
    for category in rows:
        node = category
        while node.parent_id in by_id:
            node = by_id[node.parent_id]
        result[category.id] = node.name
    return result


def build_dre(db: Session, viewer_id: int, scope: Scope, start: int, end: int, regime: str) -> dict:
    """Competencia considera tudo o que pertence ao periodo, pago ou nao. Caixa, so o que foi pago."""
    first, last = date(start // 100, start % 100, 1), clamp_day(end, 31)
    reference = func.coalesce(Transaction.competence_date, Transaction.date) if regime == "competencia" else Transaction.date
    stmt = (
        select(Transaction.kind, Transaction.category_id, func.sum(Transaction.amount_cents))
        .where(reference >= first, reference <= last, tx_filter(viewer_id, scope))
        .group_by(Transaction.kind, Transaction.category_id)
    )
    if regime == "caixa":
        stmt = stmt.where(Transaction.settled.is_(True))
    roots = _root_names(db)
    income: dict[str, int] = {}
    expenses: dict[str, dict[str, int]] = {k: {} for k in EXPENSE_KINDS}
    outside: dict[str, int] = {k: 0 for k in NOT_RESULT_KINDS}
    for kind, category_id, total in db.execute(stmt):
        name = roots.get(category_id, UNCATEGORIZED)
        if kind == "renda":
            income[name] = income.get(name, 0) + int(total)
        elif kind in outside:
            outside[kind] += int(total)
        else:
            expenses[kind][name] = expenses[kind].get(name, 0) + int(total)
    total_income = sum(income.values())
    total_expenses = sum(sum(v.values()) for v in expenses.values())
    result = total_income - total_expenses
    return {
        "regime": regime,
        "receitas": {"total": total_income, "itens": [{"nome": k, "valor": v} for k, v in sorted(income.items())]},
        "despesas": {
            "total": total_expenses,
            "grupos": [{"tipo": kind, "total": sum(items.values()), "itens": [{"nome": k, "valor": v} for k, v in sorted(items.items())]}
                       for kind, items in expenses.items()],
        },
        "resultado": result,
        "margem": round(result / total_income * 100, 1) if total_income else None,
        "situacao": "sobra" if result > 0 else "falta" if result < 0 else "zerado",
        "fora_do_resultado": outside,
        "sobra_apos_guardar": result - sum(outside.values()),
    }


def tax_report(db: Session, viewer_id: int, year: int) -> dict:
    """Apoio para o IR. Os valores vem dos registros, nao substituem informes oficiais."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    casal = tx_filter(viewer_id, Scope("casal"))
    month = func.to_char(Transaction.date, literal_column("'YYYY-MM'"))
    income = db.execute(
        select(User.name, month, Transaction.category_id, func.sum(Transaction.amount_cents))
        .join(User, User.id == Transaction.owner_user_id)
        .where(Transaction.kind == "renda", Transaction.settled.is_(True), Transaction.date.between(start, end), casal)
        .group_by(User.name, month, Transaction.category_id)
        .order_by(User.name, month)
    ).all()
    roots = _root_names(db)

    accounts = []
    for account in db.scalars(select(Account).where(account_visible_clause(viewer_id))):
        rows = db.execute(
            select(Transaction.kind, func.sum(Transaction.amount_cents))
            .where(Transaction.account_id == account.id, Transaction.date <= end, Transaction.settled.is_(True), casal)
            .group_by(Transaction.kind)
        )
        balance = account.opening_balance_cents + sum(int(t) if k == "renda" else -int(t) for k, t in rows)
        accounts.append({"nome": account.name, "saldo": balance})

    investments = []
    for inv in db.scalars(select(Investment).where(visible_clause(Investment, viewer_id))):
        contributed = db.scalar(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.investment_id == inv.id, Transaction.date <= end, casal))
        investments.append({"nome": inv.name, "tipo": inv.category, "aportado_ate_fim_do_ano": inv.initial_contributed_cents + int(contributed)})

    debts = []
    for fin in db.scalars(select(Financing).where(visible_clause(Financing, viewer_id))):
        rows = schedule(db, fin)
        paid = fin.paid_before + (db.scalar(select(func.count()).where(
            Transaction.financing_id == fin.id, Transaction.installment_no.is_not(None), Transaction.date <= end, casal)) or 0)
        paid = min(paid, len(rows))
        balance = rows[paid - 1].balance if paid else fin.asset_value_cents - fin.down_payment_cents
        paid_in_year = db.scalar(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.financing_id == fin.id, Transaction.date.between(start, end), casal))
        debts.append({"nome": fin.name, "tipo": "Financiamento", "saldo_fim_do_ano": balance, "pago_no_ano": int(paid_in_year)})
    for debt in db.scalars(select(Debt).where(visible_clause(Debt, viewer_id))):
        count, paid_in_year = db.execute(select(func.count(), func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.debt_id == debt.id, Transaction.date <= end, casal)).one()
        in_year = db.scalar(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.debt_id == debt.id, Transaction.date.between(start, end), casal))
        left = None if debt.total_installments is None else max(debt.total_installments - debt.paid_before - count, 0)
        debts.append({"nome": debt.name, "tipo": "Dívida", "saldo_fim_do_ano": None if left is None else left * debt.installment_cents, "pago_no_ano": int(in_year)})

    return {
        "ano": year,
        "rendimentos": [{"pessoa": n, "mes": m, "categoria": roots.get(c, UNCATEGORIZED), "valor": int(v)} for n, m, c, v in income],
        "contas": accounts, "investimentos": investments, "dividas": debts,
    }
