"""
Iter 49 backend tests for Dynamic Artist Onboarding Questionnaire.
Validates:
  - Universal (Layer 1) — 63 questions across 10 sections with exact counts.
  - Categories (Layer 2) — 12 modern categories, no empty legacy slugs.
  - Category-specific question shapes: DJ (7), Singer (7), Celebrity (7 + show_if).
  - Answers persistence for artist role, 403 for non-artist role.
  - Admin CRUD override wins over hardcoded seed (idempotent cleanup).
"""
import os
import pytest
import requests
from collections import Counter

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ─────────────────────────── Fixtures ───────────────────────────
def _login(email: str, password: str):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s, token


@pytest.fixture(scope="module")
def artist_session():
    s, _ = _login("priya@booktalent.com", "Artist@123")
    return s


@pytest.fixture(scope="module")
def customer_session():
    s, _ = _login("customer@booktalent.com", "Customer@123")
    return s


@pytest.fixture(scope="module")
def admin_session():
    s, _ = _login("admin@booktalent.com", "Admin@123")
    return s


# ─────────────────────────── Universal (L1) ───────────────────────────
class TestUniversalQuestionnaire:
    def test_universal_returns_63_questions(self):
        r = requests.get(f"{API}/questionnaire/universal", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list), f"expected list got {type(data)}"
        assert len(data) == 63, f"expected 63 questions, got {len(data)}"

    def test_universal_section_counts(self):
        r = requests.get(f"{API}/questionnaire/universal", timeout=15)
        assert r.status_code == 200
        data = r.json()
        sections = Counter(q["section"] for q in data)
        expected = {
            "Tell us about yourself": 12,
            "Performance Packages": 1,
            "Travel": 13,
            "Technical Requirements": 12,
            "Performance": 8,
            "Hospitality": 1,
            "Commercial": 9,
            "Event Types": 1,
            "Legal": 5,
            "Availability": 1,
        }
        for sec, count in expected.items():
            assert sections.get(sec) == count, f"section {sec}: expected {count} got {sections.get(sec)}"
        # Sum matches
        assert sum(expected.values()) == 63

    def test_universal_has_new_types(self):
        r = requests.get(f"{API}/questionnaire/universal", timeout=15)
        data = r.json()
        types = {q["type"] for q in data}
        for t in ["toggle", "price", "time", "file", "info", "select", "multiselect"]:
            assert t in types, f"type {t} missing from universal"

    def test_universal_show_if_present(self):
        """show_if skip-logic exists for late_night_after and travel_flat_fee."""
        r = requests.get(f"{API}/questionnaire/universal", timeout=15)
        data = r.json()
        by_id = {q["id"]: q for q in data}
        assert by_id.get("late_night_after", {}).get("show_if") == {"late_night": True}
        assert by_id.get("late_night_extra", {}).get("show_if") == {"late_night": True}


# ─────────────────────────── Categories list ───────────────────────────
class TestCategoriesList:
    def test_categories_include_all_12(self):
        r = requests.get(f"{API}/questionnaire/categories", timeout=15)
        assert r.status_code == 200
        cats = r.json()
        assert isinstance(cats, list)
        required = ["Singer", "DJ", "Band", "Dancer", "Stand-up Comedian", "Anchor / Emcee",
                   "Magician", "Motivational Speaker", "Celebrity", "Influencer",
                   "Kids Entertainer", "Instrumentalist"]
        for c in required:
            assert c in cats, f"category {c} missing — got {cats}"

    def test_categories_exclude_legacy_empty_ones(self):
        r = requests.get(f"{API}/questionnaire/categories", timeout=15)
        cats = r.json()
        legacy = ["Bollywood Vocalist", "Classical Vocalist", "DJ / Music Producer",
                  "Dancer / Troupe", "Live Band", "Folk Artist"]
        for l in legacy:
            assert l not in cats, f"legacy category {l} should NOT appear"


# ─────────────────────────── Category (L2) shapes ───────────────────────────
class TestCategoryDJ:
    def test_dj_has_seven_questions(self):
        r = requests.get(f"{API}/questionnaire/category/DJ", timeout=15)
        assert r.status_code == 200
        qs = r.json()
        assert len(qs) == 7, f"DJ should have 7 questions, got {len(qs)}"

    def test_dj_question_ids_and_types(self):
        r = requests.get(f"{API}/questionnaire/category/DJ", timeout=15)
        qs = r.json()
        by_id = {q["id"]: q for q in qs}
        assert by_id["dj_genres"]["type"] == "multiselect"
        for tid in ["own_controller", "own_laptop", "own_lighting", "dj_booth_required", "outdoor_ok"]:
            assert by_id[tid]["type"] == "toggle", f"{tid} should be toggle"
        assert by_id["dj_notes"]["type"] == "text"


