import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.visibility import visible_clause
from app.modules.autenticacao.deps import current_user
from app.modules.autenticacao.models import User
from app.modules.contas.models import Account
from app.modules.contas.service import parse_scope
from app.modules.investimentos.models import Investment
from app.modules.investimentos.routes import serialize as investment_info
from app.modules.lancamentos.models import Transaction
from app.modules.lancamentos.service import summarize, totals_by_kind, tx_filter
from app.modules.relatorios import service
from app.modules.relatorios.dre import build_dre, tax_report
from app.modules.relatorios.models import MonthClosing

router = APIRouter(prefix="/api/relatorios", tags=["relatorios"])


def month_param():
    return Query(ge=200001, le=299912)


def closing_status(db: Session, viewer_id: int, year: int, month: int) -> dict | None:
    row = db.scalar(select(MonthClosing).where(
        MonthClosing.year == year, MonthClosing.month == month, MonthClosing.viewer_id == viewer_id))
    if row is None:
        return None
    return {"situacao": row.status, "fechado_em": row.closed_at, "reaberto_em": row.reopened_at}


@router.get("/mensal")
def monthly(ano: int = Query(ge=2000, le=2999), mes: int = Query(ge=1, le=12), escopo: str = "casal",
            db: Session = Depends(get_db), user=Depends(current_user)):
    scope = parse_scope(escopo)
    prev_year, prev_month = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    current = summarize(totals_by_kind(db, user.id, scope, ano, mes))
    previous = summarize(totals_by_kind(db, user.id, scope, prev_year, prev_month))
    return {
        "periodo": {"ano": ano, "mes": mes}, "totais": current,
        "comparado_mes_anterior": service.compare(previous, current),
        "fechamento": closing_status(db, user.id, ano, mes),
    }


@router.get("/comparar")
def compare(a_inicio: int = month_param(), a_fim: int = month_param(), b_inicio: int = month_param(), b_fim: int = month_param(),
            escopo: str = "casal", db: Session = Depends(get_db), user=Depends(current_user)):
    if a_inicio > a_fim or b_inicio > b_fim:
        raise HTTPException(422, "O início do período precisa vir antes do fim.")
    scope = parse_scope(escopo)
    return service.compare(
        service.period_totals(db, user.id, scope, a_inicio, a_fim),
        service.period_totals(db, user.id, scope, b_inicio, b_fim),
    )


@router.get("/serie")
def series(inicio: int = month_param(), fim: int = month_param(), agrupar: str = Query("mes", pattern="^(mes|ano)$"),
           escopo: str = "casal", db: Session = Depends(get_db), user=Depends(current_user)):
    scope = parse_scope(escopo)
    months = service.month_range(inicio, fim)
    if len(months) > 600:
        raise HTTPException(422, "Período longo demais.")
    if agrupar == "mes":
        return [{"periodo": f"{y}-{m:02d}", **summarize(totals_by_kind(db, user.id, scope, y, m))} for y, m in months]
    years = sorted({y for y, _ in months})
    result = []
    for year in years:
        keys = [y * 100 + m for y, m in months if y == year]
        result.append({"periodo": str(year), **service.period_totals(db, user.id, scope, min(keys), max(keys))})
    return result


@router.get("/ganhos-perdas")
def gains(inicio: int = month_param(), fim: int = month_param(), escopo: str = "casal",
          db: Session = Depends(get_db), user=Depends(current_user)):
    scope = parse_scope(escopo)
    totals = service.period_totals(db, user.id, scope, inicio, fim)
    investments = [
        investment_info(db, inv, user.id)
        for inv in db.scalars(select(Investment).where(visible_clause(Investment, user.id)))
        if scope.kind == "casal" or (scope.kind == "pessoa" and inv.owner_user_id == scope.id)
        or (scope.kind == "conta" and inv.account_id == scope.id)
    ]
    return {
        "resultado_periodo": totals["restante"], "totais": totals,
        "investimentos": {
            "aportado": sum(i["aportado"] for i in investments),
            "valor_atual": sum(i["valor_atual"] for i in investments),
            "resultado": sum(i["resultado"] for i in investments),
            "itens": investments,
        },
    }


