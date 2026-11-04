"""Um item oculto nao pode aparecer para a outra pessoa por nenhuma rota."""
from conftest import add_tx, new_client, personal_account

SECRET_CENTS = 777777
SECRET_NAME = "ItemSecreto"
MONTHS = {"ano": 2026, "mes": 11}
RANGE = {"inicio": 202611, "fim": 202611}


def read_routes(item_ids: dict) -> list[tuple[str, dict]]:
    routes = [
        ("/api/lancamentos", {}),
        ("/api/lancamentos/recorrencias", {}),
        ("/api/contas", {}),
        ("/api/painel/resumo", MONTHS),
        ("/api/painel/fluxo", MONTHS),
        ("/api/dividas", {}),
        ("/api/financiamentos", {}),
        ("/api/investimentos", {}),
        ("/api/objetivos", {}),
        ("/api/desafios", {}),
        ("/api/orcamento/resumo", {}),
        ("/api/relatorios/mensal", MONTHS),
        ("/api/relatorios/serie", RANGE),
        ("/api/relatorios/ganhos-perdas", RANGE),
        ("/api/relatorios/fechamentos", {}),
        ("/api/relatorios/progresso", {}),
        ("/api/auditoria", {}),
        ("/api/alertas", {}),
        ("/api/previsao", {}),
        ("/api/orcamento/tetos", MONTHS),
        ("/api/relatorios/dre", RANGE),
        ("/api/relatorios/imposto", {"ano": 2026}),
        ("/api/relatorios/imposto.csv", {"ano": 2026}),
        ("/api/relatorios/lancamentos.csv", {"inicio": "2026-11-01", "fim": "2026-11-30"}),
        ("/api/conciliacao/historico", {}),
        ("/api/holerites", {}),
        ("/api/holerites/analise/resumo", {}),
    ]
    return routes


def seed_hidden(ana):
    account = personal_account(ana)
    common = {"name": SECRET_NAME, "account_id": account, "hidden": True}
    ids = {
        "tx": add_tx(ana, "2026-11-05", "gasto", SECRET_CENTS, description=SECRET_NAME, hidden=True)["id"],
        "debt": ana.post("/api/dividas", json={**common, "installment_cents": SECRET_CENTS, "due_day": 1, "start_date": "2026-01-01"}).json()["id"],
        "fin": ana.post("/api/financiamentos", json={**common, "asset_value_cents": SECRET_CENTS, "annual_rate_percent": "10", "system": "SAC", "term_months": 10, "first_due": "2026-11-01"}).json()["id"],
        "inv": ana.post("/api/investimentos", json={**common, "initial_contributed_cents": SECRET_CENTS, "monthly_plan_cents": SECRET_CENTS}).json()["id"],
        "goal": ana.post("/api/objetivos", json={"name": SECRET_NAME, "joint": False, "hidden": True, "target_cents": SECRET_CENTS, "start_date": "2026-11-01", "term_months": 1}).json()["id"],
        "challenge": ana.post("/api/desafios", json={"name": SECRET_NAME, "joint": False, "hidden": True, "reward_cents": SECRET_CENTS, "start_date": "2026-11-01"}).json()["id"],
        "rule": ana.post("/api/lancamentos/recorrencias", json={"account_id": account, "kind": "gasto", "amount_cents": SECRET_CENTS, "day_of_month": 1, "start_month": 202611, "description": SECRET_NAME, "hidden": True}).json()["id"],
    }
    ana.post(f"/api/dividas/{ids['debt']}/pagar", json={"date": "2026-11-02"})
    ana.post(f"/api/investimentos/{ids['inv']}/aportar", json={"date": "2026-11-02", "amount_cents": SECRET_CENTS})
    ana.post(f"/api/objetivos/{ids['goal']}/aportar", json={"date": "2026-11-02", "amount_cents": SECRET_CENTS, "account_id": account})
    ana.post("/api/relatorios/fechamentos/2026/11")
    # Previstos e teto ocultos tambem nao podem vazar por alertas e previsao.
    add_tx(ana, "2026-11-18", "gasto", SECRET_CENTS, description=SECRET_NAME, hidden=True, settled=False)
    category = ana.get("/api/contas/categorias").json()[0]["id"]
    ana.post("/api/orcamento/tetos", json={"category_id": category, "limit_cents": SECRET_CENTS, "joint": False, "hidden": True})
    ana.post("/api/conciliacao/saldo", json={"account_id": account, "date": "2026-11-15", "real_cents": SECRET_CENTS})
    # Holerite e sempre so do dono; o liquido lancado como renda oculta tambem nao pode vazar.
    ids["payslip"] = ana.post("/api/holerites", json={
        "empresa": SECRET_NAME, "referencia": 202611, "itens": [{"descricao": SECRET_NAME, "tipo": "provento", "valor": SECRET_CENTS}],
        "total_vencimentos": SECRET_CENTS, "total_descontos": 0, "liquido": SECRET_CENTS,
        "lancar_renda": {"account_id": account, "date": "2026-11-05", "hidden": True},
    }).json()["id"]
    ids["fgts"] = ana.post("/api/holerites/fgts", json={"date": "2026-11-01", "balance_cents": SECRET_CENTS}).json()["id"]
    return ids


