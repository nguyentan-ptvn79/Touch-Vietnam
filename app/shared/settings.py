from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return tuple(dict.fromkeys(values))


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    return max(value, minimum)


@dataclass(frozen=True)
class AppSettings:
    app_name: str
    app_version: str
    environment: str
    secret_key: str
    debug: bool
    enforce_https: bool
    enable_api_docs: bool
    log_level: str
    support_email: str
    support_phone: str
    default_currency: str
    admin_emails: tuple[str, ...]
    seed_demo_users: bool
    demo_admin_full_name: str
    demo_admin_email: str
    demo_admin_password: str
    session_idle_timeout_seconds: int
    session_absolute_timeout_seconds: int
    auth_token_ttl_seconds: int
    auth_token_audience: str
    trusted_proxy_ips: tuple[str, ...]
    cors_allowed_origins: tuple[str, ...]
    data_dir: Path
    db_path: Path
    log_path: Path
    security_log_path: Path
    public_base_url: str
    max_image_pixels: int
    security_alert_window_seconds: int
    security_alert_failure_threshold: int
    integration_timeout_seconds: int
    external_ticket_api_base_url: str
    external_ticket_api_key: str
    external_ticket_search_path: str
    external_ticket_health_path: str
    external_analytics_api_base_url: str
    external_analytics_api_key: str
    external_analytics_events_path: str
    external_analytics_health_path: str
    external_ar_api_base_url: str
    external_ar_api_key: str
    external_ar_landmarks_path: str
    external_ar_place_path: str
    external_ar_health_path: str
    external_offline_map_api_base_url: str
    external_offline_map_api_key: str
    external_offline_map_packs_path: str
    external_offline_map_health_path: str
    external_weather_api_base_url: str
    external_weather_api_key: str
    external_weather_forecast_path: str
    external_weather_health_path: str
    external_nearby_api_base_url: str
    external_nearby_api_key: str
    external_nearby_search_path: str
    external_nearby_health_path: str

    def public_meta(self) -> dict[str, str]:
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "environment": self.environment,
            "support_email": self.support_email,
            "support_phone": self.support_phone,
            "default_currency": self.default_currency,
        }

    def is_admin_email(self, email: str | None) -> bool:
        if not email:
            return False
        return email.strip().lower() in self.admin_emails


def validate_production_settings(settings: AppSettings) -> None:
    if settings.environment != "production":
        return
    if settings.secret_key == "travel-guide-demo-secret" or len(settings.secret_key) < 32:  # nosec B105
        raise RuntimeError("APP_SECRET_KEY must be configured with a strong value in production.")
    if settings.debug:
        raise RuntimeError("APP_DEBUG must be disabled in production.")
    if not settings.enforce_https:
        raise RuntimeError("ENFORCE_HTTPS must be enabled in production.")
    if settings.enable_api_docs:
        raise RuntimeError("ENABLE_API_DOCS must be disabled in production.")
    if settings.seed_demo_users or settings.demo_admin_password:
        raise RuntimeError("Demo accounts must be disabled in production.")
    parsed_base_url = urlsplit(settings.public_base_url)
    if parsed_base_url.scheme != "https" or not parsed_base_url.hostname:
        raise RuntimeError("APP_PUBLIC_BASE_URL must be an absolute HTTPS URL in production.")


