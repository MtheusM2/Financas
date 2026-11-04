"""Funcoes puras de financiamento. Valores em centavos inteiros."""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def to_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def annual_to_monthly(annual_percent: Decimal) -> Decimal:
    """Taxa efetiva: (1 + a)^(1/12) - 1, em fracao."""
    return (1 + annual_percent / 100) ** (Decimal(1) / 12) - 1


def price_payment(balance: int, rate: Decimal, months: int) -> int:
    if months <= 0:
        return balance
    if rate == 0:
        return to_cents(Decimal(balance) / months)
    return to_cents(Decimal(balance) * rate / (1 - (1 + rate) ** -months))


@dataclass
class Row:
    number: int
    payment: int
    interest: int
    amortization: int
    extra: int
    fee: int
    balance: int


def build_schedule(principal: int, rate: Decimal, months: int, system: str, fee: int = 0,
                   extras: dict[int, int] | None = None, keep_term: bool = False) -> list[Row]:
    """Tabela de parcelas. Amortizacao extra entra logo apos a parcela indicada.

    keep_term=False reduz o prazo e mantem a parcela; True mantem o prazo e reduz a parcela.
    """
    extras = extras or {}
    rows: list[Row] = []
    balance = principal
    payment = price_payment(principal, rate, months) if system == "PRICE" else 0
    fixed_amort = to_cents(Decimal(principal) / months) if system == "SAC" else 0
    number = 0
    while balance > 0 and number < months:
        number += 1
        interest = to_cents(Decimal(balance) * rate)
        amort = (payment - interest) if system == "PRICE" else fixed_amort
        if number == months or amort >= balance:
            amort = balance
        balance -= amort
        extra = min(extras.get(number, 0), balance)
        balance -= extra
        rows.append(Row(number, amort + interest, interest, amort, extra, fee, balance))
        if extra and keep_term and balance > 0:
            left = months - number
            if system == "PRICE":
                payment = price_payment(balance, rate, left)
            else:
                fixed_amort = to_cents(Decimal(balance) / left)
    return rows


def totals(rows: list[Row]) -> dict:
    return {
        "parcelas": len(rows),
        "juros_total": sum(r.interest for r in rows),
        "taxas_total": sum(r.fee for r in rows),
        "total_pago": sum(r.payment + r.extra + r.fee for r in rows),
    }
