"""Importacao, conciliacao, caixa x competencia, DRE, tetos, alertas, previsao e IR."""
import base64

from app.core.db import SessionLocal
from app.core.email import outbox
from app.modules.alertas.service import send_daily_summaries
from app.modules.conciliacao.parse import line_ids, normalize, parse_amount, parse_csv, parse_ofx, parse_statement, Line
from app.modules.lancamentos.service import materialize_all
from conftest import add_tx, personal_account

OFX = """OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261105120000[-3:BRT]<TRNAMT>5000.00<FITID>A1<MEMO>SALARIO EMPRESA</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261106<TRNAMT>-45.90<FITID>A2<MEMO>UBER *1234</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>4954.10<DTASOF>20261106</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""

CSV = "Extrato do banco\n\nData;Histórico;Valor\n05/11/2026;Salário;5.000,00\n06/11/2026;Mercado;-123,45\n"


def b64(text, encoding="utf-8"):
    return base64.b64encode(text.encode(encoding)).decode()


def preview(client, account, text=OFX):
    response = client.post("/api/conciliacao/previa", json={"account_id": account, "content_base64": b64(text)})
    assert response.status_code == 200, response.text
    return response.json()


def to_lines(rows):
    return [{"date": r["data"], "amount_cents": r["valor"], "description": r["descricao"], "fitid": r["fitid"], "kind": r["tipo"],
             "category_id": r["categoria_id"], "match_id": r["conciliar_com"]["id"] if r["conciliar_com"] else None}
            for r in rows if r["situacao"] != "duplicada"]


def test_parsers():
    statement = parse_ofx(OFX)
    assert [(l.amount_cents, l.fitid) for l in statement.lines] == [(500000, "A1"), (-4590, "A2")]
    assert statement.balance_cents == 495410 and str(statement.balance_date) == "2026-11-06"
    lines = parse_csv(CSV).lines
    assert [(str(l.date), l.amount_cents) for l in lines] == [("2026-11-05", 500000), ("2026-11-06", -12345)]
    assert parse_amount("1,234.56") == 123456 and parse_amount("R$ 1.234,56") == 123456 and parse_amount("(10,00)") == -1000
    credit_debit = parse_csv("Data,Descrição,Crédito,Débito\n2026-11-01,A,100,\n2026-11-02,B,,50\n").lines
    assert [l.amount_cents for l in credit_debit] == [10000, -5000]
    assert parse_statement("Data;Histórico;Valor\n05/11/2026;Padaria São João;-5,00\n".encode("latin-1")).lines[0].description == "Padaria São João"
    assert normalize("UBER *1234") == normalize("UBER *9876")


def test_same_purchase_twice_same_day_are_different_lines():
    line = Line(__import__("datetime").date(2026, 11, 1), -500, "Café")
    first, second = line_ids(1, [line, line])
    assert first != second


def test_bad_files_are_refused(ana):
    account = personal_account(ana)
    assert ana.post("/api/conciliacao/previa", json={"account_id": account, "content_base64": b64("sem colunas\n1;2\n")}).status_code == 422
    assert ana.post("/api/conciliacao/previa", json={"account_id": account, "content_base64": "@@@"}).status_code == 422


def test_import_creates_matches_and_never_duplicates(ana):
    account = personal_account(ana)
    manual = add_tx(ana, "2026-11-04", "gasto", 4590, description="Corrida")  # o extrato veio 2 dias depois
    data = preview(ana, account)
    assert [r["situacao"] for r in data["linhas"]] == ["nova", "conciliada"]
    assert data["linhas"][1]["conciliar_com"]["id"] == manual["id"]
    assert data["saldo_banco"]["real"] == 495410
    # A previa nao grava nada.
    assert ana.get("/api/lancamentos").json()["total"] == 1
    result = ana.post("/api/conciliacao/confirmar", json={"account_id": account, "lines": to_lines(data["linhas"])}).json()
    assert result == {"criados": 1, "conciliados": 1, "ignorados": 0}
    items = ana.get("/api/lancamentos").json()["itens"]
    assert len(items) == 2 and all(i["importado"] for i in items)
    assert next(i for i in items if i["id"] == manual["id"])["data"] == "2026-11-06"
    # Importar o mesmo arquivo de novo nao muda nada.
    again = preview(ana, account)
    assert [r["situacao"] for r in again["linhas"]] == ["duplicada", "duplicada"]
    assert ana.get("/api/painel/resumo", params={"ano": 2026, "mes": 11}).json()["totais"]["renda"] == 500000


def test_import_learns_category(ana):
    account = personal_account(ana)
    category = ana.get("/api/contas/categorias").json()[0]["id"]
    lines = to_lines(preview(ana, account)["linhas"])
    lines[1].update(category_id=category, remember=True, kind="lazer")
    ana.post("/api/conciliacao/confirmar", json={"account_id": account, "lines": lines})
    other = "<OFX><STMTTRN><DTPOSTED>20261110<TRNAMT>-20.00<FITID>B1<MEMO>UBER *9999</STMTTRN></OFX>"
    row = preview(ana, account, other)["linhas"][0]
    assert row["tipo"] == "lazer" and row["categoria_id"] == category


def test_balance_reconciliation(ana):
    account = personal_account(ana)
    ana.patch(f"/api/contas/{account}", json={"opening_balance_cents": 10000})
    add_tx(ana, "2026-11-01", "renda", 5000)
    add_tx(ana, "2026-11-20", "gasto", 1000)  # depois da data conferida
    add_tx(ana, "2026-11-02", "gasto", 700, settled=False)  # previsto nao conta
    ok = ana.post("/api/conciliacao/saldo", json={"account_id": account, "date": "2026-11-10", "real_cents": 15000}).json()
    assert ok["confere"] is True
    off = ana.post("/api/conciliacao/saldo", json={"account_id": account, "date": "2026-11-10", "real_cents": 14000}).json()
    assert off["diferenca"] == -1000 and off["confere"] is False
    assert len(ana.get("/api/conciliacao/historico").json()) == 2


def test_pending_does_not_count_until_settled_and_cash_vs_accrual(ana):
    tx = add_tx(ana, "2026-10-28", "gasto", 30000, description="Conta de outubro", settled=False)
    add_tx(ana, "2026-10-05", "renda", 100000)
    summary = lambda m: ana.get("/api/painel/resumo", params={"ano": 2026, "mes": m}).json()["totais"]["gasto"]
    assert summary(10) == 0
    settled = ana.post(f"/api/lancamentos/{tx['id']}/quitar", json={"date": "2026-11-03"}).json()
    assert settled["quitado"] and settled["competencia"] == "2026-10-28"
    assert summary(10) == 0 and summary(11) == 30000  # caixa: saiu em novembro
    dre = lambda regime, month: ana.get("/api/relatorios/dre", params={"inicio": month, "fim": month, "regime": regime}).json()
    assert dre("competencia", 202610)["despesas"]["total"] == 30000  # competencia: pertence a outubro
    assert dre("caixa", 202610)["despesas"]["total"] == 0
    assert dre("caixa", 202611)["despesas"]["total"] == 30000


def test_accrual_includes_unpaid_and_cash_does_not(ana):
    add_tx(ana, "2026-11-20", "gasto", 5000, settled=False)
    params = {"inicio": 202611, "fim": 202611}
    assert ana.get("/api/relatorios/dre", params={**params, "regime": "competencia"}).json()["despesas"]["total"] == 5000
    assert ana.get("/api/relatorios/dre", params={**params, "regime": "caixa"}).json()["despesas"]["total"] == 0


def test_dre_groups_and_result(ana):
    categories = ana.get("/api/contas/categorias").json()
    housing = next(c for c in categories if c["nome"] == "Moradia")
    rent = next(c for c in housing["filhas"] if c["nome"] == "Aluguel")
    add_tx(ana, "2026-11-01", "renda", 500000)
    add_tx(ana, "2026-11-02", "gasto", 150000, category_id=rent["id"])
    add_tx(ana, "2026-11-03", "lazer", 50000)
    add_tx(ana, "2026-11-04", "investimento", 100000)
    dre = ana.get("/api/relatorios/dre", params={"inicio": 202611, "fim": 202611}).json()
    assert dre["resultado"] == 300000 and dre["margem"] == 60.0 and dre["situacao"] == "sobra"
    gasto = next(g for g in dre["despesas"]["grupos"] if g["tipo"] == "gasto")
    assert gasto["itens"] == [{"nome": "Moradia", "valor": 150000}]  # sobe para a categoria mae
    assert dre["fora_do_resultado"]["investimento"] == 100000  # investir nao e prejuizo
    assert dre["sobra_apos_guardar"] == 200000


def test_ceilings_status_and_alert(ana):
    food = next(c for c in ana.get("/api/contas/categorias").json() if c["nome"] == "Alimentação")
    market = next(c for c in food["filhas"] if c["nome"] == "Mercado")
    assert ana.post("/api/orcamento/tetos", json={"category_id": food["id"], "limit_cents": 100000}).status_code == 200
    assert ana.post("/api/orcamento/tetos", json={"category_id": food["id"], "limit_cents": 1}).status_code == 409
    add_tx(ana, "2026-11-05", "gasto", 85000, category_id=market["id"])  # subcategoria conta no teto da mae
    params = {"ano": 2026, "mes": 11}
    assert ana.get("/api/orcamento/tetos", params=params).json()[0]["situacao"] == "perto"
    add_tx(ana, "2026-11-06", "gasto", 20000, category_id=market["id"])
    ceiling = ana.get("/api/orcamento/tetos", params=params).json()[0]
    assert ceiling["situacao"] == "estourou" and ceiling["disponivel"] == -5000
    assert any(a["tipo"] == "teto" and a["nivel"] == "critico" for a in ana.get("/api/alertas").json())


def test_alerts_for_bills_receivables_and_email(ana, bia, clock):
    account = personal_account(ana)
    add_tx(ana, "2026-11-10", "gasto", 1000, description="Luz atrasada", settled=False)
    add_tx(ana, "2026-11-18", "gasto", 2000, description="Água", settled=False)
    add_tx(ana, "2026-11-10", "renda", 3000, description="Freela", settled=False)
    ana.post("/api/dividas", json={"name": "Celular", "account_id": account, "installment_cents": 5000, "due_day": 20, "total_installments": 3, "start_date": "2026-11-01"})
    alerts = {a["titulo"]: a for a in ana.get("/api/alertas").json()}
    assert alerts["Luz atrasada está atrasada"]["nivel"] == "critico"
    assert alerts["Água vence em 3 dia(s)"]["nivel"] == "atencao"
    assert alerts["Freela: recebimento em atraso"]["nivel"] == "critico"
    assert alerts["Celular vence em 5 dia(s)"]["valor"] == 5000
    outbox.clear()
    with SessionLocal() as db:
        send_daily_summaries(db)
    # Aberto por padrao: os dois recebem. O que esta oculto so vai para a dona.
    assert sorted(m["to"] for m in outbox if "Luz" in m["body"]) == ["ana@teste.com", "bia@teste.com"]
    add_tx(ana, "2026-11-10", "gasto", 1000, description="Particular", settled=False, hidden=True)
    outbox.clear()
    with SessionLocal() as db:
        send_daily_summaries(db)
    assert [m["to"] for m in outbox if "Particular" in m["body"]] == ["ana@teste.com"]
    # Quem desliga deixa de receber.
    ana.patch("/api/autenticacao/preferencias", json={"alertas_email": False})
    outbox.clear()
    with SessionLocal() as db:
        send_daily_summaries(db)
    assert not [m for m in outbox if m["to"] == "ana@teste.com"]


def test_paying_debt_clears_its_alert(ana):
    debt = ana.post("/api/dividas", json={"name": "Celular", "account_id": personal_account(ana), "installment_cents": 5000, "due_day": 20, "start_date": "2026-11-01"}).json()
    assert any("Celular" in a["titulo"] for a in ana.get("/api/alertas").json())
    ana.post(f"/api/dividas/{debt['id']}/pagar", json={"date": "2026-11-15"})
    assert not any("Celular" in a["titulo"] for a in ana.get("/api/alertas").json())


def test_forecast_projects_balance_and_warns_when_negative(ana):
    account = personal_account(ana)
    ana.patch(f"/api/contas/{account}", json={"opening_balance_cents": 100000})
    ana.post("/api/lancamentos/recorrencias", json={"account_id": account, "kind": "renda", "amount_cents": 50000, "day_of_month": 5, "start_month": 202611})
    ana.post("/api/dividas", json={"name": "Parcela", "account_id": account, "installment_cents": 80000, "due_day": 20, "total_installments": 2, "start_date": "2026-11-01"})
    add_tx(ana, "2026-11-25", "gasto", 10000, settled=False)
    data = ana.get("/api/previsao", params={"meses": 4}).json()
    # Hoje: 1.000 inicial + 500 do salario de novembro (dia 5 ja passou).
    assert data["saldo_atual"] == 150000
    assert [m["periodo"] for m in data["meses"]] == ["2026-11", "2026-12", "2027-01", "2027-02"]
    # Nov: -800 -100 | Dez: +500 -800 | Jan e Fev: so salario; a divida de 2 parcelas acabou.
    assert [m["saldo"] for m in data["meses"]] == [60000, 30000, 80000, 130000]
    assert data["menor_saldo"] == 30000 and data["fica_negativo_em"] is None
    add_tx(ana, "2026-12-01", "gasto", 200000, settled=False)
    data = ana.get("/api/previsao", params={"meses": 4}).json()
    assert data["fica_negativo_em"] == "2026-12-01"
    assert any(a["tipo"] == "previsao" for a in ana.get("/api/alertas").json())


def test_forecast_can_include_plans(ana):
    account = personal_account(ana)
    ana.post("/api/investimentos", json={"name": "T", "account_id": account, "monthly_plan_cents": 10000})
    without = ana.get("/api/previsao", params={"meses": 3}).json()["meses"][-1]["saldo"]
    assert ana.get("/api/previsao", params={"meses": 3, "incluir_planos": True}).json()["meses"][-1]["saldo"] == without - 20000


def test_recurring_future_occurrence_settles_when_date_arrives(ana, clock):
    ana.post("/api/lancamentos/recorrencias", json={"account_id": personal_account(ana), "kind": "renda", "amount_cents": 1000, "day_of_month": 20, "start_month": 202611})
    params = {"ano": 2026, "mes": 11}
    assert ana.get("/api/painel/resumo", params=params).json()["totais"]["renda"] == 0
    clock.set_date(2026, 11, 21)
    with SessionLocal() as db:
        materialize_all(db)
    assert ana.get("/api/painel/resumo", params=params).json()["totais"]["renda"] == 1000


def test_tax_report_and_csv(ana, bia):
    account = personal_account(ana)
    add_tx(ana, "2026-03-05", "renda", 500000, description="Salário")
    add_tx(ana, "2025-12-05", "renda", 100000)
    add_tx(bia, "2026-03-05", "renda", 400000)
    ana.post("/api/investimentos", json={"name": "=Fundo", "account_id": account, "initial_contributed_cents": 200000})
    fin = ana.post("/api/financiamentos", json={"name": "Carro", "account_id": account, "asset_value_cents": 1200000, "annual_rate_percent": "0", "system": "SAC", "term_months": 12, "first_due": "2026-01-10"}).json()
    ana.post(f"/api/financiamentos/{fin['id']}/pagar", json={"date": "2026-01-10"})
    data = ana.get("/api/relatorios/imposto", params={"ano": 2026}).json()
    assert sorted((r["pessoa"], r["valor"]) for r in data["rendimentos"]) == [("Ana", 500000), ("Bia", 400000)]
    assert data["dividas"][0]["saldo_fim_do_ano"] == 1100000 and data["dividas"][0]["pago_no_ano"] == 100000
    previous = ana.get("/api/relatorios/imposto", params={"ano": 2025}).json()
    assert previous["dividas"][0]["saldo_fim_do_ano"] == 1200000
    response = ana.get("/api/relatorios/imposto.csv", params={"ano": 2026})
    assert response.headers["content-type"].startswith("text/csv")
    assert "5000,00" in response.text and "Confira com os informes oficiais" in response.text
    assert "'=Fundo" in response.text  # nao vira formula ao abrir no Excel
    listing = ana.get("/api/relatorios/lancamentos.csv", params={"inicio": "2026-03-01", "fim": "2026-03-31"})
    assert "Realizado" in listing.text and "Salário" in listing.text


def test_pdf_or_garbage_gets_a_clear_message(ana):
    account = personal_account(ana)
    pdf = ana.post("/api/conciliacao/previa", json={"account_id": account, "content_base64": base64.b64encode(b"%PDF-1.4\n\x00\x01").decode()})
    assert pdf.status_code == 422 and "Holerites" in pdf.json()["detail"]
    junk = ana.post("/api/conciliacao/previa", json={"account_id": account, "content_base64": base64.b64encode(b'a;"b\rc\x00;\n"').decode()})
    assert junk.status_code == 422