def get_settings() -> AppSettings:
    data_dir = Path(os.getenv("APP_DATA_DIR") or DATA_DIR).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    environment = os.getenv("APP_ENV", "development").strip().lower()
    debug_default = environment != "production"
    production = environment == "production"
    return AppSettings(
        app_name=os.getenv("APP_NAME", "Touch! Việt Nam").strip(),
        app_version=os.getenv("APP_VERSION", "1.1.0").strip(),
        environment=environment,
        secret_key=os.getenv("APP_SECRET_KEY", "travel-guide-demo-secret").strip(),
        debug=_env_flag("APP_DEBUG", debug_default),
        enforce_https=_env_flag("ENFORCE_HTTPS", production),
        enable_api_docs=_env_flag("ENABLE_API_DOCS", not production),
        log_level=os.getenv("APP_LOG_LEVEL", "INFO").strip().upper(),
        support_email=os.getenv("SUPPORT_EMAIL", "support@touchvn.com").strip(),
        support_phone=os.getenv("SUPPORT_PHONE", "+84 1900 6868").strip(),
        default_currency=os.getenv("DEFAULT_CURRENCY", "VND").strip(),
        admin_emails=_env_list(
            "ADMIN_EMAILS", "" if environment == "production" else "admin@touchvn.com"
        ),
        seed_demo_users=_env_flag("SEED_DEMO_USERS", environment != "production"),
        demo_admin_full_name=os.getenv(
            "DEMO_ADMIN_FULL_NAME", "Quản trị viên Touch! Việt Nam"
        ).strip(),
        demo_admin_email=os.getenv("DEMO_ADMIN_EMAIL", "").strip().lower(),
        demo_admin_password=os.getenv("DEMO_ADMIN_PASSWORD", "").strip(),
        session_idle_timeout_seconds=_env_int("SESSION_IDLE_TIMEOUT_SECONDS", 30 * 60, minimum=300),
        session_absolute_timeout_seconds=_env_int(
            "SESSION_ABSOLUTE_TIMEOUT_SECONDS",
            8 * 60 * 60,
            minimum=900,
        ),
        auth_token_ttl_seconds=_env_int("AUTH_TOKEN_TTL_SECONDS", 12 * 60 * 60, minimum=300),
        auth_token_audience=os.getenv("AUTH_TOKEN_AUDIENCE", "touch-vietnam-clients").strip(),
        trusted_proxy_ips=_env_list("TRUSTED_PROXY_IPS", ""),
        cors_allowed_origins=_env_list(
            "CORS_ALLOWED_ORIGINS",
            "http://127.0.0.1:5000,http://localhost:5000,http://127.0.0.1:8000,http://localhost:8000",
        ),
        data_dir=data_dir,
        db_path=data_dir / "travel_app.db",
        log_path=data_dir / "app.log",
        security_log_path=data_dir / "security-audit.log",
        public_base_url=os.getenv("APP_PUBLIC_BASE_URL", "").strip().rstrip("/"),
        max_image_pixels=_env_int("MAX_IMAGE_PIXELS", 24_000_000, minimum=1_000_000),
        security_alert_window_seconds=_env_int("SECURITY_ALERT_WINDOW_SECONDS", 300, minimum=60),
        security_alert_failure_threshold=_env_int("SECURITY_ALERT_FAILURE_THRESHOLD", 5, minimum=2),
        integration_timeout_seconds=max(int(os.getenv("INTEGRATION_TIMEOUT_SECONDS", "8")), 1),
        external_ticket_api_base_url=os.getenv("EXTERNAL_TICKET_API_BASE_URL", "")
        .strip()
        .rstrip("/"),
        external_ticket_api_key=os.getenv("EXTERNAL_TICKET_API_KEY", "").strip(),
        external_ticket_search_path=os.getenv("EXTERNAL_TICKET_SEARCH_PATH", "/search").strip(),
        external_ticket_health_path=os.getenv("EXTERNAL_TICKET_HEALTH_PATH", "/health").strip(),
        external_analytics_api_base_url=os.getenv("EXTERNAL_ANALYTICS_API_BASE_URL", "")
        .strip()
        .rstrip("/"),
        external_analytics_api_key=os.getenv("EXTERNAL_ANALYTICS_API_KEY", "").strip(),
        external_analytics_events_path=os.getenv(
            "EXTERNAL_ANALYTICS_EVENTS_PATH", "/events"
        ).strip(),
        external_analytics_health_path=os.getenv(
            "EXTERNAL_ANALYTICS_HEALTH_PATH", "/health"
        ).strip(),
        external_ar_api_base_url=os.getenv("EXTERNAL_AR_API_BASE_URL", "").strip().rstrip("/"),
        external_ar_api_key=os.getenv("EXTERNAL_AR_API_KEY", "").strip(),
        external_ar_landmarks_path=os.getenv("EXTERNAL_AR_LANDMARKS_PATH", "/landmarks").strip(),
        external_ar_place_path=os.getenv("EXTERNAL_AR_PLACE_PATH", "/places/{place_id}").strip(),
        external_ar_health_path=os.getenv("EXTERNAL_AR_HEALTH_PATH", "/health").strip(),
        external_offline_map_api_base_url=os.getenv("EXTERNAL_OFFLINE_MAP_API_BASE_URL", "")
        .strip()
        .rstrip("/"),
        external_offline_map_api_key=os.getenv("EXTERNAL_OFFLINE_MAP_API_KEY", "").strip(),
        external_offline_map_packs_path=os.getenv(
            "EXTERNAL_OFFLINE_MAP_PACKS_PATH", "/packs"
        ).strip(),
        external_offline_map_health_path=os.getenv(
            "EXTERNAL_OFFLINE_MAP_HEALTH_PATH", "/health"
        ).strip(),
        external_weather_api_base_url=os.getenv("EXTERNAL_WEATHER_API_BASE_URL", "")
        .strip()
        .rstrip("/"),
        external_weather_api_key=os.getenv("EXTERNAL_WEATHER_API_KEY", "").strip(),
        external_weather_forecast_path=os.getenv(
            "EXTERNAL_WEATHER_FORECAST_PATH", "/forecast"
        ).strip(),
        external_weather_health_path=os.getenv("EXTERNAL_WEATHER_HEALTH_PATH", "/health").strip(),
        external_nearby_api_base_url=os.getenv("EXTERNAL_NEARBY_API_BASE_URL", "")
        .strip()
        .rstrip("/"),
        external_nearby_api_key=os.getenv("EXTERNAL_NEARBY_API_KEY", "").strip(),
        external_nearby_search_path=os.getenv("EXTERNAL_NEARBY_SEARCH_PATH", "/search").strip(),
        external_nearby_health_path=os.getenv("EXTERNAL_NEARBY_HEALTH_PATH", "/health").strip(),
    )
