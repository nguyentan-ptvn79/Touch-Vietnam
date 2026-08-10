from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import quantiles
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def validate_target_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Stress target must be an HTTP(S) URL: {url}")
    return url


def request_once(url: str) -> tuple[int, float]:
    started = time.perf_counter()
    try:
        with urlopen(  # nosec B310
            Request(validate_target_url(url), headers={"User-Agent": "TouchVN-Stress-Smoke/1.0"}),
            timeout=10,
        ) as response:
            response.read()
            status = int(response.status)
    except HTTPError as exc:
        status = exc.code
    elapsed_ms = (time.perf_counter() - started) * 1000
    return status, elapsed_ms


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded read-only stress smoke test.")
    parser.add_argument("--web-url", default="http://127.0.0.1:5000")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=120)
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--p95-ms", type=float, default=3000)
    args = parser.parse_args()

    request_count = min(max(args.requests, 20), 1000)
    concurrency = min(max(args.concurrency, 2), 50)
    targets = (
        f"{args.web_url.rstrip('/')}/healthz",
        f"{args.web_url.rstrip('/')}/places",
        f"{args.api_url.rstrip('/')}/api/health",
        f"{args.api_url.rstrip('/')}/api/places?lang=vi",
    )
    futures = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for index in range(request_count):
            futures.append(executor.submit(request_once, targets[index % len(targets)]))

    statuses: list[int] = []
    latencies: list[float] = []
    unavailable = 0
    for future in as_completed(futures):
        try:
            status, elapsed_ms = future.result()
        except (OSError, URLError):
            unavailable += 1
            continue
        statuses.append(status)
        latencies.append(elapsed_ms)

    p95 = quantiles(latencies, n=100)[94] if len(latencies) >= 2 else float("inf")
    failures = unavailable + sum(status >= 500 for status in statuses)
    summary = {
        "requests": request_count,
        "concurrency": concurrency,
        "failures": failures,
        "p95_ms": round(p95, 2),
        "max_ms": round(max(latencies, default=0), 2),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if failures or p95 > args.p95_ms:
        print("Stress smoke: FAIL")
        return 1
    print("Stress smoke: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
