from datetime import date
from datetime import date as Date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.calc_graph import touch
from app.core.db import get_db, local_today
from app.core.visibility import apply_fields, get_visible, visible_clause
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.contas.service import Scope
from app.modules.financiamentos.calc import annual_to_monthly, build_schedule, totals
from app.modules.financiamentos.models import Financing, FinancingExtra
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import add_months, add_transaction, after_change, check_account, clamp_day, due_situation, month_key, tx_filter

router = APIRouter(prefix="/api/financiamentos", tags=["financiamentos"])


class FinancingIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    account_id: int
    asset_value_cents: int = Field(gt=0)
    down_payment_cents: int = Field(default=0, ge=0)
    annual_rate_percent: Decimal = Field(ge=0, le=1000)
    system: Literal["SAC", "PRICE"]
    term_months: int = Field(gt=0, le=600)
    monthly_fee_cents: int = Field(default=0, ge=0)
    first_due: date
    paid_before: int = Field(default=0, ge=0)
    hidden: bool = False


class FinancingPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    monthly_fee_cents: int | None = Field(default=None, ge=0)
    hidden: bool | None = None
    active: bool | None = None


class PayIn(BaseModel):
    date: date


class ExtraIn(BaseModel):
    amount_cents: int = Field(gt=0)
    keep_term: bool = False
    date: Optional[Date] = None


def extras_of(db: Session, f: Financing) -> tuple[dict[int, int], bool]:
    rows = db.scalars(select(FinancingExtra).where(FinancingExtra.financing_id == f.id)).all()
    extras: dict[int, int] = {}
    for row in rows:
        extras[row.after_installment] = extras.get(row.after_installment, 0) + row.amount_cents
    return extras, any(r.keep_term for r in rows)


def schedule(db: Session, f: Financing, extra_extras: dict[int, int] | None = None, keep_term: bool | None = None):
    extras, stored_keep = extras_of(db, f)
    for number, amount in (extra_extras or {}).items():
        extras[number] = extras.get(number, 0) + amount
    return build_schedule(
        f.asset_value_cents - f.down_payment_cents, annual_to_monthly(f.annual_rate_percent), f.term_months,
        f.system, f.monthly_fee_cents, extras, stored_keep if keep_term is None else keep_term,
    )


def installments_paid(db: Session, f: Financing, viewer_id: int) -> int:
    count = db.scalar(select(func.count()).where(
        Transaction.financing_id == f.id, Transaction.installment_no.is_not(None),
        tx_filter(viewer_id, Scope("casal")),
    ))
    return f.paid_before + (count or 0)


def installment_due(f: Financing, index: int) -> date:
    """Vencimento da parcela `index`, contando desde a primeira. As ja pagas antes do cadastro tambem contam."""
    return clamp_day(add_months(month_key(f.first_due), index), f.first_due.day)


def due_status(f: Financing, total: int, paid: int, today: date) -> dict:
    if paid >= total:
        return {"situacao": "quitada", "proximo_vencimento": None, "dias": None, "atrasadas": 0}
    due = installment_due(f, paid)
    late = 0
    while paid + late < total and installment_due(f, paid + late) < today:
        late += 1
    days = (due - today).days
    return {"situacao": due_situation(days), "proximo_vencimento": due, "dias": days, "atrasadas": late}


def serialize(db: Session, f: Financing, viewer_id: int) -> dict:
    rows = schedule(db, f)
    paid = min(installments_paid(db, f, viewer_id), len(rows))
    balance = rows[paid - 1].balance if paid else f.asset_value_cents - f.down_payment_cents
    next_row = rows[paid] if paid < len(rows) else None
    return {
        "id": f.id, "nome": f.name, "pessoa_id": f.owner_user_id, "conta_id": f.account_id,
        "valor_bem": f.asset_value_cents, "entrada": f.down_payment_cents,
        "valor_financiado": f.asset_value_cents - f.down_payment_cents,
        "juros_ano": str(f.annual_rate_percent), "juros_mes": str(round(annual_to_monthly(f.annual_rate_percent) * 100, 4)),
        "sistema": f.system, "prazo": f.term_months, "taxa_mensal": f.monthly_fee_cents, "primeiro_vencimento": f.first_due,
        "parcelas_pagas": paid, "parcelas_restantes": len(rows) - paid, "saldo_devedor": balance,
        "proxima_parcela": next_row.payment + next_row.fee if next_row else 0,
        "quitado": next_row is None, "oculta": f.hidden, "ativa": f.active, **totals(rows),
        **due_status(f, len(rows), paid, local_today()),
    }


@router.get("")
def list_financings(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(Financing).where(visible_clause(Financing, user.id)).order_by(Financing.id))
    return [serialize(db, f, user.id) for f in rows]


