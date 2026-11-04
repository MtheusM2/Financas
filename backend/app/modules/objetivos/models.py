from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Goal(Base):
    """Objetivo individual (com dono) ou em conjunto (sem dono)."""
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    target_cents: Mapped[int] = mapped_column(BigInteger)
    initial_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    start_date: Mapped[date] = mapped_column(Date)
    term_months: Mapped[int | None] = mapped_column(Integer)
    monthly_cents: Mapped[int | None] = mapped_column(BigInteger)
    monthly_rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    # Divisao do aporte: {"id do usuario": porcentagem}.
    shares: Mapped[dict] = mapped_column(JSON, default=dict)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # A reserva de emergencia e um objetivo especial, com meta em meses de gastos.
    is_reserve: Mapped[bool] = mapped_column(Boolean, default=False)
    target_months: Mapped[int | None] = mapped_column(Integer)
