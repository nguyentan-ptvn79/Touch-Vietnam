from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import ValidationError

from app.shared.integration_gateways import (
    get_integration_statuses,
    get_integration_summary,
    probe_integration,
)
from app.shared.logging_utils import configure_logging
from app.shared.models import (
    AuthResponse,
    BudgetBreakdown,
    BudgetEstimateRequest,
    ChatRequest,
    ChatResponse,
    DashboardSummary,
    ItineraryPlan,
    ItineraryRequest,
    NearbySuggestion,
    Place,
    TicketOffer,
    UserLoginRequest,
    UserRegisterRequest,
    WeatherForecast,
)
from app.shared.security_audit import record_security_event
from app.shared.services import (
    chat_support,
    estimate_budget,
    generate_itinerary,
    get_admin_recommendations,
    get_ar_landmarks,
    get_categories,
    get_dashboard_summary,
    get_must_go,
    get_nearby_places,
    get_nearby_services,
    get_offline_map_packs,
    get_place,
    get_places,
    get_regions_summary,
    get_supported_languages,
    get_weather,
    login_user,
    register_user,
    revoke_auth_token,
    search_tickets,
    verify_auth_token,
)
from app.shared.settings import get_settings, validate_production_settings

settings = get_settings()
validate_production_settings(settings)
configure_logging()
logger = logging.getLogger("touch_vn.api")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)
rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)
LanguageCode = Literal["vi", "en", "ko"]

