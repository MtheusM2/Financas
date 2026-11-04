"""Grafo de dependencia dos calculos e cache sob demanda.

Cada no do grafo tem uma versao guardada no banco. Quando um dado muda, o no e
todos os que dependem dele avancam de versao. O cache guarda o resultado junto
com as versoes usadas, entao vale para todas as copias da API: uma copia ve a
versao nova no banco e recalcula apenas o que foi afetado.
"""
from collections import deque
from threading import Lock
from typing import Any, Callable

from sqlalchemy import Integer, String, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base

GRAPH: dict[str, list[str]] = {
    "contas": ["fluxo"],
    "lancamentos": ["fluxo", "sobra", "progresso"],
    "fluxo": [],
    "sobra": ["orcamento"],
    "compromissos": ["orcamento", "progresso"],
    "investimentos": ["orcamento", "progresso"],
    "objetivos": ["orcamento", "progresso"],
    "desafios": ["progresso"],
    "orcamento": [],
    "progresso": [],
}


def affected(node: str) -> list[str]:
    """Busca em largura: o no alterado e tudo o que depende dele."""
    seen, queue, order = {node}, deque([node]), []
    while queue:
        current = queue.popleft()
        order.append(current)
        for child in GRAPH[current]:
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return order


class CalcVersion(Base):
    __tablename__ = "calc_versions"
    node: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def touch(db: Session, node: str) -> None:
    """Chame na mesma transacao da escrita, antes do commit."""
    for name in sorted(affected(node)):  # ordem fixa evita deadlock entre copias
        stmt = insert(CalcVersion).values(node=name, version=1)
        stmt = stmt.on_conflict_do_update(index_elements=["node"], set_={"version": CalcVersion.version + 1})
        db.execute(stmt)


_cache: dict[tuple, Any] = {}
_lock = Lock()
_MAX_ENTRIES = 512


def cached(db: Session, node: str, key: tuple, compute: Callable[[], Any]) -> Any:
    version = db.scalar(select(CalcVersion.version).where(CalcVersion.node == node)) or 0
    full_key = (node, version, *key)
    with _lock:
        if full_key in _cache:
            return _cache[full_key]
    value = compute()
    with _lock:
        if len(_cache) >= _MAX_ENTRIES:
            _cache.clear()
        _cache[full_key] = value
    return value
