from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import local_today
from app.core.visibility import visible_clause
from app.modules.contas.models import Category
from app.modules.contas.service import Scope
from app.modules.desafios.models import Challenge
from app.modules.dividas.models import Debt
from app.modules.dividas.routes import paid_count
from app.modules.financiamentos.models import Financing
from app.modules.financiamentos.routes import installments_paid, schedule
from app.modules.investimentos.models import Investment
from app.modules.lancamentos.models import RecurringRule, Transaction
from app.modules.lancamentos.service import summarize, totals_by_kind, tx_filter
from app.modules.objetivos.models import Goal
from app.modules.objetivos.service import planned_monthly

AVERAGE_MONTHS = 3


def _last_months(count: int) -> list[tuple[int, int]]:
    """Meses completos mais recentes, sem o mes atual."""
    today = local_today()
    year, month = today.year, today.month
    result = []
    for _ in range(count):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        result.append((year, month))
    return result


def averages(db: Session, viewer_id: int, scope: Scope) -> dict:
    """Media dos ultimos meses com dados; sem historico, usa o mes atual."""
    rows = [summarize(totals_by_kind(db, viewer_id, scope, y, m)) for y, m in _last_months(AVERAGE_MONTHS)]
    rows = [r for r in rows if r["renda"] or r["saidas"]]
    if not rows:
        today = local_today()
        rows = [summarize(totals_by_kind(db, viewer_id, scope, today.year, today.month))]
    count = len(rows)
    return {
        "renda_media": sum(r["renda"] for r in rows) // count,
        "saidas_media": sum(r["saidas"] for r in rows) // count,
        "sobra_media": sum(r["restante"] for r in rows) // count,
        "meses_considerados": count,
    }


def _in_scope(item, scope: Scope) -> bool:
    if scope.kind == "pessoa":
        return item.owner_user_id == scope.id
    if scope.kind == "conta":
        return getattr(item, "account_id", None) == scope.id
    return True


def obligations(db: Session, viewer_id: int, scope: Scope) -> dict:
    debts = 0
    for debt in db.scalars(select(Debt).where(visible_clause(Debt, viewer_id), Debt.active.is_(True))):
        if not _in_scope(debt, scope):
            continue
        paid, _ = paid_count(db, debt, viewer_id)
        if debt.total_installments is None or paid < debt.total_installments:
            debts += debt.installment_cents
    financings = 0
    for item in db.scalars(select(Financing).where(visible_clause(Financing, viewer_id), Financing.active.is_(True))):
        if not _in_scope(item, scope):
            continue
        rows = schedule(db, item)
        paid = installments_paid(db, item, viewer_id)
        if paid < len(rows):
            financings += rows[paid].payment + rows[paid].fee
    fixed = 0
    for rule in db.scalars(select(RecurringRule).where(
        visible_clause(RecurringRule, viewer_id), RecurringRule.active.is_(True),
        RecurringRule.kind.in_(("gasto", "divida")),
    )):
        if _in_scope(rule, scope):
            fixed += rule.amount_cents
    return {"dividas": debts, "financiamentos": financings, "gastos_fixos": fixed, "total": debts + financings + fixed}


def plans(db: Session, viewer_id: int, scope: Scope) -> dict:
    goals = 0
    for goal in db.scalars(select(Goal).where(visible_clause(Goal, viewer_id), Goal.active.is_(True))):
        if scope.kind == "casal" or goal.owner_user_id is None or _in_scope(goal, scope):
            goals += planned_monthly(goal)
    challenges = 0
    for item in db.scalars(select(Challenge).where(visible_clause(Challenge, viewer_id), Challenge.status == "ativo")):
        if scope.kind == "casal" or item.owner_user_id is None or _in_scope(item, scope):
            challenges += item.monthly_cents or 0
    investments = 0
    for inv in db.scalars(select(Investment).where(visible_clause(Investment, viewer_id), Investment.active.is_(True))):
        if _in_scope(inv, scope):
            investments += inv.monthly_plan_cents
    return {"objetivos": goals, "desafios": challenges, "investimentos": investments}


def snapshot(db: Session, viewer_id: int, scope: Scope) -> dict:
    avg = averages(db, viewer_id, scope)
    owed = obligations(db, viewer_id, scope)
    planned = plans(db, viewer_id, scope)
    available = avg["renda_media"] - owed["total"]
    free = available - planned["objetivos"] - planned["desafios"] - planned["investimentos"]
    return {**avg, "obrigacoes": owed, "planos": planned, "disponivel": available, "livre": free}


def essential_monthly(db: Session, viewer_id: int, scope: Scope) -> int:
    """Media mensal de gastos essenciais mais dividas, base da reserva."""
    total = 0
    months = _last_months(AVERAGE_MONTHS)
    used = 0
    for year, month in months:
        first = f"{year}-{month:02d}"
        amount = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0))
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(func.to_char(Transaction.date, "YYYY-MM") == first, tx_filter(viewer_id, scope),
                   (Category.essential.is_(True) & (Transaction.kind == "gasto")) | (Transaction.kind == "divida"))
        )
        if amount:
            total += int(amount)
            used += 1
    if used:
        return total // used
    return obligations(db, viewer_id, scope)["total"]
