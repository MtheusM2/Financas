from datetime import datetime, timezone

from conftest import personal_account


def new_debt(client, **extra):
    body = {"name": "Aluguel", "account_id": personal_account(client), "installment_cents": 50000,
            "due_day": 20, "start_date": "2026-11-01", **extra}
    response = client.post("/api/dividas", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def balance_of_payments(client):
    return client.get("/api/painel/resumo", params={"ano": 2026, "mes": 11, "escopo": "casal"}).json()["totais"]["divida"]


def titles(client):
    return [a["titulo"] for a in client.get("/api/alertas").json()]


def test_debt_only_touches_balance_when_paid(ana):
    debt = new_debt(ana)
    assert debt["situacao"] == "vence_logo" and debt["proximo_vencimento"] == "2026-11-20" and debt["dias"] == 5
    assert balance_of_payments(ana) == 0


def test_payment_moves_the_due_date_and_can_be_undone(ana):
    debt = new_debt(ana)
    paid = ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15", "amount_cents": 48000}).json()
    assert paid["situacao"] == "em_dia" and paid["proximo_vencimento"] == "2026-12-20"
    assert paid["ultimo_pagamento"] == {"data": "2026-11-15", "valor": 48000}
    assert balance_of_payments(ana) == 48000
    assert "Aluguel vence em 5 dia(s)" not in titles(ana)
    undone = ana.delete(f"/api/dividas/{debt['id']}/pagamentos/ultimo").json()
    assert undone["proximo_vencimento"] == "2026-11-20" and undone["ultimo_pagamento"] is None
    assert balance_of_payments(ana) == 0
    assert "Aluguel vence em 5 dia(s)" in titles(ana)
    assert ana.delete(f"/api/dividas/{debt['id']}/pagamentos/ultimo").status_code == 404


def test_alert_appears_only_near_the_due_date(ana, clock):
    new_debt(ana, due_day=25)
    assert not any("Aluguel" in t for t in titles(ana))
    clock.set_date(2026, 11, 18)
    assert "Aluguel vence em 7 dia(s)" in titles(ana)
    clock.set_date(2026, 11, 25)
    assert "Aluguel vence hoje" in titles(ana)


def test_unpaid_month_stays_late_after_the_month_turns(ana, clock):
    debt = new_debt(ana, due_day=10, start_date="2026-11-10")
    clock.set_date(2026, 12, 12)
    status = ana.get("/api/dividas").json()[0]
    assert status["situacao"] == "atrasada" and status["proximo_vencimento"] == "2026-11-10" and status["atrasadas"] == 2
    alert = next(a for a in ana.get("/api/alertas").json() if a["titulo"] == "Aluguel está atrasada")
    assert alert["nivel"] == "critico" and "2 pagamentos" in alert["detalhe"]
    # O que atrasou pesa no saldo de hoje.
    today = ana.get("/api/previsao", params={"meses": 1}).json()["meses"][0]
    assert today["saidas"] == 100000
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-12-12"})
    assert ana.get("/api/dividas").json()[0]["proximo_vencimento"] == "2026-12-10"


def test_installments_end_and_refuse_extra_payment(ana):
    debt = new_debt(ana, total_installments=3, paid_before=2)
    assert debt["proximo_vencimento"] == "2026-11-20" and debt["parcelas_restantes"] == 1
    assert ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"}).json()["situacao"] == "quitada"
    assert ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"}).status_code == 409


def test_due_day_31_uses_the_last_day_of_short_months(ana):
    debt = new_debt(ana, due_day=31, start_date="2026-11-30")
    assert debt["proximo_vencimento"] == "2026-11-30"
    paid = ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"}).json()
    assert paid["proximo_vencimento"] == "2026-12-31"


def test_tag_goes_to_the_payment_and_can_be_removed(ana):
    tag = ana.post("/api/contas/categorias", json={"name": "Moradia teste"}).json()
    debt = new_debt(ana, category_id=tag["id"])
    assert debt["categoria"] == "Moradia teste"
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"})
    assert ana.get("/api/lancamentos", params={"categoria_id": tag["id"]}).json()["total"] == 1
    assert ana.patch(f"/api/dividas/{debt['id']}", json={"category_id": None}).json()["categoria"] is None
    assert ana.post("/api/dividas", json={"name": "X", "account_id": personal_account(ana), "installment_cents": 1, "due_day": 1,
                                          "start_date": "2026-11-01", "category_id": 99999}).status_code == 422


def test_changing_the_next_due_date_keeps_payments(ana):
    debt = new_debt(ana)
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"})
    changed = ana.patch(f"/api/dividas/{debt['id']}", json={"next_due": "2026-12-05", "installment_cents": 60000}).json()
    assert changed["proximo_vencimento"] == "2026-12-05" and changed["vencimento"] == 5 and changed["parcela"] == 60000
    assert changed["ultimo_pagamento"]["valor"] == 50000


def test_closing_and_deleting(ana):
    debt = new_debt(ana)
    assert ana.patch(f"/api/dividas/{debt['id']}", json={"active": False}).json()["ativa"] is False
    assert not any("Aluguel" in t for t in titles(ana))
    assert ana.get("/api/previsao", params={"meses": 2}).json()["meses"][1]["saidas"] == 0
    assert ana.delete(f"/api/dividas/{debt['id']}").status_code == 200
    assert ana.get("/api/dividas").json() == []


def test_deleting_a_debt_removes_its_payments_and_updates_totals(ana):
    debt = new_debt(ana)
    other = new_debt(ana, name="Luz")
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"})
    ana.post(f"/api/dividas/{other['id']}/pagar", json={"date": "2026-11-15"})
    assert balance_of_payments(ana) == 100000
    assert ana.delete(f"/api/dividas/{debt['id']}").status_code == 200
    assert balance_of_payments(ana) == 50000
    assert [d["nome"] for d in ana.get("/api/dividas").json()] == ["Luz"]
    assert ana.get("/api/lancamentos").json()["total"] == 1


def test_bulk_delete_removes_all_or_nothing(ana, bia):
    first, second, third = new_debt(ana), new_debt(ana, name="Luz"), new_debt(ana, name="Água")
    secret = new_debt(ana, name="Secreta", hidden=True)
    ana.post(f"/api/dividas/{first['id']}/pagar", json={"date": "2026-11-15"})
    # Sem ver a divida oculta, a pessoa nao exclui nenhuma do lote.
    assert bia.post("/api/dividas/excluir", json={"ids": [second["id"], secret["id"]]}).status_code == 404
    assert len(ana.get("/api/dividas").json()) == 4
    assert ana.post("/api/dividas/excluir", json={"ids": []}).status_code == 422
    done = ana.post("/api/dividas/excluir", json={"ids": [first["id"], second["id"], second["id"]]})
    assert done.status_code == 200 and done.json()["excluidas"] == 2
    assert sorted(d["id"] for d in ana.get("/api/dividas").json()) == [third["id"], secret["id"]]
    assert balance_of_payments(ana) == 0


def test_other_person_cannot_undo_or_delete_a_hidden_debt(ana, bia):
    debt = new_debt(ana, hidden=True)
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"})
    assert bia.delete(f"/api/dividas/{debt['id']}/pagamentos/ultimo").status_code == 404
    assert bia.delete(f"/api/dividas/{debt['id']}").status_code == 404
    assert ana.get("/api/dividas").json()[0]["ultimo_pagamento"] is not None


def test_today_follows_brasilia_time_at_night(ana, clock):
    # 20/11 as 23h em Brasilia ja e 21/11 em UTC: a divida ainda vence hoje, nao esta atrasada.
    new_debt(ana)
    clock.current = datetime(2026, 11, 21, 2, 0, tzinfo=timezone.utc)
    status = ana.get("/api/dividas").json()[0]
    assert status["proximo_vencimento"] == "2026-11-20" and status["dias"] == 0 and status["situacao"] != "atrasada"
    assert "Aluguel vence hoje" in titles(ana)
    clock.current = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)  # meia-noite em Brasilia
    assert ana.get("/api/dividas").json()[0]["situacao"] == "atrasada"


