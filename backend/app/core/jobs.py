"""Fila de tarefas em segundo plano, guardada no proprio banco."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base, now


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    # Impede a mesma tarefa de entrar duas vezes, por exemplo backup:2026-11-01.
    dedupe_key: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


def enqueue(db: Session, kind: str, dedupe_key: str) -> None:
    db.execute(
        insert(Job).values(kind=kind, dedupe_key=dedupe_key, status="pending", attempts=0, run_at=now())
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )


def next_job(db: Session) -> Job | None:
    # SKIP LOCKED: varios trabalhadores nunca pegam a mesma tarefa.
    stmt = (
        select(Job)
        .where(Job.status == "pending", Job.run_at <= now())
        .order_by(Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return db.scalar(stmt)
