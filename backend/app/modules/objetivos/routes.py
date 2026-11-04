from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.calc_graph import touch
from app.core.db import get_db
from app.core.visibility import apply_fields, get_visible, visible_clause
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.objetivos import service
from app.modules.objetivos.models import Goal

router = APIRouter(prefix="/api/objetivos", tags=["objetivos"])


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    joint: bool = True
    target_cents: int = Field(gt=0)
    initial_cents: int = Field(default=0, ge=0)
    start_date: date
    term_months: int | None = Field(default=None, gt=0, le=600)
    monthly_cents: int | None = Field(default=None, gt=0)
    monthly_rate_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)
    # Mantido so por compatibilidade: a divisao agora e calculada pelos aportes.
    shares: dict[str, float] = {}
    hidden: bool = False


class GoalPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    target_cents: int | None = Field(default=None, gt=0)
    term_months: int | None = Field(default=None, gt=0, le=600)
    monthly_cents: int | None = Field(default=None, gt=0)
    monthly_rate_percent: Decimal | None = Field(default=None, ge=0, le=100)
    shares: dict[str, float] | None = None
    hidden: bool | None = None
    active: bool | None = None


class ContributeIn(BaseModel):
    date: date
    amount_cents: int = Field(gt=0)
    account_id: int


def check_shares(shares: dict[str, float]) -> None:
    if shares and abs(sum(shares.values()) - 100) > 0.01:
        raise HTTPException(422, "A divisão precisa somar 100%.")


@router.get("")
def list_goals(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(Goal).where(visible_clause(Goal, user.id), Goal.is_reserve.is_(False)).order_by(Goal.id))
    return [service.serialize(db, g, user.id) for g in rows]


@router.post("")
def create_goal(data: GoalIn, db: Session = Depends(get_db), user=Depends(current_user)):
    if data.hidden and data.joint:
        raise HTTPException(422, "Objetivo em conjunto não pode ser oculto.")
    check_shares(data.shares)
    values = data.model_dump(exclude={"joint"})
    goal = Goal(**values, owner_user_id=None if data.joint else user.id, active=True, is_reserve=False)
    db.add(goal)
    db.flush()
    record(db, user.id, "criou", "objetivo", goal.id, private=goal.hidden)
    touch(db, "objetivos")
    db.commit()
    return service.serialize(db, goal, user.id)


@router.get("/{goal_id}")
def get_goal(goal_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    return service.serialize(db, get_visible(db, Goal, goal_id, user.id), user.id)


@router.patch("/{goal_id}")
def update_goal(goal_id: int, data: GoalPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    goal = get_visible(db, Goal, goal_id, user.id)
    values = data.model_dump(exclude_unset=True)
    if values.get("hidden") and goal.owner_user_id != user.id:
        raise HTTPException(422, "Só o dono de um objetivo individual pode ocultá-lo.")
    if values.get("shares"):
        check_shares(values["shares"])
    changes = apply_fields(goal, values)
    record(db, user.id, "alterou", "objetivo", goal.id, changes, private=goal.hidden)
    touch(db, "objetivos")
    db.commit()
    return service.serialize(db, goal, user.id)


@router.get("/{goal_id}/cronograma")
def schedule(goal_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    return service.timeline(db, get_visible(db, Goal, goal_id, user.id), user.id)


@router.post("/{goal_id}/aportar")
def contribute(goal_id: int, data: ContributeIn, db: Session = Depends(get_db), user=Depends(current_user)):
    goal = get_visible(db, Goal, goal_id, user.id)
    service.contribute(db, goal, user, data.date, data.amount_cents, data.account_id)
    record(db, user.id, "aportou", "objetivo", goal.id, private=goal.hidden)
    touch(db, "objetivos")
    db.commit()
    return service.serialize(db, goal, user.id)
