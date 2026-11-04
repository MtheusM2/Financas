"""Regras puras dos desafios: meta = recompensa x multiplicador."""
import math
from decimal import Decimal

from app.modules.financiamentos.calc import to_cents

DEFAULT_MULTIPLIER = Decimal(5)
# Parte da sobra mensal que a sugestao usa como recompensa, para o desafio caber sem aperto.
SUGGESTED_REWARD_SHARE = Decimal("0.25")


def target_from_reward(reward: int, multiplier: Decimal) -> int:
    return to_cents(Decimal(reward) * multiplier)


def multiplier_from_target(reward: int, target: int) -> Decimal:
    return (Decimal(target) / Decimal(reward)).quantize(Decimal("0.01"))


def split_on_completion(target: int, reward: int) -> dict:
    return {"liberado": min(reward, target), "continua_guardado": max(target - reward, 0)}


def suggest(reward: int | None, multiplier: Decimal, monthly_surplus: int) -> dict:
    """Sugestao ajustavel. Sem sobra, nao propoe prazo."""
    if monthly_surplus <= 0:
        return {"recompensa": reward or 0, "multiplicador": str(multiplier),
                "meta": target_from_reward(reward or 0, multiplier), "prazo_meses": None,
                "aporte_mensal": None, "sobra_media": monthly_surplus, "tem_sobra": False}
    value = reward or to_cents(Decimal(monthly_surplus) * SUGGESTED_REWARD_SHARE)
    target = target_from_reward(value, multiplier)
    months = max(math.ceil(target / monthly_surplus), 1)
    return {"recompensa": value, "multiplicador": str(multiplier), "meta": target, "prazo_meses": months,
            "aporte_mensal": math.ceil(target / months), "sobra_media": monthly_surplus, "tem_sobra": True}
