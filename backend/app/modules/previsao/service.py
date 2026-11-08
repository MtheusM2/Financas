"""Previsao de saldo: parte do saldo real e soma o que ja se sabe que vem pela frente."""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import local_today
from app.core.visibility import visible_clause
from app.modules.contas.service import Scope, opening_balance
from app.modules.dividas.models import Debt
from app.modules.dividas.routes import occurrence, paid_count
from app.modules.financiamentos.models import Financing
from app.modules.financiamentos.routes import installment_due, installments_paid, schedule
from app.modules.investimentos.models import Investment
from app.modules.lancamentos.models import RecurringRule, Transaction
from app.modules.lancamentos.service import balance_until, clamp_day, month_key, next_month, split_month, tx_filter
from app.modules.objetivos.models import Goal
from app.modules.objetivos.service import planned_monthly
from app.modules.orcamento.service import _in_scope


@dataclass
class Event:
    day: date
    amount: int  # positivo entra, negativo sai
    label: str
    source: str


def _signed(kind: str, amount: int) -> int:
    return amount if kind == "renda" else -amount


def _months(start: int, end: int):
    key = start
    while key <= end:
        yield key
        key = next_month(key)


def collect_events(db: Session, viewer_id: int, scope: Scope, today: date, end_key: int, include_plans: bool) -> list[Event]:
    events: list[Event] = []
    current = month_key(today)
    pending = db.scalars(select(Transaction).where(Transaction.settled.is_(False), tx_filter(viewer_id, scope)))
    for tx in pending:
        # O que ja venceu e nao foi quitado pesa no saldo de hoje.
        events.append(Event(max(tx.date, today), _signed(tx.kind, tx.amount_cents), tx.description or tx.kind, "previsto"))
    # Lancado como pago, mas com data futura: entra no dia dele, e nao no saldo de hoje.
    end = clamp_day(end_key, 31)
    future = db.scalars(select(Transaction).where(
        Transaction.settled.is_(True), Transaction.date > today, Transaction.date <= end, tx_filter(viewer_id, scope)))
    for tx in future:
        events.append(Event(tx.date, _signed(tx.kind, tx.amount_cents), tx.description or tx.kind, "lancado"))

    rules = db.scalars(select(RecurringRule).where(RecurringRule.active.is_(True), visible_clause(RecurringRule, viewer_id)))
    for rule in rules:
        if not _in_scope(rule, scope):
            continue
        start = next_month(rule.last_generated_month) if rule.last_generated_month else rule.start_month
        for key in _months(max(start, current), min(end_key, rule.end_month or end_key)):
            events.append(Event(clamp_day(key, rule.day_of_month), _signed(rule.kind, rule.amount_cents), rule.description or rule.kind, "recorrente"))

    debts = db.scalars(select(Debt).where(Debt.active.is_(True), visible_clause(Debt, viewer_id)))
    for debt in debts:
        if not _in_scope(debt, scope):
            continue
        paid, _ = paid_count(db, debt, viewer_id)
        # Comeca no vencimento mais antigo em aberto: o que atrasou pesa no saldo de hoje.
        index = paid - debt.paid_before
        while debt.total_installments is None or debt.paid_before + index < debt.total_installments:
            due = occurrence(debt, index)
            if month_key(due) > end_key:
                break
            events.append(Event(max(due, today), -debt.installment_cents, debt.name, "divida"))
            index += 1

    financings = db.scalars(select(Financing).where(Financing.active.is_(True), visible_clause(Financing, viewer_id)))
    for item in financings:
        if not _in_scope(item, scope):
            continue
        rows = schedule(db, item)
        for index in range(installments_paid(db, item, viewer_id), len(rows)):
            due = installment_due(item, index)
            if month_key(due) > end_key:
                break
            events.append(Event(max(due, today), -(rows[index].payment + rows[index].fee), item.name, "financiamento"))

    if include_plans:
        planned = 0
        for goal in db.scalars(select(Goal).where(Goal.active.is_(True), visible_clause(Goal, viewer_id))):
            if scope.kind == "casal" or goal.owner_user_id is None or _in_scope(goal, scope):
                planned += planned_monthly(goal)
        for inv in db.scalars(select(Investment).where(Investment.active.is_(True), visible_clause(Investment, viewer_id))):
            if _in_scope(inv, scope):
                planned += inv.monthly_plan_cents
        if planned:
            for key in _months(next_month(current), end_key):
                events.append(Event(clamp_day(key, 1), -planned, "Objetivos e investimentos planejados", "plano"))
    return sorted(events, key=lambda e: e.day)


def forecast(db: Session, viewer_id: int, scope: Scope, months: int = 6, include_plans: bool = False) -> dict:
    today = local_today()
    end_key = month_key(today)
    for _ in range(months - 1):
        end_key = next_month(end_key)
    start_balance = opening_balance(db, viewer_id, scope) + balance_until(db, viewer_id, scope, today)
    events = collect_events(db, viewer_id, scope, today, end_key, include_plans)

    buckets = {key: {"entradas": 0, "saidas": 0} for key in _months(month_key(today), end_key)}
    week_end = today + timedelta(days=7 * 8)
    weeks = {i: {"entradas": 0, "saidas": 0} for i in range(8)}
    balance, lowest, lowest_day, first_negative = start_balance, start_balance, today, None
    for event in events:
        balance += event.amount
        if balance < lowest:
            lowest, lowest_day = balance, event.day
        if balance < 0 and first_negative is None:
            first_negative = event.day
        bucket = buckets[month_key(event.day)]
        bucket["entradas" if event.amount > 0 else "saidas"] += abs(event.amount)
        if event.day < week_end:
            week = weeks[(event.day - today).days // 7]
            week["entradas" if event.amount > 0 else "saidas"] += abs(event.amount)

    running = start_balance
    month_rows = []
    for key, bucket in buckets.items():
        running += bucket["entradas"] - bucket["saidas"]
        year, month = split_month(key)
        month_rows.append({"periodo": f"{year}-{month:02d}", **bucket, "saldo": running})
    running = start_balance
    week_rows = []
    for index, bucket in weeks.items():
        running += bucket["entradas"] - bucket["saidas"]
        week_rows.append({"inicio": today + timedelta(days=7 * index), **bucket, "saldo": running})
    return {
        "saldo_atual": start_balance, "meses": month_rows, "semanas": week_rows,
        "menor_saldo": lowest, "menor_saldo_em": lowest_day, "fica_negativo_em": first_negative,
        "proximos": [{"data": e.day, "valor": e.amount, "descricao": e.label, "origem": e.source} for e in events[:30]],
    }
