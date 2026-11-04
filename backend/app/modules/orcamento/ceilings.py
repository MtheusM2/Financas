"""Situacao dos tetos por categoria, calculada so quando pedida."""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.visibility import visible_clause
from app.modules.contas.models import Category
from app.modules.contas.service import Scope
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import clamp_day, tx_filter
from app.modules.orcamento.models import CategoryBudget

NEAR_SHARE = 0.8


def subtree_ids(db: Session, category_id: int):
    tree = select(Category.id).where(Category.id == category_id).cte(recursive=True)
    tree = tree.union_all(select(Category.id).where(Category.parent_id == tree.c.id))
    return select(tree.c.id)


def status_of(spent: int, limit: int) -> str:
    if spent > limit:
        return "estourou"
    return "perto" if spent >= limit * NEAR_SHARE else "ok"


def ceilings_status(db: Session, viewer_id: int, year: int, month: int) -> list[dict]:
    first = date(year, month, 1)
    last = clamp_day(year * 100 + month, 31)
    rows = db.execute(
        select(CategoryBudget, Category.name)
        .join(Category, Category.id == CategoryBudget.category_id)
        .where(visible_clause(CategoryBudget, viewer_id))
        .order_by(Category.name)
    ).all()
    result = []
    for budget, name in rows:
        scope = Scope("casal") if budget.owner_user_id is None else Scope("pessoa", budget.owner_user_id)
        spent = int(db.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.date >= first, Transaction.date <= last, Transaction.kind != "renda",
                Transaction.category_id.in_(subtree_ids(db, budget.category_id)), tx_filter(viewer_id, scope),
            )
        ))
        result.append({
            "id": budget.id, "categoria_id": budget.category_id, "categoria": name, "pessoa_id": budget.owner_user_id,
            "teto": budget.limit_cents, "gasto": spent, "disponivel": budget.limit_cents - spent,
            "percentual": round(spent / budget.limit_cents * 100, 1), "situacao": status_of(spent, budget.limit_cents),
            "oculto": budget.hidden,
        })
    return result