app = FastAPI(
    title=f"{settings.app_name} API",
    version=settings.app_version,
    description="REST API for a Vietnam tourism guidance platform on web and mobile.",
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def is_rate_limited(key: str, *, limit: int, window_seconds: int) -> bool:
    now = time.time()
    bucket = rate_limit_buckets[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def client_ip_from_request(request: Request) -> str:
    remote_addr = request.client.host if request.client is not None else ""
    if remote_addr and remote_addr.lower() in settings.trusted_proxy_ips:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        forwarded_ip = forwarded_for.split(",", 1)[0].strip()
        if forwarded_ip:
            return forwarded_ip
    return remote_addr or "unknown"


def request_uses_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    remote_addr = request.client.host.lower() if request.client is not None else ""
    if remote_addr and remote_addr in settings.trusted_proxy_ips:
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
        return forwarded_proto.split(",", 1)[0].strip().lower() == "https"
    return False


async def _call_api(request: Request, call_next, request_id: str, client_ip: str):
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled API error request_id=%s path=%s",
            request_id,
            request.url.path,
        )
        record_security_event(
            "api_unhandled_exception",
            outcome="failure",
            ip_address=client_ip,
            request_id=request_id,
            details={"method": request.method, "path": request.url.path},
        )
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info(
        "request_id=%s method=%s path=%s status=%s elapsed_ms=%s ip=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        client_ip,
    )
    if response.status_code in {401, 403}:
        record_security_event(
            "api_authorization",
            outcome="denied",
            ip_address=client_ip,
            request_id=request_id,
            details={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )
    return response


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = uuid4().hex[:12]
    client_ip = client_ip_from_request(request)
    response = None
    if settings.enforce_https and not request_uses_https(request):
        target_url = f"{settings.public_base_url}{request.url.path}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"
        record_security_event(
            "api_insecure_transport",
            outcome="blocked",
            ip_address=client_ip,
            request_id=request_id,
            details={"method": request.method, "path": request.url.path},
        )
        response = RedirectResponse(target_url, status_code=308)
    elif request.method == "POST" and request.url.path in {
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/token",
    }:
        if is_rate_limited(f"auth:{client_ip}", limit=20, window_seconds=300):
            record_security_event(
                "api_auth_rate_limit",
                outcome="blocked",
                ip_address=client_ip,
                request_id=request_id,
                details={"path": request.url.path},
            )
            response = JSONResponse(
                {"detail": "Too many authentication attempts"},
                status_code=429,
            )
    elif request.method == "POST" and request.url.path == "/api/chat/support":
        if is_rate_limited(f"chat:{client_ip}", limit=60, window_seconds=60):
            record_security_event(
                "api_chat_rate_limit",
                outcome="blocked",
                ip_address=client_ip,
                request_id=request_id,
            )
            response = JSONResponse({"detail": "Too many chat requests"}, status_code=429)

    if response is None:
        response = await _call_api(request, call_next, request_id, client_ip)

    response.headers["X-Request-Id"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), geolocation=(), microphone=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    )
    if settings.environment == "production":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    if request.url.path.startswith(("/api/auth", "/api/admin")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def require_authenticated_email(
    token: str | None = Depends(oauth2_scheme),
) -> str:
    if token is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    email = verify_auth_token(token)
    if email is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return email


def require_admin_email(email: str = Depends(require_authenticated_email)) -> str:
    if not settings.is_admin_email(email):
        raise HTTPException(status_code=403, detail="Admin access required")
    return email


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "vietnam-travel-guide"}


@app.get("/api/regions")
def list_regions(lang: LanguageCode = Query(default="vi")) -> list[dict[str, str | int]]:
    return get_regions_summary(lang=lang)


@app.get("/api/categories")
def list_categories(lang: LanguageCode = Query(default="vi")) -> list[dict[str, str]]:
    return get_categories(lang=lang)


@app.get("/api/places", response_model=list[Place])
def list_places(
    region: str | None = Query(default=None),
    province: str | None = Query(default=None),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    lang: LanguageCode = Query(default="vi"),
) -> list[Place]:
    return get_places(
        region=region,
        province=province,
        category=category,
        search=search,
        lang=lang,
    )


@app.get("/api/places/{place_id}", response_model=Place)
def place_detail(place_id: str, lang: LanguageCode = Query(default="vi")) -> Place:
    place = get_place(place_id, lang=lang)
    if not place:
        raise HTTPException(status_code=404, detail="Place not found")
    return place


@app.get("/api/weather/{place_id}", response_model=WeatherForecast)
def place_weather(
    place_id: str,
    lang: LanguageCode = Query(default="vi"),
) -> WeatherForecast:
    weather = get_weather(place_id, lang=lang)
    if not weather:
        raise HTTPException(status_code=404, detail="Weather not found")
    return weather


@app.get("/api/nearby/places", response_model=list[NearbySuggestion])
def nearby_places(
    lat: float = Query(...),
    lng: float = Query(...),
    limit: int = Query(default=5, ge=1, le=10),
    lang: LanguageCode = Query(default="vi"),
) -> list[NearbySuggestion]:
    return get_nearby_places(lat=lat, lng=lng, limit=limit, lang=lang)


@app.get("/api/nearby/services", response_model=list[NearbySuggestion])
def nearby_services(
    lat: float = Query(...),
    lng: float = Query(...),
    lang: LanguageCode = Query(default="vi"),
) -> list[NearbySuggestion]:
    return get_nearby_services(lat=lat, lng=lng, lang=lang)


@app.get("/api/must-go", response_model=list[Place])
def must_go_places(
    region: str | None = None,
    province: str | None = None,
    lang: LanguageCode = Query(default="vi"),
) -> list[Place]:
    return get_must_go(region=region, province=province, lang=lang)


@app.get("/api/tickets/search", response_model=list[TicketOffer])
def ticket_search(
    origin: str,
    destination: str,
    vehicle_type: str | None = None,
    lang: LanguageCode = Query(default="vi"),
) -> list[TicketOffer]:
    return search_tickets(
        origin=origin,
        destination=destination,
        vehicle_type=vehicle_type,
        lang=lang,
    )


@app.post("/api/itinerary/plan", response_model=ItineraryPlan)
def build_itinerary(
    request: ItineraryRequest,
    lang: LanguageCode = Query(default="vi"),
) -> ItineraryPlan:
    return generate_itinerary(request, lang=lang)


@app.post("/api/budget/estimate", response_model=BudgetBreakdown)
def budget_estimate(
    request: BudgetEstimateRequest,
    lang: LanguageCode = Query(default="vi"),
) -> BudgetBreakdown:
    return estimate_budget(request, lang=lang)


@app.post("/api/chat/support", response_model=ChatResponse)
def support_chat(request: ChatRequest) -> ChatResponse:
    return chat_support(request)


@app.websocket("/api/chat/ws")
async def support_chat_websocket(websocket: WebSocket) -> None:
    client_host = websocket.client.host if websocket.client is not None else "unknown"
    await websocket.accept()
    try:
        while True:
            try:
                payload = await websocket.receive_json()
                if is_rate_limited(f"chat-ws:{client_host}", limit=60, window_seconds=60):
                    await websocket.send_json({"type": "error", "detail": "Too many chat requests"})
                    continue
                chat_request = ChatRequest.model_validate(payload)
                response = await run_in_threadpool(chat_support, chat_request)
                await websocket.send_json({"type": "message", **response.model_dump(mode="json")})
            except ValidationError as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": "Invalid chat payload",
                        "errors": exc.errors(include_url=False),
                    }
                )
            except ValueError:
                await websocket.send_json(
                    {"type": "error", "detail": "Chat payload must be valid JSON"}
                )
    except WebSocketDisconnect:
        return


