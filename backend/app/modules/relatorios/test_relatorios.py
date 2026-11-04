from pathlib import Path

from sqlalchemy import select, text

from app.core.backup import restore, run_backup
from app.core.db import SessionLocal, engine
from app.core.calc_graph import affected
from app.core.jobs import Job, enqueue
from app.core.worker import process_one, schedule_daily
from app.modules.relatorios.service import close_due_months
from conftest import add_tx, new_client, personal_account


def test_monthly_report_matches_transactions_and_compares(ana):
    add_tx(ana, "2026-10-05", "renda", 100000)
    add_tx(ana, "2026-11-05", "renda", 150000)
    add_tx(ana, "2026-11-06", "gasto", 50000)
    report = ana.get("/api/relatorios/mensal", params={"ano": 2026, "mes": 11}).json()
    assert report["totais"]["restante"] == 100000
    assert report["comparado_mes_anterior"]["renda"] == {"a": 100000, "b": 150000, "diferenca": 50000, "percentual": 50.0}


def test_compare_periods_and_years(ana):
    add_tx(ana, "2025-03-01", "gasto", 100)
    add_tx(ana, "2026-03-01", "gasto", 300)
    result = ana.get("/api/relatorios/comparar", params={"a_inicio": 202501, "a_fim": 202512, "b_inicio": 202601, "b_fim": 202612}).json()
    assert result["gasto"]["diferenca"] == 200 and result["gasto"]["percentual"] == 200.0
    yearly = ana.get("/api/relatorios/serie", params={"inicio": 202501, "fim": 202612, "agrupar": "ano"}).json()
    assert [(y["periodo"], y["gasto"]) for y in yearly] == [("2025", 100), ("2026", 300)]
    monthly = ana.get("/api/relatorios/serie", params={"inicio": 202511, "fim": 202602}).json()
    assert [m["periodo"] for m in monthly] == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_gains_and_losses(ana):
    account = personal_account(ana)
    add_tx(ana, "2026-11-01", "renda", 100000)
    investment = ana.post("/api/investimentos", json={"name": "Fundo", "account_id": account, "initial_contributed_cents": 100000}).json()
    ana.patch(f"/api/investimentos/{investment['id']}", json={"current_value_cents": 90000})
    result = ana.get("/api/relatorios/ganhos-perdas", params={"inicio": 202611, "fim": 202611}).json()
    assert result["resultado_periodo"] == 100000
    assert result["investimentos"]["resultado"] == -10000


def test_closing_reopens_when_changed_and_keeps_history(ana):
    tx = add_tx(ana, "2026-10-05", "renda", 100000)
    assert ana.post("/api/relatorios/fechamentos/2026/10").json()["situacao"] == "fechado"
    ana.patch(f"/api/lancamentos/{tx['id']}", json={"amount_cents": 120000})
    row = ana.get("/api/relatorios/fechamentos").json()[0]
    assert row["situacao"] == "reaberto" and row["totais"]["renda"] == 100000
    logs = ana.get("/api/auditoria").json()
    assert any(l["acao"] == "alterou" and l["alteracoes"]["amount_cents"]["para"] == "120000" for l in logs if l["entidade"] == "lancamento")
    ana.post("/api/relatorios/fechamentos/2026/10")
    assert ana.get("/api/relatorios/fechamentos").json()[0]["totais"]["renda"] == 120000


def test_automatic_closing_only_past_months_and_respects_reopened(ana, clock):
    tx = add_tx(ana, "2026-10-05", "renda", 100)
    add_tx(ana, "2026-11-05", "renda", 100)
    with SessionLocal() as db:
        close_due_months(db)
    rows = ana.get("/api/relatorios/fechamentos").json()
    assert [(r["ano"], r["mes"]) for r in rows] == [(2026, 10)]
    ana.patch(f"/api/lancamentos/{tx['id']}", json={"amount_cents": 200})
    with SessionLocal() as db:
        close_due_months(db)
    assert ana.get("/api/relatorios/fechamentos").json()[0]["situacao"] == "reaberto"


def test_progress_over_time(ana, clock):
    account = personal_account(ana)
    goal = ana.post("/api/objetivos", json={"name": "Viagem", "start_date": "2026-10-01", "target_cents": 300000, "term_months": 3}).json()
    debt = ana.post("/api/dividas", json={"name": "Celular", "account_id": account, "installment_cents": 10000, "due_day": 5, "total_installments": 3, "start_date": "2026-10-05"}).json()
    ana.post(f"/api/objetivos/{goal['id']}/aportar", json={"date": "2026-10-10", "amount_cents": 100000, "account_id": account})
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-10-05"})
    ana.post("/api/relatorios/fechamentos/2026/10")
    ana.post(f"/api/objetivos/{goal['id']}/aportar", json={"date": "2026-11-10", "amount_cents": 100000, "account_id": account})
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-05"})
    ana.post("/api/relatorios/fechamentos/2026/11")
    items = {(p["tipo"], p["nome"]): p for p in ana.get("/api/relatorios/progresso").json()}
    viagem = items[("objetivo", "Viagem")]
    assert [p["atual"] for p in viagem["pontos"]] == [100000, 200000]
    celular = items[("divida", "Celular")]
    assert [p["atual"] for p in celular["pontos"]] == [1, 2]
    assert celular["agora"]["saldo"] == 10000


def test_dependency_graph_only_marks_what_depends():
    assert set(affected("lancamentos")) == {"lancamentos", "fluxo", "sobra", "progresso", "orcamento"}
    assert "fluxo" not in affected("compromissos")


def test_queue_runs_once_and_retries_failure(ana, monkeypatch):
    from app.core import worker
    calls = []
    monkeypatch.setitem(worker.HANDLERS, "recorrencias", lambda db: calls.append(1))
    monkeypatch.setitem(worker.HANDLERS, "fechamento", lambda db: calls.append(2))

    def fail(db):
        raise RuntimeError("falhou de propósito")

    monkeypatch.setitem(worker.HANDLERS, "backup", fail)
    with SessionLocal() as db:
        schedule_daily(db)
        schedule_daily(db)  # nao duplica
    while process_one():
        pass
    assert sorted(calls) == [1, 2]
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.kind == "backup"))
        assert job.status == "pending" and job.attempts == 1 and "propósito" in job.error


def test_encrypted_backup_restores_data(ana):
    add_tx(ana, "2026-11-05", "renda", 12345)
    path = run_backup()
    assert b"12345" not in Path(path).read_bytes()
    engine.dispose()
    with engine.begin() as conn:
        conn.execute(text("UPDATE transactions SET amount_cents = 1"))
    engine.dispose()
    restore(path)
    engine.dispose()
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT amount_cents FROM transactions")) == 12345
