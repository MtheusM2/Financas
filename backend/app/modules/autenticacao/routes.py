from datetime import timedelta
from typing import Literal

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, now
from app.modules.auditoria.models import record
from app.modules.autenticacao.codes import check_code, issue_code
from app.modules.autenticacao.deps import COOKIE, current_user, hash_token, start_session
from app.modules.autenticacao.models import DEFAULT_PREFS, AuthSession, User

router = APIRouter(prefix="/api/autenticacao", tags=["autenticacao"])
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("senha-ficticia-para-igualar-o-tempo")


def _lower(value: str) -> str:
    return value.strip().lower()


class EmailIn(BaseModel):
    email: EmailStr
    _norm = field_validator("email")(_lower)


class SignupIn(EmailIn):
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=200)


class VerifyIn(EmailIn):
    code: str = Field(pattern=r"^\d{6}$")


class ResendIn(EmailIn):
    purpose: Literal["cadastro", "recuperacao"]


class LoginIn(EmailIn):
    password: str = Field(max_length=200)
    totp: str | None = Field(default=None, max_length=8)


class ResetIn(VerifyIn):
    password: str = Field(min_length=10, max_length=200)


class TotpIn(BaseModel):
    totp: str = Field(pattern=r"^\d{6}$")


class PrefsIn(BaseModel):
    blocos: list[str] | None = None
    ocultos: list[str] | None = None
    escopo: str | None = Field(default=None, max_length=40)
    alertas_email: bool | None = None


def public(user: User) -> dict:
    return {
        "id": user.id, "email": user.email, "nome": user.name,
        "dois_fatores": user.totp_enabled, "preferencias": {**DEFAULT_PREFS, **(user.prefs or {})},
    }


@router.post("/cadastro")
def signup(data: SignupIn, db: Session = Depends(get_db)):
    if data.email not in get_settings().allowed_email_set:
        raise HTTPException(403, "Este e-mail não está autorizado.")
    user = db.scalar(select(User).where(User.email == data.email))
    if user and user.email_verified:
        raise HTTPException(409, "Este e-mail já tem cadastro. Use a recuperação de senha.")
    if user is None:
        user = User(email=data.email, name=data.name, password_hash=hasher.hash(data.password),
                    prefs=dict(DEFAULT_PREFS))
        db.add(user)
    else:
        user.name, user.password_hash = data.name, hasher.hash(data.password)
    db.flush()
    record(db, user.id, "cadastro_iniciado", "usuario", user.id)
    return issue_code(db, data.email, "cadastro")


@router.post("/verificar")
def verify(data: VerifyIn, response: Response, db: Session = Depends(get_db)):
    check_code(db, data.email, "cadastro", data.code)
    user = db.scalar(select(User).where(User.email == data.email))
    if user is None:
        raise HTTPException(400, "Código inválido ou expirado.")
    user.email_verified = True
    from app.modules.contas.service import ensure_user_accounts
    ensure_user_accounts(db, user)
    start_session(db, user, response)
    record(db, user.id, "email_confirmado", "usuario", user.id)
    db.commit()
    return public(user)


@router.post("/reenviar")
def resend(data: ResendIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    eligible = user is not None and (user.email_verified if data.purpose == "recuperacao" else not user.email_verified)
    if not eligible:
        # A mesma resposta para e-mail existente ou nao.
        settings = get_settings()
        return {"expira_em_segundos": settings.code_ttl_seconds, "reenvios_restantes": settings.code_max_resends}
    return issue_code(db, data.email, data.purpose)


@router.post("/entrar")
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    wrong = HTTPException(401, "E-mail ou senha incorretos.")
    user = db.scalar(select(User).where(User.email == data.email).with_for_update())
    if user is None:
        try:
            hasher.verify(DUMMY_HASH, data.password)
        except Argon2Error:
            pass
        raise wrong
    if user.locked_until and user.locked_until > now():
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    try:
        hasher.verify(user.password_hash, data.password)
    except (Argon2Error, InvalidHashError):
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_attempts:
            user.locked_until = now() + timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
        record(db, user.id, "login_falhou", "usuario", user.id)
        db.commit()
        raise wrong from None
    if not user.email_verified:
        raise HTTPException(403, "email_nao_confirmado")
    if user.totp_enabled:
        if not data.totp:
            raise HTTPException(401, "codigo_2fa_necessario")
        if not pyotp.TOTP(user.totp_secret).verify(data.totp, valid_window=1):
            user.failed_logins += 1
            if user.failed_logins >= settings.login_max_attempts:
                user.locked_until = now() + timedelta(minutes=settings.login_lock_minutes)
                user.failed_logins = 0
            db.commit()
            raise wrong
    user.failed_logins, user.locked_until = 0, None
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    start_session(db, user, response)
    record(db, user.id, "login", "usuario", user.id)
    db.commit()
    return public(user)


@router.post("/sair")
def logout(response: Response, sessao: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    if sessao:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(sessao)))
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/eu")
def me(user: User = Depends(current_user)):
    return public(user)


@router.get("/usuarios")
def users(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(User).where(User.email_verified.is_(True)).order_by(User.id))
    return [{"id": u.id, "nome": u.name} for u in rows]


@router.post("/recuperar")
def recover(data: EmailIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email, User.email_verified.is_(True)))
    settings = get_settings()
    if user is None:
        return {"expira_em_segundos": settings.code_ttl_seconds, "reenvios_restantes": settings.code_max_resends}
    return issue_code(db, data.email, "recuperacao")


@router.post("/redefinir")
def reset(data: ResetIn, db: Session = Depends(get_db)):
    check_code(db, data.email, "recuperacao", data.code)
    user = db.scalar(select(User).where(User.email == data.email))
    if user is None:
        raise HTTPException(400, "Código inválido ou expirado.")
    user.password_hash = hasher.hash(data.password)
    user.failed_logins, user.locked_until = 0, None
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    record(db, user.id, "senha_redefinida", "usuario", user.id)
    db.commit()
    return {"ok": True}


@router.post("/2fa/iniciar")
def totp_start(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.totp_enabled:
        raise HTTPException(409, "A confirmação em dois passos já está ativa.")
    user.totp_secret = pyotp.random_base32()
    db.merge(user)
    db.commit()
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name="Financas do Casal")
    return {"chave": user.totp_secret, "uri": uri}


@router.post("/2fa/ativar")
def totp_enable(data: TotpIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(data.totp, valid_window=1):
        raise HTTPException(400, "Código inválido.")
    user.totp_enabled = True
    db.merge(user)
    record(db, user.id, "2fa_ativado", "usuario", user.id)
    db.commit()
    return public(user)


@router.post("/2fa/desativar")
def totp_disable(data: TotpIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.totp_enabled or not pyotp.TOTP(user.totp_secret).verify(data.totp, valid_window=1):
        raise HTTPException(400, "Código inválido.")
    user.totp_enabled, user.totp_secret = False, None
    db.merge(user)
    record(db, user.id, "2fa_desativado", "usuario", user.id)
    db.commit()
    return public(user)


@router.patch("/preferencias")
def preferences(data: PrefsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user.prefs = {**DEFAULT_PREFS, **(user.prefs or {}), **data.model_dump(exclude_none=True)}
    db.merge(user)
    db.commit()
    return public(user)
