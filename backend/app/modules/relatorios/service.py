from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import now
from app.core.visibility import visible_clause
from app.modules.auditoria.models import record
from app.modules.autenticacao.models import User
from app.modules.contas.service import Scope
from app.modules.desafios.models import Challenge
from app.modules.desafios.routes import progress as challenge_progress
from app.modules.dividas.models import Debt
from app.modules.dividas.routes import paid_count
from app.modules.financiamentos.models import Financing
from app.modules.financiamentos.routes import serialize as financing_info
from app.modules.investimentos.models import Investment
from app.modules.investimentos.routes import serialize as investment_info
from app.modules.lancamentos.models import MonthlyTotal
from app.modules.lancamentos.service import summarize, totals_by_kind, visible_rows
from app.modules.objetivos.models import Goal
from app.modules.objetivos.service import serialize as goal_info
from app.modules.relatorios.models import MonthClosing


def month_range(start: int, end: int) -> list[tuple[int, int]]:
    result = []
    year, month = start // 100, start % 100
    while year * 100 + month <= end:
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def period_totals(db: Session, viewer_id: int, scope: Scope, start: int, end: int) -> dict:
    totals: dict[str, int] = {}
    for year, month in month_range(start, end):
        for kind, value in totals_by_kind(db, viewer_id, scope, year, month).items():
            totals[kind] = totals.get(kind, 0) + value
    return summarize(totals)


def compare(a: dict, b: dict) -> dict:
    """Diferenca de b em relacao a a, em reais e em %."""
    return {
        key: {"a": a[key], "b": b[key], "diferenca": b[key] - a[key],
              "percentual": round((b[key] - a[key]) / abs(a[key]) * 100, 1) if a[key] else None}
        for key in a
    }


def progress_items(db: Session, viewer_id: int) -> list[dict]:
    """Foto do progresso de cada compromisso, gravada em cada fechamento."""
    items = []
    for goal in db.scalars(select(Goal).where(visible_clause(Goal, viewer_id), Goal.active.is_(True))):
        info = goal_info(db, goal, viewer_id)
        items.append({"tipo": "reserva" if goal.is_reserve else "objetivo", "id": goal.id, "nome": goal.name,
                      "atual": info["guardado"], "meta": goal.target_cents, "previsto": info["esperado_ate_hoje"]})
    for item in db.scalars(select(Challenge).where(visible_clause(Challenge, viewer_id), Challenge.status != "cancelado")):
        items.append({"tipo": "desafio", "id": item.id, "nome": item.name,
                      "atual": challenge_progress(db, item, viewer_id), "meta": item.target_cents, "previsto": None})
    for inv in db.scalars(select(Investment).where(visible_clause(Investment, viewer_id), Investment.active.is_(True))):
        info = investment_info(db, inv, viewer_id)
        items.append({"tipo": "investimento", "id": inv.id, "nome": inv.name, "atual": info["valor_atual"],
                      "meta": None, "previsto": info["aportado"]})
    for debt in db.scalars(select(Debt).where(visible_clause(Debt, viewer_id))):
        paid, _ = paid_count(db, debt, viewer_id)
        remaining = None if debt.total_installments is None else max(debt.total_installments - paid, 0)
        items.append({"tipo": "divida", "id": debt.id, "nome": debt.name, "atual": paid,
                      "meta": debt.total_installments, "previsto": None,
                      "saldo": None if remaining is None else remaining * debt.installment_cents})
    for fin in db.scalars(select(Financing).where(visible_clause(Financing, viewer_id))):
        info = financing_info(db, fin, viewer_id)
        items.append({"tipo": "financiamento", "id": fin.id, "nome": fin.name, "atual": info["parcelas_pagas"],
                      "meta": info["parcelas"], "previsto": None, "saldo": info["saldo_devedor"]})
    return items


def close_month(db: Session, year: int, month: int, actor_id: int | None = None) -> None:
    for user in db.scalars(select(User).where(User.email_verified.is_(True))).all():
        data = {
            "totais": summarize(totals_by_kind(db, user.id, Scope("casal"), year, month)),
            "progresso": progress_items(db, user.id),
        }
        row = db.scalar(select(MonthClosing).where(
            MonthClosing.year == year, MonthClosing.month == month, MonthClosing.viewer_id == user.id))
        if row is None:
            db.add(MonthClosing(year=year, month=month, viewer_id=user.id, status="fechado", snapshot=data, closed_at=now()))
        else:
            row.status, row.snapshot, row.closed_at = "fechado", data, now()
    record(db, actor_id, "fechou_mes", "fechamento", year * 100 + month)


def close_due_months(db: Session) -> None:
    """Fecha sozinho meses passados com dados e sem registro. Mes reaberto continua aberto."""
    today = now().date()
    current = today.year * 100 + today.month
    rows = db.execute(
        select(MonthlyTotal.year, MonthlyTotal.month).distinct().order_by(MonthlyTotal.year, MonthlyTotal.month)
    ).all()
    for year, month in rows:
        if year * 100 + month >= current:
            continue
        exists = db.scalar(select(func.count()).select_from(MonthClosing).where(
            MonthClosing.year == year, MonthClosing.month == month))
        if not exists:
            close_month(db, year, month)
    db.commit()


__all__ = ["close_due_months", "close_month", "compare", "month_range", "period_totals", "progress_items", "visible_rows"]
