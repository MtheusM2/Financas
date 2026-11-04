"""Carga: varias sessoes lendo e gravando ao mesmo tempo. Uso: python scripts/carga.py URL EMAIL SENHA SEGUNDOS"""
import statistics
import sys
import threading
import time
from datetime import date

import httpx

BASE, EMAIL, PASSWORD, SECONDS = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
WORKERS = 8
HEADERS = {"X-Financas": "1"}
today = date.today()
PARAMS = {"ano": today.year, "mes": today.month}

times: list[float] = []
failures: list[str] = []
lock = threading.Lock()


def worker(account_id: int, stop_at: float) -> None:
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=15) as client:
        response = client.post("/api/autenticacao/entrar", json={"email": EMAIL, "password": PASSWORD})
        response.raise_for_status()
        step = 0
        while time.time() < stop_at:
            step += 1
            start = time.perf_counter()
            try:
                if step % 5 == 0:
                    response = client.post("/api/lancamentos", json={
                        "date": today.isoformat(), "account_id": account_id, "kind": "gasto", "amount_cents": 100, "description": "carga",
                    })
                elif step % 2 == 0:
                    response = client.get("/api/painel/resumo", params=PARAMS)
                else:
                    response = client.get("/api/painel/fluxo", params=PARAMS)
                ok = response.status_code == 200
                detail = str(response.status_code)
            except httpx.HTTPError as error:
                ok, detail = False, type(error).__name__
            with lock:
                times.append(time.perf_counter() - start)
                if not ok:
                    failures.append(detail)


def main() -> None:
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=15) as client:
        client.post("/api/autenticacao/entrar", json={"email": EMAIL, "password": PASSWORD}).raise_for_status()
        user = client.get("/api/autenticacao/eu").json()["id"]
        account = next(a["id"] for a in client.get("/api/contas").json() if a["dono"] == user)
    stop_at = time.time() + SECONDS
    threads = [threading.Thread(target=worker, args=(account, stop_at)) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ordered = sorted(times)
    print(f"requisicoes={len(times)} por_segundo={len(times) / SECONDS:.1f} falhas={len(failures)} "
          f"mediana_ms={statistics.median(ordered) * 1000:.0f} p95_ms={ordered[int(len(ordered) * 0.95)] * 1000:.0f} "
          f"tipos_de_falha={sorted(set(failures))}")
    # Conferencia: os totais prontos precisam bater com o que foi gravado.
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=15) as client:
        client.post("/api/autenticacao/entrar", json={"email": EMAIL, "password": PASSWORD}).raise_for_status()
        total = client.get("/api/painel/resumo", params=PARAMS).json()["totais"]["gasto"]
        listed = client.get("/api/lancamentos", params={"inicio": today.replace(day=1).isoformat(), "tipo": "gasto", "por_pagina": 1}).json()["soma"]
    print(f"total_painel={total} total_lancamentos={listed} confere={total == listed}")


if __name__ == "__main__":
    main()
