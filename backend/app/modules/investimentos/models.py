from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Investment(Base):
    __tablename__ = "investments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(60), default="")
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    initial_contributed_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    current_value_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    value_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monthly_plan_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
