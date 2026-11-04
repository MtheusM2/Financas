"""Leitura pura de extratos OFX e CSV. Valores em centavos, com sinal."""
import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.modules.financiamentos.calc import to_cents


class StatementError(ValueError):
    pass


@dataclass
class Line:
    date: date
    amount_cents: int
    description: str
    fitid: str = ""


@dataclass
class Statement:
    lines: list[Line]
    balance_cents: int | None = None
    balance_date: date | None = None


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_amount(text: str) -> int:
    value = re.sub(r"[^\d,.\-+()]", "", text.strip())
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    if "," in value and "." in value:
        # O ultimo separador e o decimal.
        value = value.replace(".", "").replace(",", ".") if value.rfind(",") > value.rfind(".") else value.replace(",", "")
    elif "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        cents = to_cents(Decimal(value) * 100)
    except InvalidOperation as error:
        raise StatementError(f"Valor inválido: {text}") from error
    return -cents if negative else cents


def parse_date(text: str) -> date:
    text = text.strip()
    for pattern in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise StatementError(f"Data inválida: {text}")


def _tag(block: str, name: str) -> str | None:
    match = re.search(rf"<{name}>\s*([^<\r\n]*)", block, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _ofx_date(text: str) -> date:
    return datetime.strptime(text[:8], "%Y%m%d").date()


def parse_ofx(text: str) -> Statement:
    lines = []
    for block in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|</BANKTRANLIST>)", text, re.IGNORECASE | re.DOTALL):
        posted, amount = _tag(block, "DTPOSTED"), _tag(block, "TRNAMT")
        if not posted or not amount:
            continue
        description = _tag(block, "MEMO") or _tag(block, "NAME") or ""
        lines.append(Line(_ofx_date(posted), parse_amount(amount), description[:160], _tag(block, "FITID") or ""))
    ledger = re.search(r"<LEDGERBAL>(.*?)(?:</LEDGERBAL>|$)", text, re.IGNORECASE | re.DOTALL)
    balance, balance_date = None, None
    if ledger and _tag(ledger.group(1), "BALAMT"):
        balance = parse_amount(_tag(ledger.group(1), "BALAMT"))
        when = _tag(ledger.group(1), "DTASOF")
        balance_date = _ofx_date(when) if when else None
    return Statement(lines, balance, balance_date)


HEADERS = {
    "date": ("data", "date", "dt", "lançamento", "lancamento"),
    "amount": ("valor", "amount", "montante", "quantia"),
    "credit": ("entrada", "crédito", "credito", "credit"),
    "debit": ("saída", "saida", "débito", "debito", "debit"),
    "description": ("descrição", "descricao", "histórico", "historico", "description", "memo", "título", "titulo", "estabelecimento", "detalhes"),
}


def _map_header(row: list[str]) -> dict[str, int] | None:
    found: dict[str, int] = {}
    for index, cell in enumerate(row):
        name = cell.strip().lower()
        for key, words in HEADERS.items():
            if key not in found and any(name == w or name.startswith(w) for w in words):
                found[key] = index
                break
    if "date" in found and ("amount" in found or "credit" in found or "debit" in found):
        return found
    return None


def parse_csv(text: str) -> Statement:
    sample = text[:4000]
    delimiter = max((";", ",", "\t"), key=sample.count)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    header, start = None, 0
    for index, row in enumerate(rows[:15]):
        header = _map_header(row)
        if header:
            start = index + 1
            break
    if not header:
        raise StatementError("Não encontrei as colunas de data e valor no arquivo.")
    lines = []
    for row in rows[start:]:
        if len(row) <= header["date"] or not row[header["date"]].strip():
            continue
        cell = lambda key: row[header[key]].strip() if key in header and header[key] < len(row) else ""
        if cell("amount"):
            amount = parse_amount(cell("amount"))
        elif cell("credit"):
            amount = abs(parse_amount(cell("credit")))
        elif cell("debit"):
            amount = -abs(parse_amount(cell("debit")))
        else:
            continue
        if amount:
            lines.append(Line(parse_date(cell("date")), amount, cell("description")[:160]))
    return Statement(lines)


def parse_statement(raw: bytes) -> Statement:
    text = decode(raw)
    statement = parse_ofx(text) if re.search(r"<OFX>|<STMTTRN>", text, re.IGNORECASE) else parse_csv(text)
    if not statement.lines:
        raise StatementError("Nenhum lançamento encontrado no arquivo.")
    return statement


def line_ids(account_id: int, lines: list[Line]) -> list[str]:
    """Identifica cada linha. Compras iguais no mesmo dia sao diferenciadas pela ordem."""
    seen: dict[str, int] = {}
    result = []
    for line in lines:
        base = f"{account_id}|{line.fitid or f'{line.date}|{line.amount_cents}|{line.description}'}"
        seen[base] = seen.get(base, 0) + 1
        result.append(hashlib.sha256(f"{base}|{seen[base]}".encode()).hexdigest())
    return result


def normalize(description: str) -> str:
    """Tira numeros e espacos extras: 'UBER *1234' e 'UBER *9876' viram o mesmo padrao."""
    return re.sub(r"\s+", " ", re.sub(r"[\d*#/.\-]+", " ", description)).strip().lower()[:160]
