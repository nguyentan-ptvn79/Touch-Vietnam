"""SQLite persistence helpers and schema management for local deployments."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, TypedDict

from werkzeug.security import check_password_hash, generate_password_hash

from .i18n import text
from .models import Coordinate, Place
from .settings import get_settings
from .time_utils import today_local

SETTINGS = get_settings()
DATA_DIR = SETTINGS.data_dir
DB_PATH = SETTINGS.db_path


class UserRecord(TypedDict):
    full_name: str
    email: str
    password_hash: str


class ChatMessageRecord(TypedDict):
    role: str
    content: str
    created_at: str


class SavedTripRecord(TypedDict):
    id: int
    title: str
    departure_city: str
    destination: str
    region: str | None
    days: int
    travelers: int
    budget_total: float
    itinerary_total: float
    itinerary_data: dict[str, Any]
    budget_data: dict[str, Any]
    created_at: str


class ExpenseItemRecord(TypedDict):
    id: int
    trip_id: int
    title: str
    category: str
    paid_by: str
    split_members: list[str]
    amount: float
    note: str
    created_at: str


class TicketBookingRecord(TypedDict):
    id: int
    booking_reference: str
    user_email: str
    provider: str
    vehicle_type: str
    origin: str
    destination: str
    departure_date: str
    departure_time: str
    arrival_time: str
    seat_class: str
    contact_name: str
    contact_email: str
    contact_phone: str
    amount: float
    status: str
    created_at: str


class DashboardBlockVisibilityRecord(TypedDict):
    block_key: str
    is_visible: bool
    updated_by: str | None
    updated_at: str | None


class ManagedPlaceRecord(TypedDict):
    place: Place
    is_active: bool
    updated_by: str | None
    updated_at: str | None


class SiteContentSettingRecord(TypedDict):
    key: str
    value: str
    updated_by: str | None
    updated_at: str | None


class AdminRecommendationRecord(TypedDict):
    id: int
    title_vi: str
    detail_vi: str
    title_en: str
    detail_en: str
    title_ko: str
    detail_ko: str
    priority: str
    display_order: int
    is_active: bool
    updated_by: str | None
    updated_at: str | None
    created_at: str | None


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _create_schema() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                language TEXT NOT NULL,
                user_name TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
            ON chat_messages(session_id, id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                title TEXT NOT NULL,
                departure_city TEXT NOT NULL,
                destination TEXT NOT NULL,
                region TEXT,
                days INTEGER NOT NULL,
                travelers INTEGER NOT NULL,
                budget_total REAL NOT NULL,
                itinerary_total REAL NOT NULL,
                itinerary_json TEXT NOT NULL,
                budget_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_email) REFERENCES users(email)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_saved_trips_user_email
            ON saved_trips(user_email, id DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS expense_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                trip_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                paid_by TEXT NOT NULL,
                split_members_json TEXT NOT NULL DEFAULT '[]',
                amount REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_email) REFERENCES users(email),
                FOREIGN KEY(trip_id) REFERENCES saved_trips(id)
            )
            """
        )
        expense_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(expense_items)").fetchall()
        }
        if "split_members_json" not in expense_columns:
            connection.execute(
                """
                ALTER TABLE expense_items
                ADD COLUMN split_members_json TEXT NOT NULL DEFAULT '[]'
                """
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_expense_items_user_trip
            ON expense_items(user_email, trip_id, id DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_reference TEXT NOT NULL UNIQUE,
                user_email TEXT NOT NULL,
                provider TEXT NOT NULL,
                vehicle_type TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                departure_date TEXT NOT NULL,
                departure_time TEXT NOT NULL,
                arrival_time TEXT NOT NULL DEFAULT '',
                seat_class TEXT NOT NULL DEFAULT '',
                contact_name TEXT NOT NULL,
                contact_email TEXT NOT NULL,
                contact_phone TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'reserved',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_email) REFERENCES users(email)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ticket_bookings_user_email
            ON ticket_bookings(user_email, id DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_block_visibility (
                block_key TEXT PRIMARY KEY,
                is_visible INTEGER NOT NULL DEFAULT 1,
                updated_by TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS managed_places (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                region TEXT NOT NULL,
                province TEXT NOT NULL,
                categories_json TEXT NOT NULL,
                description TEXT NOT NULL,
                highlights_json TEXT NOT NULL,
                ticket_price REAL NOT NULL,
                avg_spend REAL NOT NULL,
                rating REAL NOT NULL,
                must_go_score INTEGER NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                nearby_services_json TEXT NOT NULL,
                transport_modes_json TEXT NOT NULL,
                image_hint TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_by TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS site_content_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_by TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title_vi TEXT NOT NULL,
                detail_vi TEXT NOT NULL,
                title_en TEXT NOT NULL DEFAULT '',
                detail_en TEXT NOT NULL DEFAULT '',
                title_ko TEXT NOT NULL DEFAULT '',
                detail_ko TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'medium',
                display_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS page_view_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                method TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                response_ms REAL NOT NULL DEFAULT 0,
                user_email TEXT,
                language TEXT,
                request_id TEXT,
                visitor_key TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS revoked_auth_tokens (
                jti TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL,
                revoked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_revoked_auth_tokens_expires_at
            ON revoked_auth_tokens(expires_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_page_view_events_created_at
            ON page_view_events(created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_page_view_events_path
            ON page_view_events(path, created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_page_view_events_visitor
            ON page_view_events(visitor_key, created_at DESC)
            """
        )
        connection.commit()


def ensure_db() -> None:
    try:
        _create_schema()
    except sqlite3.DatabaseError:
        # Recover automatically if the SQLite file is corrupted or replaced.
        if DB_PATH.exists():
            DB_PATH.unlink()
        _create_schema()
    if SETTINGS.seed_demo_users:
        _seed_demo_users()
    _seed_default_recommendations()


def _seed_demo_users() -> None:
    if not SETTINGS.demo_admin_email or not SETTINGS.demo_admin_password:
        return
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO NOTHING
            """,
            (
                SETTINGS.demo_admin_full_name,
                SETTINGS.demo_admin_email,
                generate_password_hash(SETTINGS.demo_admin_password),
            ),
        )
        connection.commit()


def _seed_default_recommendations() -> None:
    seed_marker_key = "admin_recommendations_seeded"
    defaults = [
        {
            "title_vi": text("vi", "admin_rec_1_title"),
            "detail_vi": text("vi", "admin_rec_1_detail"),
            "title_en": text("en", "admin_rec_1_title"),
            "detail_en": text("en", "admin_rec_1_detail"),
            "title_ko": text("ko", "admin_rec_1_title"),
            "detail_ko": text("ko", "admin_rec_1_detail"),
            "priority": "high",
            "display_order": 10,
        },
        {
            "title_vi": text("vi", "admin_rec_2_title"),
            "detail_vi": text("vi", "admin_rec_2_detail"),
            "title_en": text("en", "admin_rec_2_title"),
            "detail_en": text("en", "admin_rec_2_detail"),
            "title_ko": text("ko", "admin_rec_2_title"),
            "detail_ko": text("ko", "admin_rec_2_detail"),
            "priority": "high",
            "display_order": 20,
        },
        {
            "title_vi": text("vi", "admin_rec_3_title"),
            "detail_vi": text("vi", "admin_rec_3_detail"),
            "title_en": text("en", "admin_rec_3_title"),
            "detail_en": text("en", "admin_rec_3_detail"),
            "title_ko": text("ko", "admin_rec_3_title"),
            "detail_ko": text("ko", "admin_rec_3_detail"),
            "priority": "medium",
            "display_order": 30,
        },
    ]
    with _connect() as connection:
        marker = connection.execute(
            "SELECT value FROM site_content_settings WHERE key = ?",
            (seed_marker_key,),
        ).fetchone()
        if marker is not None:
            return
        row = connection.execute("SELECT COUNT(*) AS total FROM admin_recommendations").fetchone()
        if row is not None and int(row["total"]) > 0:
            connection.execute(
                """
                INSERT INTO site_content_settings (key, value, updated_by, updated_at)
                VALUES (?, '1', 'system', CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO NOTHING
                """,
                (seed_marker_key,),
            )
            connection.commit()
            return
        for item in defaults:
            connection.execute(
                """
                INSERT INTO admin_recommendations (
                    title_vi,
                    detail_vi,
                    title_en,
                    detail_en,
                    title_ko,
                    detail_ko,
                    priority,
                    display_order,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    item["title_vi"],
                    item["detail_vi"],
                    item["title_en"],
                    item["detail_en"],
                    item["title_ko"],
                    item["detail_ko"],
                    item["priority"],
                    item["display_order"],
                ),
            )
        connection.execute(
            """
            INSERT INTO site_content_settings (key, value, updated_by, updated_at)
            VALUES (?, '1', 'system', CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO NOTHING
            """,
            (seed_marker_key,),
        )
        connection.commit()


def find_user_by_email(email: str) -> UserRecord | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT full_name, email, password_hash FROM users WHERE email = ?",
            (email.lower(),),
        ).fetchone()
    if row is None:
        return None
    return {
        "full_name": row["full_name"],
        "email": row["email"],
        "password_hash": row["password_hash"],
    }


def create_user(full_name: str, email: str, password: str) -> bool:
    if find_user_by_email(email) is not None:
        return False
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash)
            VALUES (?, ?, ?)
            """,
            (
                full_name,
                email.lower(),
                generate_password_hash(password),
            ),
        )
        connection.commit()
    return True


def verify_user(email: str, password: str) -> UserRecord | None:
    user = find_user_by_email(email)
    if user is None:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return user


def revoke_auth_token_id(jti: str, expires_at: int) -> None:
    normalized_jti = jti.strip()
    if not normalized_jti:
        return
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO revoked_auth_tokens (jti, expires_at)
            VALUES (?, ?)
            ON CONFLICT(jti) DO UPDATE SET
                expires_at = excluded.expires_at,
                revoked_at = CURRENT_TIMESTAMP
            """,
            (normalized_jti, int(expires_at)),
        )
        connection.commit()


def is_auth_token_revoked(jti: str, now_epoch: int) -> bool:
    normalized_jti = jti.strip()
    if not normalized_jti:
        return True
    with _connect() as connection:
        connection.execute(
            "DELETE FROM revoked_auth_tokens WHERE expires_at <= ?",
            (int(now_epoch),),
        )
        row = connection.execute(
            "SELECT 1 FROM revoked_auth_tokens WHERE jti = ?",
            (normalized_jti,),
        ).fetchone()
        connection.commit()
    return row is not None


def count_users() -> int:
    with _connect() as connection:
        result = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
    return int(result["total"]) if result is not None else 0


def ensure_chat_session(session_id: str, language: str, user_name: str | None = None) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions (id, language, user_name)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (session_id, language, user_name),
        )
        connection.execute(
            """
            UPDATE chat_sessions
            SET language = ?, user_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (language, user_name, session_id),
        )
        connection.commit()


def add_chat_message(session_id: str, role: str, content: str) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO chat_messages (session_id, role, content)
            VALUES (?, ?, ?)
            """,
            (session_id, role, content),
        )
        connection.execute(
            """
            UPDATE chat_sessions
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (session_id,),
        )
        connection.commit()


def get_chat_messages(session_id: str, limit: int = 20) -> list[ChatMessageRecord]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT role, content, created_at
            FROM (
                SELECT role, content, created_at, id
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (session_id, limit),
        ).fetchall()
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def clear_chat_messages(session_id: str) -> None:
    with _connect() as connection:
        connection.execute(
            "DELETE FROM chat_messages WHERE session_id = ?",
            (session_id,),
        )
        connection.execute(
            """
            UPDATE chat_sessions
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (session_id,),
        )
        connection.commit()


def save_trip(
    *,
    user_email: str,
    title: str,
    departure_city: str,
    destination: str,
    region: str | None,
    days: int,
    travelers: int,
    budget_total: float,
    itinerary_total: float,
    itinerary_data: dict[str, Any],
    budget_data: dict[str, Any],
) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO saved_trips (
                user_email,
                title,
                departure_city,
                destination,
                region,
                days,
                travelers,
                budget_total,
                itinerary_total,
                itinerary_json,
                budget_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_email.lower(),
                title,
                departure_city,
                destination,
                region,
                days,
                travelers,
                budget_total,
                itinerary_total,
                json.dumps(itinerary_data, ensure_ascii=False),
                json.dumps(budget_data, ensure_ascii=False),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def _parse_trip_row(row: sqlite3.Row) -> SavedTripRecord:
    itinerary_data = json.loads(row["itinerary_json"])
    budget_data = json.loads(row["budget_json"])
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "departure_city": row["departure_city"],
        "destination": row["destination"],
        "region": row["region"],
        "days": int(row["days"]),
        "travelers": int(row["travelers"]),
        "budget_total": float(row["budget_total"]),
        "itinerary_total": float(row["itinerary_total"]),
        "itinerary_data": itinerary_data,
        "budget_data": budget_data,
        "created_at": row["created_at"],
    }


def list_saved_trips(user_email: str, limit: int = 20) -> list[SavedTripRecord]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM saved_trips
            WHERE user_email = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_email.lower(), limit),
        ).fetchall()
    return [_parse_trip_row(row) for row in rows]


def get_saved_trip(user_email: str, trip_id: int) -> SavedTripRecord | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM saved_trips
            WHERE user_email = ? AND id = ?
            """,
            (user_email.lower(), trip_id),
        ).fetchone()
    if row is None:
        return None
    return _parse_trip_row(row)


def count_saved_trips(user_email: str) -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM saved_trips WHERE user_email = ?",
            (user_email.lower(),),
        ).fetchone()
    return int(row["total"]) if row is not None else 0


def create_expense_item(
    *,
    user_email: str,
    trip_id: int,
    title: str,
    category: str,
    paid_by: str,
    split_members: list[str],
    amount: float,
    note: str,
) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO expense_items (
                user_email,
                trip_id,
                title,
                category,
                paid_by,
                split_members_json,
                amount,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_email.lower(),
                trip_id,
                title,
                category,
                paid_by,
                json.dumps(split_members, ensure_ascii=False),
                amount,
                note,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_expense_items(
    user_email: str,
    trip_id: int | None = None,
    limit: int = 100,
) -> list[ExpenseItemRecord]:
    with _connect() as connection:
        if trip_id is None:
            rows = connection.execute(
                """
                SELECT id, trip_id, title, category, paid_by, split_members_json,
                       amount, note, created_at
                FROM expense_items
                WHERE user_email = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_email.lower(), limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, trip_id, title, category, paid_by, split_members_json,
                       amount, note, created_at
                FROM expense_items
                WHERE user_email = ? AND trip_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_email.lower(), trip_id, limit),
            ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "trip_id": int(row["trip_id"]),
            "title": row["title"],
            "category": row["category"],
            "paid_by": row["paid_by"],
            "split_members": json.loads(row["split_members_json"] or "[]"),
            "amount": float(row["amount"]),
            "note": row["note"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def create_ticket_booking(
    *,
    booking_reference: str,
    user_email: str,
    provider: str,
    vehicle_type: str,
    origin: str,
    destination: str,
    departure_date: str,
    departure_time: str,
    arrival_time: str,
    seat_class: str,
    contact_name: str,
    contact_email: str,
    contact_phone: str,
    amount: float,
    status: str = "reserved",
) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO ticket_bookings (
                booking_reference,
                user_email,
                provider,
                vehicle_type,
                origin,
                destination,
                departure_date,
                departure_time,
                arrival_time,
                seat_class,
                contact_name,
                contact_email,
                contact_phone,
                amount,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking_reference,
                user_email.lower(),
                provider,
                vehicle_type,
                origin,
                destination,
                departure_date,
                departure_time,
                arrival_time,
                seat_class,
                contact_name,
                contact_email.lower(),
                contact_phone,
                amount,
                status,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_ticket_bookings(user_email: str, limit: int = 20) -> list[TicketBookingRecord]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM ticket_bookings
            WHERE user_email = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_email.lower(), limit),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "booking_reference": row["booking_reference"],
            "user_email": row["user_email"],
            "provider": row["provider"],
            "vehicle_type": row["vehicle_type"],
            "origin": row["origin"],
            "destination": row["destination"],
            "departure_date": row["departure_date"],
            "departure_time": row["departure_time"],
            "arrival_time": row["arrival_time"],
            "seat_class": row["seat_class"],
            "contact_name": row["contact_name"],
            "contact_email": row["contact_email"],
            "contact_phone": row["contact_phone"],
            "amount": float(row["amount"]),
            "status": row["status"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def count_ticket_bookings(user_email: str | None = None) -> int:
    with _connect() as connection:
        if user_email:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM ticket_bookings WHERE user_email = ?",
                (user_email.lower(),),
            ).fetchone()
        else:
            row = connection.execute("SELECT COUNT(*) AS total FROM ticket_bookings").fetchone()
    return int(row["total"]) if row is not None else 0


def sum_ticket_booking_revenue() -> float:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM ticket_bookings
            WHERE status NOT IN ('cancelled', 'refunded')
            """
        ).fetchone()
    return float(row["total"]) if row is not None else 0.0


def record_page_view(
    *,
    path: str,
    method: str,
    status_code: int,
    response_ms: float,
    user_email: str | None,
    language: str | None,
    request_id: str | None,
    visitor_key: str | None,
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO page_view_events (
                path,
                method,
                status_code,
                response_ms,
                user_email,
                language,
                request_id,
                visitor_key
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                path.strip() or "/",
                method.strip().upper() or "GET",
                int(status_code),
                float(response_ms),
                user_email.lower() if user_email else None,
                language.strip().lower() if language else None,
                request_id.strip() if request_id else None,
                visitor_key.strip() if visitor_key else None,
            ),
        )
        connection.commit()


def count_page_views(days: int | None = None) -> int:
    with _connect() as connection:
        if days is None:
            row = connection.execute("SELECT COUNT(*) AS total FROM page_view_events").fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM page_view_events "
                "WHERE created_at >= datetime('now', ?)",
                (f"-{max(1, int(days))} day",),
            ).fetchone()
    return int(row["total"]) if row is not None else 0


def count_unique_visitors(days: int | None = None) -> int:
    with _connect() as connection:
        if days is None:
            row = connection.execute(
                "SELECT COUNT(DISTINCT visitor_key) AS total FROM page_view_events"
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(DISTINCT visitor_key) AS total "
                "FROM page_view_events WHERE created_at >= datetime('now', ?)",
                (f"-{max(1, int(days))} day",),
            ).fetchone()
    return int(row["total"]) if row is not None else 0


def count_returning_visitors(days: int | None = None) -> int:
    with _connect() as connection:
        if days is None:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM ("
                "SELECT visitor_key FROM page_view_events "
                "GROUP BY visitor_key HAVING COUNT(*) >= 2)"
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM ("
                "SELECT visitor_key FROM page_view_events "
                "WHERE created_at >= datetime('now', ?) "
                "GROUP BY visitor_key HAVING COUNT(*) >= 2)",
                (f"-{max(1, int(days))} day",),
            ).fetchone()
    return int(row["total"]) if row is not None else 0


def list_top_page_views(limit: int = 5, days: int | None = 30) -> list[dict[str, Any]]:
    with _connect() as connection:
        safe_limit = max(1, min(int(limit), 50))
        if days is None:
            rows = connection.execute(
                "SELECT path, COUNT(*) AS total FROM page_view_events "
                "GROUP BY path ORDER BY total DESC, path ASC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT path, COUNT(*) AS total FROM page_view_events "
                "WHERE created_at >= datetime('now', ?) "
                "GROUP BY path ORDER BY total DESC, path ASC LIMIT ?",
                (f"-{max(1, int(days))} day", safe_limit),
            ).fetchall()
    return [{"path": row["path"], "total": int(row["total"])} for row in rows]


def list_daily_page_views(days: int = 7) -> list[dict[str, Any]]:
    total_days = max(1, int(days))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT DATE(created_at) AS view_date, COUNT(*) AS total
            FROM page_view_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY DATE(created_at)
            ORDER BY view_date ASC
            """,
            (f"-{total_days} day",),
        ).fetchall()

    row_map = {str(row["view_date"]): int(row["total"]) for row in rows}
    today = today_local()
    result: list[dict[str, Any]] = []
    for offset in range(total_days - 1, -1, -1):
        day_value = today - timedelta(days=offset)
        iso_value = day_value.isoformat()
        result.append(
            {
                "date": iso_value,
                "label": day_value.strftime("%d/%m"),
                "total": row_map.get(iso_value, 0),
            }
        )
    return result


def list_dashboard_block_visibility(
    block_keys: list[str],
) -> list[DashboardBlockVisibilityRecord]:
    if not block_keys:
        return []

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT block_key, is_visible, updated_by, updated_at
            FROM dashboard_block_visibility
            """
        ).fetchall()

    requested_keys = set(block_keys)
    row_map = {
        str(row["block_key"]): row for row in rows if str(row["block_key"]) in requested_keys
    }
    return [
        {
            "block_key": block_key,
            "is_visible": bool(row_map[block_key]["is_visible"]) if block_key in row_map else True,
            "updated_by": row_map[block_key]["updated_by"] if block_key in row_map else None,
            "updated_at": row_map[block_key]["updated_at"] if block_key in row_map else None,
        }
        for block_key in block_keys
    ]


def save_dashboard_block_visibility(
    block_keys: list[str],
    visible_keys: set[str],
    updated_by: str | None,
) -> None:
    if not block_keys:
        return

    with _connect() as connection:
        for block_key in block_keys:
            connection.execute(
                """
                INSERT INTO dashboard_block_visibility (
                    block_key,
                    is_visible,
                    updated_by,
                    updated_at
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(block_key) DO UPDATE SET
                    is_visible = excluded.is_visible,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    block_key,
                    1 if block_key in visible_keys else 0,
                    updated_by.lower() if updated_by else None,
                ),
            )
        connection.commit()


def _place_to_row(place: Place) -> tuple[Any, ...]:
    return (
        place.id,
        place.name,
        place.region,
        place.province,
        json.dumps(place.categories, ensure_ascii=False),
        place.description,
        json.dumps(place.highlights, ensure_ascii=False),
        place.ticket_price,
        place.avg_spend,
        place.rating,
        place.must_go_score,
        place.coordinate.lat,
        place.coordinate.lng,
        json.dumps(place.nearby_services, ensure_ascii=False),
        json.dumps(place.transport_modes, ensure_ascii=False),
        place.image_hint,
    )


def _place_from_row(row: sqlite3.Row) -> Place:
    return Place(
        id=row["id"],
        name=row["name"],
        region=row["region"],
        province=row["province"],
        categories=json.loads(row["categories_json"]),
        description=row["description"],
        highlights=json.loads(row["highlights_json"]),
        ticket_price=float(row["ticket_price"]),
        avg_spend=float(row["avg_spend"]),
        rating=float(row["rating"]),
        must_go_score=int(row["must_go_score"]),
        coordinate=Coordinate(lat=float(row["lat"]), lng=float(row["lng"])),
        nearby_services=json.loads(row["nearby_services_json"]),
        transport_modes=json.loads(row["transport_modes_json"]),
        image_hint=row["image_hint"],
    )


def list_managed_places(include_inactive: bool = True) -> list[ManagedPlaceRecord]:
    with _connect() as connection:
        if include_inactive:
            rows = connection.execute(
                """
                SELECT *
                FROM managed_places
                ORDER BY updated_at DESC, name ASC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM managed_places
                WHERE is_active = 1
                ORDER BY updated_at DESC, name ASC
                """
            ).fetchall()

    return [
        {
            "place": _place_from_row(row),
            "is_active": bool(row["is_active"]),
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def upsert_managed_place(
    *,
    place: Place,
    is_active: bool,
    updated_by: str | None,
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO managed_places (
                id,
                name,
                region,
                province,
                categories_json,
                description,
                highlights_json,
                ticket_price,
                avg_spend,
                rating,
                must_go_score,
                lat,
                lng,
                nearby_services_json,
                transport_modes_json,
                image_hint,
                is_active,
                updated_by,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                region = excluded.region,
                province = excluded.province,
                categories_json = excluded.categories_json,
                description = excluded.description,
                highlights_json = excluded.highlights_json,
                ticket_price = excluded.ticket_price,
                avg_spend = excluded.avg_spend,
                rating = excluded.rating,
                must_go_score = excluded.must_go_score,
                lat = excluded.lat,
                lng = excluded.lng,
                nearby_services_json = excluded.nearby_services_json,
                transport_modes_json = excluded.transport_modes_json,
                image_hint = excluded.image_hint,
                is_active = excluded.is_active,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                *_place_to_row(place),
                1 if is_active else 0,
                updated_by.lower() if updated_by else None,
            ),
        )
        connection.commit()


def list_site_content_settings() -> list[SiteContentSettingRecord]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT key, value, updated_by, updated_at
            FROM site_content_settings
            ORDER BY key ASC
            """
        ).fetchall()
    return [
        {
            "key": row["key"],
            "value": row["value"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def save_site_content_settings(
    values: dict[str, str],
    updated_by: str | None,
) -> None:
    with _connect() as connection:
        for key, value in values.items():
            cleaned = value.strip()
            if not cleaned:
                connection.execute(
                    "DELETE FROM site_content_settings WHERE key = ?",
                    (key,),
                )
                continue
            connection.execute(
                """
                INSERT INTO site_content_settings (key, value, updated_by, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    key,
                    cleaned,
                    updated_by.lower() if updated_by else None,
                ),
            )
        connection.commit()


def _recommendation_from_row(row: sqlite3.Row) -> AdminRecommendationRecord:
    return {
        "id": int(row["id"]),
        "title_vi": row["title_vi"],
        "detail_vi": row["detail_vi"],
        "title_en": row["title_en"],
        "detail_en": row["detail_en"],
        "title_ko": row["title_ko"],
        "detail_ko": row["detail_ko"],
        "priority": row["priority"],
        "display_order": int(row["display_order"]),
        "is_active": bool(row["is_active"]),
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
    }


def list_admin_recommendations(include_inactive: bool = False) -> list[AdminRecommendationRecord]:
    with _connect() as connection:
        if include_inactive:
            rows = connection.execute(
                """
                SELECT *
                FROM admin_recommendations
                ORDER BY display_order ASC, id ASC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM admin_recommendations
                WHERE is_active = 1
                ORDER BY display_order ASC, id ASC
                """
            ).fetchall()
    return [_recommendation_from_row(row) for row in rows]


def get_admin_recommendation(recommendation_id: int) -> AdminRecommendationRecord | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM admin_recommendations WHERE id = ?",
            (recommendation_id,),
        ).fetchone()
    if row is None:
        return None
    return _recommendation_from_row(row)


def upsert_admin_recommendation(
    *,
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
    updated_by: str | None,
) -> int:
    with _connect() as connection:
        if recommendation_id is None:
            cursor = connection.execute(
                """
                INSERT INTO admin_recommendations (
                    title_vi,
                    detail_vi,
                    title_en,
                    detail_en,
                    title_ko,
                    detail_ko,
                    priority,
                    display_order,
                    is_active,
                    updated_by,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    title_vi,
                    detail_vi,
                    title_en,
                    detail_en,
                    title_ko,
                    detail_ko,
                    priority,
                    display_order,
                    1 if is_active else 0,
                    updated_by.lower() if updated_by else None,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

        connection.execute(
            """
            UPDATE admin_recommendations
            SET
                title_vi = ?,
                detail_vi = ?,
                title_en = ?,
                detail_en = ?,
                title_ko = ?,
                detail_ko = ?,
                priority = ?,
                display_order = ?,
                is_active = ?,
                updated_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                title_vi,
                detail_vi,
                title_en,
                detail_en,
                title_ko,
                detail_ko,
                priority,
                display_order,
                1 if is_active else 0,
                updated_by.lower() if updated_by else None,
                recommendation_id,
            ),
        )
        connection.commit()
    return recommendation_id


def set_admin_recommendation_active(
    recommendation_id: int,
    is_active: bool,
    updated_by: str | None,
) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE admin_recommendations
            SET
                is_active = ?,
                updated_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                1 if is_active else 0,
                updated_by.lower() if updated_by else None,
                recommendation_id,
            ),
        )
        connection.commit()
    return cursor.rowcount > 0


def delete_admin_recommendation(recommendation_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM admin_recommendations WHERE id = ?",
            (recommendation_id,),
        )
        connection.commit()
    return cursor.rowcount > 0
