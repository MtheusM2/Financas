from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.calc_graph import touch
from app.core.db import get_db, now
from app.core.visibility import apply_fields, get_visible, visible_clause
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.contas.service import Scope, parse_scope
from app.modules.desafios import calc
from app.modules.desafios.models import Challenge
from app.modules.investimentos.models import Investment
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import add_transaction, tx_filter

router = APIRouter(prefix="/api/desafios", tags=["desafios"])


class ChallengeIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    metric: Literal["guardar", "investir", "livre"] = "guardar"
    joint: bool = True
    reward_cents: int = Field(gt=0)
    reward_label: str = Field(default="Lazer", min_length=1, max_length=80)
    multiplier: Decimal = Field(default=calc.DEFAULT_MULTIPLIER, gt=0, le=1000)
    # Meta personalizada, como "junte R$ 10 mil". O multiplicador passa a ser derivado dela.
    target_cents: int | None = Field(default=None, gt=0)
    initial_cents: int = Field(default=0, ge=0)
    term_months: int | None = Field(default=None, gt=0, le=600)
    monthly_cents: int | None = Field(default=None, gt=0)
    start_date: date
    hidden: bool = False


class ChallengePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    reward_label: str | None = Field(default=None, min_length=1, max_length=80)
    term_months: int | None = Field(default=None, gt=0, le=600)
    monthly_cents: int | None = Field(default=None, gt=0)
    manual_progress_cents: int | None = Field(default=None, ge=0)
    status: Literal["ativo", "cancelado"] | None = None
    hidden: bool | None = None


class ContributeIn(BaseModel):
    date: date
    amount_cents: int = Field(gt=0)
    account_id: int


class RewardIn(BaseModel):
    date: date
    account_id: int
    description: str = Field(default="", max_length=160)


def progress(db: Session, item: Challenge, viewer_id: int) -> int:
    if item.metric == "livre":
        return item.initial_cents + item.manual_progress_cents
    if item.metric == "investir":
        stmt = select(func.coalesce(func.sum(Investment.current_value_cents), 0)).where(
            visible_clause(Investment, viewer_id), Investment.active.is_(True)
        )
        if item.owner_user_id is not None:
            stmt = stmt.where(Investment.owner_user_id == item.owner_user_id)
        return int(db.scalar(stmt))
    linked = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(Transaction.challenge_id == item.id, tx_filter(viewer_id, Scope("casal")))
    )
    return item.initial_cents + int(linked)


def serialize(db: Session, item: Challenge, viewer_id: int) -> dict:
    current = progress(db, item, viewer_id)
    return {
        "id": item.id, "nome": item.name, "metrica": item.metric, "pessoa_id": item.owner_user_id,
        "conjunto": item.owner_user_id is None, "recompensa": item.reward_cents, "recompensa_rotulo": item.reward_label,
        "multiplicador": str(item.multiplier), "meta": item.target_cents, "progresso": current,
        "percentual": round(current / item.target_cents * 100, 1), "prazo": item.term_months,
        "aporte_mensal": item.monthly_cents, "inicio": item.start_date, "situacao": item.status,
        "alcancado": current >= item.target_cents, "concluido_em": item.completed_at,
        "recompensa_usada": item.reward_tx_id is not None, "oculto": item.hidden,
        **calc.split_on_completion(item.target_cents, item.reward_cents),
    }


@router.get("/sugestao")
def suggestion(
    recompensa: int | None = Query(default=None, gt=0), multiplicador: Decimal = Query(default=calc.DEFAULT_MULTIPLIER, gt=0),
    escopo: str = "casal", db: Session = Depends(get_db), user=Depends(current_user),
):
    from app.modules.orcamento.service import snapshot
    snap = snapshot(db, user.id, parse_scope(escopo))
    # Usa o menor entre a sobra real e a folga do orcamento: nao sugere o que ja esta comprometido.
    surplus = min(snap["sobra_media"], snap["livre"])
    return calc.suggest(recompensa, multiplicador, surplus)


@router.get("")
def list_challenges(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(Challenge).where(visible_clause(Challenge, user.id)).order_by(Challenge.id.desc()))
    return [serialize(db, c, user.id) for c in rows]


