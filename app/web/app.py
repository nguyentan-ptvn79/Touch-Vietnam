"""Flask application factory and web-facing routes for Touch! Việt Nam.

The routes stay in one module so this student project can be run and reviewed
without hidden framework wiring. Helpers are grouped by responsibility inside
``create_app`` and share the same request/session configuration.
"""

from __future__ import annotations

import csv
import hmac
import json
import logging
import os
import re
import secrets
import time
import unicodedata
from collections import defaultdict, deque
from datetime import timedelta
from io import BytesIO, StringIO
from urllib.parse import urlsplit
from uuid import uuid4

import qrcode
from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from pydantic import ValidationError

from app.shared.db import (
    add_chat_message,
    clear_chat_messages,
    ensure_chat_session,
    get_chat_messages,
    list_dashboard_block_visibility,
    record_page_view,
    save_dashboard_block_visibility,
)
from app.shared.i18n import (
    DEFAULT_LANGUAGE,
    get_category_labels,
    get_region_labels,
    resolve_language,
    text,
    translate_service_name,
)
from app.shared.integration_gateways import (
    get_integration_statuses,
    get_integration_summary,
    probe_integration,
    track_external_analytics_event,
)
from app.shared.logging_utils import configure_logging
from app.shared.media_utils import (
    get_place_image_asset,
    get_place_image_info,
    get_site_media_assets,
    image_conversion_available,
    remove_uploaded_place_image,
    remove_uploaded_site_image,
    save_uploaded_place_image,
    save_uploaded_site_image,
)
from app.shared.models import (
    BudgetEstimateRequest,
    ChatRequest,
    ChatResponse,
    ItineraryRequest,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.shared.openai_chat import generate_openai_chat_answer, is_openai_available
from app.shared.security_audit import record_security_event
from app.shared.services import (
    add_group_expense,
    chat_support,
    create_ticket_reservation,
    estimate_budget,
    generate_itinerary,
    get_admin_analytics_snapshot,
    get_admin_category_options,
    get_admin_place_record,
    get_admin_place_records,
    get_admin_recommendation_priority_options,
    get_admin_recommendation_record,
    get_admin_recommendation_records,
    get_admin_recommendations,
    get_admin_region_options,
    get_admin_transport_options,
    get_ar_landmarks,
    get_categories,
    get_dashboard_summary,
    get_featured_places,
    get_google_maps_embed_url,
    get_google_maps_view_url,
    get_group_expense_items,
    get_group_expense_summary,
    get_nearby_services,
    get_offline_map_packs,
    get_place,
    get_places,
    get_product_status,
    get_provinces_summary,
    get_regions_summary,
    get_site_content,
    get_supported_languages,
    get_ticket_vehicle_options,
    get_user_saved_trips,
    get_user_ticket_bookings,
    get_user_trip,
    get_weather,
    get_weather_batch,
    login_user,
    register_user,
    remove_admin_recommendation,
    save_admin_place,
    save_admin_recommendation,
    save_site_content,
    save_trip_plan,
    search_tickets,
    set_admin_place_active,
    set_admin_recommendation_visibility,
)
from app.shared.settings import get_settings, validate_production_settings
from app.shared.time_utils import (
    APP_TIMEZONE_NAME,
    format_local_date,
    format_local_datetime,
    now_local,
    to_local_iso,
)
from app.web.dashboard_layout import (
    build_dashboard_layout,
    filter_dashboard_layout,
    get_dashboard_blocks,
)


def create_app() -> Flask:
    configure_logging()
    settings = get_settings()
    logger = logging.getLogger("touch_vn.web")
    app = Flask(__name__)
    validate_production_settings(settings)
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = settings.environment == "production"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        seconds=settings.session_absolute_timeout_seconds
    )
    app.config["SESSION_REFRESH_EACH_REQUEST"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = settings.environment != "production"
    app.jinja_env.auto_reload = settings.environment != "production"
    rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)

    # Request security and session helpers. These closures intentionally sit
    # beside the Flask configuration because they depend on the same settings.
    def get_csrf_token() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return str(token)

    def csrf_token_from_request() -> str:
        return (
            request.headers.get("X-CSRF-Token")
            or request.headers.get("X-CSRFToken")
            or request.form.get("csrf_token")
            or ""
        )

    def csrf_response():
        message = "Phiên bảo mật đã hết hạn hoặc không hợp lệ. Vui lòng tải lại trang."
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": message}), 400
        return (
            render_template(
                "error.html",
                error_code=400,
                error_title="Yêu cầu không hợp lệ",
                error_body=message,
            ),
            400,
        )

    def check_csrf_token() -> bool:
        expected_token = session.get("csrf_token")
        submitted_token = csrf_token_from_request()
        return bool(
            expected_token
            and submitted_token
            and hmac.compare_digest(str(expected_token), str(submitted_token))
        )

    def client_ip_address() -> str:
        remote_addr = request.remote_addr or ""
        if remote_addr and remote_addr.lower() in settings.trusted_proxy_ips:
            forwarded_for = request.headers.get("X-Forwarded-For", "")
            forwarded_ip = forwarded_for.split(",", 1)[0].strip()
            if forwarded_ip:
                return forwarded_ip
        return remote_addr or "unknown"

    def request_uses_https() -> bool:
        if request.is_secure:
            return True
        remote_addr = (request.remote_addr or "").lower()
        if remote_addr and remote_addr in settings.trusted_proxy_ips:
            forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
            return forwarded_proto.split(",", 1)[0].strip().lower() == "https"
        return False

    def client_rate_key(scope: str) -> str:
        client_ip = client_ip_address()
        user_part = current_user_email() or session.get("visitor_key") or client_ip
        return f"{scope}:{user_part}:{client_ip}"

    def is_rate_limited(scope: str, *, limit: int, window_seconds: int) -> bool:
        now = time.time()
        bucket = rate_limit_buckets[client_rate_key(scope)]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
        return False

    def rate_limit_response():
        message = "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút."
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": message}), 429
        flash(message, "warning")
        return redirect(request.referrer or url_for("home"))

    def current_language() -> str:
        return resolve_language(session.get("language", DEFAULT_LANGUAGE))

    def current_chat_session_id() -> str:
        chat_session_id = session.get("chat_session_id")
        if not chat_session_id:
            chat_session_id = uuid4().hex
            session["chat_session_id"] = chat_session_id
        return str(chat_session_id)

    def current_user_email() -> str | None:
        user_email = session.get("user_email")
        if not user_email:
            return None
        return str(user_email).lower()

    def clear_authenticated_session(*, preserve_preferences: bool = True) -> None:
        lang = session.get("language") if preserve_preferences else None
        chat_session_id = session.get("chat_session_id") if preserve_preferences else None
        visitor_key = session.get("visitor_key") if preserve_preferences else None
        session.clear()
        if lang:
            session["language"] = lang
        if chat_session_id:
            session["chat_session_id"] = chat_session_id
        if visitor_key:
            session["visitor_key"] = visitor_key

    def start_authenticated_session(*, full_name: str, email: str) -> None:
        lang = current_language()
        chat_session_id = session.get("chat_session_id")
        visitor_key = session.get("visitor_key")
        session.clear()
        session.permanent = True
        session["language"] = lang
        if chat_session_id:
            session["chat_session_id"] = chat_session_id
        if visitor_key:
            session["visitor_key"] = visitor_key
        session["csrf_token"] = secrets.token_urlsafe(32)
        session["user"] = full_name
        session["user_email"] = email.lower()
        now_epoch = int(time.time())
        session["authenticated_at"] = now_epoch
        session["last_activity_at"] = now_epoch

    def expire_inactive_session() -> bool:
        if not current_user_email():
            return False
        now_epoch = int(time.time())
        authenticated_at = int(session.get("authenticated_at") or now_epoch)
        last_activity_at = int(session.get("last_activity_at") or authenticated_at)
        idle_expired = now_epoch - last_activity_at > settings.session_idle_timeout_seconds
        absolute_expired = now_epoch - authenticated_at > settings.session_absolute_timeout_seconds
        if idle_expired or absolute_expired:
            record_security_event(
                "session_expired",
                outcome="blocked",
                ip_address=client_ip_address(),
                actor_email=current_user_email() or "",
                request_id=getattr(g, "request_id", ""),
                details={"reason": "idle" if idle_expired else "absolute"},
            )
            clear_authenticated_session()
            return True
        if now_epoch - last_activity_at >= 60:
            session["last_activity_at"] = now_epoch
        return False

    def current_visitor_key() -> str:
        visitor_key = session.get("visitor_key")
        if not visitor_key:
            visitor_key = uuid4().hex
            session["visitor_key"] = visitor_key
        return str(visitor_key)

    def translate(key: str, **kwargs: object) -> str:
        return text(current_language(), key, **kwargs)

    def can_manage_dashboard() -> bool:
        return settings.is_admin_email(current_user_email())

    def default_dashboard_endpoint() -> str:
        if can_manage_dashboard():
            return "admin_dashboard"
        return "dashboard"

    no_weather_fetch = object()

    # View-model builders keep localization and fallback logic out of Jinja.
    def build_place_card(place, lang: str, weather=None) -> dict[str, object]:
        if weather is no_weather_fetch:
            resolved_weather = None
        else:
            resolved_weather = weather if weather is not None else get_weather(place.id, lang=lang)
        return {
            "place": place,
            "weather": resolved_weather,
            "map_embed_url": get_google_maps_embed_url(place),
            "map_view_url": get_google_maps_view_url(place),
            "detail_url": url_for("place_detail", place_id=place.id),
            "qr_image_url": url_for("place_qr_image", place_id=place.id),
        }

    def qr_target_url(place_id: str) -> str:
        public_base_url = (os.getenv("APP_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if public_base_url:
            return f"{public_base_url}{url_for('place_detail', place_id=place_id)}"
        return url_for("place_detail", place_id=place_id, _external=True)

    def slugify(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        normalized = "".join(
            character for character in normalized if not unicodedata.combining(character)
        )
        normalized = re.sub(r"[^\w\s-]", " ", normalized.lower())
        normalized = re.sub(r"[\s_]+", "-", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized)
        return normalized.strip("-")

    def resolve_qr_place_id(raw_code: str) -> str | None:
        value = str(raw_code or "").strip()
        if not value:
            return None

        if value.startswith("touchvn://place/"):
            candidate = value.rsplit("/", 1)[-1].strip()
            return candidate or None

        parsed = urlsplit(value)
        path = parsed.path.strip("/")
        for pattern in (
            r"^places/([a-z0-9][a-z0-9-]*)$",
            r"^qr/place/([a-z0-9][a-z0-9-]*)$",
        ):
            matched = re.match(pattern, path)
            if matched:
                return matched.group(1)

        if re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
            return value
        return None

    def build_ar_landmark_cards(lang: str) -> list[dict[str, object]]:
        cards: list[dict[str, object]] = []
        for item in get_ar_landmarks(lang=lang):
            matched_places = get_places(search=item["name"], lang=lang)
            matched_place = matched_places[0] if matched_places else None
            cards.append(
                {
                    "name": item["name"],
                    "province": item["province"],
                    "note": item["note"],
                    "slug": slugify(item["name"]),
                    "matched_place": matched_place,
                    "viewer_url": (
                        url_for("ar_place_view", place_id=matched_place.id)
                        if matched_place
                        else url_for("ar_landmark_view", slug=slugify(item["name"]))
                    ),
                }
            )
        return cards

    def find_ar_landmark(slug: str, lang: str) -> dict[str, object] | None:
        language_codes = [lang, DEFAULT_LANGUAGE, "en", "ko"]
        seen_languages: set[str] = set()
        localized_items = get_ar_landmarks(lang=lang)

        for candidate_lang in language_codes:
            candidate_lang = resolve_language(candidate_lang)
            if candidate_lang in seen_languages:
                continue
            seen_languages.add(candidate_lang)

            for index, item in enumerate(get_ar_landmarks(lang=candidate_lang)):
                if slugify(item["name"]) != slug:
                    continue

                localized_item = localized_items[index] if index < len(localized_items) else item
                matched_places = get_places(search=localized_item["name"], lang=lang)
                return {
                    "landmark": localized_item,
                    "matched_place": matched_places[0] if matched_places else None,
                }
        return None

    def build_offline_pack_payload(region: str, lang: str) -> dict[str, object]:
        region_codes = {item["code"] for item in get_regions_summary(lang=lang)}
        if region not in region_codes:
            raise KeyError(region)

        places_in_region = get_places(region=region, lang=lang)
        pack = next(
            (item for item in get_offline_map_packs(lang=lang) if item.get("region") == region),
            None,
        )
        landmarks: list[dict[str, object]] = []
        for item in build_ar_landmark_cards(lang):
            matched_place = item.get("matched_place")
            if matched_place is not None and matched_place.region == region:
                landmarks.append(
                    {
                        "name": item["name"],
                        "province": item["province"],
                        "note": item["note"],
                        "viewer_url": item["viewer_url"],
                    }
                )

        return {
            "generated_at": to_local_iso(now_local()),
            "language": lang,
            "region": region,
            "pack_name": pack["name"] if pack else region,
            "coverage": pack["coverage"] if pack else "",
            "places": [
                {
                    "id": place.id,
                    "name": place.name,
                    "province": place.province,
                    "categories": place.categories,
                    "coordinate": place.coordinate.model_dump(),
                    "must_go_score": place.must_go_score,
                    "ticket_price": place.ticket_price,
                    "avg_spend": place.avg_spend,
                    "detail_url": url_for("place_detail", place_id=place.id, _external=True),
                    "map_url": get_google_maps_view_url(place),
                }
                for place in places_in_region
            ],
            "ar_landmarks": landmarks,
            "travel_tips": [
                text(lang, "travel_tip_1"),
                text(lang, "travel_tip_2"),
                text(lang, "travel_tip_3"),
            ],
            "support": {
                "email": get_site_content(lang=lang).get("support_email", ""),
                "phone": get_site_content(lang=lang).get("support_phone", ""),
            },
        }

    def build_offline_pack_geojson(region: str, lang: str) -> dict[str, object]:
        payload = build_offline_pack_payload(region, lang)
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            item["coordinate"]["lng"],
                            item["coordinate"]["lat"],
                        ],
                    },
                    "properties": {
                        "id": item["id"],
                        "name": item["name"],
                        "province": item["province"],
                        "categories": item["categories"],
                        "must_go_score": item["must_go_score"],
                    },
                }
                for item in payload["places"]
            ],
        }

    def chat_quick_prompts(lang: str) -> list[dict[str, str]]:
        return [
            {
                "label": text(lang, "chat_prompt_itinerary_label"),
                "question": text(lang, "chat_prompt_itinerary_question"),
            },
            {
                "label": text(lang, "chat_prompt_budget_label"),
                "question": text(lang, "chat_prompt_budget_question"),
            },
            {
                "label": text(lang, "chat_prompt_weather_label"),
                "question": text(lang, "chat_prompt_weather_question"),
            },
        ]

    def runtime_ui_labels(lang: str) -> dict[str, str]:
        labels = {
            "vi": {
                "offline_download_json": "Tải gói JSON",
                "offline_download_geojson": "Tải gói GeoJSON",
                "offline_download_short": "Tải gói",
                "ar_open_viewer": "Mở AR camera",
                "ar_viewer_title": "AR camera: {place}",
                "ar_viewer_intro": "Mở camera điện thoại để đọc nhanh thông tin di tích, điểm đến và các tiện ích liên quan ngay trên lớp phủ màn hình.",
                "ar_camera_label": "Chế độ AR",
                "ar_info_label": "Thông tin lớp phủ",
                "ar_open_camera": "Mở camera AR",
                "ar_stop_camera": "Dừng camera",
                "ar_status_idle": "Sẵn sàng mở camera AR.",
                "ar_status_active": "Camera đang hoạt động. Hướng máy vào di tích hoặc cảnh quan để thuyết minh trên màn hình.",
                "ar_status_error": "Không thể mở camera trên thiết bị hoặc trình duyệt hiện tại.",
            },
            "en": {
                "offline_download_json": "Download JSON pack",
                "offline_download_geojson": "Download GeoJSON pack",
                "offline_download_short": "Download pack",
                "ar_open_viewer": "Open AR camera",
                "ar_viewer_title": "AR camera: {place}",
                "ar_viewer_intro": "Use your phone camera to read destination, heritage, and nearby information as an on-screen overlay.",
                "ar_camera_label": "AR mode",
                "ar_info_label": "Overlay information",
                "ar_open_camera": "Open AR camera",
                "ar_stop_camera": "Stop camera",
                "ar_status_idle": "Ready to open the AR camera.",
                "ar_status_active": "Camera is active. Point the phone at the landmark or scenery to view contextual guidance.",
                "ar_status_error": "The camera could not be opened on this device or browser.",
            },
            "ko": {
                "offline_download_json": "JSON 팩 다운로드",
                "offline_download_geojson": "GeoJSON 팩 다운로드",
                "offline_download_short": "팩 다운로드",
                "ar_open_viewer": "AR 카메라 열기",
                "ar_viewer_title": "AR 카메라: {place}",
                "ar_viewer_intro": "휴대폰 카메라를 열어 유적지와 여행지 정보를 화면 오버레이로 바로 확인하세요.",
                "ar_camera_label": "AR 모드",
                "ar_info_label": "오버레이 정보",
                "ar_open_camera": "AR 카메라 열기",
                "ar_stop_camera": "카메라 중지",
                "ar_status_idle": "AR 카메라를 열 준비가 되었습니다.",
                "ar_status_active": "카메라가 실행 중입니다. 유적이나 풍경을 비추면 안내 정보가 화면에 표시됩니다.",
                "ar_status_error": "이 기기 또는 브라우저에서 카메라를 열 수 없습니다.",
            },
        }
        return labels.get(lang, labels["en"])

    def fallback_chat_response(question: str, lang: str) -> ChatResponse:
        return chat_support(ChatRequest(question=question, language=lang))

    def build_chat_context(question: str, lang: str) -> str | None:
        matched_places = get_places(search=question, lang=lang)
        if not matched_places:
            return None

        place = matched_places[0]
        forecast = get_weather(place.id, lang=lang)
        nearby_services = get_nearby_services(
            lat=place.coordinate.lat,
            lng=place.coordinate.lng,
            lang=lang,
            prefer_live=False,
        )[:3]
        nearby_summary = ", ".join(
            f"{item.name} ({item.distance_km} km)" for item in nearby_services
        )
        weather_summary = (
            f"{forecast.condition}, {forecast.temperature_c}C, {forecast.advice}"
            if forecast
            else "No weather data"
        )
        return (
            f"Matched destination: {place.name}, province {place.province}. "
            f"Description: {place.description}. "
            f"Highlights: {', '.join(place.highlights[:3])}. "
            f"Average spend: {place.avg_spend:.0f} VND, ticket price: {place.ticket_price:.0f} VND. "
            f"Weather summary: {weather_summary}. "
            f"Nearby useful services: {nearby_summary}."
        )

    def serialize_chat_history(session_id: str) -> list[dict[str, str]]:
        return [
            {
                "role": message["role"],
                "content": message["content"],
                "created_at": to_local_iso(message["created_at"]),
            }
            for message in get_chat_messages(session_id, limit=30)
        ]

    def build_chat_response(question: str, lang: str) -> ChatResponse:
        session_id = current_chat_session_id()
        ensure_chat_session(session_id, lang, session.get("user"))

        history = get_chat_messages(session_id, limit=12)
        fallback = fallback_chat_response(question, lang)
        answer = fallback.answer

        if is_openai_available():
            try:
                answer = generate_openai_chat_answer(
                    question=question,
                    language=lang,
                    history=history,
                    context=build_chat_context(question, lang),
                )
            except Exception:
                logger.exception("OpenAI chat failed; using the local fallback response.")
                answer = fallback.answer

        add_chat_message(session_id, "user", question)
        add_chat_message(session_id, "assistant", answer)
        return ChatResponse(
            answer=answer,
            suggested_actions=fallback.suggested_actions,
        )

    def extract_chat_question() -> str:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            question = str(payload.get("question") or "").strip()
            if question:
                return question

        form_question = str(request.form.get("question", "")).strip()
        if form_question:
            return form_question

        raw_body = (request.get_data(cache=False, as_text=True) or "").strip()
        if not raw_body:
            return ""

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError:
            return raw_body

        if isinstance(parsed, dict):
            return str(parsed.get("question") or "").strip()
        return ""

    def safe_next_url(target: str | None) -> str:
        if not target:
            return url_for("home")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            return url_for("home")
        path = parsed.path or "/"
        if parsed.query:
            return f"{path}?{parsed.query}"
        return path

    app.config["DASHBOARD_LAYOUT_BASE"] = build_dashboard_layout()

    # Template filters and context shared by every rendered page.
    @app.template_filter("currency")
    def currency_filter(value: float) -> str:
        try:
            return f"{value:,.0f} VND".replace(",", ".")
        except (ValueError, TypeError):
            return "0 VND"

    @app.template_filter("datetime_local")
    def datetime_local_filter(value: object) -> str:
        return format_local_datetime(value)

    @app.template_filter("date_local")
    def date_local_filter(value: object) -> str:
        return format_local_date(value)

    @app.template_filter("iso_datetime")
    def iso_datetime_filter(value: object) -> str:
        return to_local_iso(value)

    @app.context_processor
    def inject_globals() -> dict[str, object]:
        lang = current_language()
        current_time = now_local()
        site_content = get_site_content(lang=lang)
        return {
            "supported_languages": get_supported_languages(),
            "logged_in_user": session.get("user"),
            "current_language": lang,
            "region_labels": get_region_labels(lang),
            "category_labels": get_category_labels(lang),
            "chat_quick_prompts": chat_quick_prompts(lang),
            "app_meta": settings.public_meta(),
            "site_content": site_content,
            "site_media": get_site_media_assets(),
            "app_time_zone": APP_TIMEZONE_NAME,
            "current_time_iso": to_local_iso(current_time),
            "current_time_display": format_local_datetime(current_time, "%H:%M:%S %d/%m/%Y"),
            "can_manage_dashboard": can_manage_dashboard(),
            "is_admin_user": can_manage_dashboard(),
            "place_image_asset": get_place_image_asset,
            "service_label": lambda kind: translate_service_name(kind, lang),
            "runtime_ui": runtime_ui_labels(lang),
            "csrf_token": get_csrf_token,
            "t": translate,
        }

    # HTTPS, session expiry, CSRF, throttling, logging, and response headers.
    @app.before_request
    def before_request():
        g.request_started_at = time.perf_counter()
        g.request_id = uuid4().hex[:10]
        if settings.enforce_https and not app.testing and not request_uses_https():
            target_url = f"{settings.public_base_url}{request.full_path}"
            target_url = target_url.removesuffix("?")
            record_security_event(
                "insecure_transport",
                outcome="blocked",
                ip_address=client_ip_address(),
                request_id=g.request_id,
                details={"method": request.method, "path": request.path},
            )
            return redirect(target_url, code=308)
        if expire_inactive_session():
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "Authentication session expired."}), 401
            flash("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.", "warning")
            return redirect(url_for("login"))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not check_csrf_token():
            record_security_event(
                "csrf_validation",
                outcome="blocked",
                ip_address=client_ip_address(),
                actor_email=current_user_email() or "",
                request_id=g.request_id,
                details={"method": request.method, "path": request.path},
            )
            return csrf_response()
        if (
            request.endpoint == "login"
            and request.method == "POST"
            and is_rate_limited("login", limit=10, window_seconds=300)
        ):
            record_security_event(
                "login_rate_limit",
                outcome="blocked",
                ip_address=client_ip_address(),
                request_id=g.request_id,
            )
            return rate_limit_response()
        if (
            request.endpoint in {"chat_support_api", "chat_history_reset_api"}
            and request.method == "POST"
            and is_rate_limited("chat", limit=30, window_seconds=60)
        ):
            record_security_event(
                "chat_rate_limit",
                outcome="blocked",
                ip_address=client_ip_address(),
                actor_email=current_user_email() or "",
                request_id=g.request_id,
            )
            return rate_limit_response()
        return None

    @app.after_request
    def after_request(response):
        started = getattr(g, "request_started_at", None)
        elapsed_ms = 0.0
        if started is not None:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request_id=%s method=%s path=%s status=%s elapsed_ms=%s ip=%s",
            getattr(g, "request_id", "-"),
            request.method,
            request.path,
            response.status_code,
            elapsed_ms,
            client_ip_address(),
        )
        if request.path.startswith("/admin"):
            admin_allowed = can_manage_dashboard()
            if request.method in {"POST", "PUT", "PATCH", "DELETE"} or not admin_allowed:
                outcome = (
                    "success"
                    if admin_allowed and response.status_code < 400
                    else "denied"
                    if not admin_allowed
                    else "failure"
                )
                record_security_event(
                    "admin_action" if request.method != "GET" else "admin_access",
                    outcome=outcome,
                    ip_address=client_ip_address(),
                    actor_email=current_user_email() or "",
                    request_id=getattr(g, "request_id", ""),
                    details={
                        "method": request.method,
                        "path": request.path,
                        "status_code": response.status_code,
                    },
                )
        elif response.status_code in {401, 403}:
            record_security_event(
                "authorization_denied",
                outcome="denied",
                ip_address=client_ip_address(),
                actor_email=current_user_email() or "",
                request_id=getattr(g, "request_id", ""),
                details={"method": request.method, "path": request.path},
            )
        if (
            request.method == "GET"
            and not request.path.startswith("/static/")
            and request.path != "/healthz"
            and response.mimetype == "text/html"
        ):
            try:
                record_page_view(
                    path=request.path,
                    method=request.method,
                    status_code=response.status_code,
                    response_ms=elapsed_ms,
                    user_email=current_user_email(),
                    language=current_language(),
                    request_id=getattr(g, "request_id", "-"),
                    visitor_key=current_visitor_key(),
                )
            except Exception:
                logger.exception(
                    "Could not persist local page-view analytics for path=%s",
                    request.path,
                )
            track_external_analytics_event(
                "page_view",
                {
                    "path": request.path,
                    "status_code": response.status_code,
                    "elapsed_ms": elapsed_ms,
                    "request_id": getattr(g, "request_id", "-"),
                    "language": current_language(),
                    "user_email": current_user_email(),
                },
                settings=settings,
            )
        response.headers["X-Request-Id"] = getattr(g, "request_id", "-")
        response.headers["X-App-Version"] = settings.app_version
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(self), geolocation=(self), microphone=()",
        )
        content_security_policy = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "frame-src 'self' https://www.google.com https://www.google.com.vn; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'"
        )
        if settings.environment == "production":
            content_security_policy += "; upgrade-insecure-requests"
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        response.headers.setdefault("Content-Security-Policy", content_security_policy)
        if request.path.startswith(("/login", "/register", "/admin", "/dashboard")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # Error and operational endpoints stay ahead of the feature routes so they
    # are easy to find during deployment checks.
    @app.errorhandler(404)
    def not_found(_error):
        return (
            render_template(
                "error.html",
                error_code=404,
                error_title=text(current_language(), "error_404_title"),
                error_body=text(current_language(), "error_404_body"),
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(_error):
        logger.exception("Unhandled server error for path=%s", request.path)
        record_security_event(
            "unhandled_exception",
            outcome="failure",
            ip_address=client_ip_address(),
            actor_email=current_user_email() or "",
            request_id=getattr(g, "request_id", ""),
            details={"path": request.path},
        )
        return (
            render_template(
                "error.html",
                error_code=500,
                error_title=text(current_language(), "error_500_title"),
                error_body=text(current_language(), "error_500_body"),
            ),
            500,
        )

    @app.route("/healthz")
    def healthz():
        return jsonify(
            {
                "status": "ok",
                "app_name": settings.app_name,
                "version": settings.app_version,
                "environment": settings.environment,
            }
        )

    @app.route("/api/system/status")
    def system_status_api():
        return jsonify(
            {
                "app": settings.public_meta(),
                "metrics": get_product_status(current_user_email()),
                "integrations": get_integration_summary(settings),
            }
        )

    @app.route("/api/integrations/status")
    def integration_status_api():
        if not can_manage_dashboard():
            return jsonify({"error": "admin_only"}), 403
        return jsonify(
            {
                "summary": get_integration_summary(settings),
                "integrations": get_integration_statuses(settings),
            }
        )

    @app.route("/api/integrations/probe/<integration_key>")
    def integration_probe_api(integration_key: str):
        if not can_manage_dashboard():
            return jsonify({"error": "admin_only"}), 403
        try:
            return jsonify(probe_integration(integration_key, settings=settings))
        except KeyError:
            return jsonify({"error": "integration_not_found"}), 404

    @app.route("/set-language/<lang_code>")
    def set_language(lang_code: str):
        session["language"] = resolve_language(lang_code)
        return redirect(safe_next_url(request.args.get("next")))

    # Public discovery, destination, QR/AR, planning, and ticket flows.
    @app.route("/")
    def home():
        lang = current_language()
        featured_places = get_featured_places(limit=3, lang=lang)
        weather_places = sorted(
            get_places(lang=lang),
            key=lambda place: (place.province.casefold(), place.name.casefold()),
        )
        weather_places_by_id = {place.id: place for place in weather_places}
        requested_weather_place_id = (request.args.get("weather_place_id") or "").strip()
        if requested_weather_place_id in weather_places_by_id:
            session["weather_place_id"] = requested_weather_place_id

        selected_weather_place_id = str(session.get("weather_place_id") or "")
        if selected_weather_place_id not in weather_places_by_id:
            default_weather_place = featured_places[0] if featured_places else None
            selected_weather_place_id = default_weather_place.id if default_weather_place else ""

        selected_weather_place = weather_places_by_id.get(selected_weather_place_id)
        weather_forecast = (
            get_weather(selected_weather_place.id, lang=lang) if selected_weather_place else None
        )
        return render_template(
            "index.html",
            featured_places=featured_places,
            weather_places=weather_places,
            selected_weather_place_id=selected_weather_place_id,
            weather_forecast=weather_forecast,
            category_labels={item["code"]: item["label"] for item in get_categories(lang=lang)},
            vehicle_options=get_ticket_vehicle_options(lang=lang),
        )

    @app.route("/places")
    def places():
        lang = current_language()
        region = request.args.get("region") or None
        province = request.args.get("province") or None
        category = request.args.get("category") or None
        search = request.args.get("search") or None
        places_result = get_places(
            region=region,
            province=province,
            category=category,
            search=search,
            lang=lang,
        )
        page_size = 12
        total_places = len(places_result)
        total_pages = max((total_places + page_size - 1) // page_size, 1)
        page = min(max(request.args.get("page", default=1, type=int) or 1, 1), total_pages)
        page_start = (page - 1) * page_size
        visible_places = places_result[page_start : page_start + page_size]

        weather_map = get_weather_batch(
            [place.id for place in visible_places],
            lang=lang,
            max_workers=8,
        )
        place_cards = [
            build_place_card(place, lang=lang, weather=weather_map.get(place.id, no_weather_fetch))
            for place in visible_places
        ]
        return render_template(
            "places.html",
            place_cards=place_cards,
            categories=get_categories(lang=lang),
            regions=get_regions_summary(lang=lang),
            provinces=get_provinces_summary(region=region, lang=lang),
            selected_region=region,
            selected_province=province,
            selected_category=category,
            keyword=search or "",
            category_labels={item["code"]: item["label"] for item in get_categories(lang=lang)},
            pagination={
                "page": page,
                "page_size": page_size,
                "total_items": total_places,
                "total_pages": total_pages,
            },
        )

    @app.route("/places/<place_id>")
    def place_detail(place_id: str):
        lang = current_language()
        place = get_place(place_id, lang=lang)
        if place is None:
            return (
                render_template(
                    "error.html",
                    error_code=404,
                    error_title=text(lang, "error_404_title"),
                    error_body=text(lang, "error_404_body"),
                ),
                404,
            )
        place_card = build_place_card(place, lang=lang)
        nearby_services = get_nearby_services(
            lat=place.coordinate.lat,
            lng=place.coordinate.lng,
            lang=lang,
            prefer_live=False,
        )
        offline_pack = next(
            (
                item
                for item in get_offline_map_packs(lang=lang)
                if item.get("region") == place.region
            ),
            None,
        )
        ar_landmarks = [
            item
            for item in build_ar_landmark_cards(lang)
            if (item.get("matched_place") is not None and item["matched_place"].id == place.id)
            or item.get("province") == place.province
        ]
        region_labels = {item["code"]: item["label"] for item in get_regions_summary(lang=lang)}
        category_labels = {item["code"]: item["label"] for item in get_categories(lang=lang)}
        transport_labels = {
            item["code"]: item["label"] for item in get_ticket_vehicle_options(lang=lang)
        }
        place_detail_rows = [
            {
                "label": text(lang, "place_detail_region"),
                "value": region_labels.get(place.region, place.region),
            },
            {"label": text(lang, "place_detail_province"), "value": place.province},
            {
                "label": text(lang, "place_detail_categories"),
                "value": ", ".join(category_labels.get(item, item) for item in place.categories),
            },
            {"label": text(lang, "place_detail_rating"), "value": f"{place.rating}/5"},
            {"label": text(lang, "place_detail_must_go"), "value": f"{place.must_go_score}/100"},
            {"label": text(lang, "ticket_price"), "value": currency_filter(place.ticket_price)},
            {"label": text(lang, "places_avg_spend"), "value": currency_filter(place.avg_spend)},
            {
                "label": text(lang, "place_detail_coordinates"),
                "value": f"{place.coordinate.lat:.4f}, {place.coordinate.lng:.4f}",
            },
            {
                "label": text(lang, "planner_transport_mode"),
                "value": ", ".join(
                    transport_labels.get(item, item.title()) for item in place.transport_modes
                ),
            },
            {
                "label": text(lang, "place_detail_best_time"),
                "value": place_card["weather"].best_visit_time
                if place_card.get("weather")
                else text(lang, "weather_best_time"),
            },
        ]
        return render_template(
            "place_detail.html",
            place_card=place_card,
            nearby_services=nearby_services,
            offline_pack=offline_pack,
            ar_landmarks=ar_landmarks,
            qr_target_url=qr_target_url(place.id),
            place_detail_rows=place_detail_rows,
            category_labels=category_labels,
        )

    @app.route("/ar/places/<place_id>")
    def ar_place_view(place_id: str):
        lang = current_language()
        place = get_place(place_id, lang=lang)
        if place is None:
            return (
                render_template(
                    "error.html",
                    error_code=404,
                    error_title=text(lang, "error_404_title"),
                    error_body=text(lang, "error_404_body"),
                ),
                404,
            )

        weather = get_weather(place.id, lang=lang)
        nearby_services = get_nearby_services(
            lat=place.coordinate.lat,
            lng=place.coordinate.lng,
            lang=lang,
            prefer_live=False,
        )[:4]
        return render_template(
            "ar_viewer.html",
            ar_place=place,
            ar_landmark=None,
            weather=weather,
            nearby_services=nearby_services,
            map_view_url=get_google_maps_view_url(place),
            qr_image_url=url_for("place_qr_image", place_id=place.id),
        )

    @app.route("/ar/landmarks/<slug>")
    def ar_landmark_view(slug: str):
        lang = current_language()
        item = find_ar_landmark(slug, lang)
        if item is None:
            return (
                render_template(
                    "error.html",
                    error_code=404,
                    error_title=text(lang, "error_404_title"),
                    error_body=text(lang, "error_404_body"),
                ),
                404,
            )

        matched_place = item["matched_place"]
        weather = get_weather(matched_place.id, lang=lang) if matched_place else None
        nearby_services = (
            get_nearby_services(
                lat=matched_place.coordinate.lat,
                lng=matched_place.coordinate.lng,
                lang=lang,
                prefer_live=False,
            )[:4]
            if matched_place
            else []
        )
        return render_template(
            "ar_viewer.html",
            ar_place=matched_place,
            ar_landmark=item["landmark"],
            weather=weather,
            nearby_services=nearby_services,
            map_view_url=get_google_maps_view_url(matched_place) if matched_place else None,
            qr_image_url=(
                url_for("place_qr_image", place_id=matched_place.id) if matched_place else None
            ),
        )

    @app.route("/places/<place_id>/qr.png")
    def place_qr_image(place_id: str):
        lang = current_language()
        place = next((item for item in get_places(lang=lang) if item.id == place_id), None)
        if place is None:
            return (
                render_template(
                    "error.html",
                    error_code=404,
                    error_title=text(lang, "error_404_title"),
                    error_body=text(lang, "error_404_body"),
                ),
                404,
            )
        image = qrcode.make(qr_target_url(place.id))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="image/png",
            download_name=f"{place.id}-qr.png",
            max_age=3600,
        )

    @app.route("/qr-scanner")
    @app.route("/scan-qr")
    def scan_qr():
        return render_template("qr_scanner.html")

    @app.route("/api/qr/resolve", methods=["POST"])
    def qr_resolve_api():
        lang = current_language()
        payload = request.get_json(silent=True) or {}
        code = str(payload.get("code") or "").strip()
        place_id = resolve_qr_place_id(code)
        if not place_id:
            return jsonify({"error": text(lang, "qr_scan_invalid")}), 400

        place = get_place(place_id, lang=lang)
        if place is None:
            return jsonify({"error": text(lang, "qr_scan_not_found")}), 404

        weather = get_weather(place.id, lang=lang)
        nearby_services = get_nearby_services(
            lat=place.coordinate.lat,
            lng=place.coordinate.lng,
            lang=lang,
            prefer_live=False,
        )[:4]
        return jsonify(
            {
                "place": place.model_dump(),
                "weather": weather.model_dump() if weather else None,
                "nearby_services": [item.model_dump() for item in nearby_services],
                "detail_url": url_for("place_detail", place_id=place.id),
                "map_view_url": get_google_maps_view_url(place),
                "qr_image_url": url_for("place_qr_image", place_id=place.id),
            }
        )

    @app.route("/planner", methods=["GET", "POST"])
    def planner():
        lang = current_language()
        itinerary = None
        budget = None
        nearby_lat = None
        nearby_lng = None
        nearby_from_user_location = False
        try:
            nearby_lat = float(request.args.get("lat") or "")
            nearby_lng = float(request.args.get("lng") or "")
            nearby_from_user_location = True
        except ValueError:
            nearby_lat = 16.0471
            nearby_lng = 108.2068
        nearby_services = get_nearby_services(
            lat=nearby_lat,
            lng=nearby_lng,
            lang=lang,
            prefer_live=nearby_from_user_location,
        )

        if request.method == "POST":
            try:
                interests = [
                    item.strip()
                    for item in request.form.get("interests", "").split(",")
                    if item.strip()
                ]

                itinerary_request = ItineraryRequest(
                    departure_city=request.form.get(
                        "departure_city", text(lang, "default_departure_city")
                    ),
                    region=request.form.get("region") or None,
                    destination=request.form.get("destination") or None,
                    days=int(request.form.get("days", 3)),
                    budget=float(request.form.get("budget", 3000000)),
                    travelers=int(request.form.get("travelers", 2)),
                    interests=interests,
                )

                itinerary = generate_itinerary(itinerary_request, lang=lang)
                budget = estimate_budget(
                    BudgetEstimateRequest(
                        travelers=itinerary_request.travelers,
                        days=itinerary_request.days,
                        region=itinerary_request.region or "central",
                        transport_mode=request.form.get("transport_mode", "plane"),
                        accommodation_level=request.form.get("accommodation_level", "midrange"),
                        include_tickets=request.form.get("include_tickets") == "on",
                    ),
                    lang=lang,
                )
                requested_destination = (
                    request.form.get("destination", "").strip() or itinerary.destination
                )
                matched_places = get_places(
                    region=itinerary_request.region,
                    search=requested_destination,
                    lang=lang,
                )
                if not matched_places and itinerary.destination:
                    matched_places = get_places(
                        region=itinerary_request.region,
                        search=itinerary.destination,
                        lang=lang,
                    )
                if matched_places:
                    focus_place = matched_places[0]
                    nearby_services = get_nearby_services(
                        lat=focus_place.coordinate.lat,
                        lng=focus_place.coordinate.lng,
                        lang=lang,
                        prefer_live=False,
                    )

                if request.form.get("save_trip") == "on":
                    user_email = current_user_email()
                    if user_email:
                        save_trip_plan(
                            user_email=user_email,
                            itinerary_request=itinerary_request,
                            itinerary=itinerary,
                            budget=budget,
                            lang=lang,
                        )
                        flash(text(lang, "planner_saved_trip_success"), "success")
                    else:
                        flash(text(lang, "planner_saved_trip_need_login"), "warning")
            except (ValidationError, ValueError):
                flash(text(lang, "planner_invalid"), "danger")

        return render_template(
            "planner.html",
            itinerary=itinerary,
            budget=budget,
            regions=get_regions_summary(lang=lang),
            nearby_services=nearby_services,
            nearby_from_user_location=nearby_from_user_location,
        )

    @app.route("/tickets", methods=["GET", "POST"])
    def tickets():
        lang = current_language()
        origin = (request.values.get("origin") or "").strip()
        destination = (request.values.get("destination") or "").strip()
        selected_vehicle = (request.values.get("vehicle_type") or "").strip()
        departure_date = (
            request.values.get("departure_date") or ""
        ).strip() or now_local().date().isoformat()
        try:
            passengers = max(1, min(20, int(request.values.get("passengers") or 1)))
        except ValueError:
            passengers = 1
        latest_booking = None

        if request.method == "POST" and request.form.get("action") == "book":
            user_email = current_user_email()
            if not user_email:
                flash(text(lang, "planner_saved_trip_need_login"), "warning")
                return redirect(url_for("login"))
            contact_name = (request.form.get("contact_name") or session.get("user") or "").strip()
            contact_email = (request.form.get("contact_email") or user_email).strip()
            contact_phone = (request.form.get("contact_phone") or "").strip()
            if not contact_name or not contact_email or not contact_phone:
                flash(text(lang, "booking_invalid"), "warning")
            else:
                latest_booking = create_ticket_reservation(
                    user_email=user_email,
                    provider=(request.form.get("provider") or "").strip(),
                    vehicle_type=(request.form.get("vehicle_type") or "").strip(),
                    origin=(request.form.get("origin") or "").strip(),
                    destination=(request.form.get("destination") or "").strip(),
                    departure_date=(request.form.get("departure_date") or "").strip(),
                    departure_time=(request.form.get("departure_time") or "").strip(),
                    arrival_time=(request.form.get("arrival_time") or "").strip(),
                    seat_class=(request.form.get("seat_class") or "").strip(),
                    amount=float(request.form.get("amount") or 0),
                    contact_name=contact_name,
                    contact_email=contact_email,
                    contact_phone=contact_phone,
                )
                flash(
                    text(
                        lang,
                        "booking_success",
                        reference=latest_booking["booking_reference"],
                    ),
                    "success",
                )
            origin = (request.form.get("search_origin") or origin).strip()
            destination = (request.form.get("search_destination") or destination).strip()
            selected_vehicle = (request.form.get("search_vehicle_type") or selected_vehicle).strip()
            departure_date = (
                request.form.get("search_departure_date") or departure_date
            ).strip() or departure_date
            try:
                passengers = max(
                    1, min(20, int(request.form.get("search_passengers") or passengers))
                )
            except ValueError:
                passengers = 1

        searched = bool(origin and destination)
        offers = []

        if searched:
            offers = search_tickets(
                origin=origin,
                destination=destination,
                vehicle_type=selected_vehicle or None,
                departure_date=departure_date,
                passengers=passengers,
                lang=lang,
            )

        vehicle_options = get_ticket_vehicle_options(lang=lang)
        return render_template(
            "tickets.html",
            origin=origin,
            destination=destination,
            selected_vehicle=selected_vehicle,
            departure_date=departure_date,
            passengers=passengers,
            searched=searched,
            offers=offers,
            vehicle_options=vehicle_options,
            latest_booking=latest_booking,
            recent_bookings=get_user_ticket_bookings(current_user_email(), lang=lang)[:6]
            if current_user_email()
            else [],
        )

    @app.route("/about")
    def about():
        return render_template("about.html")

    # Signed-in dashboards and administrative maintenance screens.
    @app.route("/dashboard")
    def dashboard():
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))
        if can_manage_dashboard():
            return redirect(url_for("admin_dashboard"))

        user_email = current_user_email()
        if not user_email:
            flash(text(lang, "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))

        dashboard_layout_base = app.config["DASHBOARD_LAYOUT_BASE"]
        visible_keys = {
            block.key
            for block in get_dashboard_blocks(dashboard_layout_base)
            if block.key != "upgrades"
        }
        return render_template(
            "dashboard.html",
            dashboard_eyebrow_key="user_dashboard_eyebrow",
            dashboard_title_key="user_dashboard_title",
            dashboard_intro_key="user_dashboard_intro",
            dashboard_layout=filter_dashboard_layout(dashboard_layout_base, visible_keys),
            summary=get_dashboard_summary(lang=lang),
            saved_trips=get_user_saved_trips(user_email),
            expense_summary=get_group_expense_summary(user_email, lang=lang),
            recent_expenses=get_group_expense_items(user_email, lang=lang)[:6],
            recent_bookings=get_user_ticket_bookings(user_email, lang=lang)[:6],
            ar_landmarks=build_ar_landmark_cards(lang),
            offline_map_packs=get_offline_map_packs(lang=lang),
            languages=get_supported_languages(),
        )

    @app.route("/admin")
    def admin_dashboard():
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))

        dashboard_layout_base = app.config["DASHBOARD_LAYOUT_BASE"]
        dashboard_blocks = get_dashboard_blocks(dashboard_layout_base)
        visibility_records = list_dashboard_block_visibility(
            [block.key for block in dashboard_blocks]
        )
        visibility_map = {item["block_key"]: item["is_visible"] for item in visibility_records}
        dashboard_block_controls = [
            {
                "key": block.key,
                "title": text(lang, block.title_key),
                "visible": visibility_map.get(block.key, True),
            }
            for block in dashboard_blocks
        ]

        return render_template(
            "admin_dashboard.html",
            summary=get_dashboard_summary(lang=lang),
            recommendations=get_admin_recommendations(lang=lang),
            dashboard_block_controls=dashboard_block_controls,
            analytics=get_admin_analytics_snapshot(lang=lang),
        )

    @app.route("/admin/analytics/export.csv")
    def admin_analytics_export():
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))

        analytics = get_admin_analytics_snapshot(lang=lang)
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["section", "label", "value"])
        writer.writerow(
            [
                "headline",
                analytics["labels"]["visits_30d"],
                analytics["headline"]["total_visits_30d"],
            ]
        )
        writer.writerow(
            [
                "headline",
                analytics["labels"]["visits_7d"],
                analytics["headline"]["weekly_visits"],
            ]
        )
        writer.writerow(
            [
                "headline",
                analytics["labels"]["unique_visitors"],
                analytics["headline"]["unique_visitors_30d"],
            ]
        )
        writer.writerow(
            [
                "headline",
                analytics["labels"]["repeat_rate"],
                analytics["headline"]["repeat_rate"],
            ]
        )
        for item in analytics["top_pages"]:
            writer.writerow(["top_page", item["path"], item["total"]])
        for item in analytics["daily_views"]:
            writer.writerow(["daily_view", item["date"], item["total"]])

        return app.response_class(
            buffer.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=touch-vietnam-analytics.csv"},
        )

    @app.route("/admin/integrations")
    def admin_integrations():
        if "user" not in session:
            flash(text(current_language(), "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))
        return render_template(
            "admin_integrations.html",
            integration_summary=get_integration_summary(settings),
            integrations=get_integration_statuses(settings),
        )

    @app.route("/dashboard/layout", methods=["POST"])
    def dashboard_layout_settings():
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))

        user_email = current_user_email()
        if not settings.is_admin_email(user_email):
            return redirect(url_for("home"))

        dashboard_blocks = get_dashboard_blocks(app.config["DASHBOARD_LAYOUT_BASE"])
        block_keys = [block.key for block in dashboard_blocks]
        visible_keys = set(request.form.getlist("visible_blocks"))
        if not visible_keys:
            flash(text(lang, "flash_dashboard_layout_empty"), "warning")
            return redirect(url_for("admin_dashboard"))

        save_dashboard_block_visibility(
            block_keys=block_keys,
            visible_keys=visible_keys,
            updated_by=user_email,
        )
        flash(text(lang, "flash_dashboard_layout_saved"), "success")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/site-content", methods=["GET", "POST"])
    def admin_site_content():
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))

        if request.method == "POST":
            values = {
                "brand_name": request.form.get("brand_name", ""),
                "browser_title": request.form.get("browser_title", ""),
                "footer_brand_line": request.form.get("footer_brand_line", ""),
                "support_email": request.form.get("support_email", ""),
                "support_phone": request.form.get("support_phone", ""),
            }
            save_site_content(values, current_user_email())
            logo_file = request.files.get("logo_image")
            hero_file = request.files.get("hero_image")
            image_messages: list[str] = []
            try:
                if logo_file and (logo_file.filename or "").strip():
                    save_uploaded_site_image(
                        asset_key="site-logo",
                        file=logo_file,
                        output_format=request.form.get("logo_image_format"),
                    )
                    image_messages.append("Đã cập nhật logo website.")
                elif request.form.get("remove_logo_image") == "on":
                    if remove_uploaded_site_image("site-logo"):
                        image_messages.append("Đã xóa logo tùy chỉnh.")

                if hero_file and (hero_file.filename or "").strip():
                    save_uploaded_site_image(
                        asset_key="home-hero",
                        file=hero_file,
                        output_format=request.form.get("hero_image_format"),
                    )
                    image_messages.append("Đã cập nhật ảnh hero trang chủ.")
                elif request.form.get("remove_hero_image") == "on":
                    if remove_uploaded_site_image("home-hero"):
                        image_messages.append("Đã xóa ảnh hero tùy chỉnh.")
            except ValueError as exc:
                flash(f"Đã cập nhật thông tin website. Lỗi xử lý hình ảnh: {exc}", "danger")
                return redirect(url_for("admin_site_content"))

            success_message = "Đã cập nhật thông tin website."
            if image_messages:
                success_message = f"{success_message} {' '.join(image_messages)}"
            flash(success_message, "success")
            return redirect(url_for("admin_site_content"))

        return render_template(
            "admin_site_content.html",
            site_content_form=get_site_content(lang=lang),
            media_assets=get_site_media_assets(),
            image_conversion_available=image_conversion_available(),
        )

    @app.route("/admin/places", methods=["GET", "POST"])
    def admin_places():
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))

        current_place_id = (
            request.args.get("place_id") or request.form.get("place_id") or ""
        ).strip()
        if request.method == "POST":
            try:
                saved_place_id = save_admin_place(
                    user_email=current_user_email(),
                    place_id=current_place_id,
                    name=request.form.get("name", ""),
                    region=request.form.get("region", ""),
                    province=request.form.get("province", ""),
                    categories=request.form.getlist("categories"),
                    description=request.form.get("description", ""),
                    highlights_text=request.form.get("highlights_text", ""),
                    ticket_price=float(request.form.get("ticket_price", 0) or 0),
                    avg_spend=float(request.form.get("avg_spend", 0) or 0),
                    rating=float(request.form.get("rating", 0) or 0),
                    must_go_score=int(request.form.get("must_go_score", 0) or 0),
                    lat=float(request.form.get("lat", 0) or 0),
                    lng=float(request.form.get("lng", 0) or 0),
                    nearby_services_text=request.form.get("nearby_services_text", ""),
                    transport_modes=request.form.getlist("transport_modes"),
                    image_hint=request.form.get("image_hint", ""),
                )
                image_file = request.files.get("image_file")
                image_messages: list[str] = []
                try:
                    if image_file and (image_file.filename or "").strip():
                        save_uploaded_place_image(
                            place_id=saved_place_id,
                            file=image_file,
                            output_format=request.form.get("image_output_format"),
                        )
                        image_messages.append("Đã cập nhật hình ảnh địa điểm.")
                    elif request.form.get("remove_place_image") == "on":
                        if remove_uploaded_place_image(saved_place_id):
                            image_messages.append("Đã xóa hình ảnh tùy chỉnh.")
                except ValueError as exc:
                    flash(f"Đã lưu thay đổi địa điểm. Lỗi xử lý hình ảnh: {exc}", "danger")
                    return redirect(url_for("admin_places", place_id=saved_place_id))

                success_message = "Đã lưu thay đổi địa điểm."
                if image_messages:
                    success_message = f"{success_message} {' '.join(image_messages)}"
                flash(success_message, "success")
                return redirect(url_for("admin_places", place_id=saved_place_id))
            except (ValidationError, ValueError):
                flash("Thông tin địa điểm chưa hợp lệ. Vui lòng kiểm tra lại.", "danger")

        admin_place_rows = get_admin_place_records(lang=lang)
        for item in admin_place_rows:
            item["image"] = get_place_image_info(item["place"].id)
        selected_place = (
            get_admin_place_record(current_place_id, lang=lang) if current_place_id else None
        )
        if selected_place is not None:
            selected_place["image"] = get_place_image_info(selected_place["place"].id)
        return render_template(
            "admin_places.html",
            admin_places=admin_place_rows,
            selected_place=selected_place,
            region_options=get_admin_region_options(lang=lang),
            category_options=get_admin_category_options(lang=lang),
            transport_options=get_admin_transport_options(lang=lang),
            image_conversion_available=image_conversion_available(),
        )

    @app.route("/admin/places/<place_id>/visibility", methods=["POST"])
    def admin_place_visibility(place_id: str):
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_dashboard_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))

        action = (request.form.get("action") or "").strip().lower()
        is_active = action != "hide"
        if set_admin_place_active(place_id, is_active=is_active, user_email=current_user_email()):
            state_label = "Đang hiển thị" if is_active else "Đang ẩn"
            flash(f"Đã cập nhật trạng thái địa điểm: {state_label}.", "success")
        else:
            flash("Thông tin địa điểm chưa hợp lệ. Vui lòng kiểm tra lại.", "danger")
        return redirect(url_for("admin_places", place_id=place_id))

    # Trip utilities: shared expenses, offline packs, and chat history.
    @app.route("/expenses", methods=["GET", "POST"])
    def expenses():
        lang = current_language()
        user_email = current_user_email()
        if not user_email:
            flash(text(lang, "planner_saved_trip_need_login"), "warning")
            return redirect(url_for("login"))

        saved_trips = get_user_saved_trips(user_email)
        selected_trip_id_raw = (
            request.form.get("trip_id")
            or request.args.get("trip_id")
            or (str(saved_trips[0]["id"]) if saved_trips else "")
        )
        selected_trip = None
        if selected_trip_id_raw.isdigit():
            selected_trip = get_user_trip(user_email, int(selected_trip_id_raw))

        category_options = [
            {"code": "transport", "label": text(lang, "expense_category_transport")},
            {"code": "stay", "label": text(lang, "expense_category_stay")},
            {"code": "food", "label": text(lang, "expense_category_food")},
            {"code": "ticket", "label": text(lang, "expense_category_ticket")},
            {"code": "shopping", "label": text(lang, "expense_category_shopping")},
            {"code": "emergency", "label": text(lang, "expense_category_emergency")},
            {"code": "other", "label": text(lang, "expense_category_other")},
        ]

        if request.method == "POST" and selected_trip is not None:
            try:
                title = (request.form.get("title") or "").strip()
                paid_by = (request.form.get("paid_by") or "").strip()
                split_members = [
                    item.strip()
                    for item in (request.form.get("split_members") or "")
                    .replace("\n", ",")
                    .split(",")
                    if item.strip()
                ]
                category = request.form.get("category") or "other"
                amount = float(request.form.get("amount") or 0)
                note = (request.form.get("note") or "").strip()
                if title and paid_by and amount > 0:
                    add_group_expense(
                        user_email=user_email,
                        trip_id=int(selected_trip["id"]),
                        title=title,
                        category=category,
                        paid_by=paid_by,
                        split_members=split_members,
                        amount=amount,
                        note=note,
                    )
                    flash(text(lang, "flash_expense_added"), "success")
                    return redirect(url_for("expenses", trip_id=selected_trip["id"]))
                flash(text(lang, "expenses_invalid"), "warning")
            except ValueError:
                flash(text(lang, "expenses_invalid"), "warning")

        trip_id = int(selected_trip["id"]) if selected_trip is not None else None
        expense_items = get_group_expense_items(user_email, trip_id=trip_id, lang=lang)
        expense_summary = get_group_expense_summary(user_email, trip_id=trip_id, lang=lang)

        return render_template(
            "expenses.html",
            saved_trips=saved_trips,
            selected_trip=selected_trip,
            selected_trip_id=selected_trip_id_raw,
            expense_items=expense_items,
            expense_summary=expense_summary,
            category_options=category_options,
        )

    @app.route("/offline-packs/<region>.json")
    def offline_pack_download(region: str):
        lang = current_language()
        try:
            payload = build_offline_pack_payload(region, lang)
        except KeyError:
            return (
                render_template(
                    "error.html",
                    error_code=404,
                    error_title=text(lang, "error_404_title"),
                    error_body=text(lang, "error_404_body"),
                ),
                404,
            )

        buffer = BytesIO()
        buffer.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/json",
            as_attachment=True,
            download_name=f"touch-vietnam-offline-{region}.json",
            max_age=0,
        )

    @app.route("/offline-packs/<region>.geojson")
    def offline_pack_geojson(region: str):
        lang = current_language()
        try:
            payload = build_offline_pack_geojson(region, lang)
        except KeyError:
            return (
                render_template(
                    "error.html",
                    error_code=404,
                    error_title=text(lang, "error_404_title"),
                    error_body=text(lang, "error_404_body"),
                ),
                404,
            )

        buffer = BytesIO()
        buffer.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/geo+json",
            as_attachment=True,
            download_name=f"touch-vietnam-offline-{region}.geojson",
            max_age=0,
        )

    @app.route("/api/chat-history")
    def chat_history_api():
        lang = current_language()
        session_id = current_chat_session_id()
        ensure_chat_session(session_id, lang, session.get("user"))
        return jsonify(
            {
                "messages": serialize_chat_history(session_id),
                "empty_text": text(lang, "chatbot_history_empty"),
            }
        )

    @app.route("/api/chat-history/reset", methods=["POST"])
    def chat_history_reset_api():
        lang = current_language()
        session_id = current_chat_session_id()
        ensure_chat_session(session_id, lang, session.get("user"))
        clear_chat_messages(session_id)
        return jsonify(
            {
                "message": text(lang, "chatbot_reset_done"),
                "messages": [],
            }
        )

    @app.route("/api/chat-support", methods=["POST"])
    def chat_support_api():
        lang = current_language()
        session_id = current_chat_session_id()
        ensure_chat_session(session_id, lang, session.get("user"))

        question = extract_chat_question()
        if not question:
            return jsonify({"error": text(lang, "chatbot_error")}), 400

        response = build_chat_response(question, lang)
        return jsonify(
            {
                "answer": response.answer,
                "suggested_actions": response.suggested_actions,
                "question": question,
                "messages": serialize_chat_history(session_id),
            }
        )

    @app.route("/admin/recommendations", methods=["GET", "POST"])
    def admin_recommends():
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_admin_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))

        current_recommendation_id_raw = (
            request.args.get("recommendation_id") or request.form.get("recommendation_id") or ""
        ).strip()
        current_recommendation_id = (
            int(current_recommendation_id_raw) if current_recommendation_id_raw.isdigit() else None
        )

        if request.method == "POST":
            try:
                saved_recommendation_id = save_admin_recommendation(
                    user_email=current_user_email(),
                    recommendation_id=current_recommendation_id,
                    title_vi=request.form.get("title_vi", ""),
                    detail_vi=request.form.get("detail_vi", ""),
                    title_en=request.form.get("title_en", ""),
                    detail_en=request.form.get("detail_en", ""),
                    title_ko=request.form.get("title_ko", ""),
                    detail_ko=request.form.get("detail_ko", ""),
                    priority=request.form.get("priority", "medium"),
                    display_order=int(request.form.get("display_order", 0) or 0),
                    is_active=request.form.get("is_active") == "on",
                )
                flash(text(lang, "adminrec_saved"), "success")
                return redirect(
                    url_for(
                        "admin_recommends",
                        recommendation_id=saved_recommendation_id,
                    )
                )
            except (TypeError, ValueError):
                flash(text(lang, "adminrec_invalid"), "danger")

        return render_template(
            "admin_recommends.html",
            recommendations=get_admin_recommendations(lang=lang),
            admin_recommendation_rows=get_admin_recommendation_records(lang=lang),
            selected_recommendation=(
                get_admin_recommendation_record(current_recommendation_id, lang=lang)
                if current_recommendation_id is not None
                else None
            ),
            priority_options=get_admin_recommendation_priority_options(lang=lang),
        )

    @app.route("/admin/recommendations/<int:recommendation_id>/visibility", methods=["POST"])
    def admin_recommendation_visibility(recommendation_id: int):
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_admin_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))

        action = (request.form.get("action") or "").strip().lower()
        is_active = action != "hide"
        if set_admin_recommendation_visibility(
            recommendation_id,
            is_active=is_active,
            user_email=current_user_email(),
        ):
            flash(text(lang, "adminrec_visibility_updated"), "success")
        else:
            flash(text(lang, "adminrec_invalid"), "danger")
        return redirect(url_for("admin_recommends", recommendation_id=recommendation_id))

    @app.route("/admin/recommendations/<int:recommendation_id>/delete", methods=["POST"])
    def admin_recommendation_delete(recommendation_id: int):
        lang = current_language()
        if "user" not in session:
            flash(text(lang, "flash_admin_login"), "warning")
            return redirect(url_for("login"))
        if not can_manage_dashboard():
            return redirect(url_for("home"))

        if remove_admin_recommendation(recommendation_id):
            flash(text(lang, "adminrec_deleted"), "success")
            return redirect(url_for("admin_recommends"))
        flash(text(lang, "adminrec_invalid"), "danger")
        return redirect(url_for("admin_recommends", recommendation_id=recommendation_id))

    # Authentication routes depend on the shared session and CSRF helpers.
    @app.route("/login", methods=["GET", "POST"])
    def login():
        lang = current_language()
        if request.method == "POST":
            try:
                response = login_user(
                    UserLoginRequest(
                        email=request.form.get("email", ""),
                        password=request.form.get("password", ""),
                    ),
                    lang=lang,
                )
                if response.token:
                    start_authenticated_session(
                        full_name=response.full_name or "",
                        email=response.email or "",
                    )
                    record_security_event(
                        "login",
                        outcome="success",
                        ip_address=client_ip_address(),
                        actor_email=response.email or "",
                        request_id=getattr(g, "request_id", ""),
                    )
                    flash(text(lang, "flash_login_success"), "success")
                    return redirect(url_for(default_dashboard_endpoint()))
                record_security_event(
                    "login",
                    outcome="failure",
                    ip_address=client_ip_address(),
                    actor_email=request.form.get("email", ""),
                    request_id=getattr(g, "request_id", ""),
                )
                flash(response.message, "danger")
            except ValidationError:
                record_security_event(
                    "login",
                    outcome="failure",
                    ip_address=client_ip_address(),
                    actor_email=request.form.get("email", ""),
                    request_id=getattr(g, "request_id", ""),
                    details={"reason": "invalid_input"},
                )
                flash(text(lang, "flash_login_invalid_format"), "danger")

        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        lang = current_language()
        if request.method == "POST":
            try:
                response = register_user(
                    UserRegisterRequest(
                        full_name=request.form.get("full_name", ""),
                        email=request.form.get("email", ""),
                        password=request.form.get("password", ""),
                    ),
                    lang=lang,
                )
                if response.token:
                    start_authenticated_session(
                        full_name=response.full_name or "",
                        email=response.email or "",
                    )
                    record_security_event(
                        "registration",
                        outcome="success",
                        ip_address=client_ip_address(),
                        actor_email=response.email or "",
                        request_id=getattr(g, "request_id", ""),
                    )
                    flash(text(lang, "flash_register_success"), "success")
                    return redirect(url_for(default_dashboard_endpoint()))
                record_security_event(
                    "registration",
                    outcome="failure",
                    ip_address=client_ip_address(),
                    actor_email=request.form.get("email", ""),
                    request_id=getattr(g, "request_id", ""),
                )
                flash(response.message, "danger")
            except ValidationError:
                record_security_event(
                    "registration",
                    outcome="failure",
                    ip_address=client_ip_address(),
                    actor_email=request.form.get("email", ""),
                    request_id=getattr(g, "request_id", ""),
                    details={"reason": "invalid_input"},
                )
                flash(text(lang, "flash_register_invalid"), "danger")

        return render_template("register.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        lang = current_language()
        user_email = current_user_email() or ""
        record_security_event(
            "logout",
            outcome="success",
            ip_address=client_ip_address(),
            actor_email=user_email,
            request_id=getattr(g, "request_id", ""),
        )
        clear_authenticated_session()
        session["language"] = lang
        flash(text(lang, "flash_logout_success"), "success")
        return redirect(url_for("home"))

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "5000")),
        debug=get_settings().debug,
    )