@router.post("")
def create_financing(data: FinancingIn, db: Session = Depends(get_db), user=Depends(current_user)):
    check_account(db, data.account_id, user.id)
    if data.down_payment_cents >= data.asset_value_cents:
        raise HTTPException(422, "A entrada precisa ser menor que o valor do bem.")
    financing = Financing(**data.model_dump(), owner_user_id=user.id, active=True)
    db.add(financing)
    db.flush()
    record(db, user.id, "criou", "financiamento", financing.id, private=financing.hidden)
    touch(db, "compromissos")
    db.commit()
    return serialize(db, financing, user.id)


@router.patch("/{item_id}")
def update_financing(item_id: int, data: FinancingPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    financing = get_visible(db, Financing, item_id, user.id)
    values = data.model_dump(exclude_none=True)
    if "hidden" in values and financing.owner_user_id != user.id:
        raise HTTPException(422, "Só a própria pessoa pode ocultar.")
    changes = apply_fields(financing, values)
    record(db, user.id, "alterou", "financiamento", financing.id, changes, private=financing.hidden)
    touch(db, "compromissos")
    db.commit()
    return serialize(db, financing, user.id)


@router.delete("/{item_id}")
def delete_financing(item_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    financing = get_visible(db, Financing, item_id, user.id)
    payments = db.scalars(select(Transaction).where(Transaction.financing_id == financing.id)).all()
    days = [tx.date for tx in payments]
    for tx in payments:
        db.delete(tx)
    db.execute(delete(FinancingExtra).where(FinancingExtra.financing_id == financing.id))
    record(db, user.id, "excluiu", "financiamento", financing.id, {"pagamentos": len(payments)}, private=financing.hidden)
    db.delete(financing)
    after_change(db, days)
    touch(db, "compromissos")
    db.commit()
    return {"ok": True}


@router.get("/{item_id}/parcelas")
def installments(item_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    financing = get_visible(db, Financing, item_id, user.id)
    paid = installments_paid(db, financing, user.id)
    year, month = financing.first_due.year, financing.first_due.month
    result = []
    for row in schedule(db, financing):
        index = year * 12 + month - 1 + row.number - 1
        result.append({
            "numero": row.number, "mes": f"{index // 12}-{index % 12 + 1:02d}", "parcela": row.payment, "juros": row.interest,
            "amortizacao": row.amortization, "extra": row.extra, "taxa": row.fee, "saldo": row.balance,
            "paga": row.number <= paid,
        })
    return result


@router.post("/{item_id}/simular")
def simulate(item_id: int, data: ExtraIn, db: Session = Depends(get_db), user=Depends(current_user)):
    """So calcula: nao grava nada."""
    financing = get_visible(db, Financing, item_id, user.id)
    paid = installments_paid(db, financing, user.id)
    before = totals(schedule(db, financing))
    after = totals(schedule(db, financing, {max(paid, 1): data.amount_cents}, data.keep_term))
    return {
        "atual": before, "simulado": after,
        "juros_economizados": before["juros_total"] - after["juros_total"],
        "meses_a_menos": before["parcelas"] - after["parcelas"],
    }


@router.post("/{item_id}/pagar")
def pay(item_id: int, data: PayIn, db: Session = Depends(get_db), user=Depends(current_user)):
    financing = get_visible(db, Financing, item_id, user.id)
    rows = schedule(db, financing)
    paid = installments_paid(db, financing, user.id)
    if paid >= len(rows):
        raise HTTPException(409, "Este financiamento já está quitado.")
    row = rows[paid]
    add_transaction(
        db, user.id, day=data.date, account_id=financing.account_id, owner_id=financing.owner_user_id, kind="divida",
        amount_cents=row.payment + row.fee, description=f"Parcela {row.number}: {financing.name}",
        hidden=financing.hidden, financing_id=financing.id, installment_no=row.number,
    )
    record(db, user.id, "pagou", "financiamento", financing.id, {"parcela": row.number}, private=financing.hidden)
    touch(db, "compromissos")
    db.commit()
    return serialize(db, financing, user.id)


@router.post("/{item_id}/amortizar")
def amortize(item_id: int, data: ExtraIn, db: Session = Depends(get_db), user=Depends(current_user)):
    financing = get_visible(db, Financing, item_id, user.id)
    if data.date is None:
        raise HTTPException(422, "Informe a data da amortização.")
    paid = installments_paid(db, financing, user.id)
    db.add(FinancingExtra(financing_id=financing.id, after_installment=max(paid, 1),
                          amount_cents=data.amount_cents, keep_term=data.keep_term))
    add_transaction(
        db, user.id, day=data.date, account_id=financing.account_id, owner_id=financing.owner_user_id, kind="divida",
        amount_cents=data.amount_cents, description=f"Amortização extra: {financing.name}",
        hidden=financing.hidden, financing_id=financing.id,
    )
    record(db, user.id, "amortizou", "financiamento", financing.id, private=financing.hidden)
    touch(db, "compromissos")
    db.commit()
    return serialize(db, financing, user.id)
