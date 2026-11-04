from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import now
from app.modules.autenticacao.models import User
from app.modules.contas.service import Scope
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import add_transaction, month_key, tx_filter
from app.modules.objetivos.calc import months_to_reach, project, required_monthly, split_by_contributions
from app.modules.objetivos.models import Goal


def monthly_rate(goal: Goal) -> Decimal:
    return Decimal(goal.monthly_rate_percent or 0) / 100


def planned_monthly(goal: Goal, saved: int | None = None) -> int:
    """Aporte do plano: o informado ou o necessario para cumprir o prazo."""
    if goal.monthly_cents:
        return goal.monthly_cents
    if goal.term_months:
        return required_monthly(goal.target_cents, goal.initial_cents if saved is None else saved,
                                goal.term_months, monthly_rate(goal))
    return 0


def saved_of(db: Session, goal: Goal, viewer_id: int) -> tuple[int, dict[int, int]]:
    rows = db.execute(
        select(Transaction.owner_user_id, func.sum(Transaction.amount_cents))
        .where(Transaction.goal_id == goal.id, tx_filter(viewer_id, Scope("casal")))
        .group_by(Transaction.owner_user_id)
    )
    per_person = {uid: int(total) for uid, total in rows}
    return goal.initial_cents + sum(per_person.values()), per_person


def months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def add_months(start: date, months: int) -> str:
    index = start.year * 12 + start.month - 1 + months
    return f"{index // 12}-{index % 12 + 1:02d}"


def serialize(db: Session, goal: Goal, viewer_id: int) -> dict:
    saved, per_person = saved_of(db, goal, viewer_id)
    rate = monthly_rate(goal)
    plan = planned_monthly(goal)
    elapsed = max(months_between(goal.start_date, now().date()), 0)
    expected = goal.initial_cents
    if plan:
        points = project(goal.initial_cents, plan, elapsed, rate)
        expected = min(points[-1], goal.target_cents) if points else goal.initial_cents
    months = months_to_reach(goal.target_cents, goal.initial_cents, plan, rate)
    needed = required_monthly(goal.target_cents, goal.initial_cents, goal.term_months, rate) if goal.term_months else None
    gap = (goal.monthly_cents - needed) if goal.monthly_cents and needed is not None else None
    if saved >= goal.target_cents:
        status = "concluido"
    elif not plan:
        status = "sem_plano"
    elif saved >= expected:
        status = "no_ritmo"
    else:
        status = "atrasado"
    return {
        "id": goal.id, "nome": goal.name, "pessoa_id": goal.owner_user_id, "conjunto": goal.owner_user_id is None,
        "valor_objetivo": goal.target_cents, "valor_inicial": goal.initial_cents, "inicio": goal.start_date,
        "prazo": goal.term_months, "aporte_mensal": goal.monthly_cents, "juros_mes": str(goal.monthly_rate_percent),
        "aporte_necessario": needed, "aporte_plano": plan, "folga_mensal": gap,
        "meses_previstos": months, "data_prevista": add_months(goal.start_date, months) if months is not None else None,
        "guardado": saved, "percentual": round(saved / goal.target_cents * 100, 1) if goal.target_cents else 0,
        "esperado_ate_hoje": expected, "situacao": status,
        # A divisao vem dos aportes de cada um; nao e mais digitada.
        "divisao": split_by_contributions(per_person),
        "por_pessoa": per_person, "oculto": goal.hidden, "ativo": goal.active, "reserva": goal.is_reserve,
    }


def timeline(db: Session, goal: Goal, viewer_id: int) -> list[dict]:
    """Cronograma mes a mes: previsto contra realizado acumulado."""
    rate = monthly_rate(goal)
    plan = planned_monthly(goal)
    horizon = goal.term_months or months_to_reach(goal.target_cents, goal.initial_cents, plan, rate) or 12
    horizon = min(horizon, 600)
    planned = project(goal.initial_cents, plan, horizon, rate)
    rows = db.execute(
        select(Transaction.date, Transaction.amount_cents)
        .where(Transaction.goal_id == goal.id, tx_filter(viewer_id, Scope("casal")))
    ).all()
    by_month: dict[int, int] = {}
    for day, amount in rows:
        by_month[month_key(day)] = by_month.get(month_key(day), 0) + amount
    today = month_key(now().date())
    accumulated = goal.initial_cents
    result = []
    for i in range(horizon):
        label = add_months(goal.start_date, i)
        key = int(label.replace("-", ""))
        accumulated += by_month.get(key, 0)
        result.append({
            "mes": label, "previsto": planned[i],
            "realizado": accumulated if key <= today else None,
            "por_mes": plan,
        })
    return result


def contribute(db: Session, goal: Goal, user: User, day: date, amount: int, account_id: int):
    hidden = goal.hidden
    return add_transaction(
        db, user.id, day=day, account_id=account_id, owner_id=user.id, kind="guardado", amount_cents=amount,
        description=f"Aporte: {goal.name}", hidden=hidden, goal_id=goal.id,
    )
