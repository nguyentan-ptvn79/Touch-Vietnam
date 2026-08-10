"""Application services shared by the Flask website and FastAPI endpoints."""

from __future__ import annotations

import json
import logging
import os
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from uuid import uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from .db import (
    count_page_views,
    count_returning_visitors,
    count_saved_trips,
    count_ticket_bookings,
    count_unique_visitors,
    count_users,
    create_expense_item,
    create_ticket_booking,
    create_user,
    delete_admin_recommendation,
    ensure_db,
    find_user_by_email,
    get_admin_recommendation,
    get_saved_trip,
    is_auth_token_revoked,
    list_admin_recommendations,
    list_daily_page_views,
    list_expense_items,
    list_managed_places,
    list_saved_trips,
    list_site_content_settings,
    list_ticket_bookings,
    list_top_page_views,
    revoke_auth_token_id,
    save_site_content_settings,
    save_trip,
    set_admin_recommendation_active,
    sum_ticket_booking_revenue,
    upsert_admin_recommendation,
    upsert_managed_place,
    verify_user,
)
from .geography import normalize_province_name
from .i18n import (
    DEFAULT_LANGUAGE,
    get_category_labels,
    get_language_options,
    get_place_aliases,
    get_region_labels,
    resolve_language,
    text,
    translate_ar_item,
    translate_offline_pack,
    translate_place,
    translate_service_name,
    translate_ticket_offer,
)
from .integration_gateways import (
    fetch_external_ar_landmarks,
    fetch_external_nearby_services,
    fetch_external_offline_map_packs,
    fetch_external_ticket_offers,
    fetch_external_weather_forecast,
)
from .models import (
    AdminRecommendation,
    AuthResponse,
    BudgetBreakdown,
    BudgetEstimateRequest,
    ChatRequest,
    ChatResponse,
    Coordinate,
    DashboardMetric,
    DashboardSummary,
    ItineraryDay,
    ItineraryPlan,
    ItineraryRequest,
    NearbySuggestion,
    Place,
    TicketOffer,
    UserLoginRequest,
    UserRegisterRequest,
    WeatherForecast,
)
from .openai_planner import (
    enhance_itinerary_with_openai,
    is_openai_planner_available,
)
from .sample_data import (
    AR_LANDMARKS,
    OFFLINE_MAP_PACKS,
    PLACE_VIEWS,
    PLACES,
    TICKET_OFFERS,
)
from .settings import get_settings
from .time_utils import (
    combine_local_date_time,
    now_local,
    parse_local_date,
    to_local_iso,
    today_local,
)

AUTH_TOKEN_MAX_AGE_SECONDS = get_settings().auth_token_ttl_seconds
AUTH_TOKEN_ALGORITHM = "HS256"  # nosec B105
AUTH_TOKEN_ISSUER = "touch-vietnam-api"  # nosec B105
logger = logging.getLogger("touch_vn.services")


def create_auth_token(email: str) -> str:
    normalized_email = email.strip().lower()
    issued_at = datetime.now(UTC)
    settings = get_settings()
    payload = {
        "sub": normalized_email,
        "email": normalized_email,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=AUTH_TOKEN_MAX_AGE_SECONDS),
        "iss": AUTH_TOKEN_ISSUER,
        "aud": settings.auth_token_audience,
        "jti": uuid4().hex,
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=AUTH_TOKEN_ALGORITHM,
    )


def _decode_auth_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[AUTH_TOKEN_ALGORITHM],
            issuer=AUTH_TOKEN_ISSUER,
            audience=settings.auth_token_audience,
            options={"require": ["sub", "iat", "exp", "iss", "aud", "jti", "type"]},
        )
    except InvalidTokenError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "access":
        return None
    return payload


def verify_auth_token(token: str) -> str | None:
    payload = _decode_auth_token(token)
    if payload is None:
        return None
    jti = str(payload.get("jti") or "")
    if is_auth_token_revoked(jti, int(time.time())):
        return None
    email = str(payload.get("sub") or "").strip().lower()
    if not email or find_user_by_email(email) is None:
        return None
    return email


def revoke_auth_token(token: str) -> bool:
    payload = _decode_auth_token(token)
    if payload is None:
        return False
    jti = str(payload.get("jti") or "").strip()
    try:
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError):
        return False
    revoke_auth_token_id(jti, expires_at)
    return True


INTEREST_ALIASES = {
    "culture": "culture",
    "food": "food",
    "beach": "beach",
    "island": "island",
    "mountain": "mountain",
    "spiritual": "spiritual",
    "history": "history",
    "entertainment": "entertainment",
    "van hoa": "culture",
    "am thuc": "food",
    "bien": "beach",
    "dao": "island",
    "hai dao": "island",
    "nui": "mountain",
    "tam linh": "spiritual",
    "lich su": "history",
    "giai tri": "entertainment",
    "문화": "culture",
    "음식": "food",
    "해변": "beach",
    "섬": "island",
    "산": "mountain",
    "산악": "mountain",
    "영성": "spiritual",
    "역사": "history",
    "엔터테인먼트": "entertainment",
}

LOCATION_ALIASES = {
    "ha noi": {"ha noi", "hanoi", "hn", "noi bai"},
    "ho chi minh": {
        "ho chi minh",
        "ho chi minh city",
        "hcm",
        "tphcm",
        "tp hcm",
        "sai gon",
        "saigon",
        "sgn",
        "tan son nhat",
    },
    "da nang": {"da nang", "danang", "dng"},
    "hue": {"hue", "co do hue"},
    "hoi an": {"hoi an", "pho co hoi an"},
    "phu quoc": {"phu quoc", "dao ngoc phu quoc", "pqc"},
    "sa pa": {"sa pa", "sapa"},
    "trang an": {"trang an", "ninh binh", "trang an ninh binh"},
    "ha long": {"ha long", "ha long bay", "vinh ha long", "halong"},
    "can tho": {"can tho", "mekong can tho"},
    "ba na hills": {"ba na hills", "ba na", "sun world ba na hills"},
}

WEATHER_CACHE_TTL_SECONDS = 900
WEATHER_CACHE: dict[tuple[str, str], tuple[float, WeatherForecast]] = {}
NEARBY_CACHE_TTL_SECONDS = 1800
NEARBY_LIVE_TIMEOUT_SECONDS = 2.5
WEATHER_LIVE_TIMEOUT_SECONDS = float(os.getenv("WEATHER_LIVE_TIMEOUT_SECONDS", "1.5"))
NEARBY_SERVICE_CACHE: dict[tuple[float, float, str], tuple[float, list[NearbySuggestion]]] = {}
SETTINGS = get_settings()


ensure_db()


def _normalize_text(value: str) -> str:
    lowered = value.strip().lower().replace("đ", "d").replace("Đ", "d")
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _format_currency_number(value: float) -> str:
    return f"{value:,.0f}"


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _with_current_province(place: Place) -> Place:
    current_province = normalize_province_name(place.province)
    if current_province == place.province:
        return place
    return place.model_copy(update={"province": current_province})


def _expand_location_aliases(value: str) -> set[str]:
    normalized = _normalize_text(value)
    aliases = {normalized}
    for canonical, candidates in LOCATION_ALIASES.items():
        if normalized == canonical or normalized in candidates:
            aliases.update(candidates)
            aliases.add(canonical)
            continue
        if any(normalized in candidate or candidate in normalized for candidate in candidates):
            aliases.update(candidates)
            aliases.add(canonical)
    return aliases


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return round(2 * radius * asin(sqrt(a)), 1)


def _search_corpus(place: Place) -> list[str]:
    localized_variants = [place]
    for language in ("en", "ko"):
        localized_variants.append(translate_place(place, language))
    texts: list[str] = []
    for variant in localized_variants:
        texts.extend(
            [
                variant.name,
                variant.province,
                variant.description,
                *variant.highlights,
            ]
        )
    texts.extend(get_place_aliases(place))
    normalized_name = _normalize_text(place.name)
    normalized_province = _normalize_text(place.province)
    for canonical, candidates in LOCATION_ALIASES.items():
        if (
            canonical in normalized_name
            or canonical in normalized_province
            or any(
                candidate in normalized_name or candidate in normalized_province
                for candidate in candidates
            )
        ):
            texts.append(canonical)
            texts.extend(candidates)
    return [_normalize_text(item) for item in texts]


def _match_place_from_question(question: str) -> Place | None:
    normalized_question = _normalize_text(question)
    for place in _runtime_place_pool():
        if any(alias in normalized_question for alias in _search_corpus(place)):
            return place
    return None


def _active_places() -> list[Place]:
    merged_map: dict[str, Place] = {place.id: _with_current_province(place) for place in PLACES}

    for record in list_managed_places(include_inactive=True):
        place = _with_current_province(record["place"])
        if record["is_active"]:
            merged_map[place.id] = place
        else:
            merged_map.pop(place.id, None)

    ordered_places: list[Place] = []
    for place in PLACES:
        active = merged_map.pop(place.id, None)
        if active is not None:
            ordered_places.append(active)

    custom_places = sorted(
        merged_map.values(),
        key=lambda item: (_normalize_text(item.name), item.id),
    )
    ordered_places.extend(custom_places)
    return ordered_places


def _active_place_by_id(place_id: str) -> Place | None:
    for place in _active_places():
        if place.id == place_id:
            return place
    for place in PLACES:
        if place.id == place_id:
            return place
    return None


def _runtime_place_pool() -> list[Place]:
    active_places = _active_places()
    return active_places or list(PLACES)


