from sqlalchemy import BigInteger, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CategoryBudget(Base):
    """Teto mensal de uma categoria, do casal (sem dono) ou de uma pessoa."""
    __tablename__ = "category_budgets"
    __table_args__ = (UniqueConstraint("category_id", "owner_user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    limit_cents: Mapped[int] = mapped_column(BigInteger)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
