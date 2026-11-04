"""Holerites com dados ficticios. Nunca coloque aqui um holerite de verdade."""
import base64

import pytest

from app.modules.holerites.extract import check_pdf, chars_to_words, extract_words
from app.modules.holerites.parse import PayslipError, Word, parse_words
from conftest import personal_account

# Layout 1: valores abaixo dos rotulos e duas vias na mesma folha (empresa e funcionario).
VIA = [
    (20, 20, "EMPRESA FICTICIA ALFA LTDA"),
    (20, 32, "CNPJ: 11.222.333/0001-81"), (420, 32, "Folha Mensal"),
    (420, 44, "Marco de 2026"),
    (20, 58, "Codigo  Nome do Funcionario"), (380, 58, "Admissao: 01/02/2020"),
    (20, 80, "Codigo"), (60, 80, "Descricao"), (290, 80, "Referencia"), (370, 80, "Vencimentos"), (460, 80, "Descontos"),
    (25, 92, "1"), (60, 92, "SALARIO MENSAL"), (300, 92, "30,00"), (380, 92, "3.000,00"),
    (25, 103, "45"), (60, 103, "HORAS EXTRAS 50%"), (300, 103, "10:00"), (390, 103, "204,55"),
    (25, 114, "998"), (60, 114, "I.N.S.S."), (300, 114, "9,00"), (470, 114, "288,41"),
    (25, 125, "217"), (60, 125, "VALE TRANSPORTE 6%"), (300, 125, "6,00"), (470, 125, "180,00"),
    (370, 200, "Total de Vencimentos"), (460, 200, "Total de Descontos"),
    (380, 212, "3.204,55"), (470, 212, "468,41"),
    (350, 230, "Valor Líquido"), (470, 230, "2.736,14"),
    (30, 250, "Salário Base"), (120, 250, "Sal. Contr. INSS"), (210, 250, "Base Cálc. FGTS"),
    (300, 250, "F.G.T.S do Mês"), (390, 250, "Base Cálc. IRRF"),
    (30, 260, "3.000,00"), (120, 260, "3.204,55"), (210, 260, "3.204,55"), (300, 260, "256,36"), (390, 260, "2.916,14"),
]
LAYOUT_1 = VIA + [(x, y + 400, text) for x, y, text in VIA]

# Layout 2: outro sistema de folha, com outros nomes e totais ao lado do rotulo.
LAYOUT_2 = [
    (20, 20, "DEMONSTRATIVO DE PAGAMENTO"),
    (20, 34, "Comercio Beta Ficticio S/A"), (330, 34, "CNPJ 44.555.666/0001-99"),
    (20, 48, "Competência: 10/2026"), (330, 48, "Admissão 15/03/2024"),
    (20, 70, "Cód."), (60, 70, "Evento"), (280, 70, "Qtde"), (360, 70, "Proventos"), (460, 70, "Descontos"),
    (20, 82, "10"), (60, 82, "Salário"), (285, 82, "30"), (365, 82, "2.500,00"),
    (20, 93, "20"), (60, 93, "Adicional Noturno"), (365, 93, "150,00"),
    (20, 104, "30"), (60, 104, "INSS"), (470, 104, "212,10"),
    (20, 115, "40"), (60, 115, "Adiantamento"), (470, 115, "1.000,00"),
    (20, 126, "50"), (60, 126, "Pensão Alimentícia"), (470, 126, "300,00"),
    (300, 160, "Total Proventos"), (420, 160, "2.650,00"),
    (300, 172, "Total Descontos"), (420, 172, "1.512,10"),
    (300, 184, "Líquido a Receber"), (420, 184, "1.137,90"),
    (20, 210, "Base INSS"), (110, 210, "Base FGTS"), (200, 210, "FGTS do Mês"), (290, 210, "Base IRRF"),
    (20, 221, "2.650,00"), (110, 221, "2.650,00"), (200, 221, "212,00"), (290, 221, "2.137,90"),
]


def as_words(items, char_width=5.0):
    """Simula as palavras que o PDF entrega, com a posicao de cada uma."""
    words = []
    for x, y, text in items:
        cursor = x
        for part in text.split(" "):
            if part:
                words.append(Word(part, cursor, cursor + len(part) * char_width, y))
            cursor += (len(part) + 1) * char_width
    return words


