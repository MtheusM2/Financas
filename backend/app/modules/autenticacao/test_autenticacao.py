import pyotp

from app.core.email import outbox
from app.modules.auditoria.models import AuditLog
from app.core.db import SessionLocal
from conftest import last_code, new_client, sign_up

SIGNUP = {"email": "ana@teste.com", "name": "Ana", "password": "senha-bem-longa-1"}


def test_only_authorized_email_can_sign_up(clock):
    response = new_client().post("/api/autenticacao/cadastro", json={**SIGNUP, "email": "outro@teste.com"})
    assert response.status_code == 403
    assert outbox == []


def test_signup_needs_code_before_login(clock):
    client = new_client()
    client.post("/api/autenticacao/cadastro", json=SIGNUP)
    response = client.post("/api/autenticacao/entrar", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    assert response.status_code == 403
    client.post("/api/autenticacao/verificar", json={"email": SIGNUP["email"], "code": last_code(SIGNUP["email"])})
    assert client.get("/api/autenticacao/eu").json()["nome"] == "Ana"


def test_code_expires_after_one_minute(clock):
    client = new_client()
    client.post("/api/autenticacao/cadastro", json=SIGNUP)
    code = last_code(SIGNUP["email"])
    clock.advance(seconds=61)
    assert client.post("/api/autenticacao/verificar", json={"email": SIGNUP["email"], "code": code}).status_code == 400


def test_resend_invalidates_previous_and_restarts_timer(clock):
    client = new_client()
    client.post("/api/autenticacao/cadastro", json=SIGNUP)
    old = last_code(SIGNUP["email"])
    clock.advance(seconds=50)
    client.post("/api/autenticacao/reenviar", json={"email": SIGNUP["email"], "purpose": "cadastro"})
    new = last_code(SIGNUP["email"])
    clock.advance(seconds=50)  # 100s depois do primeiro, 50s depois do novo
    if old != new:
        assert client.post("/api/autenticacao/verificar", json={"email": SIGNUP["email"], "code": old}).status_code == 400
    assert client.post("/api/autenticacao/verificar", json={"email": SIGNUP["email"], "code": new}).status_code == 200


def test_blocks_after_five_resends(clock):
    client = new_client()
    client.post("/api/autenticacao/cadastro", json=SIGNUP)
    payload = {"email": SIGNUP["email"], "purpose": "cadastro"}
    for remaining in (4, 3, 2, 1, 0):
        response = client.post("/api/autenticacao/reenviar", json=payload)
        assert response.status_code == 200
        assert response.json()["reenvios_restantes"] == remaining
    assert client.post("/api/autenticacao/reenviar", json=payload).status_code == 429
    sent = len(outbox)
    assert client.post("/api/autenticacao/reenviar", json=payload).status_code == 429
    assert len(outbox) == sent
    clock.advance(minutes=16)
    assert client.post("/api/autenticacao/reenviar", json=payload).status_code == 200


def test_wrong_code_attempts_are_limited(clock):
    client = new_client()
    client.post("/api/autenticacao/cadastro", json=SIGNUP)
    good = last_code(SIGNUP["email"])
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/autenticacao/verificar", json={"email": SIGNUP["email"], "code": wrong}).status_code == 400
    assert client.post("/api/autenticacao/verificar", json={"email": SIGNUP["email"], "code": good}).status_code == 429


def test_password_recovery_changes_password_and_ends_sessions(clock):
    ana = sign_up("ana@teste.com", "Ana")
    other = new_client()
    assert other.post("/api/autenticacao/recuperar", json={"email": "ana@teste.com"}).status_code == 200
    response = other.post("/api/autenticacao/redefinir", json={
        "email": "ana@teste.com", "code": last_code("ana@teste.com"), "password": "nova-senha-longa-2",
    })
    assert response.status_code == 200
    assert ana.get("/api/autenticacao/eu").status_code == 401
    assert other.post("/api/autenticacao/entrar", json={"email": "ana@teste.com", "password": "senha-bem-longa-1"}).status_code == 401
    assert other.post("/api/autenticacao/entrar", json={"email": "ana@teste.com", "password": "nova-senha-longa-2"}).status_code == 200


def test_recovery_does_not_reveal_unknown_email(clock):
    response = new_client().post("/api/autenticacao/recuperar", json={"email": "ninguem@teste.com"})
    assert response.status_code == 200
    assert outbox == []


def test_login_locks_after_failures(clock):
    sign_up("ana@teste.com", "Ana")
    client = new_client()
    for _ in range(5):
        assert client.post("/api/autenticacao/entrar", json={"email": "ana@teste.com", "password": "errada"}).status_code == 401
    good = {"email": "ana@teste.com", "password": "senha-bem-longa-1"}
    assert client.post("/api/autenticacao/entrar", json=good).status_code == 429
    clock.advance(minutes=16)
    assert client.post("/api/autenticacao/entrar", json=good).status_code == 200


def test_two_factor_is_required_once_enabled(clock):
    ana = sign_up("ana@teste.com", "Ana")
    key = ana.post("/api/autenticacao/2fa/iniciar").json()["chave"]
    assert ana.post("/api/autenticacao/2fa/ativar", json={"totp": pyotp.TOTP(key).now()}).status_code == 200
    client = new_client()
    credentials = {"email": "ana@teste.com", "password": "senha-bem-longa-1"}
    assert client.post("/api/autenticacao/entrar", json=credentials).json()["detail"] == "codigo_2fa_necessario"
    assert client.post("/api/autenticacao/entrar", json={**credentials, "totp": pyotp.TOTP(key).now()}).status_code == 200


def test_requires_app_header_and_login(clock):
    client = new_client()
    assert client.get("/api/contas").status_code == 401
    del client.headers["X-Financas"]
    assert client.post("/api/autenticacao/entrar", json={"email": "a@a.com", "password": "x"}).status_code == 403


def test_audit_never_stores_secrets(clock):
    from sqlalchemy import select
    sign_up("ana@teste.com", "Ana")
    with SessionLocal() as db:
        logs = db.scalars(select(AuditLog)).all()
    assert logs
    assert "senha-bem-longa" not in str([log.changes for log in logs])
