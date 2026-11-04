from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Challenge(Base):
    __tablename__ = "challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    # guardar: soma de aportes | investir: valor atual dos investimentos | livre: progresso informado
    metric: Mapped[str] = mapped_column(String(10))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reward_cents: Mapped[int] = mapped_column(BigInteger)
    reward_label: Mapped[str] = mapped_column(String(80))
    multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    target_cents: Mapped[int] = mapped_column(BigInteger)
    initial_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    manual_progress_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    term_months: Mapped[int | None] = mapped_column(Integer)
    monthly_cents: Mapped[int | None] = mapped_column(BigInteger)
    start_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="ativo")  # ativo | concluido | cancelado
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reward_tx_id: Mapped[int | None] = mapped_column(Integer)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
