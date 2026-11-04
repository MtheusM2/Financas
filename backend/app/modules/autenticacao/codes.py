"""Codigos enviados por e-mail: expiracao, reenvio limitado e bloqueio."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import now
from app.core.email import send_email
from app.modules.autenticacao.models import VerificationCode

SUBJECTS = {"cadastro": "Confirme seu e-mail", "recuperacao": "Recuperação de senha"}


def _hash(email: str, purpose: str, code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{email}:{purpose}:{code}".encode(), hashlib.sha256).hexdigest()


def _locked(row: VerificationCode) -> None:
    if row.locked_until and row.locked_until > now():
        seconds = int((row.locked_until - now()).total_seconds())
        raise HTTPException(429, {"mensagem": "Muitas tentativas. Aguarde para tentar de novo.", "aguarde_segundos": seconds})


def issue_code(db: Session, email: str, purpose: str) -> dict:
    """Envia um codigo novo. O anterior deixa de valer e o timer recomeca."""
    settings = get_settings()
    row = db.scalar(select(VerificationCode).where(
        VerificationCode.email == email, VerificationCode.purpose == purpose
    ).with_for_update())
    current = now()
    if row is None:
        row = VerificationCode(email=email, purpose=purpose, resend_count=0, attempts=0)
        db.add(row)
    else:
        _locked(row)
        idle = row.last_sent_at and current - row.last_sent_at > timedelta(minutes=settings.code_lock_minutes)
        if row.locked_until or idle:
            row.resend_count, row.locked_until = 0, None
        elif row.last_sent_at:
            if row.resend_count >= settings.code_max_resends:
                row.locked_until = current + timedelta(minutes=settings.code_lock_minutes)
                row.code_hash = None
                db.commit()
                _locked(row)
            row.resend_count += 1

    code = f"{secrets.randbelow(10**6):06d}"
    row.code_hash = _hash(email, purpose, code)
    row.expires_at = current + timedelta(seconds=settings.code_ttl_seconds)
    row.last_sent_at = current
    row.attempts = 0
    try:
        send_email(email, SUBJECTS[purpose], f"Seu código é {code}. Ele expira em {settings.code_ttl_seconds} segundos.")
    except OSError as error:
        db.rollback()
        raise HTTPException(503, "Não foi possível enviar o e-mail agora.") from error
    db.commit()
    return {
        "expira_em_segundos": settings.code_ttl_seconds,
        "reenvios_restantes": settings.code_max_resends - row.resend_count,
    }


def check_code(db: Session, email: str, purpose: str, code: str) -> None:
    """Confere o codigo e o consome. Erra com a mesma mensagem em qualquer caso."""
    settings = get_settings()
    row = db.scalar(select(VerificationCode).where(
        VerificationCode.email == email, VerificationCode.purpose == purpose
    ).with_for_update())
    invalid = HTTPException(400, "Código inválido ou expirado.")
    if row is None:
        raise invalid
    _locked(row)
    if not row.code_hash or row.expires_at is None or row.expires_at <= now():
        raise invalid
    if not hmac.compare_digest(row.code_hash, _hash(email, purpose, code)):
        row.attempts += 1
        if row.attempts >= settings.code_max_attempts:
            row.code_hash = None
            row.locked_until = now() + timedelta(minutes=settings.code_lock_minutes)
        db.commit()
        raise invalid
    db.delete(row)
    db.flush()
