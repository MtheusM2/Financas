"""Regra unica de privacidade. Toda consulta de dados de usuario passa por aqui."""
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session


def visible_clause(model, viewer_id: int):
    return or_(model.hidden.is_(False), model.owner_user_id == viewer_id)


def get_visible(db: Session, model, item_id: int, viewer_id: int):
    item = db.get(model, item_id)
    if item is None or (item.hidden and item.owner_user_id != viewer_id):
        # A mesma resposta de "nao existe": nao revela que o item oculto existe.
        raise HTTPException(404, "Não encontrado.")
    return item


def apply_fields(item, data: dict) -> dict:
    """Aplica os campos e devolve so o que mudou, para o historico."""
    changes = {}
    for key, value in data.items():
        old = getattr(item, key)
        if old != value:
            changes[key] = {"de": str(old), "para": str(value)}
            setattr(item, key, value)
    return changes