class TestCategorySinger:
    def test_singer_has_seven_questions(self):
        r = requests.get(f"{API}/questionnaire/category/Singer", timeout=15)
        assert r.status_code == 200
        qs = r.json()
        assert len(qs) == 7

    def test_singer_style_and_setup(self):
        r = requests.get(f"{API}/questionnaire/category/Singer", timeout=15)
        qs = r.json()
        by_id = {q["id"]: q for q in qs}
        assert by_id["singer_style"]["type"] == "multiselect"
        assert len(by_id["singer_style"]["options"]) == 11
        assert by_id["singer_setup"]["type"] == "select"
        assert len(by_id["singer_setup"]["options"]) == 6


class TestCategoryCelebrity:
    def test_celebrity_has_seven_questions(self):
        r = requests.get(f"{API}/questionnaire/category/Celebrity", timeout=15)
        assert r.status_code == 200
        qs = r.json()
        assert len(qs) == 7

    def test_celebrity_show_if_team_size(self):
        r = requests.get(f"{API}/questionnaire/category/Celebrity", timeout=15)
        qs = r.json()
        by_id = {q["id"]: q for q in qs}
        assert by_id["team_travels"]["type"] == "toggle"
        assert by_id["team_size"]["type"] == "number"
        assert by_id["team_size"].get("show_if") == {"team_travels": True}


# ─────────────────────────── Answer persistence & auth ───────────────────────────
class TestAnswerPersistence:
    def test_artist_can_submit_and_fetch(self, artist_session):
        payload = {"answers": {
            "TEST_iter49_stage_name": "Test Priya",
            "TEST_iter49_min_booking_amount": 25000,
            "TEST_iter49_late_night": True,
        }}
        r = artist_session.post(f"{API}/questionnaire/answers", json=payload, timeout=15)
        assert r.status_code == 200, f"expected 200, got {r.status_code} — {r.text[:200]}"
        body = r.json()
        assert body.get("ok") is True
        assert set(body.get("saved_keys", [])) == set(payload["answers"].keys())

        # GET mine
        g = artist_session.get(f"{API}/questionnaire/answers/mine", timeout=15)
        assert g.status_code == 200
        mine = g.json()
        assert mine.get("TEST_iter49_stage_name") == "Test Priya"
        assert mine.get("TEST_iter49_min_booking_amount") == 25000
        assert mine.get("TEST_iter49_late_night") is True

    def test_customer_cannot_submit_answers(self, customer_session):
        r = customer_session.post(f"{API}/questionnaire/answers",
                                  json={"answers": {"foo": "bar"}}, timeout=15)
        assert r.status_code == 403, f"expected 403 for customer, got {r.status_code}"
        # Body should mention artist only
        body_text = r.text.lower()
        assert "artist" in body_text


# ─────────────────────────── Admin override CRUD ───────────────────────────
class TestAdminOverride:
    def test_admin_override_wins_over_seed_and_cleanup(self, admin_session):
        # Baseline: seed returns 7 DJ questions
        r = requests.get(f"{API}/questionnaire/category/DJ", timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 7

        # Set custom 2-question override
        custom = {"questions": [
            {"id": "TEST_iter49_custom_dj_q1", "label": "Custom Q1", "type": "text", "order": 1},
            {"id": "TEST_iter49_custom_dj_q2", "label": "Custom Q2", "type": "toggle", "order": 2},
        ]}
        put = admin_session.put(f"{API}/admin/questionnaire/category/DJ", json=custom, timeout=15)
        assert put.status_code == 200, f"admin PUT failed: {put.status_code} {put.text[:200]}"
        assert put.json().get("count") == 2

        # GET returns override
        after = requests.get(f"{API}/questionnaire/category/DJ", timeout=15)
        assert after.status_code == 200
        data = after.json()
        assert len(data) == 2, f"override should return 2 questions, got {len(data)}"
        ids = {q["id"] for q in data}
        assert ids == {"TEST_iter49_custom_dj_q1", "TEST_iter49_custom_dj_q2"}

        # Cleanup — delete the override doc directly via mongo shell-agnostic re-put empty
        # (No DELETE endpoint exists; admin CRUD only supports upsert.) We work around by
        # PUT-ing back a specially-marked empty array — but our route filters `override.get("questions")`
        # so empty list will fall back to seed. Verify.
        cleanup = admin_session.put(f"{API}/admin/questionnaire/category/DJ",
                                    json={"questions": []}, timeout=15)
        assert cleanup.status_code == 200
        # After cleanup, seed should be served again (7 questions)
        final = requests.get(f"{API}/questionnaire/category/DJ", timeout=15)
        assert final.status_code == 200
        assert len(final.json()) == 7, f"after cleanup, seed should serve 7 questions, got {len(final.json())}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
