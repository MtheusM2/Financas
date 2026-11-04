import base64
import binascii
import csv
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.visibility import get_visible
from app.modules.auditoria.models import record
from app.modules.autenticacao.deps import current_user
from app.modules.conciliacao.models import ImportRule, Reconciliation
from app.modules.conciliacao.parse import Line, StatementError, line_ids, normalize, parse_statement
from app.modules.contas.models import Account
from app.modules.contas.service import Scope
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import add_transaction, after_change, check_account, tx_filter

router = APIRouter(prefix="/api/conciliacao", tags=["conciliacao"])

MAX_FILE_BYTES = 2_000_000
MATCH_WINDOW_DAYS = 3
Kind = Literal["renda", "gasto", "fora_escopo", "divida", "investimento", "guardado", "lazer"]


class PreviewIn(BaseModel):
    account_id: int
    content_base64: str = Field(max_length=MAX_FILE_BYTES * 2)


class LineIn(BaseModel):
    date: date
    amount_cents: int
    description: str = Field(default="", max_length=160)
    fitid: str = Field(default="", max_length=200)
    kind: Kind
    category_id: Optional[int] = None
    match_id: Optional[int] = None
    remember: bool = False


class ConfirmIn(BaseModel):
    account_id: int
    lines: list[LineIn] = Field(max_length=5000)


class BalanceIn(BaseModel):
    account_id: int
    date: date
    real_cents: int


def system_balance(db: Session, account: Account, day: date, viewer_id: int) -> int:
    rows = db.execute(
        select(Transaction.kind, func.sum(Transaction.amount_cents))
        .where(Transaction.account_id == account.id, Transaction.date <= day, Transaction.settled.is_(True),
               tx_filter(viewer_id, Scope("casal")))
        .group_by(Transaction.kind)
    )
    return account.opening_balance_cents + sum(int(t) if k == "renda" else -int(t) for k, t in rows)


def find_match(db: Session, line: Line, account_id: int, viewer_id: int, taken: set[int]) -> Transaction | None:
    """Lancamento manual ou previsto de mesmo valor e sentido, com data proxima e sem extrato ligado."""
    income = line.amount_cents > 0
    stmt = select(Transaction).where(
        Transaction.account_id == account_id, Transaction.amount_cents == abs(line.amount_cents),
        Transaction.external_id.is_(None),
        Transaction.date.between(line.date - timedelta(days=MATCH_WINDOW_DAYS), line.date + timedelta(days=MATCH_WINDOW_DAYS)),
        (Transaction.kind == "renda") if income else (Transaction.kind != "renda"),
        tx_filter(viewer_id, Scope("casal")),
    ).order_by(func.abs(Transaction.date - line.date), Transaction.id)
    for tx in db.scalars(stmt):
        if tx.id not in taken:
            return tx
    return None


@router.post("/previa")
def preview(data: PreviewIn, db: Session = Depends(get_db), user=Depends(current_user)):
    """So le e compara: nada e gravado ate a confirmacao."""
    account = check_account(db, data.account_id, user.id)
    try:
        raw = base64.b64decode(data.content_base64, validate=True)
    except binascii.Error as error:
        raise HTTPException(422, "Arquivo inválido.") from error
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(413, "Arquivo maior que 2 MB.")
    if raw.lstrip()[:5] == b"%PDF-":
        raise HTTPException(422, "Este arquivo é um PDF. Holerite se importa na tela Holerites; o extrato do banco precisa ser OFX ou CSV.")
    try:
        statement = parse_statement(raw)
    except StatementError as error:
        raise HTTPException(422, str(error)) from error
    except (csv.Error, ValueError, UnicodeError) as error:
        # Arquivo que nao e extrato: mensagem clara em vez de "Erro inesperado".
        raise HTTPException(422, "Não consegui ler este arquivo como extrato. Exporte do banco em OFX ou CSV.") from error

    ids = line_ids(account.id, statement.lines)
    existing = set(db.scalars(select(Transaction.external_id).where(Transaction.external_id.in_(ids))))
    rules = {r.pattern: r for r in db.scalars(select(ImportRule))}
    taken: set[int] = set()
    result = []
    for line, external_id in zip(statement.lines, ids):
        rule = rules.get(normalize(line.description))
        kind = rule.kind if rule and (rule.kind == "renda") == (line.amount_cents > 0) else ("renda" if line.amount_cents > 0 else "gasto")
        item = {
            "data": line.date, "valor": line.amount_cents, "descricao": line.description, "fitid": line.fitid,
            "tipo": kind, "categoria_id": rule.category_id if rule else None, "situacao": "nova", "conciliar_com": None,
        }
        if external_id in existing:
            item["situacao"] = "duplicada"
        else:
            match = find_match(db, line, account.id, user.id, taken)
            if match:
                taken.add(match.id)
                item.update(situacao="conciliada", tipo=match.kind, categoria_id=match.category_id,
                            conciliar_com={"id": match.id, "data": match.date, "descricao": match.description, "quitado": match.settled})
        result.append(item)
    balance = None
    if statement.balance_cents is not None:
        day = statement.balance_date or max(line.date for line in statement.lines)
        balance = {"data": day, "real": statement.balance_cents}
    return {"linhas": result, "saldo_banco": balance}