def _all_admin_place_records() -> list[dict[str, Any]]:
    managed_map = {
        record["place"].id: record for record in list_managed_places(include_inactive=True)
    }
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for base_place in PLACES:
        managed = managed_map.get(base_place.id)
        current_place = _with_current_province(managed["place"] if managed else base_place)
        rows.append(
            {
                "place": current_place,
                "is_active": managed["is_active"] if managed else True,
                "is_custom": False,
                "is_overridden": managed is not None,
                "updated_by": managed["updated_by"] if managed else None,
                "updated_at": managed["updated_at"] if managed else None,
            }
        )
        seen_ids.add(base_place.id)

    for place_id, managed in managed_map.items():
        if place_id in seen_ids:
            continue
        rows.append(
            {
                "place": managed["place"],
                "is_active": managed["is_active"],
                "is_custom": True,
                "is_overridden": True,
                "updated_by": managed["updated_by"],
                "updated_at": managed["updated_at"],
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            0 if item["is_active"] else 1,
            _normalize_text(item["place"].name),
            item["place"].id,
        ),
    )


def _site_content_defaults(lang: str) -> dict[str, str]:
    language = resolve_language(lang)
    return {
        "brand_name": SETTINGS.app_name,
        "browser_title": SETTINGS.app_name,
        "footer_brand_line": text(language, "footer_brand_line"),
        "support_email": SETTINGS.support_email,
        "support_phone": SETTINGS.support_phone,
    }


def get_places(
    region: str | None = None,
    province: str | None = None,
    category: str | None = None,
    search: str | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> list[Place]:
    results = _active_places()
    if region:
        results = [place for place in results if place.region == region]
    if province:
        normalized_province = _normalize_text(province)
        results = [
            place for place in results if _normalize_text(place.province) == normalized_province
        ]
    if category:
        results = [place for place in results if category in place.categories]
    if search:
        keyword = _normalize_text(search)
        results = [
            place for place in results if any(keyword in token for token in _search_corpus(place))
        ]
    return [translate_place(place, lang) for place in results]


def get_provinces_summary(
    region: str | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> list[dict[str, str | int]]:
    places = _active_places()
    if region:
        places = [place for place in places if place.region == region]

    summary: dict[str, dict[str, str | int]] = {}
    for place in places:
        item = summary.setdefault(
            place.province,
            {
                "name": place.province,
                "region": place.region,
                "count": 0,
            },
        )
        item["count"] = int(item["count"]) + 1

    return sorted(summary.values(), key=lambda item: str(item["name"]))


def get_place(place_id: str, lang: str = DEFAULT_LANGUAGE) -> Place | None:
    place = _active_place_by_id(place_id)
    if place is None:
        return None
    PLACE_VIEWS[place.id] = PLACE_VIEWS.get(place.id, 0) + 1
    return translate_place(place, lang)


def get_categories(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    labels = get_category_labels(lang)
    values = sorted({category for place in _active_places() for category in place.categories})
    return [{"code": code, "label": labels.get(code, code.title())} for code in values]


def get_regions_summary(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str | int]]:
    labels = get_region_labels(lang)
    active_places = _active_places()
    return [
        {
            "code": region_code,
            "label": labels[region_code],
            "count": len([place for place in active_places if place.region == region_code]),
        }
        for region_code in ("north", "central", "south")
    ]


def get_featured_places(limit: int = 6, lang: str = DEFAULT_LANGUAGE) -> list[Place]:
    featured = sorted(
        _active_places(),
        key=lambda place: (place.must_go_score, place.rating),
        reverse=True,
    )[:limit]
    return [translate_place(place, lang) for place in featured]


def _weather_condition_key(weather_code: int) -> str:
    if weather_code == 0:
        return "weather_code_clear"
    if weather_code in {1, 2}:
        return "weather_code_partly_cloudy"
    if weather_code == 3:
        return "weather_code_overcast"
    if weather_code in {45, 48}:
        return "weather_code_fog"
    if weather_code in {51, 53, 55, 56, 57}:
        return "weather_code_drizzle"
    if weather_code in {61, 63, 65, 66, 67}:
        return "weather_code_rain"
    if weather_code in {71, 73, 75, 77}:
        return "weather_code_snow"
    if weather_code in {80, 81, 82}:
        return "weather_code_showers"
    if weather_code in {95, 96, 99}:
        return "weather_code_thunderstorm"
    return "weather_code_partly_cloudy"


def _weather_advice(language: str, temperature_c: int, weather_code: int) -> str:
    if weather_code in {45, 48}:
        return text(language, "weather_fog_advice")
    if weather_code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}:
        return text(language, "weather_rain_advice")
    if temperature_c >= 32:
        return text(language, "weather_hot_advice")
    if temperature_c <= 18:
        return text(language, "weather_cool_advice")
    return text(language, "weather_general_advice")


def _build_fallback_weather(place: Place, lang: str) -> WeatherForecast:
    localized_place = translate_place(place, lang)
    language = resolve_language(lang)
    current_time = now_local()
    presets = {
        "north": (
            text(language, "weather_north_condition"),
            text(language, "weather_north_advice"),
        ),
        "central": (
            text(language, "weather_central_condition"),
            text(language, "weather_central_advice"),
        ),
        "south": (
            text(language, "weather_south_condition"),
            text(language, "weather_south_advice"),
        ),
    }
    condition, advice = presets[place.region]
    temperature = {"north": 26, "central": 30, "south": 31}[place.region]
    return WeatherForecast(
        destination=localized_place.name,
        forecast_date=current_time.date().isoformat(),
        temperature_c=temperature,
        condition=condition,
        advice=advice,
        best_visit_time=text(language, "weather_best_time"),
        temperature_high_c=temperature + 2,
        temperature_low_c=temperature - 3,
        wind_speed_kmh=12.0,
        source=text(language, "places_weather_source_demo"),
        updated_at=to_local_iso(current_time),
    )


def _build_weather_from_external_payload(
    place: Place,
    payload: dict[str, Any],
    lang: str,
) -> WeatherForecast | None:
    language = resolve_language(lang)
    localized_place = translate_place(place, language)

    temperature_raw = payload.get("temperature_c", payload.get("temperature"))
    condition = str(payload.get("condition") or "").strip()
    if temperature_raw is None or not condition:
        return None

    try:
        temperature = round(float(temperature_raw))
    except (TypeError, ValueError):
        return None

    forecast_date = str(
        payload.get("forecast_date")
        or payload.get("date")
        or payload.get("forecast_time")
        or today_local().isoformat()
    )
    advice = str(payload.get("advice") or "").strip() or text(language, "weather_general_advice")
    best_visit_time = str(payload.get("best_visit_time") or "").strip() or text(
        language, "weather_best_time"
    )
    source = str(payload.get("source") or "").strip() or text(
        language, "places_weather_source_live"
    )
    updated_at = (
        payload.get("updated_at") or payload.get("updated") or payload.get("time") or now_local()
    )

    try:
        high = (
            round(float(payload["temperature_high_c"]))
            if payload.get("temperature_high_c") is not None
            else round(float(payload["high"]))
            if payload.get("high") is not None
            else None
        )
        low = (
            round(float(payload["temperature_low_c"]))
            if payload.get("temperature_low_c") is not None
            else round(float(payload["low"]))
            if payload.get("low") is not None
            else None
        )
        wind_speed = (
            round(float(payload["wind_speed_kmh"]), 1)
            if payload.get("wind_speed_kmh") is not None
            else round(float(payload["wind_speed"]), 1)
            if payload.get("wind_speed") is not None
            else None
        )
    except (TypeError, ValueError):
        high = None
        low = None
        wind_speed = None

    return WeatherForecast(
        destination=str(
            payload.get("destination") or payload.get("place_name") or localized_place.name
        ),
        forecast_date=forecast_date,
        temperature_c=temperature,
        condition=condition,
        advice=advice,
        best_visit_time=best_visit_time,
        temperature_high_c=high,
        temperature_low_c=low,
        wind_speed_kmh=wind_speed,
        source=source,
        updated_at=to_local_iso(updated_at),
    )


def _fetch_live_weather(place: Place, lang: str) -> WeatherForecast:
    language = resolve_language(lang)
    localized_place = translate_place(place, language)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={place.coordinate.lat}"
        f"&longitude={place.coordinate.lng}"
        "&current=temperature_2m,weather_code,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min"
        "&forecast_days=1"
        "&timezone=auto"
    )
    with urlopen(url, timeout=WEATHER_LIVE_TIMEOUT_SECONDS) as response:  # nosec B310
        payload = json.loads(response.read().decode("utf-8"))

    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    temperature = round(float(current["temperature_2m"]))
    weather_code = int(current["weather_code"])
    wind_speed = round(float(current.get("wind_speed_10m", 0.0)), 1)
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    high = round(float(highs[0])) if highs else None
    low = round(float(lows[0])) if lows else None
    return WeatherForecast(
        destination=localized_place.name,
        forecast_date=str(current.get("time") or today_local().isoformat()),
        temperature_c=temperature,
        condition=text(language, _weather_condition_key(weather_code)),
        advice=_weather_advice(language, temperature, weather_code),
        best_visit_time=text(language, "weather_best_time"),
        temperature_high_c=high,
        temperature_low_c=low,
        wind_speed_kmh=wind_speed,
        source=text(language, "places_weather_source_live"),
        updated_at=to_local_iso(current.get("time") or now_local()),
    )


