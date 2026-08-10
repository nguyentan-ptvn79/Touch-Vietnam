from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


DEFAULT_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh").strip() or "Asia/Ho_Chi_Minh"


def _resolve_timezone():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(DEFAULT_TIMEZONE_NAME)
        except (KeyError, ValueError):
            return timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")
    return timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


APP_TIMEZONE = _resolve_timezone()
APP_TIMEZONE_NAME = getattr(APP_TIMEZONE, "key", DEFAULT_TIMEZONE_NAME)


def now_local() -> datetime:
    return datetime.now(APP_TIMEZONE)


def today_local() -> date:
    return now_local().date()


def parse_local_datetime(value: str | date | datetime | None) -> datetime | None:
    if value is None:
        return None

    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        raw = str(value).strip()
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(raw, fmt).replace(tzinfo=APP_TIMEZONE)
                    break
                except ValueError:
                    continue

    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=APP_TIMEZONE)
    return parsed.astimezone(APP_TIMEZONE)


def parse_local_date(value: str | date | datetime | None) -> date | None:
    parsed = parse_local_datetime(value)
    if parsed is None:
        return None
    return parsed.date()


def parse_clock_time(value: str | None) -> time | None:
    if not value:
        return None
    raw = value.strip()
    try:
        return time.fromisoformat(raw)
    except ValueError:
        return None


def combine_local_date_time(
    date_value: str | date | datetime | None, time_value: str | None
) -> datetime | None:
    parsed_date = parse_local_date(date_value)
    parsed_time = parse_clock_time(time_value)
    if parsed_date is None or parsed_time is None:
        return None
    return datetime.combine(parsed_date, parsed_time, tzinfo=APP_TIMEZONE)


def to_local_iso(value: str | date | datetime | None) -> str:
    parsed = parse_local_datetime(value)
    if parsed is None:
        return ""
    return parsed.isoformat(timespec="seconds")


def format_local_datetime(value: str | date | datetime | None, fmt: str = "%H:%M %d/%m/%Y") -> str:
    parsed = parse_local_datetime(value)
    if parsed is None:
        return ""
    return parsed.strftime(fmt)


def format_local_date(value: str | date | datetime | None, fmt: str = "%d/%m/%Y") -> str:
    parsed = parse_local_datetime(value)
    if parsed is None:
        return ""
    return parsed.strftime(fmt)
