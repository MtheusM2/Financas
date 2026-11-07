from datetime import date
from datetime import date as Date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import get_db, local_today
from app.core.visibility import apply_fields, get_visible, visible_clause
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.autenticacao.models import User
from app.modules.contas.models import Account, Category
from app.modules.contas.service import parse_scope
from app.modules.lancamentos import service
from app.modules.lancamentos.models import RecurringRule, Transaction

router = APIRouter(prefix="/api/lancamentos", tags=["lancamentos"])

Kind = Literal["renda", "gasto", "fora_escopo", "divida", "investimento", "guardado", "lazer"]


class TxIn(BaseModel):
    date: date
    account_id: int
    owner_user_id: int | None = None
    kind: Kind
    amount_cents: int = Field(gt=0)
    description: str = Field(default="", max_length=160)
    notes: str | None = Field(default=None, max_length=2000)
    category_id: int | None = None
    hidden: bool = False
    settled: bool = True
    competence_date: Optional[Date] = None


class SettleIn(BaseModel):
    date: date


class TxPatch(BaseModel):
    date: Optional[Date] = None
    settled: bool | None = None
    competence_date: Optional[Date] = None
    account_id: int | None = None
    kind: Kind | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)
    category_id: int | None = None
    hidden: bool | None = None


class RuleIn(BaseModel):
    account_id: int
    kind: Kind
    amount_cents: int = Field(gt=0)
    description: str = Field(default="", max_length=160)
    category_id: int | None = None
    day_of_month: int = Field(ge=1, le=31)
    start_month: int = Field(ge=200001, le=299912)
    end_month: int | None = Field(default=None, ge=200001, le=299912)
    hidden: bool = False


class RulePatch(BaseModel):
    """Vale de from_month em diante. Ocorrencias editadas a mao ficam como estao."""
    from_month: int = Field(ge=200001, le=299912)
    amount_cents: int | None = Field(default=None, gt=0)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    description: str | None = Field(default=None, max_length=160)
    active: bool | None = None
    end_month: int | None = None


class IncomePayment(BaseModel):
    date: date
    amount_cents: int = Field(gt=0)


class IncomeIn(BaseModel):
    """Uma renda com quantas datas precisar. Mensal repete cada data; senao, vale so uma vez."""
    description: str = Field(min_length=1, max_length=160)
    account_id: int
    category_id: int | None = None
    monthly: bool = True
    hidden: bool = False
    payments: list[IncomePayment] = Field(min_length=1, max_length=31)


def serialize(tx: Transaction) -> dict:
    return {
        "id": tx.id, "data": tx.date, "conta_id": tx.account_id, "pessoa_id": tx.owner_user_id, "tipo": tx.kind,
        "valor": tx.amount_cents, "descricao": tx.description, "observacoes": tx.notes,
        "categoria_id": tx.category_id, "oculto": tx.hidden, "recorrente": tx.rule_id is not None,
        "editado": tx.edited, "quitado": tx.settled, "competencia": tx.competence_date,
        "importado": tx.external_id is not None,
    }


def serialize_rule(r: RecurringRule) -> dict:
    return {
        "id": r.id, "conta_id": r.account_id, "pessoa_id": r.owner_user_id, "tipo": r.kind, "valor": r.amount_cents,
        "descricao": r.description, "categoria_id": r.category_id, "dia": r.day_of_month,
        "inicio": r.start_month, "fim": r.end_month, "ativa": r.active, "oculta": r.hidden,
    }


@router.get("")
def search(
    inicio: date | None = None, fim: date | None = None, escopo: str = "casal", tipo: Kind | None = None,
    categoria_id: int | None = None, busca: str | None = Query(default=None, max_length=80),
    pagina: int = Query(1, ge=1), por_pagina: int = Query(50, le=200), pendentes: bool = False,
    db: Session = Depends(get_db), user=Depends(current_user),
):
    conditions = [service.tx_filter(user.id, parse_scope(escopo))]
    if pendentes:
        conditions.append(Transaction.settled.is_(False))
    if inicio:
        conditions.append(Transaction.date >= inicio)
    if fim:
        conditions.append(Transaction.date <= fim)
    if tipo:
        conditions.append(Transaction.kind == tipo)
    if categoria_id:
        # Inclui as subcategorias: desce a arvore com uma consulta recursiva.
        tree = select(Category.id).where(Category.id == categoria_id).cte(recursive=True)
        tree = tree.union_all(select(Category.id).where(Category.parent_id == tree.c.id))
        conditions.append(Transaction.category_id.in_(select(tree.c.id)))
    if busca:
        conditions.append(Transaction.description.icontains(busca, autoescape=True))
    is_income = Transaction.kind == "renda"
    total, soma, entradas = db.execute(
        select(func.count(), func.coalesce(func.sum(Transaction.amount_cents), 0),
               func.coalesce(func.sum(Transaction.amount_cents).filter(is_income), 0)).where(*conditions)
    ).one()
    # Entradas e saidas separadas: somar as duas juntas daria um total sem sentido.
    entradas, saidas = int(entradas), int(soma) - int(entradas)
    rows = db.execute(
        select(Transaction, User.name, Account.name)
        .join(User, User.id == Transaction.owner_user_id)
        .join(Account, Account.id == Transaction.account_id)
        .where(*conditions)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((pagina - 1) * por_pagina).limit(por_pagina)
    )
    return {
        "total": total, "soma": int(soma), "entradas": entradas, "saidas": saidas, "resultado": entradas - saidas,
        "pagina": pagina,
        "itens": [{**serialize(t), "pessoa": name, "conta": account} for t, name, account in rows],
    }


