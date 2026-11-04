"""Objetivos, reserva, desafios e avisos de orcamento."""
from decimal import Decimal

from app.modules.desafios.calc import split_on_completion, suggest, target_from_reward
from app.modules.objetivos.calc import months_to_reach, project, required_monthly, split_by_contributions
from app.modules.orcamento.calc import alternatives, assess
from conftest import add_tx, personal_account


def test_goal_calculations():
    assert required_monthly(1_000_000, 0, 10) == 100000
    assert required_monthly(1_000_000, 1_000_000, 10) == 0
    assert months_to_reach(1_000_000, 0, 100000) == 10
    assert months_to_reach(1_000_000, 0, 0) is None
    # Com juros, o aporte necessario diminui e a projecao chega na meta.
    monthly = required_monthly(1_000_000, 0, 12, Decimal("0.01"))
    assert monthly < 1_000_000 // 12
    assert abs(project(0, monthly, 12, Decimal("0.01"))[-1] - 1_000_000) < 12


def test_assess_levels():
    assert assess(10000, 100000, 0, 100000) == "cabe"
    assert assess(90000, 100000, 0, 100000) == "atencao"
    assert assess(120000, 100000, 50000, 200000) == "atencao"  # so cabe reduzindo investimento
    assert assess(200000, 100000, 50000, 200000) == "compromete"
    assert assess(100, 100000, 50000, 0) == "compromete"
    assert assess(100, -5000, 10000, -1) == "compromete"


def test_alternatives_show_extend_reduce_and_pause():
    result = alternatives(total=1_200_000, saved=0, amount=120000, term=10, free=100000, invest_plans=50000, invest_rate=Decimal("0.01"))
    assert result["aumentar_prazo"]["meses"] == 12
    assert result["reduzir_valor"]["valor_possivel"] == 1_000_000
    pause = result["pausar_investimentos"]
    assert pause["reduzir_por_mes"] == 20000 and pause["deixa_de_aportar"] == 200000
    assert pause["deixa_de_acumular"] > 200000  # inclui o rendimento que deixaria de ter


def test_alternatives_without_room():
    result = alternatives(1_000_000, 0, 100000, 10, 0, 0)
    assert result == {"aumentar_prazo": None, "reduzir_valor": None, "pausar_investimentos": None}


def test_challenge_rules():
    assert target_from_reward(50000, Decimal(5)) == 250000
    assert split_on_completion(250000, 50000) == {"liberado": 50000, "continua_guardado": 200000}
    plan = suggest(50000, Decimal(5), 80000)
    assert plan["meta"] == 250000 and plan["prazo_meses"] == 4
    assert suggest(50000, Decimal(5), -100)["tem_sobra"] is False


def seed_budget(client, clock):
    """Renda de R$ 5.000 e dois meses de historico."""
    for month in ("09", "10"):
        add_tx(client, f"2026-{month}-05", "renda", 500000)
        add_tx(client, f"2026-{month}-10", "gasto", 200000)


def test_budget_warning_for_mandatory_debts(ana, clock):
    seed_budget(ana, clock)
    account = personal_account(ana)
    ana.post("/api/dividas", json={"name": "Empréstimo", "account_id": account, "installment_cents": 450000,
                                   "due_day": 10, "total_installments": 24, "start_date": "2026-01-10"})
    result = ana.post("/api/orcamento/avaliar", json={"target_cents": 1_000_000, "term_months": 10}).json()
    assert result["orcamento"]["disponivel"] == 50000
    assert result["situacao"] == "compromete"
    assert "compromete" in result["mensagem"]
    assert result["alternativas"]["aumentar_prazo"]["meses"] == 20


def test_budget_suggests_pausing_investments(ana, clock):
    seed_budget(ana, clock)
    account = personal_account(ana)
    ana.post("/api/investimentos", json={"name": "Tesouro", "account_id": account, "monthly_plan_cents": 450000})
    result = ana.post("/api/orcamento/avaliar", json={"target_cents": 1_000_000, "term_months": 10}).json()
    assert result["situacao"] == "atencao"
    assert result["alternativas"]["pausar_investimentos"]["reduzir_por_mes"] == 50000
    # Avaliar nao muda nada.
    assert ana.get("/api/investimentos").json()[0]["aporte_mensal"] == 450000


