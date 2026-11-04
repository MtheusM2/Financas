"""Leitura generica de holerite a partir das palavras do PDF e da posicao de cada uma.

Nao ha modelo fixo por empresa: o leitor acha a linha de titulos das colunas
(vencimentos e descontos), le os itens abaixo dela e procura os totais pelos
rotulos de rotulos.json, ao lado ou logo abaixo de cada rotulo. Depois confere as
somas. Funcao pura: recebe palavras, devolve holerites, nao toca no banco."""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

LINE_TOLERANCE = 3.0      # pontos: palavras com topo tao proximo estao na mesma linha
BELOW_DISTANCE = 45.0     # ate onde procurar o valor abaixo de um rotulo
SIDE_MARGIN = 25.0        # folga horizontal ao procurar o valor abaixo de um rotulo
MAX_ITEMS = 80
END_KEYS = ("total_vencimentos", "total_descontos", "liquido")

MONEY = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}-?$|^-?\d+,\d{2}-?$")
NUMBER = re.compile(r"^\d[\d.,:]*%?$")
CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
MONTHS = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]
MONTH_NAME = re.compile(r"\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s*(?:de\s+|/\s*|-\s*)?((?:19|20)\d{2})\b")
MONTH_NUMBER = re.compile(r"(?<![\d/])(0?[1-9]|1[0-2])\s*/\s*((?:19|20)\d{2})\b")
MONTH_HINT = ("referencia", "competencia", "mes", "periodo")


class PayslipError(ValueError):
    pass


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Line:
    top: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Item:
    codigo: str
    descricao: str
    referencia: str
    tipo: str  # "provento" ou "desconto"
    valor: int


@dataclass
class Payslip:
    empresa: str = ""
    cnpj: str = ""
    referencia: int | None = None  # AAAAMM
    itens: list[Item] = field(default_factory=list)
    totais: dict[str, int] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    # Valores com rotulo que o leitor nao conhece: a revisao deixa a pessoa dizer o que sao.
    desconhecidos: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"empresa": self.empresa, "cnpj": self.cnpj, "referencia": self.referencia,
                "itens": [vars(i) for i in self.itens], "totais": dict(self.totais), "avisos": list(self.avisos),
                "conferido": not self.avisos, "desconhecidos": list(self.desconhecidos)}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm(text: str) -> str:
    text = strip_accents(text).lower().replace(".", "")
    return " ".join(re.sub(r"[^a-z0-9%]+", " ", text).split())


def to_cents(text: str) -> int:
    negative = text.startswith("-") or text.endswith("-")
    digits = text.strip("-").replace(".", "").replace(",", "")
    return -int(digits) if negative else int(digits)


@lru_cache
def labels() -> dict:
    data = json.loads((Path(__file__).with_name("rotulos.json")).read_text(encoding="utf-8"))
    for group in ("colunas", "totais"):
        # Os mais longos primeiro: "valor liquido" vence "liquido".
        data[group] = {k: sorted((norm(s) for s in v), key=lambda s: -len(s.split())) for k, v in data[group].items()}
    data["cabecalho_ignorar"] = [norm(s) for s in data["cabecalho_ignorar"]]
    return data


def group_lines(words: list[Word]) -> list[Line]:
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(word.top - lines[-1].top) <= LINE_TOLERANCE:
            lines[-1].words.append(word)
        else:
            lines.append(Line(word.top, [word]))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


@dataclass
class Match:
    key: str
    line: int
    x0: float
    x1: float
    top: float
    end: int  # indice da palavra seguinte ao rotulo


def find_labels(line: Line, index: int, table: dict[str, list[str]]) -> list[Match]:
    """Rotulos de `table` nesta linha, sem sobrepor palavras. Compara sem espacos,
    para "Sal.Contr.INSS" e "Sal. Contr. INSS" darem no mesmo."""
    words = [(w, norm(w.text).replace(" ", "")) for w in line.words]
    words = [(w, n) for w, n in words if n]
    candidates = sorted(((len(s.split()), len(s), key, s.replace(" ", "")) for key, synonyms in table.items() for s in synonyms),
                        reverse=True)
    used = [False] * len(words)
    found = []
    for size, _, key, synonym in candidates:
        for start in range(len(words)):
            for stop in range(start + 1, min(len(words), start + size) + 1):
                if any(used[start:stop]):
                    break
                joined = "".join(n for _, n in words[start:stop])
                if joined == synonym:
                    for i in range(start, stop):
                        used[i] = True
                    chunk = [w for w, _ in words[start:stop]]
                    found.append(Match(key, index, chunk[0].x0, chunk[-1].x1, line.top, line.words.index(chunk[-1]) + 1))
                    break
                if not synonym.startswith(joined):
                    break
    return sorted(found, key=lambda m: m.x0)


