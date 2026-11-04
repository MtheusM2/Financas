from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.calc_graph import touch
from app.core.db import get_db, now
from app.core.visibility import apply_fields, get_visible, visible_clause
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.contas.service import Scope
from app.modules.investimentos.models import Investment
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import add_transaction, check_account, tx_filter

router = APIRouter(prefix="/api/investimentos", tags=["investimentos"])


class InvestmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(default="", max_length=60)
    account_id: int
    initial_contributed_cents: int = Field(default=0, ge=0)
    current_value_cents: int | None = Field(default=None, ge=0)
    monthly_plan_cents: int = Field(default=0, ge=0)
    hidden: bool = False


class InvestmentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = Field(default=None, max_length=60)
    current_value_cents: int | None = Field(default=None, ge=0)
    monthly_plan_cents: int | None = Field(default=None, ge=0)
    hidden: bool | None = None
    active: bool | None = None


class ContributeIn(BaseModel):
    date: date
    amount_cents: int = Field(gt=0)


def serialize(db: Session, inv: Investment, viewer_id: int) -> dict:
    contributed = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(Transaction.investment_id == inv.id, tx_filter(viewer_id, Scope("casal")))
    )
    total = inv.initial_contributed_cents + int(contributed)
    return {
        "id": inv.id, "nome": inv.name, "categoria": inv.category, "pessoa_id": inv.owner_user_id, "conta_id": inv.account_id,
        "aportado": total, "valor_atual": inv.current_value_cents, "resultado": inv.current_value_cents - total,
        "valor_atualizado_em": inv.value_updated_at, "aporte_mensal": inv.monthly_plan_cents,
        "oculto": inv.hidden, "ativo": inv.active,
    }


@router.get("")
def list_investments(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(Investment).where(visible_clause(Investment, user.id)).order_by(Investment.id))
    return [serialize(db, i, user.id) for i in rows]


@router.post("")
def create_investment(data: InvestmentIn, db: Session = Depends(get_db), user=Depends(current_user)):
    check_account(db, data.account_id, user.id)
    values = data.model_dump()
    if values["current_value_cents"] is None:
        values["current_value_cents"] = data.initial_contributed_cents
    investment = Investment(**values, owner_user_id=user.id, active=True, value_updated_at=now())
    db.add(investment)
    db.flush()
    record(db, user.id, "criou", "investimento", investment.id, private=investment.hidden)
    touch(db, "investimentos")
    db.commit()
    return serialize(db, investment, user.id)


@router.patch("/{item_id}")
def update_investment(item_id: int, data: InvestmentPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    investment = get_visible(db, Investment, item_id, user.id)
    values = data.model_dump(exclude_none=True)
    if "hidden" in values and investment.owner_user_id != user.id:
        raise HTTPException(422, "Só a própria pessoa pode ocultar.")
    changes = apply_fields(investment, values)
    if "current_value_cents" in changes:
        investment.value_updated_at = now()
    record(db, user.id, "alterou", "investimento", investment.id, changes, private=investment.hidden)
    touch(db, "investimentos")
    db.commit()
    return serialize(db, investment, user.id)


@router.post("/{item_id}/aportar")
def contribute(item_id: int, data: ContributeIn, db: Session = Depends(get_db), user=Depends(current_user)):
    investment = get_visible(db, Investment, item_id, user.id)
    add_transaction(
        db, user.id, day=data.date, account_id=investment.account_id, owner_id=investment.owner_user_id,
        kind="investimento", amount_cents=data.amount_cents, description=f"Aporte: {investment.name}",
        hidden=investment.hidden, investment_id=investment.id,
    )
    investment.current_value_cents += data.amount_cents
    investment.value_updated_at = now()
    record(db, user.id, "aportou", "investimento", investment.id, private=investment.hidden)
    touch(db, "investimentos")
    db.commit()
    return serialize(db, investment, user.id)
