from app.modules.lancamentos.service import materialize_all
from app.core.db import SessionLocal
from conftest import add_tx, personal_account, shared_account


def summary(client, year=2026, month=11, scope="casal"):
    return client.get("/api/painel/resumo", params={"ano": year, "mes": month, "escopo": scope}).json()


def flow(client, year=2026, month=11, scope="casal"):
    return client.get("/api/painel/fluxo", params={"ano": year, "mes": month, "escopo": scope}).json()


def test_totals_and_remaining(ana):
    add_tx(ana, "2026-11-05", "renda", 500000)
    add_tx(ana, "2026-11-06", "gasto", 100000)
    add_tx(ana, "2026-11-07", "fora_escopo", 20000)
    add_tx(ana, "2026-11-08", "divida", 50000)
    add_tx(ana, "2026-11-09", "investimento", 30000)
    add_tx(ana, "2026-11-10", "lazer", 10000)
    totals = summary(ana)["totais"]
    assert totals["renda"] == 500000
    assert totals["saidas"] == 210000
    assert totals["restante"] == 290000
    assert totals["fora_escopo"] == 20000


def income(client, monthly, *payments):
    response = client.post("/api/lancamentos/rendas", json={
        "description": "Salário", "account_id": personal_account(client), "monthly": monthly,
        "payments": [{"date": d, "amount_cents": c} for d, c in payments],
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_salary_with_three_paydays_repeats_every_month(ana, clock):
    assert income(ana, True, ("2026-11-05", 100000), ("2026-11-15", 50000), ("2026-11-25", 70000))["criados"] == 3
    assert [r["dia"] for r in ana.get("/api/lancamentos/recorrencias").json()] == [5, 15, 25]
    # So o que ja chegou conta como recebido; o dia 25 fica previsto.
    assert summary(ana)["totais"]["renda"] == 150000
    assert [(p["data"], p["previsto"]) for p in summary(ana)["recebimentos"]][-1] == ("2026-11-25", True)
    december = ana.get("/api/previsao", params={"meses": 2}).json()["meses"][1]
    assert december["entradas"] == 220000
    clock.set_date(2026, 12, 6)
    with SessionLocal() as db:
        materialize_all(db)
    assert summary(ana, month=12)["totais"]["renda"] == 100000


def test_each_person_has_their_own_paydays_and_extras_happen_once(ana, bia, clock):
    income(ana, True, ("2026-11-05", 100000))
    income(bia, True, ("2026-11-10", 200000), ("2026-11-14", 30000))
    income(ana, False, ("2026-11-12", 40000))
    assert summary(ana)["totais"]["renda"] == 370000
    clock.set_date(2026, 12, 14)
    with SessionLocal() as db:
        materialize_all(db)
    # O freela de novembro nao se repete em dezembro.
    assert summary(ana, month=12)["totais"]["renda"] == 330000


def test_future_one_time_income_stays_predicted(ana):
    income(ana, False, ("2026-11-20", 40000))
    assert summary(ana)["totais"]["renda"] == 0
    assert ana.get("/api/lancamentos", params={"pendentes": True}).json()["total"] == 1


def test_income_needs_a_payment_and_a_valid_account(ana, bia):
    base = {"description": "Salário", "account_id": personal_account(ana), "payments": []}
    assert ana.post("/api/lancamentos/rendas", json=base).status_code == 422
    other = {**base, "account_id": personal_account(bia), "payments": [{"date": "2026-11-05", "amount_cents": 1}]}
    assert ana.post("/api/lancamentos/rendas", json=other).status_code == 422


def test_payday_can_change_and_be_split(ana):
    add_tx(ana, "2026-10-05", "renda", 300000)
    november = add_tx(ana, "2026-11-05", "renda", 200000)
    add_tx(ana, "2026-11-20", "renda", 100000)
    ana.patch(f"/api/lancamentos/{november['id']}", json={"date": "2026-11-08"})
    data = summary(ana)
    assert [p["data"] for p in data["recebimentos"]] == ["2026-11-08", "2026-11-20"]
    days = flow(ana)["dias"]
    assert days[4]["entradas"] == 0
    assert days[7]["entradas"] == 200000
    assert days[7]["saldo"] == 500000


def test_moving_transaction_across_months_rebuilds_both(ana):
    tx = add_tx(ana, "2026-10-31", "gasto", 1000)
    ana.patch(f"/api/lancamentos/{tx['id']}", json={"date": "2026-11-01"})
    assert summary(ana, month=10)["totais"]["gasto"] == 0
    assert summary(ana)["totais"]["gasto"] == 1000


def test_february_has_right_number_of_days(ana):
    add_tx(ana, "2027-02-28", "renda", 1000)
    assert len(flow(ana, 2027, 2)["dias"]) == 28
    assert len(flow(ana, 2028, 2)["dias"]) == 29


def test_opening_balance_carries_over(ana):
    ana.patch(f"/api/contas/{personal_account(ana)}", json={"opening_balance_cents": 10000})
    add_tx(ana, "2026-10-01", "renda", 5000)
    data = flow(ana)
    assert data["saldo_inicial"] == 15000
    add_tx(ana, "2026-10-02", "gasto", 1000)  # o cache precisa perceber a mudanca
    assert flow(ana)["saldo_inicial"] == 14000


def test_couple_person_and_shared_scopes(ana, bia):
    shared = shared_account(ana)
    add_tx(ana, "2026-11-05", "renda", 300000)
    add_tx(bia, "2026-11-06", "renda", 400000)
    add_tx(ana, "2026-11-07", "gasto", 10000, account=shared)
    assert summary(ana)["totais"]["renda"] == 700000
    assert summary(ana, scope=f"pessoa:{bia.user['id']}")["totais"]["renda"] == 400000
    assert summary(ana, scope=f"conta:{shared}")["totais"]["gasto"] == 10000
    people = {p["nome"]: p for p in summary(ana)["pessoas"]}
    assert people["Bia"]["renda"] == 400000


def test_recurring_rule_keeps_single_edit_and_changes_going_forward(ana, clock):
    clock.set_date(2026, 11, 15)
    rule = ana.post("/api/lancamentos/recorrencias", json={
        "account_id": personal_account(ana), "kind": "renda", "amount_cents": 100000, "day_of_month": 31,
        "start_month": 202609, "description": "Salário",
    }).json()
    items = ana.get("/api/lancamentos", params={"tipo": "renda"}).json()["itens"]
    assert sorted(i["data"] for i in items) == ["2026-09-30", "2026-10-31", "2026-11-30"]
    # Muda so outubro: dia diferente naquele mes.
    october = next(i for i in items if i["data"] == "2026-10-31")
    ana.patch(f"/api/lancamentos/{october['id']}", json={"date": "2026-10-20"})
    # Muda a regra de novembro em diante.
    assert ana.patch(f"/api/lancamentos/recorrencias/{rule['id']}", json={"from_month": 202611, "day_of_month": 10, "amount_cents": 120000}).status_code == 200
    items = ana.get("/api/lancamentos", params={"tipo": "renda"}).json()["itens"]
    assert {i["data"]: i["valor"] for i in items} == {
        "2026-09-30": 100000, "2026-10-20": 100000, "2026-11-10": 120000,
    }
    # Virar o mes gera a proxima ocorrencia, sem repetir as anteriores.
    clock.set_date(2026, 12, 1)
    with SessionLocal() as db:
        materialize_all(db)
        materialize_all(db)
    assert ana.get("/api/lancamentos", params={"tipo": "renda"}).json()["total"] == 4


def test_search_filters_and_category_tree(ana):
    tree = ana.get("/api/contas/categorias").json()
    food = next(c for c in tree if c["nome"] == "Alimentação")
    market = next(c for c in food["filhas"] if c["nome"] == "Mercado")
    add_tx(ana, "2026-11-05", "gasto", 1000, category_id=market["id"], description="Feira 100%")
    add_tx(ana, "2026-11-06", "gasto", 2000, description="Outra coisa")
    found = ana.get("/api/lancamentos", params={"categoria_id": food["id"]}).json()
    assert found["total"] == 1 and found["soma"] == 1000
    assert ana.get("/api/lancamentos", params={"busca": "100%"}).json()["total"] == 1
    assert ana.get("/api/lancamentos", params={"inicio": "2026-11-06"}).json()["total"] == 1


def test_cannot_post_to_other_persons_account(ana, bia):
    response = ana.post("/api/lancamentos", json={
        "date": "2026-11-05", "account_id": personal_account(bia), "kind": "gasto", "amount_cents": 100,
    })
    assert response.status_code == 422
