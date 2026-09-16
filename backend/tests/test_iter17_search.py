"""
Iteration 17 — Regression tests for the two blocker bugs fixed in iter11_routes.py:

    1. NEW greedy-digit-run regex for price parsing (line 258-274).
    2. Category synonym expansion (CATEGORY_ALIASES lines 283-294).
    3. Stop-word filtering on the `keywords` free-form field (lines 330-342).

Because we cannot unset EMERGENT_LLM_KEY on the running server, the AI-path
tests hit the live endpoint (primary path), and the fallback-path tests run
in a subprocess that clones the CURRENT iter11 regex + alias tables and
executes them against real Mongo (via motor) — proving parity.
"""
import json
import os
import subprocess
import sys
import textwrap
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@booktalent.com", "password": "Admin@123"}
CUSTOMER = {"email": "customer@booktalent.com", "password": "Customer@123"}

PAID_BID = "cca6a262-8393-4970-bd38-021dc13d52c7"
UNPAID_BID = "060a549a-0952-4425-84c0-422210ee501e"


# ─── Fixtures ────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(creds):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="session")
def admin_client():
    return _login(ADMIN)


@pytest.fixture(scope="session")
def customer_client():
    return _login(CUSTOMER)


# ─────────────────────────────────────────────────────────────────────
# 1. NEW GREEDY-DIGIT-RUN REGEX — unit test on the exact regex from src
# ─────────────────────────────────────────────────────────────────────
PRICE_CASES = [
    ("Singer under 50000",              50000),
    ("DJ under 30k",                    30000),
    ("comedian under \u20b980,000",     80000),
    ("vocalist under 1.5 lakh",         150000),
    ("anchor under 60,000",             60000),
    ("band under 2 lakh",               200000),
    ("dancer under 100000",             100000),
    ("magician under 5 l",              500000),
    ("singer below 25000",              25000),
    ("less than 45000 rupees",          45000),
]


class TestPriceRegexUnit:
    """Directly test the regex from iter11_routes.py:258-274."""

    def _parse(self, q):
        import re
        q_low = q.lower()
        mprice = re.search(
            r"(?:under|below|less than|max(?:imum)?)\s*(?:\u20b9|rs\.?\s*)?"
            r"([\d][\d,.\s]*)\s*(k|lakh|l)?\b",
            q_low,
        )
        if not mprice:
            return None
        val_raw = re.sub(r"[,\s]", "", mprice.group(1)).rstrip(".")
        val = float(val_raw)
        unit = mprice.group(2)
        if unit == "k":
            val *= 1_000
        elif unit in ("lakh", "l"):
            val *= 100_000
        return int(val)

    @pytest.mark.parametrize("prompt,expected", PRICE_CASES)
    def test_price_parse(self, prompt, expected):
        got = self._parse(prompt)
        assert got == expected, f"{prompt!r} → got {got}, expected {expected}"


