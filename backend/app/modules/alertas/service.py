"""Alertas calculados sob demanda e resumo diario por e-mail."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import local_today
from app.core.email import send_email
from app.core.visibility import visible_clause
from app.modules.autenticacao.models import User
from app.modules.contas.service import Scope
from app.modules.dividas.models import Debt
from app.modules.dividas.routes import due_status, paid_count
from app.modules.financiamentos.models import Financing
from app.modules.financiamentos.routes import due_status as financing_status, installments_paid, schedule
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import DUE_WINDOW_DAYS as WINDOW_DAYS, tx_filter
from app.modules.orcamento.ceilings import ceilings_status
from app.modules.previsao.service import forecast


def _money(cents: int) -> str:
    text = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def _due_alert(tipo: str, name: str, due: date, amount: int, today: date) -> dict | None:
    days = (due - today).days
    if days < 0:
        return {"nivel": "critico", "tipo": tipo, "titulo": f"{name} está atrasada", "data": due, "valor": amount,
                "detalhe": f"Venceu há {-days} dia(s)."}
    if days <= WINDOW_DAYS:
        when = "hoje" if days == 0 else f"em {days} dia(s)"
        return {"nivel": "atencao", "tipo": tipo, "titulo": f"{name} vence {when}", "data": due, "valor": amount, "detalhe": ""}
    return None


def collect(db: Session, viewer_id: int) -> list[dict]:
    today = local_today()
    alerts: list[dict | None] = []
    scope = Scope("casal")

    pending = db.scalars(select(Transaction).where(
        Transaction.settled.is_(False), Transaction.date <= today + timedelta(days=WINDOW_DAYS), tx_filter(viewer_id, scope),
    ).order_by(Transaction.date))
    for tx in pending:
        name = tx.description or "Lançamento"
        if tx.kind == "renda":
            if tx.date < today:
                alerts.append({"nivel": "critico", "tipo": "a_receber", "titulo": f"{name}: recebimento em atraso", "data": tx.date,
                               "valor": tx.amount_cents, "detalhe": f"Era esperado há {(today - tx.date).days} dia(s)."})
            elif tx.date <= today + timedelta(days=WINDOW_DAYS):
                alerts.append({"nivel": "info", "tipo": "a_receber", "titulo": f"{name}: a receber", "data": tx.date, "valor": tx.amount_cents, "detalhe": ""})
        else:
            alerts.append(_due_alert("a_pagar", name, tx.date, tx.amount_cents, today))

    for debt in db.scalars(select(Debt).where(Debt.active.is_(True), visible_clause(Debt, viewer_id))):
        paid, _ = paid_count(db, debt, viewer_id)
        status = due_status(debt, paid, today)
        if status["situacao"] == "quitada":
            continue
        alert = _due_alert("divida", debt.name, status["proximo_vencimento"], debt.installment_cents, today)
        if alert and status["atrasadas"] > 1:
            alert["detalhe"] += f" São {status['atrasadas']} pagamentos em aberto."
        alerts.append(alert)

    for item in db.scalars(select(Financing).where(Financing.active.is_(True), visible_clause(Financing, viewer_id))):
        rows = schedule(db, item)
        paid = installments_paid(db, item, viewer_id)
        status = financing_status(item, len(rows), paid, today)
        if status["situacao"] == "quitada":
            continue
        alert = _due_alert("financiamento", f"Parcela de {item.name}", status["proximo_vencimento"],
                           rows[paid].payment + rows[paid].fee, today)
        if alert and status["atrasadas"] > 1:
            alert["detalhe"] += f" São {status['atrasadas']} parcelas em aberto."
        alerts.append(alert)

    for ceiling in ceilings_status(db, viewer_id, today.year, today.month):
        if ceiling["situacao"] == "estourou":
            alerts.append({"nivel": "critico", "tipo": "teto", "titulo": f"Teto de {ceiling['categoria']} estourado", "data": None,
                           "valor": -ceiling["disponivel"], "detalhe": f"Gasto de {_money(ceiling['gasto'])} para um teto de {_money(ceiling['teto'])}."})
        elif ceiling["situacao"] == "perto":
            alerts.append({"nivel": "atencao", "tipo": "teto", "titulo": f"Teto de {ceiling['categoria']} perto do limite", "data": None,
                           "valor": ceiling["disponivel"], "detalhe": f"{ceiling['percentual']}% usado."})

    future = forecast(db, viewer_id, scope, 3)
    if future["fica_negativo_em"]:
        alerts.append({"nivel": "critico", "tipo": "previsao", "titulo": "O saldo previsto fica negativo", "data": future["fica_negativo_em"],
                       "valor": future["menor_saldo"], "detalhe": "Considera o que já está lançado, recorrente ou parcelado."})

    order = {"critico": 0, "atencao": 1, "info": 2}
    # Dentro do mesmo nivel, o que tem data para pagar vem antes.
    return sorted((a for a in alerts if a), key=lambda a: (order[a["nivel"]], a["tipo"] not in ("divida", "financiamento")))


def send_daily_summaries(db: Session) -> None:
    for user in db.scalars(select(User).where(User.email_verified.is_(True))).all():
        if not (user.prefs or {}).get("alertas_email", True):
            continue
        alerts = [a for a in collect(db, user.id) if a["nivel"] != "info"]
        if not alerts:
            continue
        lines = [f"- {a['titulo']}: {_money(a['valor'])}. {a['detalhe']}".rstrip() for a in alerts]
        send_email(user.email, f"Finanças do Casal: {len(alerts)} alerta(s)", "\n".join(lines))