def _csv_cell(value) -> str:
    """Numero em formato brasileiro; texto protegido contra formulas ao abrir no Excel."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _cents(value: int | None) -> str:
    return "" if value is None else f"{value / 100:.2f}".replace(".", ",")


def _csv(name: str, rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerows(rows)
    # BOM: o Excel reconhece os acentos.
    return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.get("/dre")
def income_statement(inicio: int = month_param(), fim: int = month_param(), regime: str = Query("competencia", pattern="^(caixa|competencia)$"),
                     escopo: str = "casal", db: Session = Depends(get_db), user=Depends(current_user)):
    if inicio > fim:
        raise HTTPException(422, "O início do período precisa vir antes do fim.")
    return build_dre(db, user.id, parse_scope(escopo), inicio, fim, regime)


@router.get("/imposto")
def tax(ano: int = Query(ge=2000, le=2999), db: Session = Depends(get_db), user=Depends(current_user)):
    return tax_report(db, user.id, ano)


@router.get("/imposto.csv")
def tax_csv(ano: int = Query(ge=2000, le=2999), db: Session = Depends(get_db), user=Depends(current_user)):
    data = tax_report(db, user.id, ano)
    rows: list[list] = [[f"Apoio à declaração de {ano}. Confira com os informes oficiais."], [], ["Rendimentos"], ["Pessoa", "Mês", "Categoria", "Valor"]]
    rows += [[_csv_cell(r["pessoa"]), r["mes"], _csv_cell(r["categoria"]), _cents(r["valor"])] for r in data["rendimentos"]]
    rows += [[], ["Saldos em 31/12"], ["Conta", "Saldo"]]
    rows += [[_csv_cell(a["nome"]), _cents(a["saldo"])] for a in data["contas"]]
    rows += [[], ["Investimentos"], ["Nome", "Tipo", "Aportado até 31/12"]]
    rows += [[_csv_cell(i["nome"]), _csv_cell(i["tipo"]), _cents(i["aportado_ate_fim_do_ano"])] for i in data["investimentos"]]
    rows += [[], ["Dívidas e financiamentos"], ["Nome", "Tipo", "Saldo em 31/12", "Pago no ano"]]
    rows += [[_csv_cell(d["nome"]), d["tipo"], _cents(d["saldo_fim_do_ano"]), _cents(d["pago_no_ano"])] for d in data["dividas"]]
    return _csv(f"imposto-{ano}", rows)


@router.get("/lancamentos.csv")
def transactions_csv(inicio: date, fim: date, escopo: str = "casal", db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.execute(
        select(Transaction, User.name, Account.name)
        .join(User, User.id == Transaction.owner_user_id).join(Account, Account.id == Transaction.account_id)
        .where(Transaction.date >= inicio, Transaction.date <= fim, tx_filter(user.id, parse_scope(escopo)))
        .order_by(Transaction.date)
    )
    result = [["Data", "Competência", "Pessoa", "Conta", "Tipo", "Descrição", "Valor", "Situação"]]
    for tx, person, account in rows:
        result.append([tx.date, tx.competence_date or "", _csv_cell(person), _csv_cell(account), tx.kind, _csv_cell(tx.description),
                       _cents(tx.amount_cents), "Realizado" if tx.settled else "Previsto"])
    return _csv(f"lancamentos-{inicio}-{fim}", result)


@router.get("/fechamentos")
def closings(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(MonthClosing).where(MonthClosing.viewer_id == user.id)
                      .order_by(MonthClosing.year.desc(), MonthClosing.month.desc()))
    return [{"ano": r.year, "mes": r.month, "situacao": r.status, "fechado_em": r.closed_at, "reaberto_em": r.reopened_at,
             "totais": r.snapshot["totais"]} for r in rows]


@router.post("/fechamentos/{ano}/{mes}")
def close(ano: int, mes: int, db: Session = Depends(get_db), user=Depends(current_user)):
    if not (2000 <= ano <= 2999 and 1 <= mes <= 12):
        raise HTTPException(422, "Mês inválido.")
    service.close_month(db, ano, mes, user.id)
    db.commit()
    return closing_status(db, user.id, ano, mes)


@router.get("/progresso")
def progress(db: Session = Depends(get_db), user=Depends(current_user)):
    """Evolucao de cada compromisso, de fechamento em fechamento, mais a foto de agora."""
    rows = db.scalars(select(MonthClosing).where(MonthClosing.viewer_id == user.id)
                      .order_by(MonthClosing.year, MonthClosing.month)).all()
    history: dict[tuple[str, int], dict] = {}
    for row in rows:
        for item in row.snapshot["progresso"]:
            entry = history.setdefault((item["tipo"], item["id"]), {
                "tipo": item["tipo"], "id": item["id"], "nome": item["nome"], "meta": item["meta"], "pontos": [],
            })
            entry["pontos"].append({"periodo": f"{row.year}-{row.month:02d}", "atual": item["atual"],
                                    "previsto": item.get("previsto"), "saldo": item.get("saldo")})
    for item in service.progress_items(db, user.id):
        entry = history.setdefault((item["tipo"], item["id"]), {
            "tipo": item["tipo"], "id": item["id"], "nome": item["nome"], "meta": item["meta"], "pontos": [],
        })
        entry["nome"], entry["meta"] = item["nome"], item["meta"]
        entry["agora"] = {"atual": item["atual"], "previsto": item.get("previsto"), "saldo": item.get("saldo")}
    # Um item oculto depois do fechamento nao aparece mais no "agora", mas o historico e da propria pessoa.
    return [e for e in history.values() if "agora" in e]