def is_header(line: Line) -> dict[str, float] | None:
    """Linha de titulos: tem coluna de vencimentos e de descontos e nenhum total."""
    table = labels()
    if find_labels(line, 0, table["totais"]):
        return None
    columns = {m.key: (m.x0 + m.x1) / 2 for m in find_labels(line, 0, table["colunas"])}
    if "vencimentos" in columns and "descontos" in columns:
        return columns
    return None


def read_item(line: Line, columns: dict[str, float]) -> Item | None:
    values: dict[str, str] = {}
    text_words = []
    for word in line.words:
        # Numero ja na regiao das colunas (e nao o codigo do inicio da linha) e valor, nao descricao.
        in_columns = word.center >= min(columns.values()) - 2 * SIDE_MARGIN
        if MONEY.match(word.text) or (NUMBER.match(word.text) and text_words and in_columns):
            column = min(columns, key=lambda c: abs(columns[c] - word.center))
            if not in_columns and not values:
                text_words.append(word)  # numero no meio da descricao
                continue
            values.setdefault(column, word.text)
        elif not values:
            text_words.append(word)
    money = [(c, values[c]) for c in ("vencimentos", "descontos") if c in values and MONEY.match(values[c])]
    if len(money) != 1:
        return None
    code = ""
    if text_words and text_words[0].text.isdigit():
        code = text_words.pop(0).text
    description = " ".join(w.text for w in text_words).strip()
    if not description:
        return None
    column, value = money[0]
    return Item(code, description[:80], values.get("referencia", ""), "provento" if column == "vencimentos" else "desconto",
                abs(to_cents(value)))


def value_for(match: Match, lines: list[Line], labels_by_line: dict[int, list[Match]], taken: set[int]) -> Word | None:
    line = lines[match.line]
    others = [m.x0 for m in labels_by_line.get(match.line, []) if m.x0 > match.x1]
    limit = min(others) if others else float("inf")
    for word in line.words[match.end:]:
        if word.x0 >= limit:
            break
        if MONEY.match(word.text) and id(word) not in taken:
            return word
    best = None
    for index in range(match.line + 1, len(lines)):
        below = lines[index]
        if below.top - match.top > BELOW_DISTANCE:
            break
        for word in below.words:
            overlaps = word.x1 >= match.x0 - SIDE_MARGIN and word.x0 <= match.x1 + SIDE_MARGIN
            if overlaps and MONEY.match(word.text) and id(word) not in taken:
                distance = abs(word.center - (match.x0 + match.x1) / 2)
                if best is None or distance < best[0]:
                    best = (distance, word)
        if best:
            return best[1]
    return None


def find_month(texts: list[str]) -> int | None:
    plain = [strip_accents(t).lower() for t in texts]
    # Primeiro perto de "referencia"/"competencia"; depois mes por extenso; por ultimo MM/AAAA.
    for pattern in (MONTH_NAME, MONTH_NUMBER):
        hinted = [t for t in plain if any(h in t for h in MONTH_HINT)]
        for text in hinted + plain:
            found = pattern.search(text)
            if found:
                month = found.group(1)
                number = int(month) if month.isdigit() else [m[:3] for m in MONTHS].index(month[:3]) + 1
                return int(found.group(2)) * 100 + number
    return None


def find_company(lines: list[Line]) -> tuple[str, str]:
    ignore = labels()["cabecalho_ignorar"]
    cnpj = ""
    for line in lines:
        found = CNPJ.search(line.text)
        if found:
            cnpj = found.group(0)
            break
    for line in lines:
        text = CNPJ.sub("", line.text).replace("CNPJ:", "").replace("CNPJ", "").strip(" -:")
        for phrase in ignore:  # "EMPRESA X   RECIBO DE PAGAMENTO" na mesma linha
            text = re.sub(r"\s*" + r"\W*\s*".join(map(re.escape, phrase.split())) + r"\s*$", "", text, flags=re.I).strip()
        normalized = norm(text)
        letters = [w for w in normalized.split() if re.search(r"[a-z]{2}", w)]
        if len(letters) >= 2 and not any(normalized == i or normalized.startswith(i + " ") for i in ignore) \
                and not find_month([text]) and not MONEY.search(text.split()[-1] if text.split() else ""):
            return text[:160], cnpj
    return "", cnpj


def merged_totals(learned: dict[str, list[str]] | None) -> dict[str, list[str]]:
    """Rotulos do arquivo mais os aprendidos na revisao."""
    table = {k: list(v) for k, v in labels()["totais"].items()}
    for key, synonyms in (learned or {}).items():
        if key in table:
            table[key] = sorted(set(table[key]) | {norm(s) for s in synonyms if norm(s)}, key=lambda s: -len(s.split()))
    return table


