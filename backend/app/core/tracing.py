"""Codigo de rastreio por requisicao e logs em JSON."""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger("financas")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "nivel": record.levelname,
            "msg": record.getMessage(),
            "rastreio": request_id_var.get(),
        }
        data.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            data["erro"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def module_of(path: str) -> str:
    parts = path.strip("/").split("/")
    return parts[1] if len(parts) > 1 else "-"


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Rastreio"] = rid
            return response
        finally:
            logger.info(
                "requisicao",
                extra={"extra_fields": {
                    "metodo": request.method,
                    "rota": request.url.path,  # sem query string: nunca registra dados
                    "modulo": module_of(request.url.path),
                    "status": status,
                    "ms": round((time.perf_counter() - start) * 1000, 1),
                }},
            )
            request_id_var.reset(token)
