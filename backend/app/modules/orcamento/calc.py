"""Avaliacao pura: um novo compromisso mensal cabe no que sobra?"""
import math
from decimal import Decimal

from app.modules.objetivos.calc import project

ATTENTION_SHARE = Decimal("0.8")


def assess(amount: int, free: int, invest_plans: int, available: int) -> str:
    """cabe | atencao | compromete."""
    if available <= 0 or amount > free + invest_plans:
        return "compromete"
    if amount > free or amount > free * ATTENTION_SHARE:
        return "atencao"
    return "cabe"


def alternatives(total: int, saved: int, amount: int, term: int, free: int, invest_plans: int,
                 invest_rate: Decimal = Decimal(0)) -> dict:
    """Caminhos para quando nao cabe. So contas: a decisao e de quem usa o sistema."""
    missing = max(total - saved, 0)
    result: dict = {"aumentar_prazo": None, "reduzir_valor": None, "pausar_investimentos": None}
    if free > 0:
        months = math.ceil(missing / free) if missing else 0
        result["aumentar_prazo"] = {"aporte_mensal": free, "meses": months, "serie": project(saved, free, min(months, 600))}
        reachable = saved + free * term
        result["reduzir_valor"] = {"aporte_mensal": free, "meses": term, "valor_possivel": reachable, "serie": project(saved, free, term)}
    shortage = amount - max(free, 0)
    if 0 < shortage <= invest_plans:
        foregone = project(0, shortage, term, invest_rate)
        result["pausar_investimentos"] = {
            "reduzir_por_mes": shortage, "meses": term, "aporte_mensal": amount,
            "deixa_de_aportar": shortage * term, "deixa_de_acumular": foregone[-1] if foregone else 0,
            "serie": project(saved, amount, term),
        }
    return result