def test_budget_updates_after_new_debt(ana, clock):
    seed_budget(ana, clock)
    before = ana.get("/api/orcamento/resumo").json()["disponivel"]
    ana.post("/api/dividas", json={"name": "X", "account_id": personal_account(ana), "installment_cents": 1000,
                                   "due_day": 1, "start_date": "2026-01-01"})
    assert ana.get("/api/orcamento/resumo").json()["disponivel"] == before - 1000


def test_goal_with_term_with_monthly_and_both(ana, clock):
    base = {"start_date": "2026-11-01", "target_cents": 1_200_000}
    by_term = ana.post("/api/objetivos", json={**base, "name": "A", "term_months": 12}).json()
    assert by_term["aporte_necessario"] == 100000
    by_monthly = ana.post("/api/objetivos", json={**base, "name": "B", "monthly_cents": 60000}).json()
    assert by_monthly["meses_previstos"] == 20 and by_monthly["data_prevista"] == "2028-07"
    both = ana.post("/api/objetivos", json={**base, "name": "C", "term_months": 12, "monthly_cents": 80000}).json()
    assert both["folga_mensal"] == -20000


def test_goal_contribution_counts_in_flow_and_schedule(ana, clock):
    goal = ana.post("/api/objetivos", json={"name": "Viagem", "start_date": "2026-11-01", "target_cents": 300000,
                                            "term_months": 3, "shares": {str(ana.user["id"]): 100}}).json()
    assert goal["situacao"] == "no_ritmo"
    updated = ana.post(f"/api/objetivos/{goal['id']}/aportar", json={
        "date": "2026-11-05", "amount_cents": 100000, "account_id": personal_account(ana)}).json()
    assert updated["guardado"] == 100000 and updated["percentual"] == 33.3
    assert updated["por_pessoa"] == {str(ana.user["id"]): 100000}
    assert ana.get("/api/painel/resumo", params={"ano": 2026, "mes": 11}).json()["totais"]["guardado"] == 100000
    schedule = ana.get(f"/api/objetivos/{goal['id']}/cronograma").json()
    assert [s["previsto"] for s in schedule] == [100000, 200000, 300000]
    assert schedule[0]["realizado"] == 100000 and schedule[1]["realizado"] is None
    clock.set_date(2027, 1, 15)
    ana.post("/api/autenticacao/entrar", json={"email": "ana@teste.com", "password": "senha-bem-longa-1"})  # sessao expirou
    assert ana.get(f"/api/objetivos/{goal['id']}").json()["situacao"] == "atrasado"


def test_split_by_contributions():
    assert split_by_contributions({}) == {}
    assert split_by_contributions({1: 60000, 2: 40000}) == {"1": 60.0, "2": 40.0}
    assert split_by_contributions({1: 100000}) == {"1": 100.0}
    assert split_by_contributions({1: 1, 2: 2}) == {"1": 33.3, "2": 66.7}


def test_joint_goal_split_comes_from_each_persons_contributions(ana, bia, clock):
    goal = ana.post("/api/objetivos", json={"name": "Casa", "start_date": "2026-11-01", "target_cents": 1_000_000,
                                            "term_months": 10}).json()
    assert goal["divisao"] == {}
    ana.post(f"/api/objetivos/{goal['id']}/aportar", json={
        "date": "2026-11-05", "amount_cents": 60000, "account_id": personal_account(ana)})
    bia.post(f"/api/objetivos/{goal['id']}/aportar", json={
        "date": "2026-11-06", "amount_cents": 40000, "account_id": personal_account(bia)})
    expected = {str(ana.user["id"]): 60.0, str(bia.user["id"]): 40.0}
    for client in (ana, bia):
        seen = client.get(f"/api/objetivos/{goal['id']}").json()
        assert seen["guardado"] == 100000 and seen["divisao"] == expected
    # Uma divisao digitada a mao (versao antiga da tela) e ignorada.
    ana.patch(f"/api/objetivos/{goal['id']}", json={"shares": {str(ana.user["id"]): 10, str(bia.user["id"]): 90}})
    assert ana.get(f"/api/objetivos/{goal['id']}").json()["divisao"] == expected


