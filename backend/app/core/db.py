from collections.abc import Iterator
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, mapped_column, sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Unico relogio do sistema, para os testes poderem avancar o tempo."""
    return datetime.now(timezone.utc)


def now() -> datetime:
    return utcnow()


# O casal vive no horario de Brasilia. O "dia de hoje" (vencimentos, alertas,
# rendas recebidas, mes atual) segue esse fuso, e nao o UTC: das 21h a meia-noite
# o UTC ja esta no dia seguinte.
FUSO = ZoneInfo("America/Sao_Paulo")


def local_now() -> datetime:
    return utcnow().astimezone(FUSO)


def local_today() -> date:
    return local_now().date()


def created_at_column():
    return mapped_column(DateTime(timezone=True), default=lambda: now(), nullable=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