def get_google_maps_embed_url(place: Place) -> str:
    query = quote_plus(f"{place.name}, {place.province}, Vietnam")
    api_key = os.getenv("GOOGLE_MAPS_EMBED_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    if api_key:
        return f"https://www.google.com/maps/embed/v1/place?key={api_key}&q={query}"
    return f"https://www.google.com/maps?q={query}&z=13&output=embed"


def get_google_maps_view_url(place: Place) -> str:
    query = quote_plus(f"{place.name}, {place.province}, Vietnam")
    return f"https://www.google.com/maps/search/?api=1&query={query}"


def get_weather(place_id: str, lang: str = DEFAULT_LANGUAGE) -> WeatherForecast | None:
    place = _active_place_by_id(place_id)
    if not place:
        return None
    language = resolve_language(lang)
    cache_key = (place_id, language)
    cached = WEATHER_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < WEATHER_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        external_payload = fetch_external_weather_forecast(
            latitude=place.coordinate.lat,
            longitude=place.coordinate.lng,
            place_name=translate_place(place, language).name,
            lang=language,
        )
        forecast = (
            _build_weather_from_external_payload(place, external_payload, language)
            if external_payload
            else None
        )
        if forecast is None:
            forecast = _fetch_live_weather(place, language)
    except (KeyError, TimeoutError, URLError, ValueError, OSError, json.JSONDecodeError):
        forecast = _build_fallback_weather(place, language)

    WEATHER_CACHE[cache_key] = (time.time(), forecast)
    return forecast


def get_weather_batch(
    place_ids: list[str],
    lang: str = DEFAULT_LANGUAGE,
    max_workers: int = 4,
) -> dict[str, WeatherForecast | None]:
    unique_place_ids = list(dict.fromkeys(place_ids))
    if not unique_place_ids:
        return {}

    results: dict[str, WeatherForecast | None] = {}
    worker_count = min(max_workers, len(unique_place_ids))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(get_weather, place_id, lang): place_id for place_id in unique_place_ids
        }
        for future in as_completed(future_map):
            place_id = future_map[future]
            try:
                results[place_id] = future.result()
            except Exception:
                logger.exception("Weather lookup failed for place_id=%s", place_id)
                results[place_id] = None
    return results


def get_nearby_places(
    lat: float,
    lng: float,
    limit: int = 5,
    lang: str = DEFAULT_LANGUAGE,
) -> list[NearbySuggestion]:
    language = resolve_language(lang)
    ranked = sorted(
        _runtime_place_pool(),
        key=lambda place: _haversine_km(lat, lng, place.coordinate.lat, place.coordinate.lng),
    )
    suggestions: list[NearbySuggestion] = []
    for place in ranked[:limit]:
        localized = translate_place(place, language)
        suggestions.append(
            NearbySuggestion(
                name=localized.name,
                kind="tourist-spot",
                province=localized.province,
                distance_km=_haversine_km(lat, lng, place.coordinate.lat, place.coordinate.lng),
                note=text(
                    language,
                    "nearby_place_note",
                    highlights=", ".join(localized.highlights[:2]).lower(),
                ),
            )
        )
    return suggestions


def _nearby_kind_from_tags(tags: dict[str, str]) -> str | None:
    amenity = tags.get("amenity")
    tourism = tags.get("tourism")
    shop = tags.get("shop")
    leisure = tags.get("leisure")

    if amenity in {"restaurant", "fast_food", "food_court"}:
        return "restaurant"
    if amenity == "cafe":
        return "cafe"
    if amenity == "pharmacy":
        return "pharmacy"
    if amenity in {"hospital", "clinic", "doctors"}:
        return "hospital"
    if amenity == "marketplace":
        return "market"
    if shop in {"supermarket", "department_store", "mall"}:
        return "supermarket"
    if shop in {"convenience", "general"}:
        return "convenience-store"
    if tourism == "hotel":
        return "hotel"
    if tourism == "resort":
        return "resort"
    if tourism in {"guest_house", "hostel", "apartment"}:
        return "homestay"
    if leisure in {"theme_park", "water_park", "amusement_arcade"}:
        return "theme-park"
    if tourism == "attraction":
        return "theme-park"
    return None


def _nearby_kind_priority(kind: str) -> int:
    priorities = {
        "pharmacy": 0,
        "hospital": 1,
        "hotel": 2,
        "homestay": 3,
        "resort": 4,
        "supermarket": 5,
        "convenience-store": 6,
        "market": 7,
        "restaurant": 8,
        "cafe": 9,
        "theme-park": 10,
    }
    return priorities.get(kind, 99)


def _fetch_live_nearby_services(
    *,
    lat: float,
    lng: float,
    province: str,
    place_name: str,
    lang: str,
    limit: int = 6,
) -> list[NearbySuggestion]:
    language = resolve_language(lang)
    cache_key = (round(lat, 3), round(lng, 3), language)
    cached = NEARBY_SERVICE_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < NEARBY_CACHE_TTL_SECONDS:
        return cached[1][:limit]

    query = f"""
[out:json][timeout:6];
(
  nwr(around:5000,{lat},{lng})[amenity~"restaurant|fast_food|food_court|cafe|pharmacy|hospital|clinic|doctors|marketplace"];
  nwr(around:5000,{lat},{lng})[shop~"supermarket|department_store|mall|convenience|general"];
  nwr(around:5000,{lat},{lng})[tourism~"hotel|resort|guest_house|hostel|apartment|attraction"];
  nwr(around:5000,{lat},{lng})[leisure~"theme_park|water_park|amusement_arcade"];
);
out center 60;
""".strip()
    request = Request(
        "https://overpass-api.de/api/interpreter",
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "User-Agent": f"{SETTINGS.app_name}/{SETTINGS.app_version}",
        },
    )
    with urlopen(request, timeout=NEARBY_LIVE_TIMEOUT_SECONDS) as response:  # nosec B310
        payload = json.loads(response.read().decode("utf-8"))

    kind_caps = {
        "restaurant": 2,
        "cafe": 1,
        "hotel": 1,
        "homestay": 1,
        "resort": 1,
        "pharmacy": 1,
        "hospital": 1,
        "supermarket": 1,
        "convenience-store": 1,
        "market": 1,
        "theme-park": 1,
    }
    raw_candidates: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        kind = _nearby_kind_from_tags(tags)
        if kind is None:
            continue
        point_lat = element.get("lat") or (element.get("center") or {}).get("lat")
        point_lng = element.get("lon") or (element.get("center") or {}).get("lon")
        if point_lat is None or point_lng is None:
            continue
        raw_candidates.append(
            {
                "name": (tags.get("name") or "").strip() or translate_service_name(kind, language),
                "kind": kind,
                "distance_km": _haversine_km(lat, lng, float(point_lat), float(point_lng)),
                "priority": _nearby_kind_priority(kind),
            }
        )

    raw_candidates.sort(
        key=lambda item: (
            item["priority"],
            item["distance_km"],
            _normalize_text(item["name"]),
        )
    )

    selected: list[NearbySuggestion] = []
    seen_names: set[tuple[str, str]] = set()
    per_kind: dict[str, int] = {}
    for item in raw_candidates:
        signature = (item["kind"], _normalize_text(item["name"]))
        if signature in seen_names:
            continue
        if per_kind.get(item["kind"], 0) >= kind_caps.get(item["kind"], 1):
            continue
        selected.append(
            NearbySuggestion(
                name=item["name"],
                kind=item["kind"],
                province=province,
                distance_km=item["distance_km"],
                note=text(language, "nearby_service_note", place=place_name),
            )
        )
        seen_names.add(signature)
        per_kind[item["kind"]] = per_kind.get(item["kind"], 0) + 1
        if len(selected) >= limit:
            break

    NEARBY_SERVICE_CACHE[cache_key] = (time.time(), selected)
    return selected


def _build_fallback_nearby_services(
    nearest_place: Place,
    localized_place: Place,
    language: str,
) -> list[NearbySuggestion]:
    suggestions: list[NearbySuggestion] = []
    for index, service in enumerate(nearest_place.nearby_services, start=1):
        suggestions.append(
            NearbySuggestion(
                name=translate_service_name(service, language),
                kind=service,
                province=localized_place.province,
                distance_km=round(0.4 + index * 0.3, 1),
                note=text(language, "nearby_service_note", place=localized_place.name),
            )
        )
    return suggestions


def _build_nearby_from_external_items(
    items: list[dict[str, Any]],
    *,
    province: str,
    place_name: str,
    language: str,
    limit: int = 6,
) -> list[NearbySuggestion]:
    suggestions: list[NearbySuggestion] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kind = str(
            item.get("kind") or item.get("type") or item.get("category") or "tourist-spot"
        ).strip()
        raw_distance = item.get("distance_km", item.get("distance"))
        try:
            distance_km = round(float(raw_distance), 1) if raw_distance is not None else 0.0
        except (TypeError, ValueError):
            distance_km = 0.0
        note = str(
            item.get("note") or item.get("description") or item.get("address") or ""
        ).strip() or text(language, "nearby_service_note", place=place_name)
        suggestions.append(
            NearbySuggestion(
                name=name,
                kind=kind,
                province=str(item.get("province") or province),
                distance_km=distance_km,
                note=note,
            )
        )
        if len(suggestions) >= limit:
            break
    return suggestions