def make_pdf(items, height=842) -> bytes:
    """PDF minimo com texto nas posicoes dadas (topo a partir de cima da folha)."""
    ops = []
    for x, y, text in items:
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 8 Tf {x} {height - y - 8} Td ({safe}) Tj ET")
    stream = "\n".join(ops).encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 {height}] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>".encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_layout_1_with_two_copies_becomes_one_payslip():
    slips = parse_words(as_words(LAYOUT_1))
    assert len(slips) == 1
    slip = slips[0].as_dict()
    assert slip["empresa"] == "EMPRESA FICTICIA ALFA LTDA"
    assert slip["cnpj"] == "11.222.333/0001-81"
    assert slip["referencia"] == 202603
    assert [(i["codigo"], i["descricao"], i["tipo"], i["valor"]) for i in slip["itens"]] == [
        ("1", "SALARIO MENSAL", "provento", 300000), ("45", "HORAS EXTRAS 50%", "provento", 20455),
        ("998", "I.N.S.S.", "desconto", 28841), ("217", "VALE TRANSPORTE 6%", "desconto", 18000),
    ]
    assert slip["itens"][1]["referencia"] == "10:00"
    assert slip["totais"] == {
        "total_vencimentos": 320455, "total_descontos": 46841, "liquido": 273614, "salario_base": 300000,
        "base_inss": 320455, "base_fgts": 320455, "fgts_mes": 25636, "base_irrf": 291614,
    }
    assert slip["conferido"] and slip["avisos"] == []


def test_layout_2_other_labels_without_new_code():
    slip = parse_words(as_words(LAYOUT_2))[0].as_dict()
    assert slip["empresa"] == "Comercio Beta Ficticio S/A"
    assert slip["cnpj"] == "44.555.666/0001-99"
    assert slip["referencia"] == 202610  # nao confunde com a data de admissao
    assert (slip["itens"][0]["descricao"], slip["itens"][0]["referencia"]) == ("Salário", "30")
    assert sum(i["valor"] for i in slip["itens"] if i["tipo"] == "provento") == 265000
    assert [i["descricao"] for i in slip["itens"] if i["tipo"] == "desconto"] == ["INSS", "Adiantamento", "Pensão Alimentícia"]
    assert slip["totais"]["liquido"] == 113790
    assert slip["totais"]["base_fgts"] == 265000 and slip["totais"]["fgts_mes"] == 21200
    assert slip["totais"]["base_irrf"] == 213790
    assert slip["conferido"]


def test_sums_that_do_not_match_are_reported():
    broken = [item if item[2] != "2.736,14" else (item[0], item[1], "2.000,00") for item in VIA]
    slip = parse_words(as_words(broken))[0].as_dict()
    assert not slip["conferido"]
    assert "Vencimentos menos descontos não dá o valor líquido." in slip["avisos"]


def test_missing_totals_are_calculated_and_flagged():
    only_items = [item for item in VIA if item[1] < 150]
    slip = parse_words(as_words(only_items))[0].as_dict()
    assert slip["totais"]["liquido"] == 320455 - 46841
    assert not slip["conferido"]


def test_text_without_table_is_refused():
    with pytest.raises(PayslipError):
        parse_words(as_words([(20, 20, "Qualquer texto"), (20, 40, "Total 10,00")]))


def test_real_pdf_path_with_accents():
    words = extract_words(make_pdf(VIA))
    slip = parse_words(words)[0].as_dict()
    assert slip["referencia"] == 202603 and slip["totais"]["liquido"] == 273614 and slip["conferido"]


def test_only_real_pdfs_are_accepted():
    with pytest.raises(PayslipError, match="não é um PDF"):
        check_pdf(b"<html><script>alert(1)</script></html>")
    with pytest.raises(PayslipError, match="5 MB"):
        check_pdf(b"%PDF-1.4" + b"0" * 5_000_001)
    with pytest.raises(PayslipError):
        extract_words(b"%PDF-1.4\nisto nao e um pdf de verdade")


def test_chars_become_words():
    chars = [(c, 10 + i * 5, 14 + i * 5, 100.0, 8.0) for i, c in enumerate("ab cd")]
    assert [w.text for w in chars_to_words(chars)] == ["ab", "cd"]


# ---------- rotas ----------

def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def reviewed(client, raw=None) -> dict:
    response = client.post("/api/holerites/previa", json={"content_base64": b64(raw or make_pdf(VIA))})
    assert response.status_code == 200, response.text
    slip = response.json()["holerites"][0]
    return {k: v for k, v in slip.items() if k not in ("avisos", "conferido", "ja_importado")}


def test_preview_save_and_launch_income(ana):
    data = reviewed(ana)
    account = personal_account(ana)
    response = ana.post("/api/holerites", json={**data, "lancar_renda": {"account_id": account, "date": "2026-04-05"}})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["liquido"] == 273614 and saved["lancamento_id"]
    found = ana.get("/api/lancamentos", params={"inicio": "2026-04-01", "fim": "2026-04-30"}).json()["itens"]
    tx = next(t for t in found if t["id"] == saved["lancamento_id"])
    assert (tx["tipo"], tx["valor"], tx["quitado"], str(tx["competencia"])) == ("renda", 273614, True, "2026-03-01")
    # O mesmo holerite de novo: avisa na previa e recusa ao gravar.
    again = ana.post("/api/holerites/previa", json={"content_base64": b64(make_pdf(VIA))}).json()["holerites"][0]
    assert again["ja_importado"] is True
    assert ana.post("/api/holerites", json=data).status_code == 409
    assert [p["id"] for p in ana.get("/api/holerites").json()] == [saved["id"]]


