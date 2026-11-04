from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, created_at_column


class Payslip(Base):
    """Holerite revisado e confirmado. O PDF nao e guardado: so os valores."""
    __tablename__ = "payslips"
    __table_args__ = (UniqueConstraint("owner_user_id", "fingerprint"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Sempre oculto: holerite e dado pessoal e so o dono ve.
    hidden: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()
    company: Mapped[str] = mapped_column(String(160), default="")
    cnpj: Mapped[str] = mapped_column(String(20), default="")
    reference_month: Mapped[int] = mapped_column(Integer)  # AAAAMM
    gross_cents: Mapped[int] = mapped_column(BigInteger)
    deductions_cents: Mapped[int] = mapped_column(BigInteger)
    net_cents: Mapped[int] = mapped_column(BigInteger)
    base_salary_cents: Mapped[int | None] = mapped_column(BigInteger)
    inss_base_cents: Mapped[int | None] = mapped_column(BigInteger)
    fgts_base_cents: Mapped[int | None] = mapped_column(BigInteger)
    fgts_cents: Mapped[int | None] = mapped_column(BigInteger)
    irrf_base_cents: Mapped[int | None] = mapped_column(BigInteger)
    items: Mapped[list] = mapped_column(JSON, default=list)
    # Lancamento de renda criado junto, se a pessoa pediu.
    transaction_id: Mapped[int | None] = mapped_column(Integer)
    # Rendas ja lancadas ligadas a este holerite: [{"id", "papel"}].
    links: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # Impede gravar o mesmo holerite duas vezes.
    fingerprint: Mapped[str] = mapped_column(String(64))


class PayslipLabel(Base):
    """Rotulo aprendido na revisao ("este valor e o liquido"). So o texto do rotulo, sem valores."""
    __tablename__ = "payslip_labels"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(60), unique=True)
    field: Mapped[str] = mapped_column(String(30))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()


class FgtsBalance(Base):
    """Saldo de FGTS informado pela pessoa (extrato da Caixa)."""
    __tablename__ = "fgts_balances"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=True)
    date: Mapped[date] = mapped_column(Date)
    balance_cents: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at_column()
