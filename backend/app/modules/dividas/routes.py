from datetime import date
from datetime import date as Date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.calc_graph import touch
from app.core.db import get_db, local_today
from app.core.visibility import apply_fields, get_visible, visible_clause
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.contas.models import Category
from app.modules.dividas.models import Debt
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import add_months, add_transaction, after_change, check_account, clamp_day, due_situation, month_key, next_month, tx_filter
from app.modules.contas.service import Scope

router = APIRouter(prefix="/api/dividas", tags=["dividas"])


class DebtIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    account_id: int
    category_id: int | None = None
    installment_cents: int = Field(gt=0)
    due_day: int = Field(ge=1, le=31)
    total_installments: int | None = Field(default=None, gt=0)
    paid_before: int = Field(default=0, ge=0)
    start_date: date
    hidden: bool = False


class DebtPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    category_id: int | None = None
    installment_cents: int | None = Field(default=None, gt=0)
    total_installments: int | None = Field(default=None, gt=0)
    next_due: Optional[Date] = None
    paid_before: int | None = Field(default=None, ge=0)
    hidden: bool | None = None
    active: bool | None = None


class BulkDelete(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class PayIn(BaseModel):
    date: date
    amount_cents: int | None = Field(default=None, gt=0)


def check_category(db: Session, category_id: int | None) -> None:
    if category_id is not None and db.get(Category, category_id) is None:
        raise HTTPException(422, "Tag inválida.")


def paid_count(db: Session, debt: Debt, viewer_id: int) -> tuple[int, int]:
    count, total = db.execute(
        select(func.count(), func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(Transaction.debt_id == debt.id, tx_filter(viewer_id, Scope("casal")))
    ).one()
    return debt.paid_before + count, int(total)


def occurrence(debt: Debt, index: int) -> date:
    """Vencimento numero `index`, contado a partir do inicio. Parcelas anteriores estao em paid_before."""
    first = month_key(debt.start_date)
    if clamp_day(first, debt.due_day) < debt.start_date:
        first = next_month(first)
    return clamp_day(add_months(first, index), debt.due_day)


def due_status(debt: Debt, paid: int, today: date) -> dict:
    """Cada pagamento quita o vencimento mais antigo em aberto: o saldo nunca muda sozinho."""
    total = debt.total_installments
    if total is not None and paid >= total:
        return {"situacao": "quitada", "proximo_vencimento": None, "dias": None, "atrasadas": 0}
    index = paid - debt.paid_before
    due = occurrence(debt, index)
    late = 0
    while occurrence(debt, index + late) < today and (total is None or paid + late < total):
        late += 1
    days = (due - today).days
    return {"situacao": due_situation(days), "proximo_vencimento": due, "dias": days, "atrasadas": late}


def last_payment(db: Session, debt: Debt, viewer_id: int) -> Transaction | None:
    return db.scalar(
        select(Transaction).where(Transaction.debt_id == debt.id, tx_filter(viewer_id, Scope("casal")))
        .order_by(Transaction.id.desc()).limit(1)
    )


def serialize(db: Session, debt: Debt, viewer_id: int) -> dict:
    paid, paid_cents = paid_count(db, debt, viewer_id)
    remaining = None if debt.total_installments is None else max(debt.total_installments - paid, 0)
    category = db.get(Category, debt.category_id) if debt.category_id else None
    last = last_payment(db, debt, viewer_id)
    return {
        "id": debt.id, "nome": debt.name, "pessoa_id": debt.owner_user_id, "conta_id": debt.account_id,
        "categoria_id": debt.category_id, "categoria": category.name if category else None,
        "parcela": debt.installment_cents, "vencimento": debt.due_day, "total_parcelas": debt.total_installments,
        "parcelas_ja_pagas": debt.paid_before,
        "parcelas_pagas": paid, "parcelas_restantes": remaining, "total_pago": paid_cents,
        "saldo_restante": None if remaining is None else remaining * debt.installment_cents,
        "inicio": debt.start_date, "oculta": debt.hidden, "ativa": debt.active, "quitada": remaining == 0,
        "ultimo_pagamento": {"data": last.date, "valor": last.amount_cents} if last else None,
        **due_status(debt, paid, local_today()),
    }


@router.get("")
def list_debts(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(Debt).where(visible_clause(Debt, user.id)).order_by(Debt.due_day))
    return [serialize(db, d, user.id) for d in rows]


@router.post("")
def create_debt(data: DebtIn, db: Session = Depends(get_db), user=Depends(current_user)):
    # "Parcelas ja pagas" nao cria lancamento: uma divida que ja nasce quitada nunca sairia do saldo.
    if data.total_installments is not None and data.paid_before >= data.total_installments:
        raise HTTPException(422, "As parcelas já pagas não podem ser todas. Elas não saem do saldo: "
                                 "para um pagamento feito agora, cadastre e use Registrar pagamento.")
    check_account(db, data.account_id, user.id)
    check_category(db, data.category_id)
    debt = Debt(**data.model_dump(), owner_user_id=user.id, active=True)
    db.add(debt)
    db.flush()
    record(db, user.id, "criou", "divida", debt.id, private=debt.hidden)
    touch(db, "compromissos")
    db.commit()
    return serialize(db, debt, user.id)


@router.patch("/{debt_id}")
def update_debt(debt_id: int, data: DebtPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    debt = get_visible(db, Debt, debt_id, user.id)
    # So estes podem voltar a ficar vazios: sem tag ou sem prazo.
    values = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k in ("category_id", "total_installments")}
    if "hidden" in values and debt.owner_user_id != user.id:
        raise HTTPException(422, "Só a própria pessoa pode ocultar.")
    check_category(db, values.get("category_id"))
    if "paid_before" in values or "total_installments" in values:
        registered = paid_count(db, debt, user.id)[0] - debt.paid_before
        before = values.get("paid_before", debt.paid_before)
        total = values.get("total_installments", debt.total_installments)
        if total is not None and before + registered > total:
            raise HTTPException(422, "As parcelas já pagas e os pagamentos registrados passam do total de parcelas.")
    next_due = values.pop("next_due", None)
    if next_due:
        # O inicio recua o que ja foi pago, para o proximo vencimento cair na data escolhida.
        paid, _ = paid_count(db, debt, user.id)
        values["due_day"] = next_due.day
        values["start_date"] = clamp_day(add_months(month_key(next_due), debt.paid_before - paid), next_due.day)
    changes = apply_fields(debt, values)
    record(db, user.id, "alterou", "divida", debt.id, changes, private=debt.hidden)
    touch(db, "compromissos")
    db.commit()
    return serialize(db, debt, user.id)


def remove_debt(db: Session, debt: Debt, user_id: int) -> list[date]:
    """Exclui a divida e os pagamentos dela. Para manter o historico, use active=False."""
    payments = db.scalars(select(Transaction).where(Transaction.debt_id == debt.id)).all()
    days = [tx.date for tx in payments]
    for tx in payments:
        db.delete(tx)
    record(db, user_id, "excluiu", "divida", debt.id, {"pagamentos": len(payments)}, private=debt.hidden)
    db.delete(debt)
    return days


def finish_removal(db: Session, days: list[date]) -> None:
    after_change(db, days)
    touch(db, "compromissos")
    db.commit()


@router.post("/excluir")
def delete_many(data: BulkDelete, db: Session = Depends(get_db), user=Depends(current_user)):
    # Se alguma nao puder ser excluida, nenhuma e: o commit so acontece no fim.
    debts = [get_visible(db, Debt, debt_id, user.id) for debt_id in set(data.ids)]
    days = [day for debt in debts for day in remove_debt(db, debt, user.id)]
    finish_removal(db, days)
    return {"excluidas": len(debts)}


@router.delete("/{debt_id}")
def delete_debt(debt_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    debt = get_visible(db, Debt, debt_id, user.id)
    finish_removal(db, remove_debt(db, debt, user.id))
    return {"ok": True}


@router.post("/{debt_id}/pagar")
def pay(debt_id: int, data: PayIn, db: Session = Depends(get_db), user=Depends(current_user)):
    debt = get_visible(db, Debt, debt_id, user.id)
    paid, _ = paid_count(db, debt, user.id)
    if debt.total_installments is not None and paid >= debt.total_installments:
        raise HTTPException(409, "Esta dívida já está quitada.")
    prefix = "Pagamento" if debt.total_installments is None else "Parcela"
    tx = add_transaction(
        db, user.id, day=data.date, account_id=debt.account_id, owner_id=debt.owner_user_id, kind="divida",
        amount_cents=data.amount_cents or debt.installment_cents, description=f"{prefix}: {debt.name}",
        category_id=debt.category_id, hidden=debt.hidden, debt_id=debt.id,
    )
    record(db, user.id, "pagou", "divida", debt.id, {"lancamento": tx.id}, private=debt.hidden)
    touch(db, "compromissos")
    db.commit()
    return serialize(db, debt, user.id)


@router.delete("/{debt_id}/pagamentos/ultimo")
def undo_payment(debt_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    debt = get_visible(db, Debt, debt_id, user.id)
    tx = last_payment(db, debt, user.id)
    if tx is None:
        raise HTTPException(404, "Nenhum pagamento para desfazer.")
    tx_id, day = tx.id, tx.date
    db.delete(tx)
    after_change(db, [day])
    record(db, user.id, "desfez_pagamento", "divida", debt.id, {"lancamento": tx_id}, private=debt.hidden)
    touch(db, "compromissos")
    db.commit()
    return serialize(db, debt, user.id)
