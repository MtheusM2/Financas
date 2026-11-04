from datetime import date, datetime

from sqlalchemy import BigInteger, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, created_at_column


class Reconciliation(Base):
    """Conferencia: saldo real do banco contra o saldo calculado pelo sistema."""
    __tablename__ = "reconciliations"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    real_cents: Mapped[int] = mapped_column(BigInteger)
    system_cents: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at_column()


class ImportRule(Base):
    """Aprendizado: extratos com este texto recebem o mesmo tipo e categoria."""
    __tablename__ = "import_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
