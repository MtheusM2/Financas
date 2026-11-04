"""Funcoes puras de planejamento. Taxa mensal em fracao; aporte no fim de cada mes."""
import math
from decimal import Decimal

from app.modules.financiamentos.calc import to_cents


def required_monthly(target: int, saved: int, months: int, rate: Decimal = Decimal(0)) -> int:
    if months <= 0:
        return max(target - saved, 0)
    if rate == 0:
        return max(math.ceil((target - saved) / months), 0)
    growth = (1 + rate) ** months
    return max(to_cents((target - Decimal(saved) * growth) * rate / (growth - 1)), 0)


def months_to_reach(target: int, saved: int, monthly: int, rate: Decimal = Decimal(0)) -> int | None:
    """None quando o plano nunca chega ao objetivo."""
    if saved >= target:
        return 0
    if monthly <= 0 and (rate == 0 or saved <= 0):
        return None
    if rate == 0:
        return math.ceil((target - saved) / monthly)
    balance, months = Decimal(saved), 0
    while balance < target:
        balance = balance * (1 + rate) + monthly
        months += 1
        if months > 1200:
            return None
    return months


def project(saved: int, monthly: int, months: int, rate: Decimal = Decimal(0)) -> list[int]:
    """Saldo previsto ao fim de cada mes."""
    balance, result = Decimal(saved), []
    for _ in range(months):
        balance = balance * (1 + rate) + monthly
        result.append(to_cents(balance))
    return result


def split_by_contributions(per_person: dict[int, int]) -> dict[str, float]:
    """Quanto cada pessoa investiu, em % do total aportado. Mostra a participacao, nao compara quem guardou mais."""
    total = sum(v for v in per_person.values() if v > 0)
    if total <= 0:
        return {}
    return {str(uid): round(v / total * 100, 1) for uid, v in per_person.items() if v > 0}
