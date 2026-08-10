from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RegionCode = Literal["north", "central", "south"]
CategoryCode = Literal[
    "mountain",
    "island",
    "beach",
    "spiritual",
    "culture",
    "food",
    "history",
    "entertainment",
]


class Coordinate(BaseModel):
    lat: float
    lng: float


class Place(BaseModel):
    id: str
    name: str
    region: RegionCode
    province: str
    categories: list[CategoryCode]
    description: str
    highlights: list[str]
    ticket_price: float
    avg_spend: float
    rating: float
    must_go_score: int
    coordinate: Coordinate
    nearby_services: list[str]
    transport_modes: list[str]
    image_hint: str


class NearbySuggestion(BaseModel):
    name: str
    kind: str
    province: str
    distance_km: float
    note: str


class WeatherForecast(BaseModel):
    destination: str
    forecast_date: str
    temperature_c: int
    condition: str
    advice: str
    best_visit_time: str
    temperature_high_c: int | None = None
    temperature_low_c: int | None = None
    wind_speed_kmh: float | None = None
    source: str | None = None
    updated_at: str | None = None


class TicketOffer(BaseModel):
    provider: str
    vehicle_type: str
    origin: str
    destination: str
    departure: str
    departure_date: str | None = None
    arrival: str | None = None
    duration: str | None = None
    seat_class: str | None = None
    available_seats: int | None = None
    operator_note: str | None = None
    price: float
    booking_url: str


class ItineraryRequest(BaseModel):
    departure_city: str = Field(default="", max_length=120)
    region: RegionCode | None = None
    destination: str | None = Field(default=None, max_length=120)
    days: int = Field(default=3, ge=1, le=14)
    budget: float = Field(default=3_000_000, ge=0)
    travelers: int = Field(default=2, ge=1, le=20)
    interests: list[str] = Field(default_factory=list, max_length=20)


class ItineraryDay(BaseModel):
    day: int
    title: str
    morning: str
    afternoon: str
    evening: str
    estimated_cost: float


class ItineraryPlan(BaseModel):
    destination: str
    overview: str
    total_estimated_cost: float
    days: list[ItineraryDay]
    travel_tips: list[str]
    generation_mode: Literal["openai", "smart-fallback"] = "smart-fallback"


class BudgetEstimateRequest(BaseModel):
    travelers: int = Field(default=2, ge=1, le=50)
    days: int = Field(default=3, ge=1, le=30)
    region: RegionCode = "north"
    transport_mode: Literal["plane", "train", "bus", "car"] = "plane"
    accommodation_level: Literal["budget", "midrange", "premium"] = "midrange"
    include_tickets: bool = True


class BudgetBreakdown(BaseModel):
    transport: float
    stay: float
    food: float
    attraction_tickets: float
    emergency_fund: float
    total: float
    note: str


class DashboardMetric(BaseModel):
    name: str
    value: str
    trend: str


class DashboardSummary(BaseModel):
    metrics: list[DashboardMetric]
    top_places: list[str]
    recommended_upgrades: list[str]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    language: Literal["vi", "en", "ko"] = "vi"


class ChatResponse(BaseModel):
    answer: str
    suggested_actions: list[str]


class UserRegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def reject_common_passwords(cls, value: str) -> str:
        normalized = value.strip().lower()
        common_passwords = {
            "1234567890",
            "admin12345",
            "password123",
            "qwerty12345",
            "touchvn123",
        }
        if normalized in common_passwords or len(set(normalized)) < 4:
            raise ValueError("Password is too common.")
        return value


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    message: str
    token: str | None = None
    access_token: str | None = None
    token_type: Literal["bearer"] = "bearer"
    expires_in: int | None = None
    full_name: str | None = None
    email: str | None = None


class AdminRecommendation(BaseModel):
    id: int | None = None
    title: str
    detail: str
    priority: Literal["high", "medium", "low"]
    is_active: bool = True
    display_order: int = 0
    title_vi: str | None = None
    detail_vi: str | None = None
    title_en: str | None = None
    detail_en: str | None = None
    title_ko: str | None = None
    detail_ko: str | None = None
