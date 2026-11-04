from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base, now
from app.core.tracing import request_id_var

SENSITIVE = ("senha", "password", "code", "codigo", "secret", "token", "totp")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: now(), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(32))
    private: Mapped[bool] = mapped_column(Boolean, default=False)
    changes: Mapped[dict | None] = mapped_column(JSON)


def clean(changes: dict | None) -> dict | None:
    if not changes:
        return None
    return {k: v for k, v in changes.items() if not any(word in k.lower() for word in SENSITIVE)}


def record(db: Session, user_id: int | None, action: str, entity: str, entity_id: int | None = None,
           changes: dict | None = None, private: bool = False) -> None:
    db.add(AuditLog(
        user_id=user_id, action=action, entity=entity, entity_id=entity_id,
        request_id=request_id_var.get(), private=private, changes=clean(changes),
    ))