def get_nearby_services(
    lat: float,
    lng: float,
    lang: str = DEFAULT_LANGUAGE,
    *,
    prefer_live: bool = True,
) -> list[NearbySuggestion]:
    language = resolve_language(lang)
    active_places = _runtime_place_pool()
    if not active_places:
        return []
    nearest_place = min(
        active_places,
        key=lambda place: _haversine_km(lat, lng, place.coordinate.lat, place.coordinate.lng),
    )
    localized_place = translate_place(nearest_place, language)
    if prefer_live:
        try:
            external_items = fetch_external_nearby_services(
                latitude=lat,
                longitude=lng,
                place_name=localized_place.name,
                province=localized_place.province,
                lang=language,
            )
            if external_items:
                return _build_nearby_from_external_items(
                    external_items,
                    province=localized_place.province,
                    place_name=localized_place.name,
                    language=language,
                )

            live_suggestions = _fetch_live_nearby_services(
                lat=lat,
                lng=lng,
                province=localized_place.province,
                place_name=localized_place.name,
                lang=language,
            )
            if live_suggestions:
                return live_suggestions
        except (
            HTTPError,
            TimeoutError,
            URLError,
            ValueError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            logger.warning(
                "Nearby-service lookup failed for latitude=%s longitude=%s: %s",
                lat,
                lng,
                exc,
            )

    return _build_fallback_nearby_services(nearest_place, localized_place, language)


def get_must_go(
    region: str | None = None,
    province: str | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> list[Place]:
    candidates = _active_places()
    if region:
        candidates = [place for place in candidates if place.region == region]
    if province:
        keyword = _normalize_text(province)
        candidates = [
            place
            for place in candidates
            if any(keyword in token for token in _search_corpus(place))
        ]
    ranked = sorted(
        candidates, key=lambda place: (place.must_go_score, place.rating), reverse=True
    )[:5]
    return [translate_place(place, lang) for place in ranked]


def _resolve_ticket_date(departure_date: str | None) -> date:
    today = today_local()
    parsed = parse_local_date(departure_date)
    if parsed is None:
        return today
    if parsed < today:
        return today
    return parsed


def _materialize_ticket_offer(
    offer: TicketOffer,
    requested_date: date,
    anchor_date: date,
    passengers: int,
) -> TicketOffer | None:
    base_date = parse_local_date(offer.departure_date) or anchor_date
    day_offset = max((base_date - anchor_date).days, 0)
    resolved_date = requested_date + timedelta(days=day_offset)
    departure_at = combine_local_date_time(resolved_date, offer.departure)
    current_time = now_local()
    if departure_at is not None and departure_at <= (current_time + timedelta(minutes=45)):
        return None

    available_seats = offer.available_seats or 20
    lead_days = max((resolved_date - current_time.date()).days, 0)
    if lead_days == 0:
        available_seats = max(passengers, available_seats - 4)
    elif lead_days <= 2:
        available_seats = max(passengers, available_seats - 2)

    if available_seats < passengers:
        return None

    price_multiplier = 1.0
    if lead_days == 0:
        price_multiplier += 0.15
    elif lead_days <= 2:
        price_multiplier += 0.08
    if resolved_date.weekday() >= 4:
        price_multiplier += 0.05

    adjusted_payload = _model_dump(offer)
    adjusted_payload["departure_date"] = resolved_date.isoformat()
    adjusted_payload["available_seats"] = available_seats
    adjusted_payload["price"] = round(offer.price * price_multiplier / 1000) * 1000
    return TicketOffer(**adjusted_payload)


ATTRACTION_TICKET_SUGGESTIONS: dict[str, list[dict[str, Any]]] = {
    "ha noi": [
        {
            "name": "Hoàng thành Thăng Long",
            "provider": "Di sản Hà Nội Pass",
            "price": 120_000,
            "seat_class": "Vé tham quan di sản",
        },
        {
            "name": "Văn Miếu - Quốc Tử Giám",
            "provider": "Hanoi Culture Pass",
            "price": 90_000,
            "seat_class": "Vé tham quan văn hóa",
        },
        {
            "name": "Bảo tàng Dân tộc học Việt Nam",
            "provider": "Hanoi Museum Pass",
            "price": 80_000,
            "seat_class": "Vé bảo tàng",
        },
    ],
    "ho chi minh": [
        {
            "name": "Công viên văn hóa Đầm Sen",
            "provider": "Saigon Family Pass",
            "price": 260_000,
            "seat_class": "Vé vui chơi trọn gói",
        },
        {
            "name": "Suối Tiên Theme Park",
            "provider": "Saigon Attraction Pass",
            "price": 320_000,
            "seat_class": "Vé khu vui chơi",
        },
        {
            "name": "Bảo tàng Chứng tích Chiến tranh",
            "provider": "Saigon Museum Pass",
            "price": 80_000,
            "seat_class": "Vé tham quan",
        },
    ],
    "da nang": [
        {
            "name": "Bà Nà Hills",
            "provider": "Sun World Ba Na Hills",
            "price": 900_000,
            "seat_class": "Combo cáp treo + tham quan",
        },
        {
            "name": "Asia Park Đà Nẵng",
            "provider": "Da Nang Fun Pass",
            "price": 250_000,
            "seat_class": "Vé công viên giải trí",
        },
        {
            "name": "Ngũ Hành Sơn",
            "provider": "Da Nang Heritage Pass",
            "price": 120_000,
            "seat_class": "Vé danh thắng",
        },
    ],
    "hoi an": [
        {
            "name": "Ký ức Hội An",
            "provider": "Hoi An Memories",
            "price": 620_000,
            "seat_class": "Vé biểu diễn",
        },
        {
            "name": "Phố cổ Hội An",
            "provider": "Hoi An Heritage Pass",
            "price": 120_000,
            "seat_class": "Vé tham quan phố cổ",
        },
        {
            "name": "Rừng dừa Bảy Mẫu",
            "provider": "Hoi An Eco Tour",
            "price": 180_000,
            "seat_class": "Vé thuyền thúng",
        },
    ],
    "ha long": [
        {
            "name": "Sun World Hạ Long",
            "provider": "Sun World Ha Long",
            "price": 650_000,
            "seat_class": "Combo Dragon Park",
        },
        {
            "name": "Cáp treo Nữ Hoàng",
            "provider": "Ha Long Cable Pass",
            "price": 380_000,
            "seat_class": "Vé cáp treo",
        },
        {
            "name": "Du thuyền vịnh Hạ Long",
            "provider": "Ha Long Bay Cruise",
            "price": 750_000,
            "seat_class": "Vé tham quan vịnh",
        },
    ],
    "phu quoc": [
        {
            "name": "VinWonders Phú Quốc",
            "provider": "VinWonders Phú Quốc",
            "price": 950_000,
            "seat_class": "All-in-one pass",
        },
        {
            "name": "Safari Phú Quốc",
            "provider": "Vinpearl Safari",
            "price": 650_000,
            "seat_class": "Vé safari",
        },
        {
            "name": "Cáp treo Hòn Thơm",
            "provider": "Sun World Hon Thom",
            "price": 600_000,
            "seat_class": "Vé cáp treo + công viên nước",
        },
    ],
    "nha trang": [
        {
            "name": "VinWonders Nha Trang",
            "provider": "VinWonders Nha Trang",
            "price": 880_000,
            "seat_class": "Vé khu vui chơi",
        },
        {
            "name": "Tour đảo Hòn Mun",
            "provider": "Nha Trang Island Pass",
            "price": 520_000,
            "seat_class": "Vé tour biển đảo",
        },
        {
            "name": "Tháp Bà Ponagar",
            "provider": "Nha Trang Heritage Pass",
            "price": 80_000,
            "seat_class": "Vé tham quan",
        },
    ],
    "da lat": [
        {
            "name": "Thung lũng Tình Yêu",
            "provider": "Da Lat Attraction Pass",
            "price": 250_000,
            "seat_class": "Vé tham quan",
        },
        {
            "name": "Đồi chè Cầu Đất",
            "provider": "Da Lat Experience",
            "price": 180_000,
            "seat_class": "Vé trải nghiệm",
        },
        {
            "name": "Datanla Alpine Coaster",
            "provider": "Datanla Adventure Pass",
            "price": 280_000,
            "seat_class": "Vé máng trượt",
        },
    ],
}


def _attraction_ticket_offers(
    *,
    destination: str,
    requested_date: date,
    passengers: int,
) -> list[TicketOffer]:
    destination_label = destination.strip() or "Điểm đến"
    destination_aliases = _expand_location_aliases(destination_label)
    matched_key = next(
        (
            key
            for key in ATTRACTION_TICKET_SUGGESTIONS
            if key in destination_aliases
            or any(key in alias or alias in key for alias in destination_aliases)
        ),
        None,
    )
    rows = ATTRACTION_TICKET_SUGGESTIONS.get(matched_key or "", [])
    if not rows:
        destination_text = _normalize_text(destination_label)
        place_matches = [
            place
            for place in _runtime_place_pool()
            if (
                place.ticket_price > 0
                and (
                    "entertainment" in place.categories
                    or destination_text in _normalize_text(place.name)
                    or destination_text in _normalize_text(place.province)
                    or any(alias in _search_corpus(place) for alias in destination_aliases)
                )
            )
        ][:3]
        rows = [
            {
                "name": place.name,
                "provider": "Touch Attraction Pass",
                "price": max(place.ticket_price, 120_000),
                "seat_class": "Vé tham quan",
            }
            for place in place_matches
        ]

    offers: list[TicketOffer] = []
    for index, row in enumerate(rows[:3]):
        departure_hour = 9 + index * 2
        price = float(row["price"]) * max(passengers, 1)
        attraction_name = str(row["name"])
        offers.append(
            TicketOffer(
                provider=str(row["provider"]),
                vehicle_type="entertainment",
                origin=destination_label,
                destination=attraction_name,
                departure=f"{departure_hour:02d}:00",
                departure_date=requested_date.isoformat(),
                arrival="18:00",
                duration="1 ngày",
                seat_class=str(row["seat_class"]),
                available_seats=max(10, 80 - max(passengers, 1)),
                operator_note=f"Gợi ý vé vui chơi theo điểm đến {destination_label}.",
                price=round(price / 1000) * 1000,
                booking_url=(
                    "https://booking.demo.touchvietnam.vn/attraction/"
                    f"{_normalize_text(attraction_name).replace(' ', '-')}"
                ),
            )
        )
    return offers


def _fallback_ticket_offers(
    *,
    origin: str,
    destination: str,
    vehicle_type: str | None,
    requested_date: date,
    passengers: int,
) -> list[TicketOffer]:
    origin_label = origin.strip() or "Điểm khởi hành"
    destination_label = destination.strip() or "Điểm đến"
    vehicle_types = [vehicle_type] if vehicle_type else ["plane", "train", "bus", "entertainment"]
    templates = {
        "plane": {
            "provider": "Touch Flight Connect",
            "departure": "09:20",
            "arrival": "11:30",
            "duration": "2h 10m",
            "seat_class": "Economy",
            "note": "Chuyến bay demo từ cổng kết nối nhà cung cấp.",
            "price": 1_650_000,
            "path": "flights",
        },
        "train": {
            "provider": "Đường sắt Việt Nam",
            "departure": "19:30",
            "arrival": "08:45",
            "duration": "13h 15m",
            "seat_class": "Giường nằm điều hòa",
            "note": "Chuyến tàu demo phù hợp hành trình liên tỉnh và đường dài.",
            "price": 820_000,
            "path": "trains",
        },
        "bus": {
            "provider": "Touch Bus Partner",
            "departure": "21:00",
            "arrival": "06:30",
            "duration": "9h 30m",
            "seat_class": "Limousine giường nằm",
            "note": "Chuyến xe demo linh hoạt cho tuyến tỉnh và điểm đến chưa có sân bay.",
            "price": 420_000,
            "path": "bus",
        },
        "entertainment": {
            "provider": "Touch Attraction Pass",
            "departure": "09:00",
            "arrival": "18:00",
            "duration": "1 ngày",
            "seat_class": "Vé tham quan tiêu chuẩn",
            "note": "Vé demo cho khu vui chơi, bảo tàng, cáp treo hoặc hoạt động trải nghiệm tại điểm đến.",
            "price": 350_000,
            "path": "attraction",
        },
    }
    offers: list[TicketOffer] = []
    for item in vehicle_types:
        if item not in templates:
            continue
        if item == "entertainment":
            attraction_offers = _attraction_ticket_offers(
                destination=destination_label,
                requested_date=requested_date,
                passengers=passengers,
            )
            if attraction_offers:
                offers.extend(attraction_offers)
                continue
        template = templates[item]
        offer_origin = destination_label if item == "entertainment" else origin_label
        price = float(template["price"]) * max(passengers, 1)
        offers.append(
            TicketOffer(
                provider=str(template["provider"]),
                vehicle_type=item,
                origin=offer_origin,
                destination=destination_label,
                departure=str(template["departure"]),
                departure_date=requested_date.isoformat(),
                arrival=str(template["arrival"]),
                duration=str(template["duration"]),
                seat_class=str(template["seat_class"]),
                available_seats=max(8, 24 - max(passengers, 1)),
                operator_note=str(template["note"]),
                price=round(price / 1000) * 1000,
                booking_url=(
                    "https://booking.demo.touchvietnam.vn/"
                    f"{template['path']}/fallback-{_normalize_text(origin_label).replace(' ', '-')}-"
                    f"{_normalize_text(destination_label).replace(' ', '-')}"
                ),
            )
        )
    return offers


def search_tickets(
    origin: str,
    destination: str,
    vehicle_type: str | None = None,
    departure_date: str | None = None,
    passengers: int = 1,
    lang: str = DEFAULT_LANGUAGE,
) -> list[TicketOffer]:
    external_offers = fetch_external_ticket_offers(
        origin=origin,
        destination=destination,
        vehicle_type=vehicle_type,
        departure_date=departure_date,
        passengers=passengers,
        lang=lang,
    )
    if external_offers:
        return external_offers

    origin_aliases = _expand_location_aliases(origin)
    destination_aliases = _expand_location_aliases(destination)
    requested_date = _resolve_ticket_date(departure_date)
    if vehicle_type == "entertainment":
        return [
            translate_ticket_offer(offer, lang)
            for offer in _attraction_ticket_offers(
                destination=destination,
                requested_date=requested_date,
                passengers=passengers,
            )
        ]

    canonical_offers: list[TicketOffer] = []
    for offer in TICKET_OFFERS:
        variants = [offer, translate_ticket_offer(offer, "en"), translate_ticket_offer(offer, "ko")]
        searchable = {
            (_normalize_text(item.origin), _normalize_text(item.destination)) for item in variants
        }
        matched = any(
            any(alias in origin_text or origin_text in alias for alias in origin_aliases)
            and any(
                alias in destination_text or destination_text in alias
                for alias in destination_aliases
            )
            for origin_text, destination_text in searchable
        )
        if matched:
            if vehicle_type and offer.vehicle_type != vehicle_type:
                continue
            canonical_offers.append(offer)

    if not canonical_offers:
        return [
            translate_ticket_offer(offer, lang)
            for offer in _fallback_ticket_offers(
                origin=origin,
                destination=destination,
                vehicle_type=vehicle_type,
                requested_date=requested_date,
                passengers=passengers,
            )
        ]

    anchor_date = min(
        (
            parse_local_date(item.departure_date)
            for item in canonical_offers
            if parse_local_date(item.departure_date)
        ),
        default=requested_date,
    )
    offers: list[TicketOffer] = []
    for offer in canonical_offers:
        materialized = _materialize_ticket_offer(
            offer=offer,
            requested_date=requested_date,
            anchor_date=anchor_date,
            passengers=max(passengers, 1),
        )
        if materialized is None:
            continue
        offers.append(translate_ticket_offer(materialized, lang))

    return sorted(
        offers,
        key=lambda item: (
            item.departure_date or "",
            item.departure,
            item.price,
        ),
    )


def generate_itinerary(request: ItineraryRequest, lang: str = DEFAULT_LANGUAGE) -> ItineraryPlan:
    language = resolve_language(lang)
    active_places = _runtime_place_pool()
    candidates = active_places
    if request.region:
        candidates = [place for place in candidates if place.region == request.region]
    if request.destination:
        destination_lower = _normalize_text(request.destination)
        specific = [
            place
            for place in active_places
            if any(destination_lower in token for token in _search_corpus(place))
        ]
        if specific:
            primary_place = specific[0]
            related_places = [
                place
                for place in active_places
                if place.id != primary_place.id
                and (
                    place.province == primary_place.province
                    or (
                        place.region == primary_place.region
                        and _haversine_km(
                            primary_place.coordinate.lat,
                            primary_place.coordinate.lng,
                            place.coordinate.lat,
                            place.coordinate.lng,
                        )
                        <= 90
                    )
                )
            ]
            candidates = specific + related_places
    if request.interests:
        normalized_interests = {
            INTEREST_ALIASES.get(_normalize_text(interest), _normalize_text(interest))
            for interest in request.interests
            if interest.strip()
        }
        prioritized = [
            place
            for place in candidates
            if any(category in normalized_interests for category in place.categories)
        ]
        if prioritized:
            candidates = prioritized
    if not candidates:
        candidates = sorted(
            active_places,
            key=lambda place: (place.must_go_score, place.rating),
            reverse=True,
        )[: max(request.days, 1)]
    selected = sorted(
        candidates,
        key=lambda place: (place.must_go_score, place.rating),
        reverse=True,
    )
    if not selected:
        selected = active_places[:1]

    def rotate_places(days: int) -> list[Place]:
        unique_places: list[Place] = []
        seen_ids: set[str] = set()
        for place in selected:
            if place.id in seen_ids:
                continue
            unique_places.append(place)
            seen_ids.add(place.id)
        if not unique_places:
            unique_places = [active_places[0]]

        sequence: list[Place] = []
        index = 0
        while len(sequence) < days:
            sequence.append(unique_places[index % len(unique_places)])
            index += 1
        return sequence

    def highlight_window(place: Place, day_index: int) -> tuple[str, str]:
        highlights = place.highlights or [place.name]
        start = day_index % len(highlights)
        ordered = highlights[start:] + highlights[:start]
        first = ordered[0]
        second = ordered[1] if len(ordered) > 1 else ordered[0]
        summary = ", ".join([first, second] if first != second else [first])
        return first, summary

    def estimate_day_cost(place: Place, day_index: int) -> float:
        daily_budget = request.budget / request.days if request.days else request.budget
        group_factor = 0.68 + min(request.travelers, 4) * 0.06
        base_cost = (place.avg_spend * group_factor) + place.ticket_price
        if request.days > 1 and day_index == 0:
            base_cost *= 0.92
        elif request.days > 1 and day_index == request.days - 1:
            base_cost *= 0.88
        capped_cost = max(350_000, min(daily_budget, base_cost))
        return round(capped_cost / 1000) * 1000

    rotated_places = rotate_places(request.days)
    itinerary_days: list[ItineraryDay] = []
    for index, place in enumerate(rotated_places):
        localized = translate_place(place, language)
        highlight_focus, highlight_text = highlight_window(localized, index)
        if request.days == 1 or index == 0:
            morning = text(
                language,
                "itinerary_morning_arrival",
                departure_city=request.departure_city,
                province=localized.province,
            )
            afternoon = text(
                language,
                "itinerary_afternoon_signature",
                highlights=highlight_text,
                place=localized.name,
            )
            evening = text(language, "itinerary_evening_relax")
        elif index == request.days - 1:
            morning = text(
                language,
                "itinerary_morning_departure",
                place=localized.name,
                focus=highlight_focus,
                province=localized.province,
            )
            afternoon = text(
                language,
                "itinerary_afternoon_wrap",
                highlights=highlight_text,
                place=localized.name,
            )
            evening = text(language, "itinerary_evening_wrapup")
        else:
            morning = text(
                language,
                "itinerary_morning_explore",
                place=localized.name,
                focus=highlight_focus,
                province=localized.province,
            )
            afternoon = text(
                language,
                "itinerary_afternoon",
                highlights=highlight_text,
                place=localized.name,
            )
            evening = text(language, "itinerary_evening")
        itinerary_days.append(
            ItineraryDay(
                day=index + 1,
                title=text(language, "itinerary_day_title", day=index + 1, place=localized.name),
                morning=morning,
                afternoon=afternoon,
                evening=evening,
                estimated_cost=estimate_day_cost(place, index),
            )
        )
    total_cost = sum(day.estimated_cost for day in itinerary_days)
    destination_name = request.destination or translate_place(rotated_places[0], language).name
    interest_label = (
        ", ".join(request.interests)
        if request.interests
        else text(language, "itinerary_overview_default")
    )
    base_plan = ItineraryPlan(
        destination=destination_name,
        overview=text(
            language,
            "itinerary_overview",
            days=request.days,
            travelers=request.travelers,
            interests=interest_label,
        ),
        total_estimated_cost=total_cost,
        days=itinerary_days,
        travel_tips=[
            text(language, "travel_tip_1"),
            text(language, "travel_tip_2"),
            text(language, "travel_tip_3"),
        ],
    )
    if not is_openai_planner_available():
        return base_plan

    place_context = []
    for place in rotated_places:
        localized_place = translate_place(place, language)
        place_context.append(
            {
                "name": localized_place.name,
                "province": localized_place.province,
                "description": localized_place.description,
                "categories": list(localized_place.categories),
                "highlights": localized_place.highlights[:3],
            }
        )
    try:
        return enhance_itinerary_with_openai(
            request=request,
            base_plan=base_plan,
            place_context=place_context,
            language=language,
        )
    except Exception:
        logger.exception("OpenAI itinerary generation failed; using the smart local planner.")
        return base_plan


def estimate_budget(
    request: BudgetEstimateRequest, lang: str = DEFAULT_LANGUAGE
) -> BudgetBreakdown:
    transport_base = {
        "plane": 1_600_000,
        "train": 900_000,
        "bus": 600_000,
        "car": 750_000,
    }
    stay_per_night = {
        "budget": 350_000,
        "midrange": 700_000,
        "premium": 1_400_000,
    }
    regional_factor = {"north": 1.0, "central": 0.95, "south": 1.05}
    factor = regional_factor.get(request.region, 1.0)
    transport = transport_base[request.transport_mode] * request.travelers * factor
    room_count = max(1, (request.travelers + 1) // 2)
    stay = (
        stay_per_night[request.accommodation_level] * max(1, request.days - 1) * room_count * factor
    )
    food = 250_000 * request.days * request.travelers * factor
    tickets = (
        (280_000 * request.days * request.travelers * factor) if request.include_tickets else 0
    )
    emergency = round((transport + stay + food + tickets) * 0.1, 0)
    total = round(transport + stay + food + tickets + emergency, 0)
    return BudgetBreakdown(
        transport=round(transport, 0),
        stay=round(stay, 0),
        food=round(food, 0),
        attraction_tickets=round(tickets, 0),
        emergency_fund=emergency,
        total=total,
        note=text(lang, "budget_note"),
    )


def save_trip_plan(
    *,
    user_email: str,
    itinerary_request: ItineraryRequest,
    itinerary: ItineraryPlan,
    budget: BudgetBreakdown,
    lang: str = DEFAULT_LANGUAGE,
) -> int:
    language = resolve_language(lang)
    title = text(
        language,
        "trip_title_format",
        destination=itinerary.destination,
        days=itinerary_request.days,
    )
    return save_trip(
        user_email=user_email,
        title=title,
        departure_city=itinerary_request.departure_city,
        destination=itinerary.destination,
        region=itinerary_request.region,
        days=itinerary_request.days,
        travelers=itinerary_request.travelers,
        budget_total=itinerary_request.budget,
        itinerary_total=itinerary.total_estimated_cost,
        itinerary_data=_model_dump(itinerary),
        budget_data=_model_dump(budget),
    )


def get_user_saved_trips(user_email: str) -> list[dict[str, Any]]:
    trips = list_saved_trips(user_email)
    return trips


def get_user_trip(user_email: str, trip_id: int) -> dict[str, Any] | None:
    return get_saved_trip(user_email, trip_id)


def add_group_expense(
    *,
    user_email: str,
    trip_id: int,
    title: str,
    category: str,
    paid_by: str,
    split_members: list[str],
    amount: float,
    note: str = "",
) -> int:
    normalized_members: list[str] = []
    seen_members: set[str] = set()
    for raw_member in split_members:
        member = raw_member.strip()
        member_key = member.casefold()
        if not member or member_key in seen_members:
            continue
        seen_members.add(member_key)
        normalized_members.append(member)
    if not normalized_members:
        normalized_members = [paid_by.strip()]
    return create_expense_item(
        user_email=user_email,
        trip_id=trip_id,
        title=title,
        category=category,
        paid_by=paid_by,
        split_members=normalized_members,
        amount=amount,
        note=note,
    )


def get_group_expense_items(
    user_email: str,
    trip_id: int | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> list[dict[str, Any]]:
    language = resolve_language(lang)
    items = list_expense_items(user_email, trip_id=trip_id)
    category_key_map = {
        "transport": "expense_category_transport",
        "stay": "expense_category_stay",
        "food": "expense_category_food",
        "ticket": "expense_category_ticket",
        "shopping": "expense_category_shopping",
        "emergency": "expense_category_emergency",
        "other": "expense_category_other",
    }
    for item in items:
        key = category_key_map.get(item["category"])
        item["category_label"] = text(language, key) if key else item["category"].title()
    return items


def get_group_expense_summary(
    user_email: str,
    trip_id: int | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    language = resolve_language(lang)
    items = get_group_expense_items(user_email, trip_id=trip_id, lang=language)
    total = round(sum(item["amount"] for item in items), 0)
    by_payer: dict[str, float] = {}
    by_category: dict[str, float] = {}
    balances: dict[str, float] = {}
    for item in items:
        by_payer[item["paid_by"]] = by_payer.get(item["paid_by"], 0.0) + item["amount"]
        label = item["category_label"]
        by_category[label] = by_category.get(label, 0.0) + item["amount"]
        members = item["split_members"] or [item["paid_by"]]
        share = item["amount"] / len(members)
        balances[item["paid_by"]] = balances.get(item["paid_by"], 0.0) + item["amount"]
        for member in members:
            balances[member] = balances.get(member, 0.0) - share

    payer_rows = [
        {"name": name, "amount": round(amount, 0)}
        for name, amount in sorted(by_payer.items(), key=lambda item: item[1], reverse=True)
    ]
    category_rows = [
        {"name": name, "amount": round(amount, 0)}
        for name, amount in sorted(by_category.items(), key=lambda item: item[1], reverse=True)
    ]
    balance_rows = [
        {"name": name, "amount": round(amount, 0)}
        for name, amount in sorted(balances.items(), key=lambda item: item[1], reverse=True)
        if abs(amount) >= 1
    ]
    creditors = [[name, round(amount, 2)] for name, amount in balances.items() if amount >= 1]
    debtors = [[name, round(-amount, 2)] for name, amount in balances.items() if amount <= -1]
    creditors.sort(key=lambda item: item[1], reverse=True)
    debtors.sort(key=lambda item: item[1], reverse=True)
    settlements: list[dict[str, Any]] = []
    creditor_index = 0
    debtor_index = 0
    while creditor_index < len(creditors) and debtor_index < len(debtors):
        creditor_name, credit = creditors[creditor_index]
        debtor_name, debt = debtors[debtor_index]
        payment = min(credit, debt)
        if payment >= 1:
            settlements.append(
                {
                    "from_name": debtor_name,
                    "to_name": creditor_name,
                    "amount": round(payment, 0),
                }
            )
        creditors[creditor_index][1] = round(credit - payment, 2)
        debtors[debtor_index][1] = round(debt - payment, 2)
        if creditors[creditor_index][1] < 1:
            creditor_index += 1
        if debtors[debtor_index][1] < 1:
            debtor_index += 1
    return {
        "total": total,
        "count": len(items),
        "by_payer": payer_rows,
        "by_category": category_rows,
        "balances": balance_rows,
        "settlements": settlements,
        "saved_trip_count": count_saved_trips(user_email),
    }


def get_ticket_vehicle_options(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    language = resolve_language(lang)
    return [
        {"code": "", "label": text(language, "filter_all")},
        {"code": "plane", "label": text(language, "transport_plane")},
        {"code": "train", "label": text(language, "transport_train")},
        {"code": "bus", "label": text(language, "transport_bus")},
        {"code": "entertainment", "label": text(language, "tickets_vehicle_entertainment")},
    ]


def _booking_reference() -> str:
    return f"TVN-{uuid4().hex[:8].upper()}"


def create_ticket_reservation(
    *,
    user_email: str,
    provider: str,
    vehicle_type: str,
    origin: str,
    destination: str,
    departure_date: str,
    departure_time: str,
    arrival_time: str,
    seat_class: str,
    amount: float,
    contact_name: str,
    contact_email: str,
    contact_phone: str,
) -> dict[str, Any]:
    reference = _booking_reference()
    booking_id = create_ticket_booking(
        booking_reference=reference,
        user_email=user_email,
        provider=provider,
        vehicle_type=vehicle_type,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        departure_time=departure_time,
        arrival_time=arrival_time,
        seat_class=seat_class,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        amount=amount,
        status="reserved",
    )
    return {
        "id": booking_id,
        "booking_reference": reference,
        "status": "reserved",
    }


def get_user_ticket_bookings(
    user_email: str,
    lang: str = DEFAULT_LANGUAGE,
) -> list[dict[str, Any]]:
    language = resolve_language(lang)
    rows = list_ticket_bookings(user_email)
    for row in rows:
        row["vehicle_label"] = next(
            (
                item["label"]
                for item in get_ticket_vehicle_options(language)
                if item["code"] == row["vehicle_type"]
            ),
            row["vehicle_type"].title(),
        )
        row["status_label"] = text(language, f"booking_status_{row['status']}")
    return rows


def register_user(request: UserRegisterRequest, lang: str = DEFAULT_LANGUAGE) -> AuthResponse:
    email = request.email.lower()
    if find_user_by_email(email) is not None:
        return AuthResponse(message=text(lang, "auth_email_exists"))
    if get_settings().is_admin_email(email):
        return AuthResponse(message=text(lang, "auth_email_exists"))
    create_user(full_name=request.full_name, email=email, password=request.password)
    token = create_auth_token(email)
    return AuthResponse(
        message=text(lang, "auth_register_success"),
        token=token,
        access_token=token,
        expires_in=AUTH_TOKEN_MAX_AGE_SECONDS,
        full_name=request.full_name,
        email=email,
    )


def login_user(request: UserLoginRequest, lang: str = DEFAULT_LANGUAGE) -> AuthResponse:
    user = verify_user(request.email.lower(), request.password)
    if user is None:
        return AuthResponse(message=text(lang, "auth_login_invalid"))
    token = create_auth_token(user["email"])
    return AuthResponse(
        message=text(lang, "auth_login_success"),
        token=token,
        access_token=token,
        expires_in=AUTH_TOKEN_MAX_AGE_SECONDS,
        full_name=user["full_name"],
        email=user["email"],
    )


def chat_support(request: ChatRequest) -> ChatResponse:
    language = resolve_language(request.language)
    question = _normalize_text(request.question)
    matched_place = _match_place_from_question(request.question)
    if any(keyword in question for keyword in ("weather", "thoi tiet", "날씨")):
        place = matched_place or max(_runtime_place_pool(), key=lambda item: item.must_go_score)
        forecast = get_weather(place.id, language)
        return ChatResponse(
            answer=text(
                language,
                "chat_weather_answer",
                destination=forecast.destination,
                condition=forecast.condition.lower(),
                temp=forecast.temperature_c,
                advice=forecast.advice,
            ),
            suggested_actions=[
                text(language, "chat_action_detail_weather"),
                text(language, "chat_action_update_itinerary"),
                text(language, "chat_action_download_offline"),
            ],
        )
    if any(
        keyword in question for keyword in ("lo trinh", "itinerary", "ke hoach", "일정", "계획")
    ):
        sample_plan = generate_itinerary(
            ItineraryRequest(
                departure_city=text(language, "default_departure_city"),
                destination=matched_place.name if matched_place else "Hội An",
                days=3,
                budget=4_500_000,
                travelers=2,
                interests=["culture", "food"],
            ),
            language,
        )
        return ChatResponse(
            answer=text(
                language,
                "chat_itinerary_answer",
                days=len(sample_plan.days),
                destination=sample_plan.destination,
                cost=_format_currency_number(sample_plan.total_estimated_cost),
            ),
            suggested_actions=[
                text(language, "chat_action_create_plan"),
                text(language, "chat_action_budget"),
                text(language, "chat_action_ticket"),
            ],
        )
    if any(keyword in question for keyword in ("chi phi", "budget", "비용", "예산")):
        estimate = estimate_budget(BudgetEstimateRequest(), language)
        return ChatResponse(
            answer=text(
                language,
                "chat_budget_answer",
                total=_format_currency_number(estimate.total),
            ),
            suggested_actions=[
                text(language, "chat_action_open_budget"),
                text(language, "chat_action_split_budget"),
                text(language, "chat_action_booking"),
            ],
        )
    return ChatResponse(
        answer=text(language, "chat_default_answer"),
        suggested_actions=[
            text(language, "chat_action_explore"),
            text(language, "chat_action_weather"),
            text(language, "chat_action_itinerary"),
        ],
    )


def get_dashboard_summary(lang: str = DEFAULT_LANGUAGE) -> DashboardSummary:
    language = resolve_language(lang)
    active_places = _active_places()
    active_place_map = {place.id: place for place in active_places}
    monthly_visits = count_page_views(30)
    unique_visitors = count_unique_visitors(30)
    returning_visitors = count_returning_visitors(30)
    active_users = count_users()
    total_bookings = count_ticket_bookings()
    booking_revenue = sum_ticket_booking_revenue()
    retention_value = 0
    if unique_visitors > 0:
        retention_value = round((returning_visitors / unique_visitors) * 100)
    dashboard_live_labels = {
        "vi": {
            "period_30d": "30 ngày gần đây",
            "users_live": "Tài khoản có thể đăng nhập",
            "places_live": "Đang hiển thị trên website",
            "bookings_live": "Giữ chỗ trong hệ thống",
            "revenue_live": "Doanh thu từ đơn không bị hủy",
            "retention_live": "Khách quay lại / 30 ngày",
        },
        "en": {
            "period_30d": "last 30 days",
            "users_live": "accounts able to sign in",
            "places_live": "currently published",
            "bookings_live": "reservations in system",
            "revenue_live": "revenue from non-cancelled bookings",
            "retention_live": "return visitors / 30 days",
        },
        "ko": {
            "period_30d": "최근 30일",
            "users_live": "로그인 가능한 계정",
            "places_live": "현재 공개된 여행지",
            "bookings_live": "시스템 예약 건수",
            "revenue_live": "취소되지 않은 예약 매출",
            "retention_live": "30일 재방문 비율",
        },
    }
    live_label = dashboard_live_labels.get(language, dashboard_live_labels["en"])
    top_places = [
        translate_place(
            active_place_map[place_id],
            language,
        ).name
        for place_id, _count in sorted(
            PLACE_VIEWS.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if place_id in active_place_map
    ][:5]
    return DashboardSummary(
        metrics=[
            DashboardMetric(
                name=text(language, "dashboard_metric_visits"),
                value=f"{monthly_visits:,}",
                trend=live_label["period_30d"],
            ),
            DashboardMetric(
                name=text(language, "dashboard_metric_users"),
                value=f"{active_users:,}",
                trend=live_label["users_live"],
            ),
            DashboardMetric(
                name=text(language, "dashboard_metric_places"),
                value=str(len(active_places)),
                trend=live_label["places_live"],
            ),
            DashboardMetric(
                name=text(language, "dashboard_metric_bookings"),
                value=f"{total_bookings:,}",
                trend=live_label["bookings_live"],
            ),
            DashboardMetric(
                name=text(language, "dashboard_metric_revenue"),
                value=f"{_format_currency_number(booking_revenue)} ₫",
                trend=live_label["revenue_live"],
            ),
            DashboardMetric(
                name=text(language, "dashboard_metric_retention"),
                value=f"{retention_value}%",
                trend=live_label["retention_live"],
            ),
        ],
        top_places=top_places,
        recommended_upgrades=[
            text(language, "recommended_upgrade_1"),
            text(language, "recommended_upgrade_2"),
            text(language, "recommended_upgrade_3"),
        ],
    )


def get_admin_analytics_snapshot(lang: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    language = resolve_language(lang)
    monthly_visits = count_page_views(30)
    weekly_visits = count_page_views(7)
    unique_visitors = count_unique_visitors(30)
    returning_visitors = count_returning_visitors(30)
    repeat_rate = 0
    if unique_visitors > 0:
        repeat_rate = round((returning_visitors / unique_visitors) * 100)
    labels_by_language = {
        "vi": {
            "title": "Lượt truy cập thật",
            "intro": "Số liệu lấy từ nhật ký truy cập nội bộ của ứng dụng, dùng để theo dõi hiệu quả vận hành.",
            "visits_30d": "Tổng truy cập 30 ngày",
            "visits_7d": "Tổng truy cập 7 ngày",
            "unique_visitors": "Khách truy cập duy nhất",
            "repeat_rate": "Tỉ lệ quay lại",
            "top_pages": "Trang được xem nhiều",
            "daily_views": "Lượt xem theo ngày",
            "export": "Tải CSV analytics",
        },
        "en": {
            "title": "Live analytics",
            "intro": "These numbers come from the application's local page-view log and help administrators monitor real usage.",
            "visits_30d": "Visits in 30 days",
            "visits_7d": "Visits in 7 days",
            "unique_visitors": "Unique visitors",
            "repeat_rate": "Repeat rate",
            "top_pages": "Top pages",
            "daily_views": "Daily views",
            "export": "Download analytics CSV",
        },
        "ko": {
            "title": "실시간 분석",
            "intro": "이 수치는 애플리케이션 내부 방문 로그에서 집계되며 실제 사용 현황을 관리하는 데 사용됩니다.",
            "visits_30d": "30일 방문 수",
            "visits_7d": "7일 방문 수",
            "unique_visitors": "순 방문자",
            "repeat_rate": "재방문율",
            "top_pages": "인기 페이지",
            "daily_views": "일별 조회 수",
            "export": "CSV 내려받기",
        },
    }
    return {
        "headline": {
            "total_visits_30d": monthly_visits,
            "weekly_visits": weekly_visits,
            "unique_visitors_30d": unique_visitors,
            "repeat_rate": repeat_rate,
        },
        "top_pages": list_top_page_views(limit=6, days=30),
        "daily_views": list_daily_page_views(days=7),
        "labels": {
            **labels_by_language.get(language, labels_by_language["en"]),
        },
    }


def get_product_status(user_email: str | None = None) -> dict[str, Any]:
    saved_trip_count = count_saved_trips(user_email) if user_email else 0
    return {
        "users": count_users(),
        "places": len(_active_places()),
        "ticket_offers": len(TICKET_OFFERS),
        "bookings": count_ticket_bookings(user_email),
        "saved_trips": saved_trip_count,
        "page_views_30d": count_page_views(30),
    }


def _pick_recommendation_text(record: dict[str, Any], language: str, field: str) -> str:
    preferred = (record.get(f"{field}_{language}") or "").strip()
    if preferred:
        return preferred
    for fallback_language in ("vi", "en", "ko"):
        fallback_value = (record.get(f"{field}_{fallback_language}") or "").strip()
        if fallback_value:
            return fallback_value
    return ""


def get_admin_recommendations(lang: str = DEFAULT_LANGUAGE) -> list[AdminRecommendation]:
    language = resolve_language(lang)
    rows = list_admin_recommendations(include_inactive=False)
    return [
        AdminRecommendation(
            id=row["id"],
            title=_pick_recommendation_text(row, language, "title"),
            detail=_pick_recommendation_text(row, language, "detail"),
            priority=row["priority"],
            is_active=row["is_active"],
            display_order=row["display_order"],
            title_vi=row["title_vi"],
            detail_vi=row["detail_vi"],
            title_en=row["title_en"],
            detail_en=row["detail_en"],
            title_ko=row["title_ko"],
            detail_ko=row["detail_ko"],
        )
        for row in rows
    ]


def get_supported_languages() -> list[dict[str, str]]:
    return get_language_options()


def get_ar_landmarks(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    external_items = fetch_external_ar_landmarks(lang=lang)
    if external_items is not None:
        return external_items
    return [translate_ar_item(item, lang) for item in AR_LANDMARKS]


def get_offline_map_packs(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    external_items = fetch_external_offline_map_packs(lang=lang)
    if external_items is not None:
        return external_items
    return [translate_offline_pack(item, lang) for item in OFFLINE_MAP_PACKS]


def get_site_content(lang: str = DEFAULT_LANGUAGE) -> dict[str, str]:
    content = _site_content_defaults(lang)
    for item in list_site_content_settings():
        content[item["key"]] = item["value"]
    return content


def save_site_content(
    values: dict[str, str],
    user_email: str | None,
) -> None:
    save_site_content_settings(values, updated_by=user_email)


def get_admin_recommendation_records(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, Any]]:
    language = resolve_language(lang)
    return [
        {
            "id": row["id"],
            "title": _pick_recommendation_text(row, language, "title"),
            "detail": _pick_recommendation_text(row, language, "detail"),
            "priority": row["priority"],
            "display_order": row["display_order"],
            "is_active": row["is_active"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
            "title_vi": row["title_vi"],
            "detail_vi": row["detail_vi"],
            "title_en": row["title_en"],
            "detail_en": row["detail_en"],
            "title_ko": row["title_ko"],
            "detail_ko": row["detail_ko"],
        }
        for row in list_admin_recommendations(include_inactive=True)
    ]


def get_admin_recommendation_record(
    recommendation_id: int,
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any] | None:
    language = resolve_language(lang)
    row = get_admin_recommendation(recommendation_id)
    if row is None:
        return None
    return {
        "id": row["id"],
        "title": _pick_recommendation_text(row, language, "title"),
        "detail": _pick_recommendation_text(row, language, "detail"),
        "priority": row["priority"],
        "display_order": row["display_order"],
        "is_active": row["is_active"],
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
        "title_vi": row["title_vi"],
        "detail_vi": row["detail_vi"],
        "title_en": row["title_en"],
        "detail_en": row["detail_en"],
        "title_ko": row["title_ko"],
        "detail_ko": row["detail_ko"],
    }


def save_admin_recommendation(
    *,
    user_email: str | None,
    recommendation_id: int | None,
    title_vi: str,
    detail_vi: str,
    title_en: str,
    detail_en: str,
    title_ko: str,
    detail_ko: str,
    priority: str,
    display_order: int,
    is_active: bool,
) -> int:
    priority_normalized = (priority or "medium").strip().lower()
    if priority_normalized not in {"high", "medium", "low"}:
        raise ValueError("invalid-priority")

    title_vi_clean = title_vi.strip()
    detail_vi_clean = detail_vi.strip()
    if not title_vi_clean or not detail_vi_clean:
        raise ValueError("missing-vi-content")

    return upsert_admin_recommendation(
        recommendation_id=recommendation_id,
        title_vi=title_vi_clean,
        detail_vi=detail_vi_clean,
        title_en=title_en.strip(),
        detail_en=detail_en.strip(),
        title_ko=title_ko.strip(),
        detail_ko=detail_ko.strip(),
        priority=priority_normalized,
        display_order=max(0, int(display_order)),
        is_active=is_active,
        updated_by=user_email,
    )


def set_admin_recommendation_visibility(
    recommendation_id: int,
    *,
    is_active: bool,
    user_email: str | None,
) -> bool:
    return set_admin_recommendation_active(
        recommendation_id,
        is_active=is_active,
        updated_by=user_email,
    )


def remove_admin_recommendation(recommendation_id: int) -> bool:
    return delete_admin_recommendation(recommendation_id)


def get_admin_recommendation_priority_options(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    language = resolve_language(lang)
    return [
        {"code": "high", "label": text(language, "priority_high")},
        {"code": "medium", "label": text(language, "priority_medium")},
        {"code": "low", "label": text(language, "priority_low")},
    ]


def get_admin_region_options(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    labels = get_region_labels(lang)
    return [
        {"code": "north", "label": labels["north"]},
        {"code": "central", "label": labels["central"]},
        {"code": "south", "label": labels["south"]},
    ]


def get_admin_category_options(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    labels = get_category_labels(lang)
    category_codes = [
        "mountain",
        "island",
        "beach",
        "spiritual",
        "culture",
        "food",
        "history",
        "entertainment",
    ]
    return [{"code": code, "label": labels[code]} for code in category_codes]


def get_admin_transport_options(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    language = resolve_language(lang)
    ship_label = {
        "vi": "Tàu biển",
        "en": "Ship",
        "ko": "Ship",
    }.get(language, "Ship")
    return [
        {"code": "plane", "label": text(language, "transport_plane")},
        {"code": "train", "label": text(language, "transport_train")},
        {"code": "bus", "label": text(language, "transport_bus")},
        {"code": "car", "label": text(language, "transport_car")},
        {"code": "ship", "label": ship_label},
        {"code": "entertainment", "label": text(language, "tickets_vehicle_entertainment")},
    ]


def get_admin_place_records(lang: str = DEFAULT_LANGUAGE) -> list[dict[str, Any]]:
    language = resolve_language(lang)
    source_labels = {
        "vi": {"builtin": "Dữ liệu mặc định", "custom": "Dữ liệu admin"},
        "en": {"builtin": "Built-in data", "custom": "Admin data"},
        "ko": {"builtin": "Built-in data", "custom": "Admin data"},
    }
    status_labels = {
        "vi": {True: "Đang hiển thị", False: "Đang ẩn"},
        "en": {True: "Visible", False: "Hidden"},
        "ko": {True: "Visible", False: "Hidden"},
    }
    records: list[dict[str, Any]] = []
    for item in _all_admin_place_records():
        localized = translate_place(item["place"], language)
        records.append(
            {
                "place": localized,
                "is_active": item["is_active"],
                "is_custom": item["is_custom"],
                "is_overridden": item["is_overridden"],
                "updated_by": item["updated_by"],
                "updated_at": item["updated_at"],
                "source_label": source_labels.get(language, source_labels["en"])[
                    "custom" if item["is_custom"] else "builtin"
                ],
                "status_label": status_labels.get(language, status_labels["en"])[item["is_active"]],
            }
        )
    return records


def get_admin_place_record(place_id: str, lang: str = DEFAULT_LANGUAGE) -> dict[str, Any] | None:
    for item in _all_admin_place_records():
        if item["place"].id != place_id:
            continue
        return {
            "place": item["place"],
            "is_active": item["is_active"],
            "is_custom": item["is_custom"],
            "is_overridden": item["is_overridden"],
            "updated_by": item["updated_by"],
            "updated_at": item["updated_at"],
        }
    return None


def _slugify_place_id(value: str) -> str:
    normalized = _normalize_text(value)
    cleaned = [char if char.isalnum() else "-" for char in normalized]
    collapsed = "".join(cleaned).strip("-")
    while "--" in collapsed:
        collapsed = collapsed.replace("--", "-")
    return collapsed or f"place-{uuid4().hex[:8]}"


def save_admin_place(
    *,
    user_email: str | None,
    place_id: str,
    name: str,
    region: str,
    province: str,
    categories: list[str],
    description: str,
    highlights_text: str,
    ticket_price: float,
    avg_spend: float,
    rating: float,
    must_go_score: int,
    lat: float,
    lng: float,
    nearby_services_text: str,
    transport_modes: list[str],
    image_hint: str,
) -> str:
    resolved_id = _slugify_place_id(place_id or name)
    place = Place(
        id=resolved_id,
        name=name.strip(),
        region=region,  # type: ignore[arg-type]
        province=normalize_province_name(province),
        categories=categories,  # type: ignore[arg-type]
        description=description.strip(),
        highlights=[item.strip() for item in highlights_text.split(",") if item.strip()],
        ticket_price=float(ticket_price),
        avg_spend=float(avg_spend),
        rating=float(rating),
        must_go_score=int(must_go_score),
        coordinate=Coordinate(lat=float(lat), lng=float(lng)),
        nearby_services=[item.strip() for item in nearby_services_text.split(",") if item.strip()],
        transport_modes=[item.strip() for item in transport_modes if item.strip()],
        image_hint=image_hint.strip() or "travel destination",
    )
    upsert_managed_place(
        place=place,
        is_active=True,
        updated_by=user_email,
    )
    return resolved_id


def set_admin_place_active(
    place_id: str,
    is_active: bool,
    user_email: str | None,
) -> bool:
    record = next(
        (item for item in _all_admin_place_records() if item["place"].id == place_id),
        None,
    )
    if record is None:
        return False
    upsert_managed_place(
        place=record["place"],
        is_active=is_active,
        updated_by=user_email,
    )
    return True