def saldo_final(client):
    return client.get("/api/painel/resumo", params={"ano": 2026, "mes": 11, "escopo": "casal"}).json()["saldo_final"]


def test_paying_a_debt_lowers_the_balance(ana):
    debt = new_debt(ana, total_installments=1)
    before = saldo_final(ana)
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"})
    assert saldo_final(ana) == before - 50000


def test_debt_cannot_be_born_already_paid_off(ana):
    """Parcelas ja pagas nao criam lancamento: se fossem todas, o pagamento nunca sairia do saldo."""
    body = {"name": "Cartão", "account_id": personal_account(ana), "installment_cents": 50000,
            "due_day": 20, "start_date": "2026-11-01", "total_installments": 1, "paid_before": 1}
    response = ana.post("/api/dividas", json=body)
    assert response.status_code == 422 and "Registrar pagamento" in response.json()["detail"]


def test_paid_before_can_be_fixed_and_then_paid(ana):
    debt = new_debt(ana, total_installments=3, paid_before=2)
    fixed = ana.patch(f"/api/dividas/{debt['id']}", json={"paid_before": 1}).json()
    assert fixed["parcelas_ja_pagas"] == 1 and fixed["parcelas_restantes"] == 2
    assert ana.patch(f"/api/dividas/{debt['id']}", json={"paid_before": 4}).status_code == 422
    before = saldo_final(ana)
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"})
    assert saldo_final(ana) == before - 50000


def test_forecast_today_balance_ignores_future_dated_entries(ana):
    account = personal_account(ana)
    ana.post("/api/lancamentos", json={"date": "2026-11-10", "account_id": account, "kind": "renda", "amount_cents": 100000})
    ana.post("/api/lancamentos", json={"date": "2026-11-28", "account_id": account, "kind": "gasto", "amount_cents": 30000})
    data = ana.get("/api/previsao", params={"meses": 1}).json()
    assert data["saldo_atual"] == 100000
    assert data["meses"][0]["saldo"] == 70000
