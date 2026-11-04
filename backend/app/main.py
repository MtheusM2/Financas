from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.registry import enabled_modules, load_all_models, routers
from app.core.tracing import TracingMiddleware, configure_logging, logger, request_id_var

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

configure_logging()
load_all_models()

app = FastAPI(title="Financas do Casal", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def require_app_header(request: Request, call_next):
    # Outro site nao consegue enviar este cabecalho sem a permissao do navegador.
    if request.method not in SAFE_METHODS and request.headers.get("x-financas") != "1":
        return JSONResponse({"detail": "Requisição recusada."}, status_code=403)
    return await call_next(request)


app.add_middleware(TracingMiddleware)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error("erro inesperado", exc_info=exc)
    return JSONResponse(
        {"detail": "Erro inesperado.", "rastreio": request_id_var.get()},
        status_code=500,
    )


@app.get("/api/saude")
def health():
    with SessionLocal() as db:
        db.execute(text("select 1"))
    return {"status": "ok"}


@app.get("/api/modulos")
def modules():
    return {"modulos": enabled_modules()}


for router in routers():
    app.include_router(router)