def test_payslip_is_visible_only_to_its_owner(ana, bia):
    saved = ana.post("/api/holerites", json=reviewed(ana)).json()
    assert bia.get("/api/holerites").json() == []
    assert bia.get(f"/api/holerites/{saved['id']}").status_code == 404
    assert bia.delete(f"/api/holerites/{saved['id']}").status_code == 404
    assert ana.get(f"/api/holerites/{saved['id']}").status_code == 200
    assert ana.delete(f"/api/holerites/{saved['id']}").status_code == 200
    assert ana.get("/api/holerites").json() == []


def test_invalid_files_and_values_are_refused(ana):
    bad = ana.post("/api/holerites/previa", json={"content_base64": b64(b"MZ\x90\x00 executavel")})
    assert bad.status_code == 422 and "PDF" in bad.json()["detail"]
    assert ana.post("/api/holerites/previa", json={"content_base64": "%%%"}).status_code == 422
    data = reviewed(ana)
    assert ana.post("/api/holerites", json={**data, "referencia": 202613}).status_code == 422
    assert ana.post("/api/holerites", json={**data, "liquido": -1}).status_code == 422


# ---------- ligar a rendas ja lancadas ----------

def add_income(client, day, cents, description):
    response = client.post("/api/lancamentos", json={"date": day, "account_id": personal_account(client), "kind": "renda",
                                                     "amount_cents": cents, "description": description})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_links_payslip_to_income_already_launched(ana, bia):
    # Holerite ficticio de outubro: liquido 1.137,90 e adiantamento 1.000,00 descontado.
    advance = add_income(ana, "2026-10-20", 100000, "Adiantamento quinzenal")
    salary = add_income(ana, "2026-11-06", 113790, "Salario")
    meal = add_income(ana, "2026-11-01", 30000, "VR cartao")
    other = add_income(ana, "2026-10-25", 5000, "Venda de bolo")
    add_income(bia, "2026-11-06", 113790, "Salario da Bia")  # de outra pessoa: nunca aparece

    slip = ana.post("/api/holerites/previa", json={"content_base64": b64(make_pdf(LAYOUT_2))}).json()["holerites"][0]
    suggested = {c["id"]: c["sugestao"] for c in slip["candidatos"]}
    assert suggested == {advance: "adiantamento", salary: "liquido", meal: "beneficio", other: None}

    data = {k: v for k, v in slip.items() if k not in ("avisos", "conferido", "ja_importado", "candidatos")}
    links = [{"transaction_id": i, "papel": p} for i, p in suggested.items() if p]
    # Com o salario ja ligado, lancar o liquido de novo duplicaria a renda.
    both = {**data, "vinculos": links, "lancar_renda": {"account_id": personal_account(ana), "date": "2026-11-06"}}
    assert ana.post("/api/holerites", json=both).status_code == 422
    # A outra pessoa nao consegue ligar rendas da Ana.
    assert bia.post("/api/holerites", json={**data, "vinculos": links}).status_code in (404, 422)

    before = len(ana.get("/api/lancamentos", params={"inicio": "2026-10-01", "fim": "2026-11-30"}).json()["itens"])
    saved = ana.post("/api/holerites", json={**data, "vinculos": links})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["resumo"] == {"esperado_em_conta": 213790, "ligado_salario": 213790, "beneficios": 30000,
                              "diferenca": 0, "confere": True}
    rows = ana.get("/api/lancamentos", params={"inicio": "2026-10-01", "fim": "2026-11-30"}).json()["itens"]
    assert len(rows) == before  # nada novo: so ligou
    competence = {t["id"]: str(t["competencia"]) for t in rows}
    assert competence[salary] == competence[advance] == "2026-10-01"
    assert competence[meal] in ("None", "2026-11-01")  # beneficio fica no mes em que caiu

    # Renda ja ligada nao aparece de novo nem pode ser ligada a outro holerite.
    again = ana.post("/api/holerites/previa", json={"content_base64": b64(make_pdf(LAYOUT_2))}).json()["holerites"][0]
    assert {c["id"] for c in again["candidatos"]} == {other}
    other_data = {**data, "referencia": 202609}
    assert ana.post("/api/holerites", json={**other_data, "vinculos": [{"transaction_id": salary, "papel": "liquido"}]}).status_code == 409
    assert "Salario da Bia" not in ana.get(f"/api/holerites/{body['id']}").text


# ---------- aprender rotulos, mudancas e FGTS ----------

