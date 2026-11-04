from datetime import date, datetime
from datetime import date as Day
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, created_at_column

KINDS = ("renda", "gasto", "fora_escopo", "divida", "investimento", "guardado", "lazer")
OUTFLOW_KINDS = KINDS[1:]


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_tx_date", "date"),
        Index("ix_tx_owner_date", "owner_user_id", "date"),
        Index("ix_tx_account_date", "account_id", "date"),
        UniqueConstraint("rule_id", "occurrence_month"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str | None] = mapped_column(Text)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    # Ocorrencia de uma regra recorrente, no formato AAAAMM.
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("recurring_rules.id", ondelete="SET NULL"))
    occurrence_month: Mapped[int | None] = mapped_column(Integer)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    # Caixa: `date` e quando o dinheiro entra ou sai; False significa previsto (a pagar ou a receber).
    settled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Competencia: mes a que o gasto ou a renda pertence. Vazio: o mesmo de `date`.
    competence_date: Mapped[Optional[Day]] = mapped_column(Date, nullable=True)
    # Identificador da linha do extrato: impede importar a mesma linha duas vezes.
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Vinculos: ids soltos para cada modulo poder ser ligado ou desligado.
    debt_id: Mapped[int | None] = mapped_column(Integer, index=True)
    financing_id: Mapped[int | None] = mapped_column(Integer, index=True)
    installment_no: Mapped[int | None] = mapped_column(Integer)
    investment_id: Mapped[int | None] = mapped_column(Integer, index=True)
    goal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    challenge_id: Mapped[int | None] = mapped_column(Integer, index=True)


class RecurringRule(Base):
    """Dia fixo opcional: gera uma ocorrencia por mes, que pode ser editada sozinha."""
    __tablename__ = "recurring_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(160), default="")
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    day_of_month: Mapped[int] = mapped_column(Integer)
    start_month: Mapped[int] = mapped_column(Integer)
    end_month: Mapped[int | None] = mapped_column(Integer)
    last_generated_month: Mapped[int | None] = mapped_column(Integer)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MonthlyTotal(Base):
    """Totais prontos: o painel inicial le daqui sem somar o historico."""
    __tablename__ = "monthly_totals"
    __table_args__ = (Index("ix_totals_period", "year", "month"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))
    hidden: Mapped[bool] = mapped_column(Boolean)
    total_cents: Mapped[int] = mapped_column(BigInteger)
