from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.core.db as core_db
from app.core.db import Base, engine
from app.core.email import outbox
from app.main import app


class Clock:
    def __init__(self, monkeypatch):
        self.current = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(core_db, "utcnow", lambda: self.current)

    def advance(self, **kwargs):
        self.current += timedelta(**kwargs)

    def set_date(self, year, month, day):
        self.current = datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.create_all(engine)
    yield
    with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    outbox.clear()


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch)


def new_client() -> TestClient:
    client = TestClient(app, raise_server_exceptions=True)
    client.headers["X-Financas"] = "1"
    return client


def last_code(email: str) -> str:
    message = next(m for m in reversed(outbox) if m["to"] == email)
    return next(word for word in message["body"].split() if word.rstrip(".").isdigit() and len(word.rstrip(".")) == 6).rstrip(".")


def sign_up(email: str, name: str, password: str = "senha-bem-longa-1") -> TestClient:
    client = new_client()
    assert client.post("/api/autenticacao/cadastro", json={"email": email, "name": name, "password": password}).status_code == 200
    response = client.post("/api/autenticacao/verificar", json={"email": email, "code": last_code(email)})
    assert response.status_code == 200, response.text
    client.user = response.json()
    return client


@pytest.fixture
def ana(clock):
    return sign_up("ana@teste.com", "Ana")


@pytest.fixture
def bia(clock):
    return sign_up("bia@teste.com", "Bia")


def personal_account(client: TestClient) -> int:
    return next(a["id"] for a in client.get("/api/contas").json()
                if a["tipo"] == "pessoal" and a["dono"] == client.user["id"])


def shared_account(client: TestClient) -> int:
    return next(a["id"] for a in client.get("/api/contas").json() if a["tipo"] == "compartilhada")


def add_tx(client: TestClient, day: str, kind: str, cents: int, account: int | None = None, **extra) -> dict:
    response = client.post("/api/lancamentos", json={
        "date": day, "account_id": account or personal_account(client), "kind": kind, "amount_cents": cents, **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()