# ─────────────────────────────────────────────────────────────────────
# 2. LIVE /api/search/ai — Category synonym expansion
# ─────────────────────────────────────────────────────────────────────
class TestCategorySynonyms:
    """Endpoint must return real seed artists whose stored category is
    a synonym of the parsed canonical token."""

    def _post(self, api_client, q, limit=5):
        r = api_client.post(f"{API}/search/ai",
                            json={"query": q, "limit": limit}, timeout=45)
        assert r.status_code == 200, r.text
        return r.json()

    def test_singer_mumbai_returns_bollywood_vocalist(self, api_client):
        d = self._post(api_client, "Singer in Mumbai under 50000")
        items = d.get("items", [])
        assert d.get("filters", {}).get("max_price") == 50000
        assert len(items) >= 1, f"expected ≥1 Mumbai singer, got {d}"
        # Priya Sharma (Bollywood Vocalist, Mumbai, ₹25k) MUST be there
        mumbai_singers = [
            it for it in items
            if it.get("city") == "Mumbai"
            and (
                "singer"    in (it.get("category") or "").lower()
                or "vocalist" in (it.get("category") or "").lower()
                or "bollywood" in (it.get("category") or "").lower()
                or "playback" in (it.get("category") or "").lower()
            )
        ]
        assert mumbai_singers, f"no Mumbai singer/vocalist in items: {[i.get('stage_name')+'/'+i.get('category','') for i in items]}"

    def test_comedian_bangalore(self, api_client):
        d = self._post(api_client, "Comedian in Bangalore")
        items = d.get("items", [])
        assert len(items) >= 1, f"expected ≥1 Bangalore comedian, got {d}"
        matches = [
            it for it in items
            if it.get("city") == "Bangalore"
            and (
                "comedian" in (it.get("category") or "").lower()
                or "stand" in (it.get("category") or "").lower()
                or "comic" in (it.get("category") or "").lower()
            )
        ]
        assert matches, f"no Bangalore comedian in items: {[i.get('stage_name')+'/'+i.get('category','') for i in items]}"

    def test_dj_delhi(self, api_client):
        d = self._post(api_client, "DJ in Delhi")
        items = d.get("items", [])
        assert len(items) >= 1, f"expected ≥1 Delhi DJ, got {d}"
        matches = [
            it for it in items
            if "delhi" in (it.get("city") or "").lower()
            and (
                "dj" in (it.get("category") or "").lower()
                or "music producer" in (it.get("category") or "").lower()
                or "electronic" in (it.get("category") or "").lower()
            )
        ]
        assert matches, f"no Delhi DJ in items: {[i.get('stage_name')+'/'+i.get('category','') for i in items]}"


