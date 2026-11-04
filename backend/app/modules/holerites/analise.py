"""Acompanhamento dos holerites: o que mudou de um mes para o outro e o FGTS.
Funcoes puras: recebem valores, devolvem listas e totais."""
from datetime import date

from app.modules.holerites.parse import norm

FGTS_DEPOSIT_DAY = 20  # o FGTS do mes M e depositado ate o dia 20 do mes seguinte


def item_totals(items: list[dict]) -> dict[tuple[str, str], tuple[str, int]]:
    """Soma por (tipo, descricao normalizada); guarda o nome como esta no holerite."""
    found: dict[tuple[str, str], tuple[str, int]] = {}
    for item in items:
        key = (item["tipo"], norm(item["descricao"]))
        name, value = found.get(key, (item["descricao"], 0))
        found[key] = (name, value + item["valor"])
    return found


def changes(previous: dict, current: dict) -> list[dict]:
    """previous/current: {itens, liquido}. Lista o que apareceu, sumiu ou mudou de valor."""
    before, after = item_totals(previous["itens"]), item_totals(current["itens"])
    found = []
    for key, (name, value) in after.items():
        kind = "desconto" if key[0] == "desconto" else "vencimento"
        if key not in before:
            found.append({"tipo": "novo", "texto": f"{kind.capitalize()} novo: {name}", "valor": value})
        elif before[key][1] != value:
            found.append({"tipo": "mudou", "texto": f"{name} mudou", "de": before[key][1], "para": value})
    for key, (name, value) in before.items():
        if key not in after:
            found.append({"tipo": "sumiu", "texto": f"Saiu do holerite: {name}", "valor": value})
    if previous["liquido"] != current["liquido"]:
        found.append({"tipo": "liquido", "texto": "O líquido mudou", "de": previous["liquido"], "para": current["liquido"]})
    return found


def deposit_date(reference: int) -> date:
    year, month = divmod(reference, 100)
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(year, month, FGTS_DEPOSIT_DAY)


def fgts_status(balances: list[dict], deposits: list[dict], today: date) -> dict:
    """balances: [{id, data, saldo}] informados da Caixa. deposits: [{referencia, valor}] dos holerites.
    Compara cada saldo da Caixa com o anterior mais os depositos do periodo."""
    balances = sorted(balances, key=lambda b: (b["data"], b["id"]))
    dated = sorted(({"referencia": d["referencia"], "valor": d["valor"], "data": deposit_date(d["referencia"])}
                    for d in deposits if d["valor"]), key=lambda d: d["data"])
    history = []
    for number, balance in enumerate(balances):
        row = {**balance, "esperado": None, "diferenca": None}
        if number:
            previous = balances[number - 1]
            period = sum(d["valor"] for d in dated if previous["data"] < d["data"] <= balance["data"])
            row["esperado"] = previous["saldo"] + period
            row["diferenca"] = balance["saldo"] - row["esperado"]
        history.append(row)
    last = balances[-1] if balances else None
    since = [d for d in dated if (last is None or d["data"] > last["data"]) and d["data"] <= today]
    pending = [d for d in dated if d["data"] > today]
    return {
        "saldo_caixa": last["saldo"] if last else None,
        "data_caixa": last["data"] if last else None,
        "depositos_desde": sum(d["valor"] for d in since),
        "saldo_calculado": (last["saldo"] if last else 0) + sum(d["valor"] for d in since),
        "a_depositar": sum(d["valor"] for d in pending),
        "total_holerites": sum(d["valor"] for d in dated),
        "historico": list(reversed(history)),
        # Cada deposito e onde ele entra: ja dentro do saldo da Caixa, somado depois dele, ou ainda vai cair.
        "depositos": [{**d, "situacao": "na_caixa" if last and d["data"] <= last["data"]
                       else "somado" if d["data"] <= today else "a_cair"} for d in reversed(dated)],
    }
