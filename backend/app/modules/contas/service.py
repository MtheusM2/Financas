from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modules.autenticacao.models import User
from app.modules.contas.models import Account, Category

DEFAULT_CATEGORIES = {
    "Moradia": (True, ["Aluguel", "Condomínio", "Luz", "Água", "Internet"]),
    "Alimentação": (True, ["Mercado", "Restaurante"]),
    "Transporte": (True, ["Combustível", "Aplicativo", "Manutenção"]),
    "Saúde": (True, ["Plano", "Farmácia"]),
    "Educação": (False, []),
    "Salário": (False, []),
    "Outros": (False, []),
}


def ensure_user_accounts(db: Session, user: User) -> None:
    """Conta pessoal, conta compartilhada e categorias iniciais."""
    if not db.scalar(select(Account.id).where(Account.owner_user_id == user.id).limit(1)):
        db.add(Account(name=f"Conta de {user.name}", kind="pessoal", owner_user_id=user.id,
                       hidden=False, archived=False, opening_balance_cents=0))
    if not db.scalar(select(Account.id).where(Account.kind == "compartilhada").limit(1)):
        db.add(Account(name="Conta do casal", kind="compartilhada", owner_user_id=None,
                       hidden=False, archived=False, opening_balance_cents=0))
    if not db.scalar(select(Category.id).limit(1)):
        for name, (essential, children) in DEFAULT_CATEGORIES.items():
            parent = Category(name=name, essential=essential)
            db.add(parent)
            db.flush()
            db.add_all(Category(name=c, parent_id=parent.id, essential=essential) for c in children)
    db.flush()


def account_visible_clause(viewer_id: int):
    return or_(Account.hidden.is_(False), Account.owner_user_id == viewer_id)


def hidden_account_ids(viewer_id: int):
    """Contas de outra pessoa que ela ocultou."""
    return select(Account.id).where(and_(Account.hidden.is_(True), Account.owner_user_id != viewer_id))


@dataclass(frozen=True)
class Scope:
    """Recorte pedido: casal somado, uma pessoa ou uma conta."""
    kind: str
    id: int | None = None

    @property
    def key(self) -> str:
        return self.kind if self.id is None else f"{self.kind}:{self.id}"


def parse_scope(value: str = "casal") -> Scope:
    if value == "casal":
        return Scope("casal")
    kind, _, raw = value.partition(":")
    if kind in ("pessoa", "conta") and raw.isdigit():
        return Scope(kind, int(raw))
    raise HTTPException(422, "Recorte inválido.")


def scope_clause(model, scope: Scope):
    if scope.kind == "pessoa":
        return model.owner_user_id == scope.id
    if scope.kind == "conta":
        return model.account_id == scope.id
    return True


def opening_balance(db: Session, viewer_id: int, scope: Scope) -> int:
    stmt = select(Account).where(account_visible_clause(viewer_id), Account.archived.is_(False))
    if scope.kind == "pessoa":
        stmt = stmt.where(Account.owner_user_id == scope.id)
    elif scope.kind == "conta":
        stmt = stmt.where(Account.id == scope.id)
    return sum(a.opening_balance_cents for a in db.scalars(stmt))


def build_tree(rows: list[Category]) -> list[dict]:
    nodes = {c.id: {"id": c.id, "nome": c.name, "essencial": c.essential, "filhas": []} for c in rows}
    roots = []
    for c in rows:
        (nodes[c.parent_id]["filhas"] if c.parent_id in nodes else roots).append(nodes[c.id])
    return roots
