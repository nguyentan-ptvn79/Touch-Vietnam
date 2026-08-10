from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from .settings import get_settings

_audit_logger = logging.getLogger("touch_vn.security_audit")
_alert_logger = logging.getLogger("touch_vn.security_alert")
_configuration_lock = threading.Lock()
_bucket_lock = threading.Lock()
_failure_buckets: dict[str, deque[float]] = defaultdict(deque)
_last_alert_at: dict[str, float] = {}
_configured_path: str | None = None
_blocked_detail_keys = {"password", "token", "access_token", "secret", "api_key", "authorization"}


def _configure_audit_logger() -> None:
    global _configured_path
    settings = get_settings()
    configured_path = str(settings.security_log_path.resolve())
    if _configured_path == configured_path:
        return

    with _configuration_lock:
        if _configured_path == configured_path:
            return
        settings.security_log_path.parent.mkdir(parents=True, exist_ok=True)
        for handler in list(_audit_logger.handlers):
            _audit_logger.removeHandler(handler)
            handler.close()
        handler = RotatingFileHandler(
            settings.security_log_path,
            maxBytes=2_000_000,
            backupCount=10,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        _audit_logger.addHandler(handler)
        _audit_logger.setLevel(logging.INFO)
        _audit_logger.propagate = False
        _configured_path = configured_path


def _safe_details(details: dict[str, Any] | None) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in (details or {}).items():
        normalized_key = str(key).strip().lower()
        if normalized_key in _blocked_detail_keys:
            continue
        if value is None or isinstance(value, (bool, int, float)):
            sanitized[normalized_key] = value
        else:
            sanitized[normalized_key] = str(value)[:500]
    return sanitized


def _signed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(
        get_settings().secret_key.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {**payload, "signature": f"hmac-sha256:{signature}"}


def _check_failure_threshold(event: str, ip_address: str, outcome: str) -> None:
    if outcome not in {"blocked", "denied", "failure"}:
        return
    settings = get_settings()
    now = time.monotonic()
    bucket_key = f"{event}:{ip_address or 'unknown'}"
    with _bucket_lock:
        bucket = _failure_buckets[bucket_key]
        while bucket and now - bucket[0] > settings.security_alert_window_seconds:
            bucket.popleft()
        bucket.append(now)
        last_alert = _last_alert_at.get(bucket_key, 0.0)
        if (
            len(bucket) >= settings.security_alert_failure_threshold
            and now - last_alert > settings.security_alert_window_seconds
        ):
            _last_alert_at[bucket_key] = now
            _alert_logger.warning(
                "SECURITY_ALERT event=%s source_ip=%s failures=%s window_seconds=%s",
                event,
                ip_address or "unknown",
                len(bucket),
                settings.security_alert_window_seconds,
            )


def record_security_event(
    event: str,
    *,
    outcome: str,
    ip_address: str = "",
    actor_email: str = "",
    request_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """Write a signed, structured event without accepting secrets in details."""
    _configure_audit_logger()
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event.strip().lower()[:80],
        "outcome": outcome.strip().lower()[:40],
        "source_ip": (ip_address or "unknown")[:64],
        "actor_email": actor_email.strip().lower()[:254],
        "request_id": request_id.strip()[:64],
        "details": _safe_details(details),
    }
    signed_payload = _signed_payload(payload)
    _audit_logger.info(
        json.dumps(signed_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    _check_failure_threshold(payload["event"], payload["source_ip"], payload["outcome"])


def verify_security_log_line(line: str) -> bool:
    """Verify one audit-log record using the active application secret."""
    try:
        payload = json.loads(line)
        signature = str(payload.pop("signature"))
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    expected = _signed_payload(payload)["signature"]
    return hmac.compare_digest(signature, expected)
