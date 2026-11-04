from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.calc_graph import touch
from app.core.db import get_db
from app.core.visibility import apply_fields
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.contas.models import Account, Category
from app.modules.contas.service import account_visible_clause, build_tree

router = APIRouter(prefix="/api/contas", tags=["contas"])


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern="^(pessoal|compartilhada)$")
    opening_balance_cents: int = 0
    hidden: bool = False


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    opening_balance_cents: int | None = None
    hidden: bool | None = None
    archived: bool | None = None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    parent_id: int | None = None
    essential: bool = False


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    essential: bool | None = None


def serialize(a: Account) -> dict:
    return {"id": a.id, "nome": a.name, "tipo": a.kind, "dono": a.owner_user_id, "oculta": a.hidden,
            "arquivada": a.archived, "saldo_inicial": a.opening_balance_cents}


@router.get("")
def list_accounts(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(Account).where(account_visible_clause(user.id)).order_by(Account.id))
    return [serialize(a) for a in rows]


@router.post("")
def create_account(data: AccountIn, db: Session = Depends(get_db), user=Depends(current_user)):
    shared = data.kind == "compartilhada"
    if shared and data.hidden:
        raise HTTPException(422, "Conta compartilhada não pode ser oculta.")
    account = Account(name=data.name, kind=data.kind, owner_user_id=None if shared else user.id,
                      opening_balance_cents=data.opening_balance_cents, hidden=data.hidden, archived=False)
    db.add(account)
    db.flush()
    record(db, user.id, "criou", "conta", account.id, private=data.hidden)
    touch(db, "contas")
    db.commit()
    return serialize(account)


@router.patch("/{account_id}")
def update_account(account_id: int, data: AccountPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    account = db.get(Account, account_id)
    if account is None or (account.owner_user_id not in (None, user.id)):
        raise HTTPException(404, "Não encontrado.")
    values = data.model_dump(exclude_none=True)
    if values.get("hidden") and account.owner_user_id is None:
        raise HTTPException(422, "Conta compartilhada não pode ser oculta.")
    changes = apply_fields(account, values)
    record(db, user.id, "alterou", "conta", account.id, changes, private=account.hidden)
    touch(db, "contas")
    db.commit()
    return serialize(account)


@router.get("/categorias")
def list_categories(db: Session = Depends(get_db), user=Depends(current_user)):
    return build_tree(list(db.scalars(select(Category).order_by(Category.name))))


@router.post("/categorias")
def create_category(data: CategoryIn, db: Session = Depends(get_db), user=Depends(current_user)):
    if data.parent_id is not None and db.get(Category, data.parent_id) is None:
        raise HTTPException(422, "Categoria mãe não existe.")
    category = Category(name=data.name, parent_id=data.parent_id, essential=data.essential)
    db.add(category)
    db.flush()
    record(db, user.id, "criou", "categoria", category.id)
    db.commit()
    return {"id": category.id, "nome": category.name, "essencial": category.essential, "filhas": []}


@router.patch("/categorias/{category_id}")
def update_category(category_id: int, data: CategoryPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Não encontrado.")
    changes = apply_fields(category, data.model_dump(exclude_none=True))
    record(db, user.id, "alterou", "categoria", category.id, changes)
    touch(db, "lancamentos")
    db.commit()
    return {"id": category.id, "nome": category.name, "essencial": category.essential}
