from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.auditoria.models import AuditLog
from app.modules.autenticacao.deps import current_user

router = APIRouter(prefix="/api/auditoria", tags=["auditoria"])


@router.get("")
def list_logs(limit: int = Query(100, le=500), db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(
        select(AuditLog)
        .where(or_(AuditLog.private.is_(False), AuditLog.user_id == user.id))
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    return [
        {"id": r.id, "em": r.at, "usuario": r.user_id, "acao": r.action, "entidade": r.entity,
         "entidade_id": r.entity_id, "rastreio": r.request_id, "alteracoes": r.changes}
        for r in rows
    ]
