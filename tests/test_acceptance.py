from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_SECRET_KEY", "touch-vn-test-secret-key-with-at-least-48-characters")
os.environ.setdefault("ADMIN_EMAILS", "admin@touchvn.com")
os.environ.setdefault("SEED_DEMO_USERS", "true")
os.environ.setdefault("DEMO_ADMIN_EMAIL", "admin@touchvn.com")
TEST_ADMIN_PASSWORD = "TouchVN-local-test-password"
os.environ.setdefault("DEMO_ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)

from fastapi.testclient import TestClient

from app.api.main import app as api_app
from app.shared import db
from app.shared.geography import CURRENT_PROVINCES
from app.shared.integration_gateways import _validate_external_url
from app.shared.models import ItineraryRequest, TicketOffer
from app.shared.openai_planner import (
    PlannerNarrative,
    PlannerNarrativeDay,
    enhance_itinerary_with_openai,
)
from app.shared.services import (
    _nearby_kind_from_tags,
    add_group_expense,
    create_ticket_reservation,
    generate_itinerary,
    get_categories,
    get_group_expense_summary,
    get_must_go,
    get_places,
    get_regions_summary,
    get_user_ticket_bookings,
    search_tickets,
)
from app.shared.settings import get_settings, validate_production_settings
from app.shared.translations import UI_TEXTS
from app.web.app import create_app


class DestinationAcceptanceTests(unittest.TestCase):
    def test_destination_repository_uses_current_geography(self) -> None:
        places = get_places()
        provinces = {place.province for place in places}
        region_counts = {item["code"]: item["count"] for item in get_regions_summary()}

        self.assertEqual(len(places), 63)
        self.assertEqual(provinces, set(CURRENT_PROVINCES))
        self.assertEqual(set(region_counts), {"north", "central", "south"})
        self.assertTrue(all(count > 0 for count in region_counts.values()))

    def test_search_and_filters_can_be_combined(self) -> None:
        results = get_places(
            region="north",
            province="Lào Cai",
            category="mountain",
            search="Sapa",
        )
        self.assertEqual([place.id for place in results], ["sapa"])

    def test_categories_and_must_go_ranking(self) -> None:
        expected_categories = {
            "mountain",
            "beach",
            "island",
            "spiritual",
            "culture",
            "history",
            "food",
            "entertainment",
        }
        self.assertEqual(
            {item["code"] for item in get_categories()},
            expected_categories,
        )
        ranked = get_must_go()
        self.assertGreater(len(ranked), 0)
        self.assertEqual(
            [item.must_go_score for item in ranked],
            sorted(
                [item.must_go_score for item in ranked],
                reverse=True,
            ),
        )

    def test_nearby_service_taxonomy_covers_required_types(self) -> None:
        tag_cases = {
            "restaurant": {"amenity": "restaurant"},
            "hotel": {"tourism": "hotel"},
            "pharmacy": {"amenity": "pharmacy"},
            "convenience-store": {"shop": "convenience"},
            "market": {"amenity": "marketplace"},
            "supermarket": {"shop": "supermarket"},
            "hospital": {"amenity": "hospital"},
            "theme-park": {"leisure": "theme_park"},
        }
        self.assertEqual(
            {_nearby_kind_from_tags(tags) for tags in tag_cases.values()},
            set(tag_cases),
        )

    def test_all_destination_descriptions_are_localized(self) -> None:
        vi = {place.id: place for place in get_places(lang="vi")}
        en = {place.id: place for place in get_places(lang="en")}
        ko = {place.id: place for place in get_places(lang="ko")}

        self.assertEqual(set(vi), set(en))
        self.assertEqual(set(vi), set(ko))
        self.assertTrue(all(vi[key].description != en[key].description for key in vi))
        self.assertTrue(all(vi[key].description != ko[key].description for key in vi))

    def test_interface_translations_have_matching_keys(self) -> None:
        self.assertEqual(
            len({frozenset(values) for values in UI_TEXTS.values()}),
            1,
        )
        korean_copy = UI_TEXTS["ko"]
        untranslated = [
            key
            for key, value in korean_copy.items()
            if not re.search(r"[가-힣]", value)
            and len(value) > 3
            and key
            not in {
                "about_stat_languages_value",
                "dashboard_setting_maps_value",
                "place_tools_ar_short",
                "places_map_title",
            }
        ]
        self.assertEqual(untranslated, [])


class PlannerAndTicketAcceptanceTests(unittest.TestCase):
    def test_smart_planner_fallback_respects_request(self) -> None:
        request = ItineraryRequest(
            departure_city="Hà Nội",
            destination="Hội An",
            days=3,
            budget=4_500_000,
            travelers=2,
            interests=["culture", "food"],
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            plan = generate_itinerary(request)

        self.assertEqual(plan.generation_mode, "smart-fallback")
        self.assertEqual(len(plan.days), request.days)
        self.assertLessEqual(plan.total_estimated_cost, request.budget)
        self.assertEqual(
            [item.day for item in plan.days],
            [1, 2, 3],
        )

    def test_openai_planner_uses_structured_responses_output(self) -> None:
        base_plan = generate_itinerary(
            ItineraryRequest(
                departure_city="Hà Nội",
                destination="Hội An",
                days=2,
                budget=4_000_000,
                travelers=2,
                interests=["culture"],
            )
        )
        narrative = PlannerNarrative(
            overview="Lịch trình hai ngày cân bằng giữa di sản và trải nghiệm địa phương.",
            days=[
                PlannerNarrativeDay(
                    day=1,
                    title="Ngày 1: Di sản Hội An",
                    morning="Đến Hội An và nhận phòng.",
                    afternoon="Khám phá không gian phố cổ.",
                    evening="Dạo phố đèn lồng.",
                ),
                PlannerNarrativeDay(
                    day=2,
                    title="Ngày 2: Văn hóa địa phương",
                    morning="Tham quan điểm văn hóa.",
                    afternoon="Trải nghiệm ẩm thực địa phương.",
                    evening="Tổng kết hành trình.",
                ),
            ],
            travel_tips=[
                "Chuẩn bị giày đi bộ.",
                "Giữ nước uống bên mình.",
                "Kiểm tra thời tiết trước khi đi.",
            ],
        )
        captured: dict[str, object] = {}

        class FakeResponses:
            def parse(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(output_parsed=narrative)

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.responses = FakeResponses()

        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "test-key",
                    "OPENAI_PLANNER_MODEL": "gpt-5.6-sol",
                },
            ),
            patch("openai.OpenAI", FakeOpenAI),
        ):
            enhanced = enhance_itinerary_with_openai(
                request=ItineraryRequest(
                    departure_city="Hà Nội",
                    destination="Hội An",
                    days=2,
                    budget=4_000_000,
                    travelers=2,
                    interests=["culture"],
                ),
                base_plan=base_plan,
                place_context=[
                    {
                        "name": "Phố cổ Hội An",
                        "province": "Đà Nẵng",
                        "description": "Điểm đến di sản.",
                        "categories": ["culture"],
                        "highlights": ["Chùa Cầu"],
                    }
                ],
                language="vi",
            )

        self.assertEqual(enhanced.generation_mode, "openai")
        self.assertEqual(enhanced.total_estimated_cost, base_plan.total_estimated_cost)
        self.assertEqual(captured["model"], "gpt-5.6-sol")
        self.assertIs(captured["text_format"], PlannerNarrative)
        self.assertFalse(captured["store"])

    def test_all_ticket_types_return_offers(self) -> None:
        counts = {
            vehicle_type: len(
                search_tickets(
                    "Hà Nội",
                    "Đà Nẵng",
                    vehicle_type=vehicle_type,
                    departure_date="2026-08-15",
                    passengers=2,
                )
            )
            for vehicle_type in ("plane", "train", "bus", "entertainment")
        }
        self.assertTrue(all(count > 0 for count in counts.values()))

    def test_external_ticket_gateway_has_priority(self) -> None:
        external_offer = TicketOffer(
            provider="Test provider",
            vehicle_type="plane",
            origin="Hà Nội",
            destination="Đà Nẵng",
            departure="09:00",
            departure_date="2026-08-15",
            arrival="10:20",
            duration="1h 20m",
            seat_class="Economy",
            available_seats=4,
            operator_note="Contract test",
            price=1_200_000,
            booking_url="https://provider.example/booking/1",
        )
        with patch(
            "app.shared.services.fetch_external_ticket_offers",
            return_value=[external_offer],
        ):
            offers = search_tickets(
                "Hà Nội",
                "Đà Nẵng",
                vehicle_type="plane",
                passengers=1,
            )
        self.assertEqual([item.provider for item in offers], ["Test provider"])


class DatabaseAndWebAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_data_dir = db.DATA_DIR
        cls.old_db_path = db.DB_PATH
        db.DATA_DIR = Path(cls.temp_dir.name)
        db.DB_PATH = db.DATA_DIR / "acceptance.db"
        db.ensure_db()
        cls.app = create_app()
        cls.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls) -> None:
        db.DATA_DIR = cls.old_data_dir
        db.DB_PATH = cls.old_db_path
        cls.temp_dir.cleanup()

    def test_authentication_csrf_and_admin_authorization(self) -> None:
        anonymous = self.app.test_client()
        admin_response = anonymous.get("/admin")
        self.assertEqual(admin_response.status_code, 302)
        self.assertTrue(admin_response.headers["Location"].endswith("/login"))

        csrf_response = anonymous.post(
            "/api/chat-support",
            json={"question": "chi phí"},
        )
        self.assertEqual(csrf_response.status_code, 400)

        client = self.app.test_client()
        client.get("/login")
        with client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        login_response = client.post(
            "/login",
            data={
                "email": "admin@touchvn.com",
                "password": TEST_ADMIN_PASSWORD,
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertTrue(login_response.headers["Location"].endswith("/admin"))
        self.assertEqual(client.get("/admin").status_code, 200)

    def test_security_headers_and_language_persistence(self) -> None:
        client = self.app.test_client()
        response = client.get("/about")
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("X-Request-Id", response.headers)

        client.get("/set-language/en?next=/about")
        english_page = client.get("/about")
        self.assertIn(b'<html lang="en">', english_page.data)

        client.get("/set-language/ko?next=/about")
        korean_page = client.get("/about")
        self.assertIn(b'<html lang="ko">', korean_page.data)

    def test_chat_history_and_local_fallback(self) -> None:
        client = self.app.test_client()
        client.get("/")
        with client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            response = client.post(
                "/api/chat-support",
                json={"question": "Dự toán chi phí cho chuyến đi"},
                headers={"X-CSRF-Token": csrf_token},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["messages"]), 2)
        self.assertTrue(payload["answer"])

    def test_ticket_reservation_is_persisted_for_the_signed_in_user(self) -> None:
        email = "booking@example.com"
        self.assertTrue(db.create_user("Booking User", email, "password123"))
        reservation = create_ticket_reservation(
            user_email=email,
            provider="Touch VN Demo",
            vehicle_type="train",
            origin="Hà Nội",
            destination="Đà Nẵng",
            departure_date="2026-08-15",
            departure_time="08:00",
            arrival_time="22:00",
            seat_class="Giường nằm",
            amount=950_000,
            contact_name="Booking User",
            contact_email=email,
            contact_phone="0900000000",
        )
        bookings = get_user_ticket_bookings(email)

        self.assertEqual(reservation["status"], "reserved")
        self.assertTrue(reservation["booking_reference"].startswith("TVN-"))
        self.assertEqual(len(bookings), 1)
        self.assertEqual(bookings[0]["booking_reference"], reservation["booking_reference"])
        self.assertEqual(bookings[0]["vehicle_type"], "train")
        self.assertEqual(bookings[0]["amount"], 950_000)

    def test_group_expenses_use_trip_payer_category_members_and_note(self) -> None:
        email = "traveler@example.com"
        self.assertTrue(db.create_user("Traveler", email, "password123"))
        trip_id = db.save_trip(
            user_email=email,
            title="Hội An - 2 ngày",
            departure_city="Hà Nội",
            destination="Hội An",
            region="central",
            days=2,
            travelers=2,
            budget_total=4_000_000,
            itinerary_total=3_200_000,
            itinerary_data={"days": []},
            budget_data={"total": 4_000_000},
        )
        add_group_expense(
            user_email=email,
            trip_id=trip_id,
            title="Bữa tối",
            category="food",
            paid_by="An",
            split_members=["An", "Bình"],
            amount=600_000,
            note="Chia đều hai người",
        )
        summary = get_group_expense_summary(email, trip_id=trip_id)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["total"], 600_000)
        self.assertEqual(summary["by_payer"][0]["name"], "An")
        self.assertEqual(len(summary["settlements"]), 1)

    def test_offline_json_and_geojson_are_downloadable(self) -> None:
        client = self.app.test_client()
        json_response = client.get("/offline-packs/north.json")
        geojson_response = client.get("/offline-packs/north.geojson")

        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(geojson_response.status_code, 200)
        self.assertEqual(json.loads(json_response.data)["region"], "north")
        self.assertEqual(
            json.loads(geojson_response.data)["type"],
            "FeatureCollection",
        )

    def test_internal_routes_meet_demo_performance_target(self) -> None:
        client = self.app.test_client()
        for route in ("/about", "/tickets", "/planner", "/qr-scanner", "/healthz"):
            started = time.perf_counter()
            response = client.get(route)
            elapsed = time.perf_counter() - started
            self.assertEqual(response.status_code, 200, route)
            self.assertLess(elapsed, 2.0, route)