def test_goal_shares_must_total_100(ana):
    response = ana.post("/api/objetivos", json={"name": "X", "start_date": "2026-11-01", "target_cents": 100, "term_months": 1, "shares": {"1": 60}})
    assert response.status_code == 422


def test_reserve_from_essential_expenses(ana, clock):
    categories = ana.get("/api/contas/categorias").json()
    housing = next(c for c in categories if c["nome"] == "Moradia")
    add_tx(ana, "2026-10-05", "gasto", 200000, category_id=housing["id"])
    add_tx(ana, "2026-10-06", "gasto", 99999)  # sem categoria essencial: nao entra
    reserve = ana.put("/api/reserva", json={"target_months": 6}).json()
    assert reserve["valor_objetivo"] == 1_200_000
    updated = ana.post("/api/reserva/aportar", json={"date": "2026-11-01", "amount_cents": 400000, "account_id": personal_account(ana)}).json()
    assert updated["meses_cobertos"] == 2.0
    # Reserva nao aparece misturada na lista de objetivos.
    assert ana.get("/api/objetivos").json() == []


def test_reserve_needs_data_or_manual_target(ana):
    assert ana.put("/api/reserva", json={"target_months": 6}).status_code == 422
    assert ana.put("/api/reserva", json={"target_months": 6, "manual_target_cents": 100000}).status_code == 200


def test_challenge_full_cycle(ana, clock):
    account = personal_account(ana)
    created = ana.post("/api/desafios", json={
        "name": "Hobby", "reward_cents": 50000, "reward_label": "Hobby", "multiplier": "5", "term_months": 4, "start_date": "2026-11-01",
    }).json()
    assert created["meta"] == 250000 and created["liberado"] == 50000 and created["continua_guardado"] == 200000
    assert created["aporte_mensal"] == 62500
    assert ana.post(f"/api/desafios/{created['id']}/concluir").status_code == 409
    ana.post(f"/api/desafios/{created['id']}/aportar", json={"date": "2026-11-02", "amount_cents": 250000, "account_id": account})
    assert ana.post(f"/api/desafios/{created['id']}/usar-recompensa", json={"date": "2026-11-03", "account_id": account}).status_code == 409
    done = ana.post(f"/api/desafios/{created['id']}/concluir").json()
    assert done["situacao"] == "concluido"
    used = ana.post(f"/api/desafios/{created['id']}/usar-recompensa", json={"date": "2026-11-03", "account_id": account}).json()
    assert used["recompensa_usada"]
    assert ana.post(f"/api/desafios/{created['id']}/usar-recompensa", json={"date": "2026-11-03", "account_id": account}).status_code == 409
    assert ana.get("/api/painel/resumo", params={"ano": 2026, "mes": 11}).json()["totais"]["lazer"] == 50000


def test_challenge_custom_target_and_invested_metric(ana):
    account = personal_account(ana)
    custom = ana.post("/api/desafios", json={"name": "10 mil", "reward_cents": 100000, "target_cents": 1_000_000, "metric": "investir", "start_date": "2026-11-01"}).json()
    assert custom["multiplicador"] == "10.00"
    ana.post("/api/investimentos", json={"name": "Tesouro", "account_id": account, "initial_contributed_cents": 1_000_000})
    assert ana.get("/api/desafios").json()[0]["alcancado"] is True


def test_challenge_suggestion_uses_surplus(ana, clock):
    seed_budget(ana, clock)
    plan = ana.get("/api/desafios/sugestao", params={"recompensa": 50000}).json()
    assert plan["sobra_media"] == 300000
    assert plan["meta"] == 250000 and plan["prazo_meses"] == 1