@app.post("/api/auth/register", response_model=AuthResponse)
def auth_register(payload: UserRegisterRequest, request: Request) -> AuthResponse:
    response = register_user(payload)
    if response.token is None:
        record_security_event(
            "api_registration",
            outcome="failure",
            ip_address=client_ip_from_request(request),
            actor_email=payload.email,
        )
        raise HTTPException(status_code=400, detail=response.message)
    record_security_event(
        "api_registration",
        outcome="success",
        ip_address=client_ip_from_request(request),
        actor_email=response.email or "",
    )
    return response


@app.post("/api/auth/login", response_model=AuthResponse)
def auth_login(payload: UserLoginRequest, request: Request) -> AuthResponse:
    response = login_user(payload)
    if response.token is None:
        record_security_event(
            "api_login",
            outcome="failure",
            ip_address=client_ip_from_request(request),
            actor_email=payload.email,
        )
        raise HTTPException(status_code=401, detail=response.message)
    record_security_event(
        "api_login",
        outcome="success",
        ip_address=client_ip_from_request(request),
        actor_email=response.email or "",
    )
    return response


@app.post("/api/auth/token", response_model=AuthResponse)
def auth_oauth2_token(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
) -> AuthResponse:
    response = login_user(UserLoginRequest(email=form.username, password=form.password))
    if response.access_token is None:
        record_security_event(
            "api_oauth_token",
            outcome="failure",
            ip_address=client_ip_from_request(request),
            actor_email=form.username,
        )
        raise HTTPException(
            status_code=401,
            detail=response.message,
            headers={"WWW-Authenticate": "Bearer"},
        )
    record_security_event(
        "api_oauth_token",
        outcome="success",
        ip_address=client_ip_from_request(request),
        actor_email=response.email or "",
    )
    return response


@app.post("/api/auth/logout")
def auth_logout(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
) -> dict[str, str]:
    if token is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    email = verify_auth_token(token)
    if email is None or not revoke_auth_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    record_security_event(
        "api_logout",
        outcome="success",
        ip_address=client_ip_from_request(request),
        actor_email=email,
    )
    return {"message": "Logged out"}


@app.get("/api/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    lang: LanguageCode = Query(default="vi"),
    _email: str = Depends(require_authenticated_email),
) -> DashboardSummary:
    return get_dashboard_summary(lang=lang)


@app.get("/api/admin/recommendations")
def admin_recommendations(_email: str = Depends(require_admin_email)) -> list[dict[str, str]]:
    return [item.dict() for item in get_admin_recommendations()]


@app.get("/api/settings/languages")
def language_settings() -> list[dict[str, str]]:
    return get_supported_languages()


@app.get("/api/integrations/status")
def integration_status(_email: str = Depends(require_admin_email)) -> dict[str, object]:
    return {
        "summary": get_integration_summary(),
        "integrations": get_integration_statuses(),
    }


@app.get("/api/integrations/probe/{integration_key}")
def integration_probe(
    integration_key: str,
    _email: str = Depends(require_admin_email),
) -> dict[str, object]:
    try:
        return probe_integration(integration_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration not found") from exc


@app.get("/api/ar/landmarks")
def ar_landmarks(
    lang: LanguageCode = Query(default="vi"),
) -> list[dict[str, str]]:
    return get_ar_landmarks(lang=lang)


@app.get("/api/offline/maps")
def offline_maps(
    lang: LanguageCode = Query(default="vi"),
) -> list[dict[str, str]]:
    return get_offline_map_packs(lang=lang)
