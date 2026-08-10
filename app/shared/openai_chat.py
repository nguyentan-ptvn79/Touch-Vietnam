from __future__ import annotations

import os
from typing import Any

from .i18n import resolve_language

DEFAULT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-sol")

LANGUAGE_NAMES = {
    "vi": "Vietnamese",
    "en": "English",
    "ko": "Korean",
}


def is_openai_available() -> bool:
    if not os.getenv("OPENAI_API_KEY"):
        return False
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        return False
    return True


def build_system_prompt(language: str, context: str | None = None) -> str:
    lang = resolve_language(language)
    target_language = LANGUAGE_NAMES.get(lang, LANGUAGE_NAMES["vi"])
    prompt = (
        "You are the travel assistant for the Touch! Viet Nam application. "
        "Help users plan trips in Vietnam with clear, practical, friendly answers. "
        f"Always answer in {target_language}. "
        "Stay focused on travel in Vietnam, itinerary planning, budgeting, tickets, places nearby, "
        "cultural highlights, safety tips, and app features. "
        "If the user asks for current facts you cannot verify from the provided context, "
        "say that the answer is based on the app's current data and suggest checking the latest live data. "
        "Keep answers concise but helpful."
    )
    if context:
        prompt = f"{prompt}\n\nCurrent app context:\n{context}"
    return prompt


def generate_openai_chat_answer(
    question: str,
    language: str,
    history: list[dict[str, str]],
    context: str | None = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    messages: list[dict[str, Any]] = [
        {"role": item["role"], "content": item["content"]}
        for item in history
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    messages.append({"role": "user", "content": question})

    response = client.responses.create(
        model=os.getenv("OPENAI_CHAT_MODEL", DEFAULT_MODEL),
        instructions=build_system_prompt(language, context=context),
        input=messages,
        store=False,
        max_output_tokens=500,
    )
    answer = (response.output_text or "").strip()
    if not answer:
        raise ValueError("OpenAI returned an empty response.")
    return answer
