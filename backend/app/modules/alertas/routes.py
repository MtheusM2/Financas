from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.alertas.service import collect
from app.modules.autenticacao.deps import current_user

router = APIRouter(prefix="/api/alertas", tags=["alertas"])


@router.get("")
def list_alerts(db: Session = Depends(get_db), user=Depends(current_user)):
    return collect(db, user.id)