class ApiAndSecurityAcceptanceTests(unittest.TestCase):
    def test_api_routes_and_access_control(self) -> None:
        client = TestClient(api_app)
        self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertEqual(len(client.get("/api/places").json()), 63)
        self.assertEqual(
            [
                client.get(f"/api/places?lang={language}").status_code
                for language in ("vi", "en", "ko")
            ],
            [200, 200, 200],
        )
        self.assertEqual(
            client.get("/api/integrations/status").status_code,
            401,
        )
        self.assertEqual(
            client.post(
                "/api/itinerary/plan",
                json={
                    "departure_city": "Hà Nội",
                    "destination": "Hội An",
                    "days": 0,
                    "budget": 4_000_000,
                    "travelers": 2,
                    "interests": ["culture"],
                },
            ).status_code,
            422,
        )

    def test_production_configuration_rejects_weak_secret(self) -> None:
        settings = replace(
            get_settings(),
            environment="production",
            secret_key="short",
        )
        with self.assertRaises(RuntimeError):
            validate_production_settings(settings)

    def test_external_gateway_rejects_private_network_targets(self) -> None:
        for url in (
            "http://127.0.0.1/internal",
            "http://localhost/internal",
            "http://169.254.169.254/latest/meta-data",
        ):
            with self.assertRaises(ValueError, msg=url):
                _validate_external_url(url)

    def test_database_lookup_does_not_interpret_sql_input(self) -> None:
        self.assertIsNone(db.find_user_by_email("' OR 1=1 --"))

    def test_dependencies_are_pinned(self) -> None:
        requirements = (
            (Path(__file__).resolve().parents[1] / "requirements.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        packages = [
            line.strip()
            for line in requirements
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(packages)
        self.assertTrue(all("==" in package for package in packages))


if __name__ == "__main__":
    unittest.main()