def test_hidden_items_never_reach_the_other_person(ana, bia):
    ids = seed_hidden(ana)
    for path, params in read_routes(ids):
        response = bia.get(path, params=params)
        assert response.status_code == 200, path
        assert SECRET_NAME not in response.text, path
        assert str(SECRET_CENTS) not in response.text, path


def test_hidden_items_return_404_on_direct_access(ana, bia):
    ids = seed_hidden(ana)
    assert bia.patch(f"/api/lancamentos/{ids['tx']}", json={"amount_cents": 1}).status_code == 404
    assert bia.delete(f"/api/lancamentos/{ids['tx']}").status_code == 404
    assert bia.patch(f"/api/dividas/{ids['debt']}", json={"name": "x"}).status_code == 404
    assert bia.post(f"/api/dividas/{ids['debt']}/pagar", json={"date": "2026-11-02"}).status_code == 404
    assert bia.get(f"/api/financiamentos/{ids['fin']}/parcelas").status_code == 404
    assert bia.post(f"/api/financiamentos/{ids['fin']}/simular", json={"amount_cents": 1}).status_code == 404
    assert bia.patch(f"/api/investimentos/{ids['inv']}", json={"name": "x"}).status_code == 404
    assert bia.get(f"/api/objetivos/{ids['goal']}").status_code == 404
    assert bia.get(f"/api/objetivos/{ids['goal']}/cronograma").status_code == 404
    assert bia.patch(f"/api/desafios/{ids['challenge']}", json={"name": "x"}).status_code == 404
    assert bia.patch(f"/api/lancamentos/recorrencias/{ids['rule']}", json={"from_month": 202611}).status_code == 404
    assert bia.get(f"/api/holerites/{ids['payslip']}").status_code == 404
    assert bia.delete(f"/api/holerites/{ids['payslip']}").status_code == 404
    assert bia.delete(f"/api/holerites/fgts/{ids['fgts']}").status_code == 404


def test_owner_still_sees_hidden_items(ana, bia):
    seed_hidden(ana)
    assert SECRET_NAME in ana.get("/api/lancamentos").text
    assert ana.get("/api/painel/resumo", params=MONTHS).json()["totais"]["gasto"] >= SECRET_CENTS


def test_hidden_account_is_invisible_with_its_transactions(ana, bia):
    account = personal_account(ana)
    add_tx(ana, "2026-11-05", "gasto", SECRET_CENTS, description=SECRET_NAME)
    assert SECRET_NAME in bia.get("/api/lancamentos").text  # aberto por padrao
    ana.patch(f"/api/contas/{account}", json={"hidden": True})
    assert SECRET_NAME not in bia.get("/api/lancamentos").text
    assert str(SECRET_CENTS) not in bia.get("/api/painel/resumo", params=MONTHS).text
    assert account not in [a["id"] for a in bia.get("/api/contas").json()]


def test_scope_cannot_be_used_to_reach_hidden_data(ana, bia):
    add_tx(ana, "2026-11-05", "gasto", SECRET_CENTS, hidden=True)
    scope = {"escopo": f"pessoa:{ana.user['id']}"}
    assert str(SECRET_CENTS) not in bia.get("/api/painel/resumo", params={**MONTHS, **scope}).text
    assert str(SECRET_CENTS) not in bia.get("/api/lancamentos", params=scope).text


def test_cache_does_not_leak_between_viewers(ana, bia):
    add_tx(ana, "2026-11-05", "gasto", SECRET_CENTS, hidden=True)
    assert str(SECRET_CENTS) in str(ana.get("/api/painel/fluxo", params=MONTHS).json())
    assert str(SECRET_CENTS) not in str(bia.get("/api/painel/fluxo", params=MONTHS).json())


def test_cannot_hide_for_someone_else(ana, bia):
    response = ana.post("/api/lancamentos", json={"date": "2026-11-05", "account_id": personal_account(bia),
                                                  "owner_user_id": bia.user["id"], "kind": "gasto", "amount_cents": 100, "hidden": True})
    assert response.status_code == 422


def test_no_route_works_without_login(clock):
    client = new_client()
    for path, params in read_routes({}):
        assert client.get(path, params=params).status_code == 401, path