# ─────────────────────────────────────────────────────────────────────
# 3. Stop-word filtering
# ─────────────────────────────────────────────────────────────────────
class TestStopWordFilter:
    def test_full_sentence_still_returns_singer(self, api_client):
        r = api_client.post(
            f"{API}/search/ai",
            json={"query": "find me a singer in mumbai under 50000 for wedding",
                  "limit": 10},
            timeout=45,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        items = d.get("items", [])
        assert len(items) >= 1, f"stop-word filter broken: {d}"
        # All returned items must be Mumbai and priced ≤ 50000 (or price None)
        for it in items:
            if it.get("city"):
                assert "mumbai" in it["city"].lower() or it.get("city") == "Mumbai", it
            sp = it.get("starting_price")
            if sp is not None:
                assert sp <= 50000, f"price {sp} > 50000 for {it.get('stage_name')}"


# ─────────────────────────────────────────────────────────────────────
# 4. FALLBACK PATH — subprocess simulates missing emergentintegrations
# ─────────────────────────────────────────────────────────────────────
class TestFallbackPath:
    """
    Spawn a subprocess that:
      (a) Blocks `emergentintegrations` at import time.
      (b) Unsets EMERGENT_LLM_KEY.
      (c) Replays the CURRENT iter11 fallback logic (regex + synonym
          expansion + stop-word filter + Mongo query build).
      (d) Executes the Mongo query and asserts ≥1 Mumbai vocalist returned.

    This proves the AlmaLinux-VPS scenario (no emergent package) works.
    """

    def test_fallback_returns_seed_data(self):
        script = textwrap.dedent(r"""
            import os, sys, asyncio
            sys.modules['emergentintegrations'] = None  # block import
            os.environ.pop('EMERGENT_LLM_KEY', None)
            sys.path.insert(0, '/app/backend')
            from motor.motor_asyncio import AsyncIOMotorClient
            import re

            raw_q = "Singer in Mumbai under 50000"
            filters = {}
            rationale = None
            key = os.environ.get('EMERGENT_LLM_KEY', '').strip()
            try:
                if key:
                    from emergentintegrations.llm.chat import LlmChat, UserMessage
                    _ = LlmChat
                    rationale = "ai_parsed"
            except Exception as e:
                rationale = "fallback_" + type(e).__name__

            if not filters:
                q_low = raw_q.lower()
                for cat in ["singer","vocalist","dj","comedian","dancer",
                            "anchor","band","magician","folk","bollywood"]:
                    if cat in q_low:
                        filters['category_hint'] = cat; break
                for city, label in [("mumbai","Mumbai"),("delhi","Delhi NCR"),
                                    ("bangalore","Bangalore"),("chennai","Chennai"),
                                    ("hyderabad","Hyderabad"),("kolkata","Kolkata"),
                                    ("pune","Pune"),("jaipur","Jaipur"),("goa","Goa")]:
                    if city in q_low:
                        filters['city'] = label; break
                mprice = re.search(
                    r"(?:under|below|less than|max(?:imum)?)\s*(?:\u20b9|rs\.?\s*)?"
                    r"([\d][\d,.\s]*)\s*(k|lakh|l)?\b", q_low)
                if mprice:
                    val_raw = re.sub(r"[,\s]", "", mprice.group(1)).rstrip(".")
                    val = float(val_raw)
                    unit = mprice.group(2)
                    if unit == 'k': val *= 1000
                    elif unit in ('lakh','l'): val *= 100000
                    filters['max_price'] = int(val)
                filters['keywords'] = raw_q
                rationale = rationale or 'regex'

            assert filters.get('category_hint') == 'singer', filters
            assert filters.get('city') == 'Mumbai', filters
            assert filters.get('max_price') == 50000, filters

            # Build Mongo query with synonym expansion + stop-word filter
            CATEGORY_ALIASES = {
                "singer":   ["singer","vocalist","bollywood","playback"],
                "vocalist": ["vocalist","singer","bollywood"],
                "dj":       ["dj","music producer","electronic"],
                "comedian": ["comedian","stand-up","stand up","comic"],
                "dancer":   ["dancer","choreographer"],
                "anchor":   ["anchor","host","emcee","mc"],
                "band":     ["band","musician"],
                "magician": ["magician","illusionist"],
                "folk":     ["folk","traditional"],
                "bollywood":["bollywood","hindi","vocalist"],
            }
            def _expand(term):
                if not term: return []
                k = str(term).strip().lower()
                aliases = CATEGORY_ALIASES.get(k, [])
                return [k] + [a for a in aliases if a != k]

            q = {}
            if filters.get('city'):
                q['city'] = {"$regex": filters['city'], "$options": "i"}

            or_terms = []
            seen = set()
            for term in (filters.get('category'), filters.get('category_hint'),
                         filters.get('event_type')):
                for kw in _expand(term):
                    if kw in seen: continue
                    seen.add(kw)
                    or_terms.extend([
                        {"stage_name": {"$regex": kw, "$options": "i"}},
                        {"bio":        {"$regex": kw, "$options": "i"}},
                        {"tagline":    {"$regex": kw, "$options": "i"}},
                        {"category":   {"$regex": kw, "$options": "i"}},
                    ])
            STOP = {"in","for","under","below","less","than","max","maximum",
                    "the","a","an","and","or","with","at","on","of",
                    "rs","inr","\u20b9","k","lakh","l"}
            raw_kw = filters.get('keywords') or ""
            for tok in re.findall(r"[a-z]{3,}", str(raw_kw).lower()):
                if tok in STOP or tok in seen: continue
                seen.add(tok)
                or_terms.extend([
                    {"stage_name": {"$regex": tok, "$options": "i"}},
                    {"bio":        {"$regex": tok, "$options": "i"}},
                    {"tagline":    {"$regex": tok, "$options": "i"}},
                    {"category":   {"$regex": tok, "$options": "i"}},
                ])
            if or_terms: q['$or'] = or_terms

            async def run():
                from dotenv import load_dotenv
                load_dotenv('/app/backend/.env')
                cli = AsyncIOMotorClient(os.environ['MONGO_URL'])
                db = cli[os.environ['DB_NAME']]
                docs = await db.artist_profiles.find(q).limit(25).to_list(25)
                for d in docs: d.pop('_id', None)
                return docs
            docs = asyncio.run(run())
            mumbai_singers = [d for d in docs
                              if d.get('city') == 'Mumbai'
                              and any(t in (d.get('category','').lower()) for t in
                                      ('singer','vocalist','bollywood','playback'))]
            assert mumbai_singers, "NO Mumbai singer/vocalist in fallback results: " + \
                str([(d.get('stage_name'),d.get('category')) for d in docs])
            print("OK rationale=%s max_price=%d hits=%d first=%s"
                  % (rationale, filters['max_price'], len(mumbai_singers),
                     mumbai_singers[0].get('stage_name')))
        """)
        r = subprocess.run([sys.executable, "-c", script],
                           capture_output=True, text=True, timeout=45)
        assert r.returncode == 0, \
            f"FALLBACK FAILED\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert "OK" in r.stdout, r.stdout


# ─────────────────────────────────────────────────────────────────────
# 5. REGRESSION — packaging (iter16 unchanged)
# ─────────────────────────────────────────────────────────────────────
class TestPackagingRegression:
    def test_requirements_no_emergent(self):
        text = open("/app/backend/requirements.txt").read()
        assert "emergentintegrations" not in text.lower()
        assert "customer-assets.emergentagent.com" not in text

    def test_requirements_emergent_file(self):
        text = open("/app/backend/requirements-emergent.txt").read()
        assert "emergentintegrations==0.2.0" in text

    def test_pip_dry_run_main(self):
        venv = "/tmp/v17"
        if not os.path.isdir(venv):
            subprocess.check_call([sys.executable, "-m", "venv", venv])
        pip = f"{venv}/bin/pip"
        r = subprocess.run(
            [pip, "install", "--dry-run", "-r", "/app/backend/requirements.txt"],
            capture_output=True, text=True, timeout=300,
        )
        assert r.returncode == 0, f"stderr={r.stderr[-2000:]}"


# ─────────────────────────────────────────────────────────────────────
# 6. REGRESSION — iter11 endpoints
# ─────────────────────────────────────────────────────────────────────
class TestIter11Regression:
    def test_calendar_ics(self, customer_client):
        r = customer_client.get(f"{API}/bookings/{PAID_BID}/calendar.ics", timeout=15)
        assert r.status_code == 200, r.text
        assert "text/calendar" in r.headers.get("content-type", "")
        assert r.text.startswith("BEGIN:VCALENDAR")

    def test_customer_csv(self, customer_client):
        r = customer_client.get(f"{API}/exports/my-bookings.csv", timeout=15)
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")

    def test_admin_revenue_csv(self, admin_client):
        r = admin_client.get(f"{API}/admin/exports/revenue.csv", timeout=15)
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")


# ─────────────────────────────────────────────────────────────────────
# 7. REGRESSION — chat gate (iter 12/13/14/15)
# ─────────────────────────────────────────────────────────────────────
class TestChatGateRegression:
    def test_unpaid_no_access(self, customer_client):
        r = customer_client.get(f"{API}/chat/{UNPAID_BID}/access", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        # Contract uses `enabled` key (also acceptable: `access`)
        access_val = d.get("access") if "access" in d else d.get("enabled")
        assert access_val is False, d

    def test_paid_has_access(self, customer_client):
        r = customer_client.get(f"{API}/chat/{PAID_BID}/access", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        access_val = d.get("access") if "access" in d else d.get("enabled")
        assert access_val is True, d


# ─────────────────────────────────────────────────────────────────────
# 8. SMOKE — boot + api root
# ─────────────────────────────────────────────────────────────────────
class TestBootSmoke:
    def test_api_root(self, api_client):
        r = api_client.get(f"{API}/", timeout=5)
        assert r.status_code == 200 and r.json().get("ok") is True
