"""Liga o holerite as rendas que a pessoa ja lancou (adiantamento, salario, VR/VT).
Funcoes puras: recebem valores e devolvem sugestoes e o resumo."""
import re

from app.modules.holerites.parse import norm

ROLES = ("liquido", "adiantamento", "beneficio", "outro")
BENEFIT = re.compile(r"\b(vr|va|vt|vale|refeicao|alimentacao|transporte|beneficio|flash|alelo|sodexo|ticket|caju|pluxee|swile)\b")
ADVANCE = re.compile(r"adiant")
NET_TOLERANCE = 0.005  # 0,5%: arredondamento ou tarifa do banco


def advances(items: list[dict]) -> list[int]:
    """Valores que o holerite desconta por ja terem sido pagos antes (adiantamento)."""
    return [i["valor"] for i in items if i["tipo"] == "desconto" and ADVANCE.search(norm(i["descricao"]))]


def suggest(net: int, items: list[dict], candidates: list[dict]) -> dict[int, str]:
    """candidates: [{id, valor, descricao}]. Devolve {id: papel} so para o que tem boa chance."""
    chosen: dict[int, str] = {}
    free = list(candidates)

    def take(predicate, role):
        for c in free:
            if predicate(c):
                chosen[c["id"]] = role
                free.remove(c)
                return True
        return False

    if not take(lambda c: c["valor"] == net, "liquido") and net > 0:
        take(lambda c: abs(c["valor"] - net) <= net * NET_TOLERANCE, "liquido")
    for value in advances(items):
        take(lambda c, v=value: c["valor"] == v, "adiantamento")
    for c in list(free):
        if BENEFIT.search(norm(c["descricao"])):
            chosen[c["id"]] = "beneficio"
            free.remove(c)
    return chosen


def summary(net: int, items: list[dict], links: list[dict]) -> dict:
    """links: [{papel, valor}]. Quanto o holerite diz que caiu na conta e quanto foi ligado."""
    expected = net + sum(advances(items))
    salary = sum(l["valor"] for l in links if l["papel"] != "beneficio")
    benefits = sum(l["valor"] for l in links if l["papel"] == "beneficio")
    return {"esperado_em_conta": expected, "ligado_salario": salary, "beneficios": benefits,
            "diferenca": salary - expected, "confere": salary == expected}
