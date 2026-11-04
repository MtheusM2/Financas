from decimal import Decimal

from app.modules.financiamentos.calc import annual_to_monthly, build_schedule, totals
from conftest import personal_account

ONE_PERCENT = Decimal("0.01")


def test_price_known_table():
    # R$ 100.000 a 1% ao mes em 12 meses: parcela conhecida de R$ 8.884,88.
    rows = build_schedule(10_000_000, ONE_PERCENT, 12, "PRICE")
    assert rows[0].payment == 888488
    assert rows[0].interest == 100000
    assert rows[-1].balance == 0
    assert sum(r.amortization for r in rows) == 10_000_000
    assert abs(rows[-1].payment - 888488) < 10


def test_sac_known_table():
    # R$ 120.000 a 1%: amortizacao fixa de 10 mil, juros de 1.200 ate 100.
    rows = build_schedule(12_000_000, ONE_PERCENT, 12, "SAC")
    assert (rows[0].payment, rows[0].interest) == (1_120_000, 120000)
    assert (rows[-1].payment, rows[-1].interest) == (1_010_000, 10000)
    assert totals(rows)["juros_total"] == 780000


def test_zero_rate():
    rows = build_schedule(100000, Decimal(0), 3, "PRICE")
    assert [r.payment for r in rows] == [33333, 33333, 33334]


def test_annual_to_monthly_is_effective():
    assert round(annual_to_monthly(Decimal("12.6825")), 4) == ONE_PERCENT


def test_extra_reducing_term_saves_months_and_interest():
    base = build_schedule(10_000_000, ONE_PERCENT, 12, "PRICE")
    faster = build_schedule(10_000_000, ONE_PERCENT, 12, "PRICE", extras={1: 3_000_000})
    assert len(faster) < len(base)
    assert totals(faster)["juros_total"] < totals(base)["juros_total"]
    assert faster[-1].balance == 0


def test_extra_keeping_term_reduces_payment():
    rows = build_schedule(10_000_000, ONE_PERCENT, 12, "PRICE", extras={1: 3_000_000}, keep_term=True)
    assert len(rows) == 12
    assert rows[1].payment < rows[0].payment
    assert rows[-1].balance == 0


def new_financing(client, **extra):
    response = client.post("/api/financiamentos", json={
        "name": "Carro", "account_id": personal_account(client), "asset_value_cents": 1_200_000, "annual_rate_percent": "0",
        "system": "SAC", "term_months": 12, "first_due": "2026-11-20", **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def titles(client):
    return [a["titulo"] for a in client.get("/api/alertas").json()]


def test_installment_warns_only_near_the_due_date(ana):
    created = new_financing(ana)
    assert created["situacao"] == "vence_logo" and created["proximo_vencimento"] == "2026-11-20" and created["dias"] == 5
    assert "Parcela de Carro vence em 5 dia(s)" in titles(ana)
    paid = ana.post(f"/api/financiamentos/{created['id']}/pagar", json={"date": "2026-11-15"}).json()
    assert paid["situacao"] == "em_dia" and paid["proximo_vencimento"] == "2026-12-20"
    assert not any("Carro" in t for t in titles(ana))


def test_unpaid_installment_stays_late_after_the_month_turns(ana, clock):
    created = new_financing(ana, first_due="2026-11-10")
    clock.set_date(2026, 12, 12)
    status = ana.get("/api/financiamentos").json()[0]
    assert status["situacao"] == "atrasada" and status["proximo_vencimento"] == "2026-11-10" and status["atrasadas"] == 2
    alert = next(a for a in ana.get("/api/alertas").json() if a["titulo"] == "Parcela de Carro está atrasada")
    assert alert["nivel"] == "critico" and "2 parcelas" in alert["detalhe"]
    # O que atrasou pesa no saldo de hoje.
    assert ana.get("/api/previsao", params={"meses": 1}).json()["meses"][0]["saidas"] == 200000
    ana.post(f"/api/financiamentos/{created['id']}/pagar", json={"date": "2026-12-12"})
    assert ana.get("/api/financiamentos").json()[0]["proximo_vencimento"] == "2026-12-10"


def test_installments_paid_before_signing_up_count_from_the_first_due(ana):
    created = new_financing(ana, first_due="2026-01-20", paid_before=10)
    assert created["proximo_vencimento"] == "2026-11-20" and created["atrasadas"] == 0


def test_paid_off_financing_has_no_warning_or_forecast(ana):
    created = new_financing(ana, term_months=1)
    paid = ana.post(f"/api/financiamentos/{created['id']}/pagar", json={"date": "2026-11-15"}).json()
    assert paid["situacao"] == "quitada" and paid["proximo_vencimento"] is None
    assert not any("Carro" in t for t in titles(ana))
    assert all(m["saidas"] == 0 for m in ana.get("/api/previsao", params={"meses": 3}).json()["meses"])


def test_deleting_removes_payments_and_extras_and_respects_hidden(ana, bia):
    created = new_financing(ana)
    ana.post(f"/api/financiamentos/{created['id']}/pagar", json={"date": "2026-11-15"})
    ana.post(f"/api/financiamentos/{created['id']}/amortizar", json={"amount_cents": 1000, "date": "2026-11-15"})
    secret = new_financing(ana, name="Secreto", hidden=True)
    assert bia.delete(f"/api/financiamentos/{secret['id']}").status_code == 404
    assert ana.delete(f"/api/financiamentos/{created['id']}").status_code == 200
    assert [f["nome"] for f in ana.get("/api/financiamentos").json()] == ["Secreto"]
    assert ana.get("/api/lancamentos").json()["total"] == 0
    assert ana.get("/api/painel/resumo", params={"ano": 2026, "mes": 11}).json()["totais"]["divida"] == 0


def test_financing_flow_through_api(ana):
    created = ana.post("/api/financiamentos", json={
        "name": "Carro", "account_id": personal_account(ana), "asset_value_cents": 11_000_000,
        "down_payment_cents": 1_000_000, "annual_rate_percent": "12.6825", "system": "PRICE", "term_months": 12,
        "monthly_fee_cents": 1000, "first_due": "2026-11-10",
    }).json()
    assert created["valor_financiado"] == 10_000_000
    assert created["parcelas_restantes"] == 12
    assert abs(created["proxima_parcela"] - 889488) < 20
    paid = ana.post(f"/api/financiamentos/{created['id']}/pagar", json={"date": "2026-11-10"}).json()
    assert paid["parcelas_pagas"] == 1
    assert paid["saldo_devedor"] < 10_000_000
    total = ana.get("/api/painel/resumo", params={"ano": 2026, "mes": 11}).json()["totais"]["divida"]
    assert total == created["proxima_parcela"]
    table = ana.get(f"/api/financiamentos/{created['id']}/parcelas").json()
    assert table[0]["paga"] and not table[1]["paga"] and table[1]["mes"] == "2026-12"
    simulation = ana.post(f"/api/financiamentos/{created['id']}/simular", json={"amount_cents": 3_000_000}).json()
    assert simulation["juros_economizados"] > 0 and simulation["meses_a_menos"] > 0
    # Simular nao grava nada.
    assert ana.get("/api/financiamentos").json()[0]["parcelas"] == 12
    amortized = ana.post(f"/api/financiamentos/{created['id']}/amortizar", json={"amount_cents": 3_000_000, "date": "2026-11-12"}).json()
    assert amortized["parcelas"] < 12
    # A amortizacao extra nao conta como parcela paga.
    assert amortized["parcelas_pagas"] == 1
