from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MonthClosing(Base):
    """Registro do mes visto por cada pessoa, para o historico respeitar o que ela oculta dela."""
    __tablename__ = "month_closings"
    __table_args__ = (UniqueConstraint("year", "month", "viewer_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    viewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10))  # fechado | reaberto
    snapshot: Mapped[dict] = mapped_column(JSON)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