@router.post("")
def create_challenge(data: ChallengeIn, db: Session = Depends(get_db), user=Depends(current_user)):
    if data.hidden and data.joint:
        raise HTTPException(422, "Desafio em conjunto não pode ser oculto.")
    if data.target_cents:
        target, multiplier = data.target_cents, calc.multiplier_from_target(data.reward_cents, data.target_cents)
    else:
        target, multiplier = calc.target_from_reward(data.reward_cents, data.multiplier), data.multiplier
    monthly = data.monthly_cents
    if monthly is None and data.term_months:
        monthly = -(-max(target - data.initial_cents, 0) // data.term_months)
    item = Challenge(
        name=data.name, metric=data.metric, owner_user_id=None if data.joint else user.id,
        reward_cents=data.reward_cents, reward_label=data.reward_label, multiplier=multiplier, target_cents=target,
        initial_cents=data.initial_cents, manual_progress_cents=0, term_months=data.term_months, monthly_cents=monthly,
        start_date=data.start_date, status="ativo", hidden=data.hidden,
    )
    db.add(item)
    db.flush()
    record(db, user.id, "criou", "desafio", item.id, private=item.hidden)
    touch(db, "desafios")
    touch(db, "orcamento")
    db.commit()
    return serialize(db, item, user.id)


@router.patch("/{item_id}")
def update_challenge(item_id: int, data: ChallengePatch, db: Session = Depends(get_db), user=Depends(current_user)):
    item = get_visible(db, Challenge, item_id, user.id)
    values = data.model_dump(exclude_unset=True)
    if values.get("hidden") and item.owner_user_id != user.id:
        raise HTTPException(422, "Só o dono de um desafio individual pode ocultá-lo.")
    changes = apply_fields(item, values)
    record(db, user.id, "alterou", "desafio", item.id, changes, private=item.hidden)
    touch(db, "desafios")
    touch(db, "orcamento")
    db.commit()
    return serialize(db, item, user.id)


@router.post("/{item_id}/aportar")
def contribute(item_id: int, data: ContributeIn, db: Session = Depends(get_db), user=Depends(current_user)):
    item = get_visible(db, Challenge, item_id, user.id)
    if item.metric != "guardar":
        raise HTTPException(422, "Este desafio não usa aportes.")
    add_transaction(
        db, user.id, day=data.date, account_id=data.account_id, owner_id=user.id, kind="guardado",
        amount_cents=data.amount_cents, description=f"Desafio: {item.name}", hidden=item.hidden, challenge_id=item.id,
    )
    record(db, user.id, "aportou", "desafio", item.id, private=item.hidden)
    touch(db, "desafios")
    db.commit()
    return serialize(db, item, user.id)


@router.post("/{item_id}/concluir")
def complete(item_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    item = get_visible(db, Challenge, item_id, user.id)
    if item.status == "concluido":
        raise HTTPException(409, "Este desafio já foi concluído.")
    if progress(db, item, user.id) < item.target_cents:
        raise HTTPException(409, "A meta ainda não foi alcançada.")
    item.status, item.completed_at = "concluido", now()
    record(db, user.id, "concluiu", "desafio", item.id, private=item.hidden)
    touch(db, "desafios")
    touch(db, "orcamento")
    db.commit()
    return serialize(db, item, user.id)


@router.post("/{item_id}/usar-recompensa")
def use_reward(item_id: int, data: RewardIn, db: Session = Depends(get_db), user=Depends(current_user)):
    """Transforma a recompensa liberada em um lancamento de lazer, uma unica vez."""
    item = get_visible(db, Challenge, item_id, user.id)
    if item.status != "concluido":
        raise HTTPException(409, "Conclua o desafio antes de usar a recompensa.")
    if item.reward_tx_id:
        raise HTTPException(409, "Esta recompensa já foi usada.")
    tx = add_transaction(
        db, user.id, day=data.date, account_id=data.account_id, owner_id=user.id, kind="lazer",
        amount_cents=item.reward_cents, description=data.description or f"Recompensa: {item.reward_label}", hidden=item.hidden,
    )
    item.reward_tx_id = tx.id
    record(db, user.id, "usou_recompensa", "desafio", item.id, private=item.hidden)
    touch(db, "desafios")
    db.commit()
    return serialize(db, item, user.id)
