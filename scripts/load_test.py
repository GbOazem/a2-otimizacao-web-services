
"""Testes de desempenho da API REST — Trabalho A2 UVA.

Executar somente contra a API local do projeto.
Exemplo:
    python -m scripts.load_test --users 10 --duration 10 --scenario cache
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
import statistics
import time
from urllib.parse import urlsplit

import requests


PATHS = {
    "no-cache": "/api/products/1/no-cache",
    "cache": "/api/products/1/cache",
    "lazy": "/api/orders/lazy?limit=30",
    "eager": "/api/orders/eager?limit=30",
    "optimized": "/api/orders/optimized?limit=30",
    "index": "/api/orders/search?customer_name=Cliente%200010",
}


def percentile(values, q):
    if not values:
        return None

    values = sorted(values)
    rank = (len(values) - 1) * q
    lo = math.floor(rank)
    hi = math.ceil(rank)

    return values[lo] + (values[hi] - values[lo]) * (rank - lo)


def main():
    parser = argparse.ArgumentParser(
        description="Teste de carga dos Web Services — UVA A2"
    )

    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000"
    )
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument(
        "--scenario",
        choices=PATHS.keys(),
        default="cache"
    )
    parser.add_argument("--output", default="")

    args = parser.parse_args()

    # Segurança: permitir somente servidores locais.
    parsed = urlsplit(args.base_url)

    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        parser.error(
            "Este script aceita apenas servidores HTTP locais com porta."
        )

    if args.users < 1 or args.users > 200:
        parser.error("A quantidade de usuários deve ser entre 1 e 200.")

    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("A duração deve ser positiva e finita.")

    target = args.base_url.rstrip("/") + PATHS[args.scenario]

    print(f"\nCenário: {args.scenario}")
    print(f"Usuários virtuais: {args.users}")
    print(f"Duração: {args.duration} segundos")
    print(f"URL: {target}")
    print("\nExecutando teste...\n")

    started = time.perf_counter()
    cutoff = started + args.duration

    def worker(_):
        results = []

        # Uma sessão por usuário virtual permite reutilizar conexões.
        with requests.Session() as session:
            session.trust_env = False
            session.headers.update({
                "Accept": "application/json"
            })

            while time.perf_counter() < cutoff:
                before = time.perf_counter()

                try:
                    response = session.get(
                        target,
                        timeout=10,
                        allow_redirects=False
                    )

                    status = response.status_code
                    ok = 200 <= status < 300

                    if ok:
                        error = None
                    else:
                        error = f"HTTP {status}"

                except requests.RequestException as exc:
                    ok = False
                    error = type(exc).__name__

                elapsed_ms = (
                    time.perf_counter() - before
                ) * 1000

                results.append((elapsed_ms, ok, error))

        return results

    with ThreadPoolExecutor(max_workers=args.users) as pool:
        batches = list(pool.map(worker, range(args.users)))

    elapsed = time.perf_counter() - started

    combined = [
        item
        for batch in batches
        for item in batch
    ]

    successful_times = [
        ms
        for ms, ok, error in combined
        if ok
    ]

    errors = Counter(
        error
        for ms, ok, error in combined
        if not ok
    )

    total = len(combined)
    failures = sum(errors.values())
    successes = total - failures

    report = {
        "scenario": args.scenario,
        "users": args.users,
        "duration_s": round(elapsed, 3),
        "total_requests": total,
        "successful_requests": successes,
        "errors": failures,
        "error_rate_pct": (
            round(100 * failures / total, 3)
            if total else None
        ),
        "avg_ms": (
            round(statistics.mean(successful_times), 3)
            if successful_times else None
        ),
        "p95_ms": (
            round(percentile(successful_times, 0.95), 3)
            if successful_times else None
        ),
        "p99_ms": (
            round(percentile(successful_times, 0.99), 3)
            if successful_times else None
        ),
        "throughput_req_s": (
            round(total / elapsed, 3)
            if elapsed else None
        ),
        "successful_throughput_req_s": (
            round(successes / elapsed, 3)
            if elapsed else None
        ),
        "error_details": dict(errors)
    }

    print("========== RESULTADO DO TESTE ==========")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            json.dump(
                report,
                output,
                ensure_ascii=False,
                indent=2
            )

        print(f"\nResultado salvo em: {args.output}")


if __name__ == "__main__":
    main()
