import hashlib
import secrets
from datetime import timedelta

from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, now
from app.modules.autenticacao.models import AuthSession, User

COOKIE = "sessao"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: Session, user: User, response: Response) -> None:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        token_hash=hash_token(token), user_id=user.id,
        expires_at=now() + timedelta(days=settings.session_days),
    ))
    response.set_cookie(
        COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="strict",
        max_age=settings.session_days * 86400, path="/",
    )


def current_user(sessao: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> User:
    if sessao:
        row = db.scalar(select(AuthSession).where(
            AuthSession.token_hash == hash_token(sessao), AuthSession.expires_at > now()
        ))
        if row:
            user = db.get(User, row.user_id)
            if user and user.email_verified:
                return user
    raise HTTPException(401, "Faça login para continuar.")
