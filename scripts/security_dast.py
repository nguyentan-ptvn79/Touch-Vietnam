from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from http.client import HTTPResponse
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(NoRedirect)
REQUIRED_HEADERS = {
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
    "x-request-id",
}


@dataclass
class Result:
    status: int
    headers: dict[str, str]
    body: bytes


def fetch(url: str, *, method: str = "GET", body: bytes | None = None) -> Result:
    request = Request(url, method=method, data=body)
    try:
        with OPENER.open(request, timeout=8) as response:
            return result_from_response(response)
    except HTTPError as exc:
        return Result(
            status=exc.code,
            headers={key.lower(): value for key, value in exc.headers.items()},
            body=exc.read(),
        )


def result_from_response(response: HTTPResponse) -> Result:
    return Result(
        status=int(response.status),
        headers={key.lower(): value for key, value in response.headers.items()},
        body=response.read(),
    )


def assert_headers(name: str, result: Result, failures: list[str]) -> None:
    missing = sorted(REQUIRED_HEADERS - set(result.headers))
    if missing:
        failures.append(f"{name}: missing headers {', '.join(missing)}")


def scan_web(base_url: str, failures: list[str]) -> None:
    home = fetch(f"{base_url}/")
    if home.status != 200:
        failures.append(f"web home returned {home.status}")
    assert_headers("web home", home, failures)

    logout = fetch(f"{base_url}/logout")
    if logout.status != 405:
        failures.append(f"GET /logout must return 405, got {logout.status}")

    no_csrf = fetch(
        f"{base_url}/login",
        method="POST",
        body=b"email=test%40example.com&password=invalid",
    )
    if no_csrf.status != 400:
        failures.append(f"POST /login without CSRF must return 400, got {no_csrf.status}")

    admin = fetch(f"{base_url}/admin")
    if admin.status not in {302, 303}:
        failures.append(f"anonymous /admin must redirect, got {admin.status}")

    for sensitive_path in ("/.env", "/.git/config", "/server-status"):
        result = fetch(f"{base_url}{sensitive_path}")
        if result.status != 404:
            failures.append(f"{sensitive_path} unexpectedly returned {result.status}")

    payload = "<script>alert(1)</script>"
    reflected = fetch(f"{base_url}/places?search={quote(payload)}")
    if payload.encode() in reflected.body:
        failures.append("places search reflected an unescaped script payload")


def scan_api(base_url: str, failures: list[str]) -> None:
    health = fetch(f"{base_url}/api/health")
    if health.status != 200:
        failures.append(f"API health returned {health.status}")
    assert_headers("API health", health, failures)

    protected = fetch(f"{base_url}/api/integrations/status")
    if protected.status != 401:
        failures.append(f"anonymous protected API returned {protected.status}")

    invalid_login = fetch(
        f"{base_url}/api/auth/login",
        method="POST",
        body=b'{"email":"nobody@example.com","password":"wrong"}',
    )
    if invalid_login.status not in {401, 422}:
        failures.append(f"invalid API login returned {invalid_login.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Targeted dynamic security smoke scan.")
    parser.add_argument("--web-url", default="http://127.0.0.1:5000")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    failures: list[str] = []
    try:
        scan_web(args.web_url.rstrip("/"), failures)
        scan_api(args.api_url.rstrip("/"), failures)
    except URLError as exc:
        failures.append(f"target unavailable: {exc}")

    if failures:
        print("DAST security smoke: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("DAST security smoke: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
