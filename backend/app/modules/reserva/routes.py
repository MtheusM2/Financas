from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.calc_graph import touch
from app.core.db import get_db, local_today
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.contas.service import Scope
from app.modules.objetivos import service
from app.modules.objetivos.models import Goal
from app.modules.orcamento.service import essential_monthly

router = APIRouter(prefix="/api/reserva", tags=["reserva"])


class ReserveIn(BaseModel):
    target_months: int = Field(default=6, gt=0, le=60)
    initial_cents: int = Field(default=0, ge=0)
    monthly_cents: int | None = Field(default=None, gt=0)
    # Sem historico ainda: permite informar a meta diretamente.
    manual_target_cents: int | None = Field(default=None, gt=0)


class ContributeIn(BaseModel):
    date: date
    amount_cents: int = Field(gt=0)
    account_id: int


def reserve_of(db: Session) -> Goal | None:
    return db.scalar(select(Goal).where(Goal.is_reserve.is_(True)))


def serialize(db: Session, goal: Goal, viewer_id: int) -> dict:
    essential = essential_monthly(db, viewer_id, Scope("casal"))
    return {
        **service.serialize(db, goal, viewer_id),
        "meses_meta": goal.target_months, "gasto_essencial_mensal": essential,
        "meses_cobertos": round(service.saved_of(db, goal, viewer_id)[0] / essential, 1) if essential else None,
    }


@router.get("")
def get_reserve(db: Session = Depends(get_db), user=Depends(current_user)):
    goal = reserve_of(db)
    return serialize(db, goal, user.id) if goal else None


@router.put("")
def save_reserve(data: ReserveIn, db: Session = Depends(get_db), user=Depends(current_user)):
    essential = essential_monthly(db, user.id, Scope("casal"))
    target = data.manual_target_cents or data.target_months * essential
    if target <= 0:
        raise HTTPException(422, "Ainda não há gastos essenciais registrados. Informe a meta em reais.")
    goal = reserve_of(db)
    if goal is None:
        goal = Goal(name="Reserva de emergência", owner_user_id=None, start_date=local_today(), is_reserve=True,
                    active=True, hidden=False, shares={}, target_cents=target)
        db.add(goal)
    goal.target_months, goal.initial_cents, goal.monthly_cents = data.target_months, data.initial_cents, data.monthly_cents
    goal.target_cents = target
    db.flush()
    record(db, user.id, "alterou", "reserva", goal.id)
    touch(db, "objetivos")
    db.commit()
    return serialize(db, goal, user.id)


@router.post("/aportar")
def contribute(data: ContributeIn, db: Session = Depends(get_db), user=Depends(current_user)):
    goal = reserve_of(db)
    if goal is None:
        raise HTTPException(404, "Configure a reserva primeiro.")
    service.contribute(db, goal, user, data.date, data.amount_cents, data.account_id)
    record(db, user.id, "aportou", "reserva", goal.id)
    touch(db, "objetivos")
    db.commit()
    return serialize(db, goal, user.id)
