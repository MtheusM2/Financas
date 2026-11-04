from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.autenticacao.deps import current_user
from app.modules.contas.service import parse_scope
from app.modules.previsao.service import forecast

router = APIRouter(prefix="/api/previsao", tags=["previsao"])


@router.get("")
def get_forecast(meses: int = Query(6, ge=1, le=36), incluir_planos: bool = False, escopo: str = "casal",
                 db: Session = Depends(get_db), user=Depends(current_user)):
    return forecast(db, user.id, parse_scope(escopo), meses, incluir_planos)
