import calendar
from datetime import date

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.calc_graph import touch
from app.core.db import now, local_today
from app.modules.contas.models import Account
from app.modules.contas.service import Scope, hidden_account_ids, scope_clause
from app.modules.lancamentos.models import OUTFLOW_KINDS, MonthlyTotal, RecurringRule, Transaction
from app.modules.relatorios.models import MonthClosing


DUE_WINDOW_DAYS = 7


def visible_rows(model, viewer_id: int):
    """Vale para Transaction e MonthlyTotal: esconde itens e contas ocultos por outra pessoa."""
    return and_(
        (model.hidden.is_(False)) | (model.owner_user_id == viewer_id),
        model.account_id.not_in(hidden_account_ids(viewer_id)),
    )


def tx_filter(viewer_id: int, scope: Scope):
    return and_(visible_rows(Transaction, viewer_id), scope_clause(Transaction, scope))


def check_account(db: Session, account_id: int, owner_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.archived or account.owner_user_id not in (None, owner_id):
        raise HTTPException(422, "Conta inválida para esta pessoa.")
    return account


def month_key(day: date) -> int:
    return day.year * 100 + day.month


def split_month(key: int) -> tuple[int, int]:
    return key // 100, key % 100


def next_month(key: int) -> int:
    year, month = split_month(key)
    return (year + 1) * 100 + 1 if month == 12 else key + 1


def due_situation(days: int) -> str:
    return "atrasada" if days < 0 else "vence_logo" if days <= DUE_WINDOW_DAYS else "em_dia"


def add_months(key: int, count: int) -> int:
    year, month = split_month(key)
    total = year * 12 + month - 1 + count
    return total // 12 * 100 + total % 12 + 1


def clamp_day(key: int, day: int) -> date:
    year, month = split_month(key)
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def rebuild_month(db: Session, key: int) -> None:
    year, month = split_month(key)
    db.execute(text("select pg_advisory_xact_lock(:k)"), {"k": key})
    db.execute(delete(MonthlyTotal).where(MonthlyTotal.year == year, MonthlyTotal.month == month))
    db.flush()
    first = date(year, month, 1)
    last = clamp_day(key, 31)
    rows = db.execute(
        select(Transaction.account_id, Transaction.owner_user_id, Transaction.kind, Transaction.hidden,
               func.sum(Transaction.amount_cents))
        .where(Transaction.date >= first, Transaction.date <= last, Transaction.settled.is_(True))
        .group_by(Transaction.account_id, Transaction.owner_user_id, Transaction.kind, Transaction.hidden)
    )
    db.add_all(
        MonthlyTotal(year=year, month=month, account_id=a, owner_user_id=o, kind=k, hidden=h, total_cents=t)
        for a, o, k, h, t in rows
    )


def after_change(db: Session, days: list[date]) -> None:
    """Chame depois de qualquer escrita em lancamentos, antes do commit."""
    db.flush()
    for key in sorted({month_key(d) for d in days}):
        rebuild_month(db, key)
        year, month = split_month(key)
        closings = db.scalars(select(MonthClosing).where(
            MonthClosing.year == year, MonthClosing.month == month, MonthClosing.status == "fechado"
        ))
        for closing in closings:
            closing.status, closing.reopened_at = "reaberto", now()
    touch(db, "lancamentos")


def add_transaction(db: Session, user_id: int, *, day: date, account_id: int, owner_id: int, kind: str,
                    amount_cents: int, description: str = "", category_id: int | None = None,
                    hidden: bool = False, **links) -> Transaction:
    """Ponto unico de criacao, usado tambem por pagamentos e aportes dos outros modulos."""
    check_account(db, account_id, owner_id)
    tx = Transaction(
        date=day, account_id=account_id, owner_user_id=owner_id, kind=kind, amount_cents=amount_cents,
        description=description, category_id=category_id, hidden=hidden, created_by=user_id, edited=False, **links,
    )
    db.add(tx)
    after_change(db, [day])
    return tx


def materialize_rule(db: Session, rule: RecurringRule, until: int | None = None) -> None:
    until = until or month_key(local_today())
    if rule.end_month:
        until = min(until, rule.end_month)
    key = next_month(rule.last_generated_month) if rule.last_generated_month else rule.start_month
    days = []
    while rule.active and key <= until:
        day = clamp_day(key, rule.day_of_month)
        db.execute(insert(Transaction).values(
            date=day, account_id=rule.account_id, owner_user_id=rule.owner_user_id, kind=rule.kind,
            category_id=rule.category_id, description=rule.description, amount_cents=rule.amount_cents,
            hidden=rule.hidden, created_by=rule.owner_user_id, created_at=now(), rule_id=rule.id,
            occurrence_month=key, edited=False, settled=day <= local_today(),
        ).on_conflict_do_nothing(index_elements=["rule_id", "occurrence_month"]))
        days.append(day)
        rule.last_generated_month = key
        key = next_month(key)
    if days:
        after_change(db, days)


def settle_due_recurring(db: Session) -> None:
    """Ocorrencia recorrente nao editada vira realizada quando a data chega."""
    rows = db.scalars(select(Transaction).where(
        Transaction.rule_id.is_not(None), Transaction.settled.is_(False),
        Transaction.edited.is_(False), Transaction.date <= local_today(),
    )).all()
    for tx in rows:
        tx.settled = True
    if rows:
        after_change(db, [tx.date for tx in rows])


def materialize_all(db: Session) -> None:
    for rule in db.scalars(select(RecurringRule).where(RecurringRule.active.is_(True))).all():
        materialize_rule(db, rule)
    settle_due_recurring(db)
    db.commit()


def totals_by_kind(db: Session, viewer_id: int, scope: Scope, year: int, month: int) -> dict[str, int]:
    rows = db.execute(
        select(MonthlyTotal.kind, func.sum(MonthlyTotal.total_cents))
        .where(MonthlyTotal.year == year, MonthlyTotal.month == month,
               visible_rows(MonthlyTotal, viewer_id), scope_clause(MonthlyTotal, scope))
        .group_by(MonthlyTotal.kind)
    )
    return {k: int(t) for k, t in rows}


def summarize(totals: dict[str, int]) -> dict:
    income = totals.get("renda", 0)
    outflow = sum(totals.get(k, 0) for k in OUTFLOW_KINDS)
    return {
        "renda": income,
        **{k: totals.get(k, 0) for k in OUTFLOW_KINDS},
        "saidas": outflow,
        "restante": income - outflow,
    }


def balance_before(db: Session, viewer_id: int, scope: Scope, year: int, month: int) -> int:
    """Soma de tudo o que entrou e saiu antes do mes, sem o saldo inicial."""
    rows = db.execute(
        select(MonthlyTotal.kind, func.sum(MonthlyTotal.total_cents))
        .where((MonthlyTotal.year * 100 + MonthlyTotal.month) < year * 100 + month,
               visible_rows(MonthlyTotal, viewer_id), scope_clause(MonthlyTotal, scope))
        .group_by(MonthlyTotal.kind)
    )
    return sum(int(t) if k == "renda" else -int(t) for k, t in rows)


def balance_until(db: Session, viewer_id: int, scope: Scope, day: date) -> int:
    """Tudo o que ja entrou e saiu ate o dia, inclusive, sem o saldo inicial."""
    rows = db.execute(
        select(Transaction.kind, func.sum(Transaction.amount_cents))
        .where(Transaction.date <= day, Transaction.settled.is_(True), tx_filter(viewer_id, scope))
        .group_by(Transaction.kind)
    )
    return sum(int(t) if k == "renda" else -int(t) for k, t in rows)


def daily_flow(db: Session, viewer_id: int, scope: Scope, year: int, month: int, opening: int) -> list[dict]:
    last_day = calendar.monthrange(year, month)[1]
    rows = db.execute(
        select(Transaction.date, Transaction.kind, func.sum(Transaction.amount_cents))
        .where(Transaction.date >= date(year, month, 1), Transaction.date <= date(year, month, last_day),
               Transaction.settled.is_(True), tx_filter(viewer_id, scope))
        .group_by(Transaction.date, Transaction.kind)
    ).all()
    by_day: dict[int, dict] = {d: {"entradas": 0, "saidas": 0, "fora_escopo": 0} for d in range(1, last_day + 1)}
    for day, kind, total in rows:
        slot = by_day[day.day]
        if kind == "renda":
            slot["entradas"] += int(total)
        else:
            slot["saidas"] += int(total)
            if kind == "fora_escopo":
                slot["fora_escopo"] += int(total)
    balance = opening
    result = []
    for day in range(1, last_day + 1):
        balance += by_day[day]["entradas"] - by_day[day]["saidas"]
        result.append({"dia": day, **by_day[day], "saldo": balance})
    return result