def test_learns_an_unknown_label_from_the_review(ana):
    odd = [(x, y, "Vlr. Receber Funcionario") if text == "Líquido a Receber" else (x, y, text) for x, y, text in LAYOUT_2]
    first = ana.post("/api/holerites/previa", json={"content_base64": b64(make_pdf(odd))}).json()["holerites"][0]
    assert not first["conferido"]  # sem o rotulo, o liquido foi calculado e veio com aviso
    assert {"rotulo": "Vlr. Receber Funcionario", "valor": 113790} in first["desconhecidos"]
    data = {k: v for k, v in first.items() if k not in ("avisos", "conferido", "ja_importado", "candidatos", "desconhecidos", "mudancas")}
    learn = [{"rotulo": "Vlr. Receber Funcionario", "campo": "liquido"}]
    assert ana.post("/api/holerites", json={**data, "aprender": learn}).status_code == 200
    again = ana.post("/api/holerites/previa", json={"content_base64": b64(make_pdf(odd))}).json()["holerites"][0]
    assert again["conferido"] and again["liquido"] == 113790


def test_changes_between_months():
    from app.modules.holerites.analise import changes
    before = {"liquido": 1000, "itens": [{"tipo": "desconto", "descricao": "I.N.S.S.", "valor": 100},
                                         {"tipo": "desconto", "descricao": "Vale transporte", "valor": 60}]}
    after = {"liquido": 900, "itens": [{"tipo": "desconto", "descricao": "INSS", "valor": 120},
                                       {"tipo": "desconto", "descricao": "Emprestimo folha", "valor": 80}]}
    kinds = {(c["tipo"], c["texto"]) for c in changes(before, after)}
    assert kinds == {("mudou", "INSS mudou"), ("novo", "Desconto novo: Emprestimo folha"),
                     ("sumiu", "Saiu do holerite: Vale transporte"), ("liquido", "O líquido mudou")}


def test_fgts_caixa_versus_payslips():
    from datetime import date
    from app.modules.holerites.analise import fgts_status
    balances = [{"id": 1, "data": date(2026, 8, 31), "saldo": 100000}, {"id": 2, "data": date(2026, 10, 31), "saldo": 140000}]
    deposits = [{"referencia": 202608, "valor": 20000}, {"referencia": 202609, "valor": 20000}, {"referencia": 202610, "valor": 20000}]
    status = fgts_status(balances, deposits, date(2026, 11, 25))
    assert status["historico"][0]["esperado"] == 140000 and status["historico"][0]["diferenca"] == 0  # ago e set
    assert status["saldo_caixa"] == 140000 and status["depositos_desde"] == 20000  # outubro caiu em 20/11
    assert status["saldo_calculado"] == 160000 and status["a_depositar"] == 0
    assert [(d["referencia"], d["situacao"]) for d in status["depositos"]] == [
        (202610, "somado"), (202609, "na_caixa"), (202608, "na_caixa")]


def test_analysis_route_shows_months_changes_and_fgts(ana, bia):
    base = {"empresa": "Empresa Ficticia", "cnpj": "11.222.333/0001-81", "total_descontos": 10000, "fgts_mes": 24000}
    ana.post("/api/holerites", json={**base, "referencia": 202609, "total_vencimentos": 300000, "liquido": 290000,
                                     "itens": [{"descricao": "Salario", "tipo": "provento", "valor": 300000},
                                               {"descricao": "INSS", "tipo": "desconto", "valor": 10000}]})
    ana.post("/api/holerites", json={**base, "referencia": 202610, "total_vencimentos": 300000, "liquido": 280000,
                                     "total_descontos": 20000,
                                     "itens": [{"descricao": "Salario", "tipo": "provento", "valor": 300000},
                                               {"descricao": "INSS", "tipo": "desconto", "valor": 12000},
                                               {"descricao": "Emprestimo", "tipo": "desconto", "valor": 8000}]})
    assert ana.post("/api/holerites/fgts", json={"date": "2026-10-01", "balance_cents": 500000}).status_code == 200
    data = ana.get("/api/holerites/analise/resumo").json()
    assert [m["referencia"] for m in data["meses"]] == [202609, 202610]
    assert {c["tipo"] for c in data["meses"][1]["mudancas"]} == {"mudou", "novo", "liquido"}
    # Setembro caiu em 20/10 e outubro em 20/11 (o relogio dos testes esta em 15/11).
    assert data["fgts"]["saldo_calculado"] == 524000 and data["fgts"]["a_depositar"] == 24000
    assert bia.get("/api/holerites/analise/resumo").json() == {"meses": [], "fgts": bia.get("/api/holerites/analise/resumo").json()["fgts"]}
    assert bia.get("/api/holerites/analise/resumo").json()["fgts"]["saldo_caixa"] is None
