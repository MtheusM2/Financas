"""Trabalhador: agenda as tarefas diarias e consome a fila."""
import time
from datetime import timedelta

from sqlalchemy import update

from app.core.backup import run_backup
from app.core.db import SessionLocal, now, local_today
from app.core.jobs import Job, enqueue, next_job
from app.core.registry import load_all_models
from app.core.tracing import configure_logging, logger

MAX_ATTEMPTS = 3


def _materialize(db) -> None:
    from app.modules.lancamentos.service import materialize_all
    materialize_all(db)


def _close_months(db) -> None:
    from app.modules.relatorios.service import close_due_months
    close_due_months(db)


def _send_alerts(db) -> None:
    from app.modules.alertas.service import send_daily_summaries
    send_daily_summaries(db)


HANDLERS = {
    "recorrencias": _materialize,
    "fechamento": _close_months,
    "alertas": _send_alerts,
    "backup": lambda db: run_backup(),
}


def schedule_daily(db) -> None:
    today = local_today().isoformat()
    for kind in HANDLERS:
        enqueue(db, kind, f"{kind}:{today}")
    db.commit()


def process_one() -> bool:
    with SessionLocal() as db:
        job = next_job(db)
        if job is None:
            db.rollback()
            return False
        # Grava a tentativa antes de rodar: uma falha desfaz a tarefa, nao a contagem.
        job.attempts += 1
        job.status = "running"
        db.commit()
        try:
            HANDLERS[job.kind](db)
            job.status, job.error, job.finished_at = "done", None, now()
            logger.info("tarefa concluida", extra={"extra_fields": {"tarefa": job.kind}})
        except Exception as error:
            db.rollback()
            job.error = str(error)[:500]
            if job.attempts >= MAX_ATTEMPTS:
                job.status = "failed"
            else:
                job.status = "pending"
                job.run_at = now() + timedelta(minutes=5 * job.attempts)
            logger.error("tarefa falhou", exc_info=error, extra={"extra_fields": {"tarefa": job.kind}})
        db.commit()
        return True


def requeue_interrupted() -> None:
    """Tarefa que estava rodando quando o trabalhador caiu volta para a fila."""
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.status == "running").values(status="pending"))
        db.commit()


def main() -> None:
    configure_logging()
    load_all_models()
    logger.info("trabalhador iniciado")
    requeue_interrupted()
    while True:
        with SessionLocal() as db:
            schedule_daily(db)
        while process_one():
            pass
        time.sleep(60)


if __name__ == "__main__":
    main()
