from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .i18n import DEFAULT_LANGUAGE, resolve_language
from .models import TicketOffer
from .security_audit import record_security_event
from .settings import AppSettings, get_settings

logger = logging.getLogger("touch_vn.integrations")

CUSTOM_EXTERNAL_KEYS = {
    "ticket_provider",
    "analytics_provider",
    "ar_provider",
    "offline_map_provider",
}


def _audit_integration_failure(integration: str, exc: Exception) -> None:
    record_security_event(
        "integration_failure",
        outcome="failure",
        details={
            "integration": integration,
            "error_type": type(exc).__name__,
        },
    )


def _join_url(base_url: str, path: str) -> str:
    normalized_base = (base_url or "").strip().rstrip("/")
    normalized_path = (path or "").strip()
    if not normalized_base:
        return normalized_path
    if normalized_path.startswith(("http://", "https://")):
        return normalized_path
    if not normalized_path:
        return normalized_base
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    return f"{normalized_base}{normalized_path}"


def _with_query(url: str, params: dict[str, Any]) -> str:
    filtered = {key: value for key, value in params.items() if value is not None and value != ""}
    if not filtered:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(filtered)}"


def _auth_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}", "X-API-Key": api_key}


def _validate_external_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("External integration URL must use http or https with a hostname.")

    hostname = parsed.hostname.strip().lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("External integration URL cannot target localhost.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("External integration hostname could not be resolved.") from exc

    if not addresses:
        raise ValueError("External integration hostname did not resolve.")

    for address in addresses:
        ip_address = ipaddress.ip_address(address[4][0])
        if (
            ip_address.is_private
            or ip_address.is_loopback
            or ip_address.is_link_local
            or ip_address.is_multicast
            or ip_address.is_reserved
            or ip_address.is_unspecified
        ):
            raise ValueError("External integration URL resolves to a non-public address.")


def _normalize_booking_url(value: object) -> str:
    url = str(value or "").strip()
    if not url or len(url) > 2048 or any(ord(character) < 32 for character in url):
        raise ValueError("Booking URL is empty or malformed.")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Booking URL is malformed.") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Booking URL must be an HTTP(S) URL without embedded credentials.")
    return url


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 8,
) -> tuple[Any, int]:
    _validate_external_url(url)
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    request_body = None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = Request(
        url,
        data=request_body,
        headers=request_headers,
        method=method.upper(),
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
        body = response.read().decode("utf-8", errors="ignore")
        parsed = json.loads(body) if body else {}
        return parsed, int(getattr(response, "status", 200))


def _build_integration_status(
    *,
    key: str,
    label: str,
    category: str,
    feature_route: str,
    mode: str,
    configured: bool,
    connector_path: str,
    health_path: str,
    base_url: str,
    note: str,
) -> dict[str, Any]:
    if key in CUSTOM_EXTERNAL_KEYS:
        if configured:
            status = "ready"
            status_label = "Sẵn sàng kết nối"
        else:
            status = "waiting_config"
            status_label = "Chờ cấu hình"
    elif mode.endswith("fallback"):
        status = "fallback"
        status_label = "Đang dùng dự phòng"
    else:
        status = "active"
        status_label = "Đang hoạt động"

    health_url = _join_url(base_url, health_path) if base_url and health_path else ""
    return {
        "key": key,
        "label": label,
        "category": category,
        "feature_route": feature_route,
        "mode": mode,
        "configured": configured,
        "status": status,
        "status_label": status_label,
        "connector_path": connector_path,
        "health_path": health_path,
        "health_url": health_url,
        "base_url": base_url,
        "note": note,
    }


def get_integration_statuses(settings: AppSettings | None = None) -> list[dict[str, Any]]:
    active_settings = settings or get_settings()
    return [
        _build_integration_status(
            key="ticket_provider",
            label="API vé đối tác",
            category="Tickets",
            feature_route="/tickets",
            mode="external"
            if active_settings.external_ticket_api_base_url
            else "internal-fallback",
            configured=bool(active_settings.external_ticket_api_base_url),
            connector_path=active_settings.external_ticket_search_path,
            health_path=active_settings.external_ticket_health_path,
            base_url=active_settings.external_ticket_api_base_url,
            note="Cổng chờ để thay dữ liệu vé nội bộ bằng API vé thật.",
        ),
        _build_integration_status(
            key="analytics_provider",
            label="API analytics",
            category="Analytics",
            feature_route="/admin",
            mode="external"
            if active_settings.external_analytics_api_base_url
            else "internal-metrics",
            configured=bool(active_settings.external_analytics_api_base_url),
            connector_path=active_settings.external_analytics_events_path,
            health_path=active_settings.external_analytics_health_path,
            base_url=active_settings.external_analytics_api_base_url,
            note="Cổng chờ để đẩy page view và sự kiện vận hành sang hệ thống phân tích thật.",
        ),
        _build_integration_status(
            key="ar_provider",
            label="API AR",
            category="AR",
            feature_route="/scan-qr",
            mode="external" if active_settings.external_ar_api_base_url else "qr-camera",
            configured=bool(active_settings.external_ar_api_base_url),
            connector_path=active_settings.external_ar_landmarks_path,
            health_path=active_settings.external_ar_health_path,
            base_url=active_settings.external_ar_api_base_url,
            note="Cổng chờ để thay luồng QR hiện tại bằng nội dung AR hoặc overlay thật.",
        ),
        _build_integration_status(
            key="offline_map_provider",
            label="API bản đồ offline",
            category="Offline maps",
            feature_route="/places",
            mode="external"
            if active_settings.external_offline_map_api_base_url
            else "local-pack-catalog",
            configured=bool(active_settings.external_offline_map_api_base_url),
            connector_path=active_settings.external_offline_map_packs_path,
            health_path=active_settings.external_offline_map_health_path,
            base_url=active_settings.external_offline_map_api_base_url,
            note="Cổng chờ để thay danh mục gói offline hiện tại bằng API gói bản đồ thật.",
        ),
        _build_integration_status(
            key="weather_provider",
            label="API thời tiết",
            category="Weather",
            feature_route="/places",
            mode="external"
            if active_settings.external_weather_api_base_url
            else "open-meteo-fallback",
            configured=bool(active_settings.external_weather_api_base_url),
            connector_path=active_settings.external_weather_forecast_path,
            health_path=active_settings.external_weather_health_path,
            base_url=active_settings.external_weather_api_base_url,
            note="Cổng chờ để thay Open-Meteo hiện tại bằng API thời tiết thật.",
        ),
        _build_integration_status(
            key="maps_provider",
            label="Google Maps",
            category="Maps",
            feature_route="/places",
            mode="live"
            if (os.getenv("GOOGLE_MAPS_EMBED_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY"))
            else "public-embed",
            configured=bool(
                os.getenv("GOOGLE_MAPS_EMBED_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
            ),
            connector_path="/maps/embed/v1/place",
            health_path="",
            base_url="https://www.google.com",
            note="Đang dùng nhúng bản đồ và có thể nâng lên key chính thức khi cần quota cao hơn.",
        ),
        _build_integration_status(
            key="ai_provider",
            label="OpenAI",
            category="AI",
            feature_route="/",
            mode="live" if os.getenv("OPENAI_API_KEY") else "fallback",
            configured=bool(os.getenv("OPENAI_API_KEY")),
            connector_path="/v1/responses",
            health_path="",
            base_url="https://api.openai.com",
            note="Dùng Responses API cho chat và lập lịch trình khi có API key; nếu không, hệ thống tự chuyển sang logic nội bộ an toàn.",
        ),
        _build_integration_status(
            key="nearby_provider",
            label="API nearby places",
            category="Nearby",
            feature_route="/planner",
            mode="external" if active_settings.external_nearby_api_base_url else "osm-fallback",
            configured=bool(active_settings.external_nearby_api_base_url),
            connector_path=active_settings.external_nearby_search_path,
            health_path=active_settings.external_nearby_health_path,
            base_url=active_settings.external_nearby_api_base_url,
            note="Cổng chờ để thay Overpass/OSM hiện tại bằng API nearby thật.",
        ),
    ]


def get_integration_summary(settings: AppSettings | None = None) -> dict[str, int]:
    statuses = get_integration_statuses(settings)
    return {
        "total": len(statuses),
        "ready": sum(1 for item in statuses if item["status"] == "ready"),
        "waiting": sum(1 for item in statuses if item["status"] == "waiting_config"),
        "fallback": sum(1 for item in statuses if item["status"] == "fallback"),
        "active": sum(1 for item in statuses if item["status"] == "active"),
    }


def probe_integration(
    integration_key: str,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    integration = next(
        (
            item
            for item in get_integration_statuses(active_settings)
            if item["key"] == integration_key
        ),
        None,
    )
    if integration is None:
        raise KeyError(integration_key)

    result = {
        **integration,
        "checked_at": datetime.now(UTC).isoformat(),
        "reachable": None,
        "http_status": None,
        "probe_state": "skipped",
        "error": "",
    }
    if integration["status"] == "waiting_config":
        result["probe_state"] = "waiting_config"
        return result

    if not integration["health_url"]:
        result["probe_state"] = "skipped"
        return result

    auth_key_map = {
        "ticket_provider": active_settings.external_ticket_api_key,
        "analytics_provider": active_settings.external_analytics_api_key,
        "ar_provider": active_settings.external_ar_api_key,
        "offline_map_provider": active_settings.external_offline_map_api_key,
        "weather_provider": active_settings.external_weather_api_key,
        "nearby_provider": active_settings.external_nearby_api_key,
    }
    try:
        _, status_code = _request_json(
            integration["health_url"],
            headers=_auth_headers(auth_key_map.get(integration_key, "")),
            timeout_seconds=min(active_settings.integration_timeout_seconds, 5),
        )
        result["reachable"] = True
        result["http_status"] = status_code
        result["probe_state"] = "reachable"
        return result
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("integration_probe_failed key=%s error=%s", integration_key, exc)
        _audit_integration_failure(integration_key, exc)
        result["reachable"] = False
        result["probe_state"] = "unreachable"
        result["error"] = str(exc)
        if isinstance(exc, HTTPError):
            result["http_status"] = exc.code
        return result


def fetch_external_ticket_offers(
    *,
    origin: str,
    destination: str,
    vehicle_type: str | None,
    departure_date: str | None,
    passengers: int,
    lang: str = DEFAULT_LANGUAGE,
    settings: AppSettings | None = None,
) -> list[TicketOffer] | None:
    active_settings = settings or get_settings()
    if not active_settings.external_ticket_api_base_url:
        return None

    url = _join_url(
        active_settings.external_ticket_api_base_url,
        active_settings.external_ticket_search_path,
    )
    payload = {
        "origin": origin,
        "destination": destination,
        "vehicle_type": vehicle_type,
        "departure_date": departure_date,
        "passengers": max(passengers, 1),
        "language": resolve_language(lang),
    }
    try:
        response_data, _status_code = _request_json(
            url,
            method="POST",
            payload=payload,
            headers=_auth_headers(active_settings.external_ticket_api_key),
            timeout_seconds=active_settings.integration_timeout_seconds,
        )
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("external_ticket_search_failed error=%s", exc)
        _audit_integration_failure("ticket_provider", exc)
        return None

    offer_items = (
        response_data.get("offers", response_data)
        if isinstance(response_data, dict)
        else response_data
    )
    if not isinstance(offer_items, list):
        return []

    offers: list[TicketOffer] = []
    for item in offer_items:
        if not isinstance(item, dict):
            continue
        try:
            offers.append(
                TicketOffer(
                    provider=str(item.get("provider") or "External provider"),
                    vehicle_type=str(item.get("vehicle_type") or vehicle_type or "plane"),
                    origin=str(item.get("origin") or origin),
                    destination=str(item.get("destination") or destination),
                    departure=str(item.get("departure") or item.get("departure_time") or ""),
                    departure_date=item.get("departure_date"),
                    arrival=item.get("arrival") or item.get("arrival_time"),
                    duration=item.get("duration"),
                    seat_class=item.get("seat_class") or item.get("class"),
                    available_seats=(
                        int(item["available_seats"])
                        if item.get("available_seats") is not None
                        else int(item["seats_left"])
                        if item.get("seats_left") is not None
                        else None
                    ),
                    operator_note=item.get("operator_note") or item.get("note"),
                    price=float(item.get("price") or 0),
                    booking_url=_normalize_booking_url(
                        item.get("booking_url") or active_settings.external_ticket_api_base_url
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    return offers


def track_external_analytics_event(
    event_name: str,
    payload: dict[str, Any],
    settings: AppSettings | None = None,
) -> bool:
    active_settings = settings or get_settings()
    if not active_settings.external_analytics_api_base_url:
        return False

    url = _join_url(
        active_settings.external_analytics_api_base_url,
        active_settings.external_analytics_events_path,
    )
    envelope = {
        "event_name": event_name,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
    try:
        _request_json(
            url,
            method="POST",
            payload=envelope,
            headers=_auth_headers(active_settings.external_analytics_api_key),
            timeout_seconds=min(active_settings.integration_timeout_seconds, 2),
        )
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("external_analytics_event_failed event=%s error=%s", event_name, exc)
        _audit_integration_failure("analytics_provider", exc)
        return False
    return True


def fetch_external_ar_landmarks(
    lang: str = DEFAULT_LANGUAGE,
    settings: AppSettings | None = None,
) -> list[dict[str, str]] | None:
    active_settings = settings or get_settings()
    if not active_settings.external_ar_api_base_url:
        return None

    url = _with_query(
        _join_url(
            active_settings.external_ar_api_base_url,
            active_settings.external_ar_landmarks_path,
        ),
        {"lang": resolve_language(lang)},
    )
    try:
        response_data, _status_code = _request_json(
            url,
            headers=_auth_headers(active_settings.external_ar_api_key),
            timeout_seconds=active_settings.integration_timeout_seconds,
        )
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("external_ar_landmarks_failed error=%s", exc)
        _audit_integration_failure("ar_provider", exc)
        return None

    landmark_items = (
        response_data.get("items", response_data)
        if isinstance(response_data, dict)
        else response_data
    )
    if not isinstance(landmark_items, list):
        return []

    results: list[dict[str, str]] = []
    for item in landmark_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        province = str(item.get("province") or "").strip()
        note = str(item.get("note") or item.get("description") or "").strip()
        if not name or not province or not note:
            continue
        results.append({"name": name, "province": province, "note": note})
    return results


def fetch_external_offline_map_packs(
    lang: str = DEFAULT_LANGUAGE,
    settings: AppSettings | None = None,
) -> list[dict[str, str]] | None:
    active_settings = settings or get_settings()
    if not active_settings.external_offline_map_api_base_url:
        return None

    url = _with_query(
        _join_url(
            active_settings.external_offline_map_api_base_url,
            active_settings.external_offline_map_packs_path,
        ),
        {"lang": resolve_language(lang)},
    )
    try:
        response_data, _status_code = _request_json(
            url,
            headers=_auth_headers(active_settings.external_offline_map_api_key),
            timeout_seconds=active_settings.integration_timeout_seconds,
        )
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("external_offline_map_packs_failed error=%s", exc)
        _audit_integration_failure("offline_map_provider", exc)
        return None

    pack_items = (
        response_data.get("items", response_data)
        if isinstance(response_data, dict)
        else response_data
    )
    if not isinstance(pack_items, list):
        return []

    results: list[dict[str, str]] = []
    for item in pack_items:
        if not isinstance(item, dict):
            continue
        region = str(item.get("region") or "").strip()
        name = str(item.get("name") or "").strip()
        coverage = str(item.get("coverage") or "").strip()
        if not region or not name or not coverage:
            continue
        results.append({"region": region, "name": name, "coverage": coverage})
    return results


def fetch_external_weather_forecast(
    *,
    latitude: float,
    longitude: float,
    place_name: str,
    lang: str = DEFAULT_LANGUAGE,
    settings: AppSettings | None = None,
) -> dict[str, Any] | None:
    active_settings = settings or get_settings()
    if not active_settings.external_weather_api_base_url:
        return None

    url = _join_url(
        active_settings.external_weather_api_base_url,
        active_settings.external_weather_forecast_path,
    )
    payload = {
        "latitude": latitude,
        "longitude": longitude,
        "place_name": place_name,
        "language": resolve_language(lang),
    }
    try:
        response_data, _status_code = _request_json(
            url,
            method="POST",
            payload=payload,
            headers=_auth_headers(active_settings.external_weather_api_key),
            timeout_seconds=active_settings.integration_timeout_seconds,
        )
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("external_weather_forecast_failed error=%s", exc)
        _audit_integration_failure("weather_provider", exc)
        return None

    if isinstance(response_data, dict):
        return response_data.get("forecast", response_data)
    return None


def fetch_external_nearby_services(
    *,
    latitude: float,
    longitude: float,
    place_name: str,
    province: str,
    limit: int = 6,
    lang: str = DEFAULT_LANGUAGE,
    settings: AppSettings | None = None,
) -> list[dict[str, Any]] | None:
    active_settings = settings or get_settings()
    if not active_settings.external_nearby_api_base_url:
        return None

    url = _join_url(
        active_settings.external_nearby_api_base_url,
        active_settings.external_nearby_search_path,
    )
    payload = {
        "latitude": latitude,
        "longitude": longitude,
        "place_name": place_name,
        "province": province,
        "limit": max(limit, 1),
        "language": resolve_language(lang),
    }
    try:
        response_data, _status_code = _request_json(
            url,
            method="POST",
            payload=payload,
            headers=_auth_headers(active_settings.external_nearby_api_key),
            timeout_seconds=active_settings.integration_timeout_seconds,
        )
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("external_nearby_search_failed error=%s", exc)
        _audit_integration_failure("nearby_provider", exc)
        return None

    items = (
        response_data.get("items", response_data)
        if isinstance(response_data, dict)
        else response_data
    )
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]
