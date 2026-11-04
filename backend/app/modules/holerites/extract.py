"""Tira as palavras de um PDF com seguranca.

- So aceita arquivo que comeca com %PDF, ate MAX_FILE_BYTES e MAX_PAGES paginas.
- O pdfminer so le texto: nao roda JavaScript, formularios nem anexos do PDF.
- A leitura roda em um processo separado, com limite de memoria e de tempo:
  um PDF malicioso ou quebrado nao derruba nem trava o sistema.
- O arquivo fica so na memoria e nunca e gravado em disco."""
import logging
import multiprocessing
import resource

from app.modules.holerites.parse import PayslipError, Word

MAX_FILE_BYTES = 5_000_000
MAX_PAGES = 10
MAX_WORDS = 20_000
TIMEOUT_SECONDS = 20
MEMORY_BYTES = 512 * 1024 * 1024


def check_pdf(raw: bytes) -> None:
    if len(raw) > MAX_FILE_BYTES:
        raise PayslipError("Arquivo maior que 5 MB.")
    if not raw.lstrip()[:5] == b"%PDF-":
        raise PayslipError("O arquivo não é um PDF.")


def chars_to_words(chars: list[tuple[str, float, float, float, float]]) -> list[Word]:
    """chars: (texto, x0, x1, topo, tamanho). Junta letras vizinhas em palavras."""
    rows: list[list] = []
    for char in sorted(chars, key=lambda c: (c[3], c[1])):
        if rows and abs(char[3] - rows[-1][0][3]) <= max(char[4], 1) * 0.4:
            rows[-1].append(char)
        else:
            rows.append([char])
    words: list[Word] = []
    for row in rows:
        current: list = []
        for char in sorted(row, key=lambda c: c[1]):
            text, x0, _, _, size = char
            if current and (text.isspace() or x0 - current[-1][2] > max(size, 1) * 0.25):
                words.append(make_word(current))
                current = []
            if not text.isspace():
                current.append(char)
        if current:
            words.append(make_word(current))
    return words


def make_word(chars: list) -> Word:
    return Word("".join(c[0] for c in chars), chars[0][1], chars[-1][2], min(c[3] for c in chars))


def _read(raw: bytes, conn) -> None:
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        from io import BytesIO

        from pdfminer.layout import LTChar, LTContainer
        from pdfminer.high_level import extract_pages

        chars = []
        offset = 0.0
        for number, page in enumerate(extract_pages(BytesIO(raw), laparams=None, maxpages=MAX_PAGES + 1)):
            if number >= MAX_PAGES:
                raise PayslipError(f"O PDF tem mais de {MAX_PAGES} páginas.")
            stack = [page]
            while stack:
                node = stack.pop()
                if isinstance(node, LTChar):
                    a, b, c, d = node.matrix[:4]
                    if abs(b) < 0.01 and abs(c) < 0.01 and a > 0 and d > 0:  # so texto na horizontal
                        chars.append((node.get_text(), node.x0, node.x1, offset + page.height - node.y1, node.size))
                elif isinstance(node, LTContainer):
                    stack.extend(node)
            offset += page.height + 20
            if len(chars) > MAX_WORDS * 10:
                raise PayslipError("O PDF tem texto demais para um holerite.")
        conn.send(("ok", [(w.text, w.x0, w.x1, w.top) for w in chars_to_words(chars)][:MAX_WORDS]))
    except PayslipError as error:
        conn.send(("erro", str(error)))
    except Exception as error:  # noqa: BLE001 - a pessoa ve uma mensagem simples; o log guarda so o tipo do erro
        conn.send(("erro", "Não consegui ler este PDF. Ele pode estar protegido por senha ou corrompido.",
                   type(error).__name__))
    finally:
        conn.close()


def extract_words(raw: bytes) -> list[Word]:
    check_pdf(raw)
    # "spawn" cria um processo limpo: copiar (fork) um servidor com varias threads pode travar.
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_read, args=(raw, child), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(TIMEOUT_SECONDS):
            raise PayslipError("O PDF demorou demais para ser lido.")
        status, payload, *detail = parent.recv()
    except EOFError as error:
        raise PayslipError("Não consegui ler este PDF.") from error
    finally:
        parent.close()
        if process.is_alive():
            process.kill()
        process.join(1)
    if status != "ok":
        if detail:
            logging.getLogger("financas").warning("falha ao ler PDF de holerite: %s", detail[0])
        raise PayslipError(payload)
    return [Word(*w) for w in payload]
