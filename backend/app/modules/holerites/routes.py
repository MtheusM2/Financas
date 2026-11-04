import base64
import binascii
import hashlib
import json
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import get_db, now
from app.core.visibility import get_visible, visible_clause
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.holerites.extract import MAX_FILE_BYTES, extract_words
from app.modules.holerites.analise import changes, fgts_status
from app.modules.holerites.models import FgtsBalance, Payslip, PayslipLabel
from app.modules.holerites.parse import MAX_ITEMS, PayslipError, labels, norm, parse_words
from app.modules.holerites.vinculo import ROLES, suggest, summary
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import add_transaction, after_change, check_account, clamp_day, next_month

router = APIRouter(prefix="/api/holerites", tags=["holerites"])

MAX_CENTS = 100_000_000_00  # R$ 100 milhoes: acima disso e erro de leitura
Cents = Field(ge=0, le=MAX_CENTS)


class PreviewIn(BaseModel):
    # Base64 ocupa 4/3 do arquivo.
    content_base64: str = Field(max_length=MAX_FILE_BYTES * 4 // 3 + 8)


class ItemIn(BaseModel):
    codigo: str = Field(default="", max_length=12)
    descricao: str = Field(min_length=1, max_length=80)
    referencia: str = Field(default="", max_length=12)
    tipo: Literal["provento", "desconto"]
    valor: int = Cents


class IncomeIn(BaseModel):
    account_id: int
    date: date
    category_id: Optional[int] = None
    hidden: bool = False


class LinkIn(BaseModel):
    transaction_id: int
    papel: Literal[ROLES]


class LearnIn(BaseModel):
    rotulo: str = Field(min_length=3, max_length=60)
    campo: Literal["total_vencimentos", "total_descontos", "liquido", "salario_base", "base_inss", "base_fgts",
                   "fgts_mes", "base_irrf"]


class FgtsIn(BaseModel):
    date: date
    balance_cents: int = Cents


class PayslipIn(BaseModel):
    empresa: str = Field(default="", max_length=160)
    cnpj: str = Field(default="", max_length=20)
    referencia: int
    itens: list[ItemIn] = Field(default_factory=list, max_length=MAX_ITEMS)
    total_vencimentos: int = Cents
    total_descontos: int = Cents
    liquido: int = Cents
    salario_base: Optional[int] = Field(default=None, ge=0, le=MAX_CENTS)
    base_inss: Optional[int] = Field(default=None, ge=0, le=MAX_CENTS)
    base_fgts: Optional[int] = Field(default=None, ge=0, le=MAX_CENTS)
    fgts_mes: Optional[int] = Field(default=None, ge=0, le=MAX_CENTS)
    base_irrf: Optional[int] = Field(default=None, ge=0, le=MAX_CENTS)
    lancar_renda: Optional[IncomeIn] = None
    vinculos: list[LinkIn] = Field(default_factory=list, max_length=20)
    aprender: list[LearnIn] = Field(default_factory=list, max_length=12)

    @field_validator("referencia")
    @classmethod
    def valid_month(cls, value: int) -> int:
        if not (190001 <= value <= 210012 and 1 <= value % 100 <= 12):
            raise ValueError("Mês de referência inválido.")
        return value


def fingerprint(owner_id: int, data: dict) -> str:
    """Mesmos valores do mesmo mes e empresa: e o mesmo holerite."""
    key = {k: data.get(k) for k in ("cnpj", "referencia", "total_vencimentos", "total_descontos", "liquido")}
    key["itens"] = sorted((i["tipo"], i["valor"], i["descricao"].upper()) for i in data.get("itens", []))
    raw = json.dumps([owner_id, key], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def preview_payload(slip: dict) -> dict:
    """Formato que a tela de revisao edita e devolve para /holerites."""
    totals = slip["totais"]
    return {
        "empresa": slip["empresa"], "cnpj": slip["cnpj"], "referencia": slip["referencia"], "itens": slip["itens"],
        **{k: totals.get(k) for k in ("total_vencimentos", "total_descontos", "liquido", "salario_base",
                                      "base_inss", "base_fgts", "fgts_mes", "base_irrf")},
        "avisos": slip["avisos"], "conferido": slip["conferido"], "desconhecidos": slip["desconhecidos"],
    }


def learned_labels(db: Session) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for label, key in db.execute(select(PayslipLabel.label, PayslipLabel.field)):
        found.setdefault(key, []).append(label)
    return found


def previous_payslip(db: Session, user_id: int, cnpj: str, reference: int) -> Payslip | None:
    """Holerite anterior da mesma empresa, para comparar o que mudou."""
    return db.scalar(select(Payslip).where(
        visible_clause(Payslip, user_id), Payslip.owner_user_id == user_id, Payslip.cnpj == cnpj,
        Payslip.reference_month < reference,
    ).order_by(Payslip.reference_month.desc(), Payslip.id.desc()).limit(1))


def changes_since(db: Session, user_id: int, slip: dict) -> list[dict]:
    if not slip.get("cnpj") or slip.get("referencia") is None:
        return []
    previous = previous_payslip(db, user_id, slip["cnpj"], slip["referencia"])
    if previous is None:
        return []
    return changes({"itens": previous.items, "liquido": previous.net_cents}, slip)


def linked_ids(db: Session, user_id: int) -> set[int]:
    """Rendas ja ligadas a algum holerite da pessoa: cada uma so pode ser ligada uma vez."""
    ids: set[int] = set()
    for links, tx_id in db.execute(select(Payslip.links, Payslip.transaction_id).where(Payslip.owner_user_id == user_id)):
        ids.update(l["id"] for l in links or [])
        if tx_id:
            ids.add(tx_id)
    return ids


def candidates(db: Session, user_id: int, reference: int) -> list[dict]:
    """Rendas da propria pessoa do mes do holerite ate meados do mes seguinte ao pagamento."""
    start = clamp_day(reference, 1)
    end = clamp_day(next_month(reference), 31) + timedelta(days=15)
    taken = linked_ids(db, user_id)
    rows = db.scalars(select(Transaction).where(
        Transaction.owner_user_id == user_id, Transaction.kind == "renda",
        Transaction.date.between(start, end), visible_clause(Transaction, user_id),
    ).order_by(Transaction.date, Transaction.id).limit(60))
    return [{"id": t.id, "data": t.date, "valor": t.amount_cents, "descricao": t.description}
            for t in rows if t.id not in taken]


def link_rows(db: Session, p: Payslip) -> list[dict]:
    roles = {l["id"]: l["papel"] for l in p.links or []}
    if p.transaction_id:
        roles.setdefault(p.transaction_id, "liquido")
    if not roles:
        return []
    rows = db.scalars(select(Transaction).where(Transaction.id.in_(roles), Transaction.owner_user_id == p.owner_user_id))
    return [{"id": t.id, "papel": roles[t.id], "data": t.date, "valor": t.amount_cents, "descricao": t.description}
            for t in rows]


def serialize(p: Payslip, db: Session) -> dict:
    links = link_rows(db, p)
    return {
        "vinculos": links, "resumo": summary(p.net_cents, p.items, links),
        "id": p.id, "empresa": p.company, "cnpj": p.cnpj, "referencia": p.reference_month,
        "total_vencimentos": p.gross_cents, "total_descontos": p.deductions_cents, "liquido": p.net_cents,
        "salario_base": p.base_salary_cents, "base_inss": p.inss_base_cents, "base_fgts": p.fgts_base_cents,
        "fgts_mes": p.fgts_cents, "base_irrf": p.irrf_base_cents, "itens": p.items, "lancamento_id": p.transaction_id,
    }


def own(db: Session, payslip_id: int, user_id: int) -> Payslip:
    item = get_visible(db, Payslip, payslip_id, user_id)
    if item.owner_user_id != user_id:
        raise HTTPException(404, "Não encontrado.")
    return item


@router.post("/previa")
def preview(data: PreviewIn, db: Session = Depends(get_db), user=Depends(current_user)):
    """So le o PDF e devolve o que achou: nada e gravado e o arquivo e descartado."""
    try:
        raw = base64.b64decode(data.content_base64, validate=True)
    except binascii.Error as error:
        raise HTTPException(422, "Arquivo inválido.") from error
    try:
        slips = [preview_payload(s.as_dict()) for s in parse_words(extract_words(raw), learned_labels(db))]
    except PayslipError as error:
        raise HTTPException(422, str(error)) from error
    for slip in slips:
        slip["candidatos"] = []
        slip["mudancas"] = changes_since(db, user.id, slip)
        if slip["referencia"] is not None:
            found_rows = candidates(db, user.id, slip["referencia"])
            roles = suggest(slip["liquido"] or 0, slip["itens"], found_rows)
            slip["candidatos"] = [{**c, "sugestao": roles.get(c["id"])} for c in found_rows]
            found = db.scalar(select(Payslip.id).where(Payslip.owner_user_id == user.id,
                                                       Payslip.fingerprint == fingerprint(user.id, slip)))
            slip["ja_importado"] = found is not None
        else:
            slip["ja_importado"] = False
    record(db, user.id, "leu_holerite", "holerite", None, {"holerites": len(slips)}, private=True)
    db.commit()
    return {"holerites": slips}


@router.post("")
def create(data: PayslipIn, db: Session = Depends(get_db), user=Depends(current_user)):
    payload = data.model_dump(mode="json")
    mark = fingerprint(user.id, payload)
    if db.scalar(select(Payslip.id).where(Payslip.owner_user_id == user.id, Payslip.fingerprint == mark)):
        raise HTTPException(409, "Este holerite já foi importado.")
    slip = Payslip(
        owner_user_id=user.id, hidden=True, company=data.empresa.strip(), cnpj=data.cnpj.strip(),
        reference_month=data.referencia, gross_cents=data.total_vencimentos, deductions_cents=data.total_descontos,
        net_cents=data.liquido, base_salary_cents=data.salario_base, inss_base_cents=data.base_inss,
        fgts_base_cents=data.base_fgts, fgts_cents=data.fgts_mes, irrf_base_cents=data.base_irrf,
        items=payload["itens"], fingerprint=mark,
    )
    known = {s for synonyms in labels()["totais"].values() for s in synonyms}
    for learn in data.aprender:
        label = norm(learn.rotulo)
        if len(label) >= 3 and label not in known:
            # Vale para os proximos holerites de qualquer empresa; a ultima escolha prevalece.
            db.execute(insert(PayslipLabel).values(label=label, field=learn.campo, created_by=user.id, created_at=now())
                       .on_conflict_do_update(index_elements=["label"], set_={"field": learn.campo}))
    year, month = divmod(data.referencia, 100)
    roles = {l.transaction_id: l.papel for l in data.vinculos}
    if data.lancar_renda and "liquido" in roles.values():
        raise HTTPException(422, "O salário já está ligado a uma renda lançada: não precisa lançar de novo.")
    taken = linked_ids(db, user.id)
    days = []
    for tx_id, role in roles.items():
        tx = get_visible(db, Transaction, tx_id, user.id)
        if tx.owner_user_id != user.id or tx.kind != "renda":
            raise HTTPException(422, "Só dá para ligar rendas suas.")
        if tx_id in taken:
            raise HTTPException(409, "Uma das rendas já está ligada a outro holerite.")
        if role != "beneficio":
            # Adiantamento e salario pertencem ao mes do holerite, mesmo caindo depois.
            tx.competence_date = date(year, month, 1)
            days.append(tx.date)
    slip.links = [{"id": tx_id, "papel": role} for tx_id, role in roles.items()]
    if days:
        after_change(db, days)
    if data.lancar_renda:
        income = data.lancar_renda
        if data.liquido <= 0:
            raise HTTPException(422, "O valor líquido precisa ser maior que zero para lançar como renda.")
        account = check_account(db, income.account_id, user.id)
        name = f"Salário {month:02d}/{year}" + (f" - {slip.company}" if slip.company else "")
        tx = add_transaction(db, user.id, day=income.date, account_id=account.id, owner_id=user.id, kind="renda",
                             amount_cents=data.liquido, description=name[:160], category_id=income.category_id,
                             hidden=income.hidden, settled=income.date <= now().date(),
                             competence_date=date(year, month, 1))
        db.flush()
        slip.transaction_id = tx.id
    db.add(slip)
    db.flush()
    record(db, user.id, "importou", "holerite", slip.id, private=True)
    db.commit()
    return serialize(slip, db)


@router.get("")
def list_payslips(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(Payslip).where(visible_clause(Payslip, user.id), Payslip.owner_user_id == user.id)
                      .order_by(Payslip.reference_month.desc(), Payslip.id.desc()).limit(240))
    return [serialize(p, db) for p in rows]


@router.get("/{payslip_id}")
def get_payslip(payslip_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    return serialize(own(db, payslip_id, user.id), db)


@router.delete("/{payslip_id}")
def delete_payslip(payslip_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    """Apaga so o holerite. O lancamento de renda, se houver, continua e se apaga em Lancamentos."""
    slip = own(db, payslip_id, user.id)
    db.delete(slip)
    record(db, user.id, "apagou", "holerite", payslip_id, private=True)
    db.commit()
    return {"ok": True}


@router.get("/analise/resumo")
def analysis(db: Session = Depends(get_db), user=Depends(current_user)):
    """Evolucao mes a mes, o que mudou em cada holerite e o FGTS (Caixa x holerites)."""
    rows = list(db.scalars(select(Payslip).where(visible_clause(Payslip, user.id), Payslip.owner_user_id == user.id)
                           .order_by(Payslip.reference_month, Payslip.id).limit(240)))
    months, by_company = [], {}
    for p in rows:
        previous = by_company.get(p.cnpj)
        current = {"itens": p.items, "liquido": p.net_cents}
        months.append({
            "id": p.id, "referencia": p.reference_month, "empresa": p.company, "bruto": p.gross_cents,
            "descontos": p.deductions_cents, "liquido": p.net_cents, "fgts_mes": p.fgts_cents,
            "base_inss": p.inss_base_cents, "base_irrf": p.irrf_base_cents,
            "itens": p.items, "mudancas": changes(previous, current) if previous else [],
        })
        by_company[p.cnpj] = current
    balances = [{"id": b.id, "data": b.date, "saldo": b.balance_cents} for b in db.scalars(
        select(FgtsBalance).where(visible_clause(FgtsBalance, user.id), FgtsBalance.owner_user_id == user.id))]
    deposits = [{"referencia": p.reference_month, "valor": p.fgts_cents or 0} for p in rows]
    return {"meses": months, "fgts": fgts_status(balances, deposits, now().date())}


@router.post("/fgts")
def add_fgts(data: FgtsIn, db: Session = Depends(get_db), user=Depends(current_user)):
    row = FgtsBalance(owner_user_id=user.id, hidden=True, date=data.date, balance_cents=data.balance_cents)
    db.add(row)
    db.flush()
    record(db, user.id, "informou_fgts", "fgts", row.id, private=True)
    db.commit()
    return {"id": row.id, "data": row.date, "saldo": row.balance_cents}


@router.delete("/fgts/{balance_id}")
def delete_fgts(balance_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    row = get_visible(db, FgtsBalance, balance_id, user.id)
    if row.owner_user_id != user.id:
        raise HTTPException(404, "Não encontrado.")
    db.delete(row)
    record(db, user.id, "apagou", "fgts", balance_id, private=True)
    db.commit()
    return {"ok": True}