@router.post("")
def create(data: TxIn, db: Session = Depends(get_db), user=Depends(current_user)):
    owner = data.owner_user_id or user.id
    if data.hidden and owner != user.id:
        raise HTTPException(422, "Só a própria pessoa pode ocultar um lançamento.")
    tx = service.add_transaction(
        db, user.id, day=data.date, account_id=data.account_id, owner_id=owner, kind=data.kind,
        amount_cents=data.amount_cents, description=data.description, category_id=data.category_id,
        hidden=data.hidden, notes=data.notes, settled=data.settled, competence_date=data.competence_date,
    )
    record(db, user.id, "criou", "lancamento", tx.id, private=tx.hidden)
    db.commit()
    return serialize(tx)


@router.post("/rendas")
def create_income(data: IncomeIn, db: Session = Depends(get_db), user=Depends(current_user)):
    service.check_account(db, data.account_id, user.id)
    created = 0
    for item in data.payments:
        if data.monthly:
            rule = RecurringRule(
                account_id=data.account_id, owner_user_id=user.id, kind="renda", category_id=data.category_id,
                description=data.description, amount_cents=item.amount_cents, day_of_month=item.date.day,
                start_month=service.month_key(item.date), hidden=data.hidden, active=True,
            )
            db.add(rule)
            db.flush()
            service.materialize_rule(db, rule)
            record(db, user.id, "criou", "recorrencia", rule.id, private=rule.hidden)
        else:
            tx = service.add_transaction(
                db, user.id, day=item.date, account_id=data.account_id, owner_id=user.id, kind="renda",
                amount_cents=item.amount_cents, description=data.description, category_id=data.category_id,
                hidden=data.hidden, settled=item.date <= local_today(),
            )
            record(db, user.id, "criou", "lancamento", tx.id, private=tx.hidden)
        created += 1
    db.commit()
    return {"criados": created}


@router.patch("/{tx_id}")
def update(tx_id: int, data: TxPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    tx = get_visible(db, Transaction, tx_id, user.id)
    values = data.model_dump(exclude_unset=True)
    if values.get("hidden") and tx.owner_user_id != user.id:
        raise HTTPException(422, "Só a própria pessoa pode ocultar um lançamento.")
    if "account_id" in values:
        service.check_account(db, values["account_id"], tx.owner_user_id)
    old_date = tx.date
    changes = apply_fields(tx, values)
    if changes:
        tx.edited = True
        service.after_change(db, [old_date, tx.date])
        record(db, user.id, "alterou", "lancamento", tx.id, changes, private=tx.hidden)
    db.commit()
    return serialize(tx)


@router.post("/{tx_id}/quitar")
def settle(tx_id: int, data: SettleIn, db: Session = Depends(get_db), user=Depends(current_user)):
    """Previsto vira realizado na data real em que o dinheiro entrou ou saiu."""
    tx = get_visible(db, Transaction, tx_id, user.id)
    old_date = tx.date
    # A competencia continua sendo o mes original, mesmo pagando em outro.
    if tx.competence_date is None and data.date != old_date:
        tx.competence_date = old_date
    tx.date, tx.settled, tx.edited = data.date, True, True
    service.after_change(db, [old_date, data.date])
    record(db, user.id, "quitou", "lancamento", tx.id, private=tx.hidden)
    db.commit()
    return serialize(tx)


@router.delete("/{tx_id}")
def remove(tx_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    tx = get_visible(db, Transaction, tx_id, user.id)
    day, private = tx.date, tx.hidden
    db.delete(tx)
    service.after_change(db, [day])
    record(db, user.id, "excluiu", "lancamento", tx_id, private=private)
    db.commit()
    return {"ok": True}


@router.get("/recorrencias")
def list_rules(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(RecurringRule).where(visible_clause(RecurringRule, user.id)).order_by(RecurringRule.day_of_month))
    return [serialize_rule(r) for r in rows]


@router.post("/recorrencias")
def create_rule(data: RuleIn, db: Session = Depends(get_db), user=Depends(current_user)):
    service.check_account(db, data.account_id, user.id)
    rule = RecurringRule(**data.model_dump(), owner_user_id=user.id, active=True)
    db.add(rule)
    db.flush()
    service.materialize_rule(db, rule)
    record(db, user.id, "criou", "recorrencia", rule.id, private=rule.hidden)
    db.commit()
    return serialize_rule(rule)


@router.patch("/recorrencias/{rule_id}")
def update_rule(rule_id: int, data: RulePatch, db: Session = Depends(get_db), user=Depends(current_user)):
    rule = get_visible(db, RecurringRule, rule_id, user.id)
    values = data.model_dump(exclude_unset=True, exclude={"from_month"})
    changes = apply_fields(rule, values)
    affected = db.scalars(select(Transaction.date).where(
        Transaction.rule_id == rule.id, Transaction.occurrence_month >= data.from_month, Transaction.edited.is_(False)
    )).all()
    db.execute(delete(Transaction).where(
        Transaction.rule_id == rule.id, Transaction.occurrence_month >= data.from_month, Transaction.edited.is_(False)
    ))
    previous = service.split_month(data.from_month)
    rule.last_generated_month = None if data.from_month <= rule.start_month else (
        (previous[0] - 1) * 100 + 12 if previous[1] == 1 else data.from_month - 1
    )
    service.after_change(db, list(affected))
    service.materialize_rule(db, rule)
    record(db, user.id, "alterou", "recorrencia", rule.id, changes, private=rule.hidden)
    db.commit()
    return serialize_rule(rule)