@router.post("/confirmar")
def confirm(data: ConfirmIn, db: Session = Depends(get_db), user=Depends(current_user)):
    account = check_account(db, data.account_id, user.id)
    lines = [Line(l.date, l.amount_cents, l.description, l.fitid) for l in data.lines]
    ids = line_ids(account.id, lines)
    existing = set(db.scalars(select(Transaction.external_id).where(Transaction.external_id.in_(ids))))
    created = linked = skipped = 0
    for line, external_id in zip(data.lines, ids):
        if external_id in existing or line.amount_cents == 0:
            skipped += 1
            continue
        if line.match_id:
            tx = get_visible(db, Transaction, line.match_id, user.id)
            if tx.external_id or tx.account_id != account.id or tx.amount_cents != abs(line.amount_cents):
                raise HTTPException(409, "A conciliação mudou. Refaça a importação.")
            old = tx.date
            if tx.competence_date is None and old != line.date:
                tx.competence_date = old
            tx.external_id, tx.settled, tx.date = external_id, True, line.date
            after_change(db, [old, line.date])
            linked += 1
        else:
            if (line.amount_cents > 0) != (line.kind == "renda"):
                raise HTTPException(422, "O tipo não combina com o sinal do valor.")
            add_transaction(
                db, user.id, day=line.date, account_id=account.id, owner_id=account.owner_user_id or user.id, kind=line.kind,
                amount_cents=abs(line.amount_cents), description=line.description or "Extrato", category_id=line.category_id,
                external_id=external_id,
            )
            created += 1
        pattern = normalize(line.description)
        if line.remember and pattern:
            db.execute(insert(ImportRule).values(pattern=pattern, kind=line.kind, category_id=line.category_id)
                       .on_conflict_do_update(index_elements=["pattern"], set_={"kind": line.kind, "category_id": line.category_id}))
    record(db, user.id, "importou", "extrato", account.id, {"criados": created, "conciliados": linked, "ignorados": skipped})
    db.commit()
    return {"criados": created, "conciliados": linked, "ignorados": skipped}


def serialize_reconciliation(r: Reconciliation) -> dict:
    return {"id": r.id, "conta_id": r.account_id, "data": r.date, "real": r.real_cents, "sistema": r.system_cents,
            "diferenca": r.real_cents - r.system_cents, "confere": r.real_cents == r.system_cents}


@router.post("/saldo")
def check_balance(data: BalanceIn, db: Session = Depends(get_db), user=Depends(current_user)):
    account = check_account(db, data.account_id, user.id)
    row = Reconciliation(account_id=account.id, user_id=user.id, date=data.date, real_cents=data.real_cents,
                         system_cents=system_balance(db, account, data.date, user.id))
    db.add(row)
    db.flush()
    record(db, user.id, "conferiu_saldo", "conta", account.id, private=True)
    db.commit()
    return serialize_reconciliation(row)


@router.get("/historico")
def history(db: Session = Depends(get_db), user=Depends(current_user)):
    # So as conferencias da propria pessoa: a diferenca poderia revelar itens ocultos.
    rows = db.scalars(select(Reconciliation).where(Reconciliation.user_id == user.id)
                      .order_by(Reconciliation.date.desc(), Reconciliation.id.desc()).limit(50))
    return [serialize_reconciliation(r) for r in rows]
