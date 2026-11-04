from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.calc_graph import cached
from app.core.db import get_db
from app.modules.autenticacao.deps import current_user
from app.modules.autenticacao.models import User
from app.modules.contas.service import Scope, opening_balance, parse_scope
from app.modules.lancamentos.models import MonthlyTotal, Transaction
from app.modules.lancamentos.service import (
    balance_before, daily_flow, summarize, totals_by_kind, tx_filter, visible_rows,
)

router = APIRouter(prefix="/api/painel", tags=["painel"])


def previous_months(year: int, month: int, count: int) -> list[tuple[int, int]]:
    result = []
    for _ in range(count):
        result.append((year, month))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(result))


def by_person(db: Session, viewer_id: int, scope: Scope, year: int, month: int) -> list[dict]:
    rows = db.execute(
        select(User.id, User.name, MonthlyTotal.kind, func.sum(MonthlyTotal.total_cents))
        .join(User, User.id == MonthlyTotal.owner_user_id)
        .where(MonthlyTotal.year == year, MonthlyTotal.month == month, visible_rows(MonthlyTotal, viewer_id))
        .group_by(User.id, User.name, MonthlyTotal.kind)
    )
    people: dict[int, dict] = {}
    for user_id, name, kind, total in rows:
        person = people.setdefault(user_id, {"id": user_id, "nome": name, "renda": 0, "saidas": 0, "fora_escopo": 0})
        if kind == "renda":
            person["renda"] += int(total)
        else:
            person["saidas"] += int(total)
            if kind == "fora_escopo":
                person["fora_escopo"] += int(total)
    return list(people.values())


@router.get("/resumo")
def summary(
    ano: int = Query(ge=2000, le=2999), mes: int = Query(ge=1, le=12), escopo: str = "casal",
    db: Session = Depends(get_db), user=Depends(current_user),
):
    """Leitura rapida do login: vem dos totais mensais prontos."""
    scope = parse_scope(escopo)
    evolution = []
    for year, month in previous_months(ano, mes, 12):
        item = summarize(totals_by_kind(db, user.id, scope, year, month))
        evolution.append({"ano": year, "mes": month, "renda": item["renda"], "saidas": item["saidas"], "restante": item["restante"]})
    opening = opening_balance(db, user.id, scope) + balance_before(db, user.id, scope, ano, mes)
    current = summarize(totals_by_kind(db, user.id, scope, ano, mes))
    paydays = db.execute(
        select(Transaction.date, User.name, Transaction.description, Transaction.amount_cents, Transaction.settled)
        .join(User, User.id == Transaction.owner_user_id)
        .where(func.extract("year", Transaction.date) == ano, func.extract("month", Transaction.date) == mes,
               Transaction.kind == "renda", tx_filter(user.id, scope))
        .order_by(Transaction.date)
    )
    return {
        "periodo": {"ano": ano, "mes": mes},
        "totais": current,
        "saldo_inicial": opening,
        "saldo_final": opening + current["restante"],
        "evolucao": evolution,
        "pessoas": by_person(db, user.id, scope, ano, mes),
        "recebimentos": [{"data": d, "pessoa": n, "descricao": t, "valor": v, "previsto": not s} for d, n, t, v, s in paydays],
    }


@router.get("/fluxo")
def flow(
    ano: int = Query(ge=2000, le=2999), mes: int = Query(ge=1, le=12), escopo: str = "casal",
    db: Session = Depends(get_db), user=Depends(current_user),
):
    """Calculo especifico: so roda quando o grafico diario e aberto."""
    scope = parse_scope(escopo)

    def compute():
        opening = opening_balance(db, user.id, scope) + balance_before(db, user.id, scope, ano, mes)
        return {"saldo_inicial": opening, "dias": daily_flow(db, user.id, scope, ano, mes, opening)}

    return cached(db, "fluxo", (user.id, scope.key, ano, mes), compute)
