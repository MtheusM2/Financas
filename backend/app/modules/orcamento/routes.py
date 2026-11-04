from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.calc_graph import cached
from app.core.db import get_db
from app.core.visibility import apply_fields, get_visible
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.contas.models import Category
from app.modules.contas.service import parse_scope
from app.modules.orcamento import calc, service
from app.modules.orcamento.ceilings import ceilings_status
from app.modules.orcamento.models import CategoryBudget

router = APIRouter(prefix="/api/orcamento", tags=["orcamento"])

MESSAGES = {
    "cabe": "Cabe no orçamento atual.",
    "atencao": "Atenção: cabe, mas consome quase toda a folga ou exige reduzir investimentos.",
    "compromete": "Isso compromete o orçamento: o valor é maior do que vocês têm disponível depois das obrigações.",
}


class AssessIn(BaseModel):
    target_cents: int = Field(gt=0)
    saved_cents: int = Field(default=0, ge=0)
    term_months: int = Field(gt=0, le=600)
    monthly_cents: int | None = Field(default=None, gt=0)
    invest_rate_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)
    escopo: str = "casal"


class CeilingIn(BaseModel):
    category_id: int
    limit_cents: int = Field(gt=0)
    joint: bool = True
    hidden: bool = False


class CeilingPatch(BaseModel):
    limit_cents: int = Field(gt=0)


@router.get("/tetos")
def ceilings(ano: int = Query(ge=2000, le=2999), mes: int = Query(ge=1, le=12),
             db: Session = Depends(get_db), user=Depends(current_user)):
    return ceilings_status(db, user.id, ano, mes)


@router.post("/tetos")
def create_ceiling(data: CeilingIn, db: Session = Depends(get_db), user=Depends(current_user)):
    if data.hidden and data.joint:
        raise HTTPException(422, "Teto do casal não pode ser oculto.")
    if db.get(Category, data.category_id) is None:
        raise HTTPException(422, "Categoria não existe.")
    owner = None if data.joint else user.id
    exists = db.scalar(select(CategoryBudget.id).where(
        CategoryBudget.category_id == data.category_id,
        CategoryBudget.owner_user_id.is_(None) if owner is None else CategoryBudget.owner_user_id == owner,
    ))
    if exists:
        raise HTTPException(409, "Já existe um teto para esta categoria.")
    item = CategoryBudget(category_id=data.category_id, owner_user_id=owner, limit_cents=data.limit_cents, hidden=data.hidden)
    db.add(item)
    db.flush()
    record(db, user.id, "criou", "teto", item.id, private=item.hidden)
    db.commit()
    return {"id": item.id}


@router.patch("/tetos/{item_id}")
def update_ceiling(item_id: int, data: CeilingPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    item = get_visible(db, CategoryBudget, item_id, user.id)
    changes = apply_fields(item, data.model_dump())
    record(db, user.id, "alterou", "teto", item.id, changes, private=item.hidden)
    db.commit()
    return {"id": item.id}


@router.delete("/tetos/{item_id}")
def delete_ceiling(item_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    item = get_visible(db, CategoryBudget, item_id, user.id)
    private = item.hidden
    db.delete(item)
    record(db, user.id, "excluiu", "teto", item_id, private=private)
    db.commit()
    return {"ok": True}


@router.get("/resumo")
def summary(escopo: str = "casal", db: Session = Depends(get_db), user=Depends(current_user)):
    scope = parse_scope(escopo)
    return cached(db, "orcamento", (user.id, scope.key, ), lambda: service.snapshot(db, user.id, scope))


@router.post("/avaliar")
def assess(data: AssessIn, db: Session = Depends(get_db), user=Depends(current_user)):
    """So calcula, nao altera nada. Sempre mostra a conta usada."""
    scope = parse_scope(data.escopo)
    snap = service.snapshot(db, user.id, scope)
    missing = max(data.target_cents - data.saved_cents, 0)
    amount = data.monthly_cents or -(-missing // data.term_months)
    level = calc.assess(amount, snap["livre"], snap["planos"]["investimentos"], snap["disponivel"])
    return {
        "situacao": level, "mensagem": MESSAGES[level], "aporte_mensal": amount, "orcamento": snap,
        "plano_original": calc.project(data.saved_cents, amount, data.term_months),
        "alternativas": calc.alternatives(
            data.target_cents, data.saved_cents, amount, data.term_months, snap["livre"],
            snap["planos"]["investimentos"], data.invest_rate_percent / 100,
        ),
    }
