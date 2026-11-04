from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Financing(Base):
    __tablename__ = "financings"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    asset_value_cents: Mapped[int] = mapped_column(BigInteger)
    down_payment_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    annual_rate_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    system: Mapped[str] = mapped_column(String(5))  # SAC | PRICE
    term_months: Mapped[int] = mapped_column(Integer)
    monthly_fee_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    first_due: Mapped[date] = mapped_column(Date)
    paid_before: Mapped[int] = mapped_column(Integer, default=0)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FinancingExtra(Base):
    """Amortizacao extra realmente feita, aplicada apos a parcela indicada."""
    __tablename__ = "financing_extras"
    id: Mapped[int] = mapped_column(primary_key=True)
    financing_id: Mapped[int] = mapped_column(ForeignKey("financings.id", ondelete="CASCADE"), index=True)
    after_installment: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    keep_term: Mapped[bool] = mapped_column(Boolean, default=False)