def unknown_values(lines: list[Line], start: int, stop: int, taken: set[int]) -> list[dict]:
    """Dinheiro na area dos totais que nenhum rotulo pegou, com o texto que esta ao lado ou logo acima."""
    found = []
    for index in range(start, stop):
        line = lines[index]
        for position, word in enumerate(line.words):
            if not MONEY.match(word.text) or id(word) in taken:
                continue
            left = []
            for other in reversed(line.words[:position]):
                if MONEY.match(other.text):
                    break
                left.insert(0, other.text)
            label = " ".join(left)
            if not label and index > start:
                above = [w for w in lines[index - 1].words
                         if not MONEY.match(w.text) and w.x1 >= word.x0 - SIDE_MARGIN and w.x0 <= word.x1 + SIDE_MARGIN]
                label = " ".join(w.text for w in above)
            if re.search(r"[A-Za-z]{2}", label) and to_cents(word.text) != 0:
                found.append({"rotulo": label[:60], "valor": abs(to_cents(word.text))})
    return found[:12]


def check(slip: Payslip) -> None:
    earned = sum(i.valor for i in slip.itens if i.tipo == "provento")
    deducted = sum(i.valor for i in slip.itens if i.tipo == "desconto")
    totals = slip.totais
    if not slip.itens:
        slip.avisos.append("Nenhum item encontrado: confira os valores.")
    if "total_vencimentos" not in totals:
        totals["total_vencimentos"] = earned
        slip.avisos.append("Total de vencimentos não encontrado: usei a soma dos itens.")
    elif totals["total_vencimentos"] != earned:
        slip.avisos.append("A soma dos vencimentos não bate com o total do holerite.")
    if "total_descontos" not in totals:
        totals["total_descontos"] = deducted
        slip.avisos.append("Total de descontos não encontrado: usei a soma dos itens.")
    elif totals["total_descontos"] != deducted:
        slip.avisos.append("A soma dos descontos não bate com o total do holerite.")
    expected = totals["total_vencimentos"] - totals["total_descontos"]
    if "liquido" not in totals:
        totals["liquido"] = expected
        slip.avisos.append("Valor líquido não encontrado: usei vencimentos menos descontos.")
    elif totals["liquido"] != expected:
        slip.avisos.append("Vencimentos menos descontos não dá o valor líquido.")
    if slip.referencia is None:
        slip.avisos.append("Mês de referência não encontrado.")


def parse_words(words: list[Word], learned: dict[str, list[str]] | None = None) -> list[Payslip]:
    lines = group_lines(words)
    headers = [(i, cols) for i, line in enumerate(lines) if (cols := is_header(line))]
    if not headers:
        raise PayslipError("Não achei a tabela de vencimentos e descontos. O PDF precisa ter texto (não pode ser só uma foto).")
    table = merged_totals(learned)
    slips: list[Payslip] = []
    previous_end = 0
    for number, (start, columns) in enumerate(headers):
        stop = headers[number + 1][0] if number + 1 < len(headers) else len(lines)
        slip = Payslip()
        index = start + 1
        while index < stop and len(slip.itens) < MAX_ITEMS:
            item = read_item(lines[index], columns)
            found = find_labels(lines[index], index, table)
            # Um total encerra a tabela; outro rotulo so encerra se a linha nao for um item.
            if found and (not item or any(m.key in END_KEYS for m in found)):
                break
            if item:
                slip.itens.append(item)
            index += 1
        labels_by_line = {i: find_labels(lines[i], i, table) for i in range(index, stop)}
        taken: set[int] = set()
        last = index
        for i in range(index, stop):
            for match in labels_by_line[i]:
                if match.key in slip.totais:
                    continue
                word = value_for(match, lines, labels_by_line, taken)
                if word:
                    taken.add(id(word))
                    slip.totais[match.key] = abs(to_cents(word.text))
                    last = max(last, i + 1)
        slip.desconhecidos = unknown_values(lines, index, stop, taken)
        header_area = lines[previous_end:start]
        slip.empresa, slip.cnpj = find_company(header_area)
        slip.referencia = find_month([line.text for line in header_area])
        if not slip.empresa or not slip.cnpj or slip.referencia is None:
            # Alguns modelos poem o cabecalho so uma vez, ou depois da tabela.
            empresa, cnpj = find_company(lines)
            slip.empresa, slip.cnpj = slip.empresa or empresa, slip.cnpj or cnpj
            slip.referencia = slip.referencia or find_month([line.text for line in lines])
        previous_end = max(last, start + 1)
        check(slip)
        slips.append(slip)
    return dedupe(slips)


def dedupe(slips: list[Payslip]) -> list[Payslip]:
    """Vias repetidas (empresa e funcionario) viram um holerite so; fica a mais completa."""
    unique: dict[tuple, Payslip] = {}
    for slip in slips:
        key = (slip.referencia, slip.totais.get("liquido"), slip.totais.get("total_vencimentos"))
        current = unique.get(key)
        if current is None or len(slip.avisos) < len(current.avisos) or \
                (len(slip.avisos) == len(current.avisos) and len(slip.totais) > len(current.totais)):
            unique[key] = slip
    return list(unique.values())
