import re
from pathlib import Path

from sqlalchemy import text

from app.core.db import Base, engine
from conftest import add_tx, personal_account

SQL = (Path(__file__).parents[2] / "scripts" / "zerar_dados.sql").read_text()
CLEARED = set(re.findall(r"\w+", re.search(r"TRUNCATE(.*?)RESTART", SQL, re.S).group(1)))
KEPT = {"users", "auth_sessions", "verification_codes", "accounts", "categories", "audit_logs", "jobs", "calc_versions",
        "payslip_labels"}  # rotulos aprendidos dos holerites: nao sao dados financeiros


def count(table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f'select count(*) from "{table}"')).scalar()


def test_every_table_is_either_cleared_or_kept():
    assert set(Base.metadata.tables) == CLEARED | KEPT


def test_reset_clears_finances_and_keeps_the_login(ana):
    account = personal_account(ana)
    ana.patch(f"/api/contas/{account}", json={"opening_balance_cents": 1000})
    tag = ana.post("/api/contas/categorias", json={"name": "Minha tag"}).json()
    add_tx(ana, "2026-11-05", "renda", 5000, category_id=tag["id"])
    debt = ana.post("/api/dividas", json={"name": "Aluguel", "account_id": account, "installment_cents": 100, "due_day": 20,
                                          "start_date": "2026-11-01", "category_id": tag["id"]}).json()
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"})
    ana.post("/api/lancamentos/rendas", json={"description": "Salário", "account_id": account, "payments": [{"date": "2026-11-05", "amount_cents": 1}]})
    fin = ana.post("/api/financiamentos", json={"name": "Carro", "account_id": account, "asset_value_cents": 1000, "annual_rate_percent": "0",
                                                "system": "SAC", "term_months": 2, "first_due": "2026-11-20"}).json()
    ana.post(f"/api/financiamentos/{fin['id']}/amortizar", json={"amount_cents": 10, "date": "2026-11-15"})
    ana.post("/api/investimentos", json={"name": "T", "account_id": account, "monthly_plan_cents": 1})
    ana.post("/api/objetivos", json={"name": "Viagem", "start_date": "2026-11-01", "target_cents": 1000, "term_months": 2})
    accounts, categories = count("accounts"), count("categories")

    with engine.begin() as conn:
        conn.exec_driver_sql(SQL)

    for table in CLEARED:
        assert count(table) == 0, table
    assert (count("users"), count("accounts"), count("categories")) == (1, accounts, categories)
    # A sessao continua valendo: a pessoa nao precisa entrar de novo.
    assert ana.get("/api/autenticacao/eu").status_code == 200
    assert ana.get("/api/contas").json()[0]["saldo_inicial"] == 0
    assert ana.get("/api/lancamentos").json()["total"] == 0
    assert ana.get("/api/dividas").json() == []
    assert any(a["acao"] == "zerou_dados" for a in ana.get("/api/auditoria").json())
    # O sistema continua funcionando depois.
    assert add_tx(ana, "2026-11-06", "renda", 100)["id"] == 1
