from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from .i18n import resolve_language
from .models import ItineraryDay, ItineraryPlan, ItineraryRequest

DEFAULT_PLANNER_MODEL = os.getenv(
    "OPENAI_PLANNER_MODEL",
    os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-sol"),
)

LANGUAGE_NAMES = {
    "vi": "Vietnamese",
    "en": "English",
    "ko": "Korean",
}


class PlannerNarrativeDay(BaseModel):
    day: int = Field(ge=1, le=14)
    title: str = Field(min_length=3, max_length=160)
    morning: str = Field(min_length=3, max_length=500)
    afternoon: str = Field(min_length=3, max_length=500)
    evening: str = Field(min_length=3, max_length=500)


class PlannerNarrative(BaseModel):
    overview: str = Field(min_length=10, max_length=800)
    days: list[PlannerNarrativeDay] = Field(min_length=1, max_length=14)
    travel_tips: list[str] = Field(min_length=3, max_length=6)


def is_openai_planner_available() -> bool:
    if not os.getenv("OPENAI_API_KEY"):
        return False
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        return False
    return True


def enhance_itinerary_with_openai(
    *,
    request: ItineraryRequest,
    base_plan: ItineraryPlan,
    place_context: list[dict[str, Any]],
    language: str,
) -> ItineraryPlan:
    from openai import OpenAI

    resolved_language = resolve_language(language)
    target_language = LANGUAGE_NAMES.get(resolved_language, LANGUAGE_NAMES["vi"])
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=12.0,
        max_retries=1,
    )
    planning_input = {
        "request": {
            "departure_city": request.departure_city,
            "destination": request.destination,
            "region": request.region,
            "days": request.days,
            "budget_vnd": request.budget,
            "travelers": request.travelers,
            "interests": request.interests,
        },
        "verified_places": place_context,
        "cost_guardrails": {
            "total_estimated_cost_vnd": base_plan.total_estimated_cost,
            "daily_costs_vnd": [
                {"day": item.day, "estimated_cost": item.estimated_cost} for item in base_plan.days
            ],
        },
    }
    response = client.responses.parse(
        model=os.getenv("OPENAI_PLANNER_MODEL", DEFAULT_PLANNER_MODEL),
        instructions=(
            "You are the itinerary planner for Touch! Viet Nam. "
            f"Write the complete itinerary in {target_language}. "
            "Use only the verified destination data supplied in the input. "
            "Do not invent opening hours, prices, travel times, provider availability, or live facts. "
            "Return exactly one narrative day for every requested day. "
            "Keep activities practical, culturally respectful, and suitable for the stated group and interests. "
            "The application owns all cost calculations, so do not include or change prices in the narrative."
        ),
        input=json.dumps(planning_input, ensure_ascii=False),
        text_format=PlannerNarrative,
        reasoning={"effort": "low"},
        store=False,
        max_output_tokens=2200,
        safety_identifier="touch-vn-itinerary-planner",
    )
    narrative = response.output_parsed
    if narrative is None or len(narrative.days) != len(base_plan.days):
        raise ValueError("OpenAI itinerary did not return the requested number of days.")

    narrative_by_day = {item.day: item for item in narrative.days}
    if set(narrative_by_day) != {item.day for item in base_plan.days}:
        raise ValueError("OpenAI itinerary returned an invalid day sequence.")

    days = [
        ItineraryDay(
            day=base_day.day,
            title=narrative_by_day[base_day.day].title,
            morning=narrative_by_day[base_day.day].morning,
            afternoon=narrative_by_day[base_day.day].afternoon,
            evening=narrative_by_day[base_day.day].evening,
            estimated_cost=base_day.estimated_cost,
        )
        for base_day in base_plan.days
    ]
    return ItineraryPlan(
        destination=base_plan.destination,
        overview=narrative.overview,
        total_estimated_cost=base_plan.total_estimated_cost,
        days=days,
        travel_tips=narrative.travel_tips,
        generation_mode="openai",
    )
