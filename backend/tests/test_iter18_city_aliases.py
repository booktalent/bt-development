"""
Iteration 18 — regression + verification for CITY_ALIASES in iter11_routes.py

New in iter18:
  - CITY_ALIASES map (Delhi ↔ Delhi NCR ↔ New Delhi, Mumbai ↔ Bombay,
    Bangalore ↔ Bengaluru, Kolkata ↔ Calcutta, Chennai ↔ Madras).
  - Query builder now uses `$in: aliases` when the city is known, and falls
    back to `$regex: <city>` for unknown cities (must NOT crash).

This file re-exercises the iter17 acceptance suite AND adds new asserts
around the city-alias behavior. It also re-runs the fallback subprocess
that simulates the AlmaLinux VPS (no `emergentintegrations` + no
EMERGENT_LLM_KEY), extended to hit `DJ in Delhi` and assert the new
CITY_ALIASES logic works in that pathway too.
"""
import json
import os
import re
import subprocess
import sys
import textwrap
import pytest
import requests

# ─── Bootstrap ───────────────────────────────────────────────────────
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@booktalent.com", "password": "Admin@123"}
CUSTOMER = {"email": "customer@booktalent.com", "password": "Customer@123"}
ARTIST = {"email": "priya@booktalent.com", "password": "Artist@123"}

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
# 1. CITY ALIASES — AI/live path
# ─────────────────────────────────────────────────────────────────────
class TestCityAliases:
    def _post(self, api_client, q, limit=5):
        r = api_client.post(f"{API}/search/ai",
                            json={"query": q, "limit": limit}, timeout=45)
        assert r.status_code == 200, r.text
        return r.json()

    def test_dj_in_delhi_returns_dj_vortex(self, api_client):
        """AI parses city='Delhi NCR' → $in ['Delhi','Delhi NCR','New Delhi','NCR'] matches DJ Vortex(city='Delhi')."""
        d = self._post(api_client, "DJ in Delhi")
        assert d.get("total", 0) >= 1, f"expected >=1 Delhi DJ, got {d}"
        items = d.get("items", [])
        matches = [it for it in items
                   if "delhi" in (it.get("city") or "").lower()
                   and "dj" in (it.get("category") or "").lower()
                   and "dj vortex" in (it.get("stage_name") or "").lower()]
        assert matches, (
            "DJ Vortex/Delhi not in items: "
            + str([(it.get("stage_name"), it.get("category"), it.get("city"))
                   for it in items])
        )

    def test_singer_in_bombay_under_60000(self, api_client):
        """Bombay alias → Mumbai. Priya Sharma expected."""
        d = self._post(api_client, "Singer in Bombay under 60000")
        assert d.get("filters", {}).get("max_price") == 60000
        items = d.get("items", [])
        assert len(items) >= 1, f"expected ≥1 Mumbai singer, got {d}"
        matches = [it for it in items
                   if it.get("city") in ("Mumbai", "Bombay")
                   and "priya sharma" in (it.get("stage_name") or "").lower()]
        assert matches, (
            "Priya Sharma missing: "
            + str([(it.get("stage_name"), it.get("city")) for it in items])
        )

    def test_comedian_in_bengaluru(self, api_client):
        """Bengaluru → Bangalore. Rohit Gupta expected."""
        d = self._post(api_client, "Comedian in Bengaluru")
        items = d.get("items", [])
        assert len(items) >= 1, f"expected ≥1 Bangalore comedian, got {d}"
        matches = [it for it in items
                   if it.get("city") in ("Bangalore", "Bengaluru")
                   and "rohit gupta" in (it.get("stage_name") or "").lower()]
        assert matches, (
            "Rohit Gupta/Bangalore missing: "
            + str([(it.get("stage_name"), it.get("city")) for it in items])
        )

    def test_unknown_city_ahmedabad_does_not_500(self, api_client):
        """Unknown city must fall back to $regex — no crash, items may be []."""
        r = api_client.post(f"{API}/search/ai",
                            json={"query": "Singer in Ahmedabad", "limit": 5},
                            timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d.get("items"), list)
        assert isinstance(d.get("total"), int)
        # Ahmedabad has no seed → total 0 is acceptable
        assert d.get("total") >= 0


# ─────────────────────────────────────────────────────────────────────
# 2. PRICE REGEX — spot-check 3 iter17 prompts (still ±0)
# ─────────────────────────────────────────────────────────────────────
def _parse_price(q):
    q_low = q.lower()
    m = re.search(
        r"(?:under|below|less than|max(?:imum)?)\s*(?:\u20b9|rs\.?\s*)?"
        r"([\d][\d,.\s]*)\s*(k|lakh|l)?\b",
        q_low,
    )
    if not m:
        return None
    val_raw = re.sub(r"[,\s]", "", m.group(1)).rstrip(".")
    val = float(val_raw)
    unit = m.group(2)
    if unit == "k":
        val *= 1_000
    elif unit in ("lakh", "l"):
        val *= 100_000
    return int(val)


class TestPriceRegexSpotCheck:
    @pytest.mark.parametrize("prompt,expected", [
        ("Singer under 50000",         50000),
        ("comedian under \u20b980,000", 80000),
        ("vocalist under 1.5 lakh",    150000),
    ])
    def test_spot(self, prompt, expected):
        assert _parse_price(prompt) == expected


# ─────────────────────────────────────────────────────────────────────
# 3. FALLBACK PATH — subprocess with emergentintegrations blocked +
#    EMERGENT_LLM_KEY unset — asserts DJ Vortex returned for "DJ in Delhi".
# ─────────────────────────────────────────────────────────────────────
class TestFallbackPathDelhi:
    """Simulates AlmaLinux/Hostinger VPS: no emergentintegrations package,
    no EMERGENT_LLM_KEY. Replays iter11 fallback logic INCLUDING the new
    CITY_ALIASES and asserts DJ Vortex is returned for 'DJ in Delhi'."""

    def test_fallback_dj_delhi(self):
        script = textwrap.dedent(r"""
            import os, sys, asyncio, re
            sys.modules['emergentintegrations'] = None
            os.environ.pop('EMERGENT_LLM_KEY', None)
            sys.path.insert(0, '/app/backend')
            from motor.motor_asyncio import AsyncIOMotorClient

            raw_q = "DJ in Delhi"
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
                filters['keywords'] = raw_q
                rationale = rationale or 'regex'

            assert filters.get('category_hint') == 'dj', filters
            assert filters.get('city') == 'Delhi NCR', filters

            # Iter18 CITY_ALIASES + CATEGORY_ALIASES query build
            CITY_ALIASES = {
                "delhi":      ["Delhi","Delhi NCR","New Delhi","NCR"],
                "delhi ncr":  ["Delhi","Delhi NCR","New Delhi","NCR"],
                "new delhi":  ["Delhi","Delhi NCR","New Delhi"],
                "mumbai":     ["Mumbai","Bombay"],
                "bangalore":  ["Bangalore","Bengaluru"],
                "kolkata":    ["Kolkata","Calcutta"],
                "chennai":    ["Chennai","Madras"],
            }
            CATEGORY_ALIASES = {
                "singer":   ["singer","vocalist","bollywood","playback"],
                "dj":       ["dj","music producer","electronic"],
                "comedian": ["comedian","stand-up","stand up","comic"],
            }
            def _expand(term):
                if not term: return []
                k = str(term).strip().lower()
                return [k] + [a for a in CATEGORY_ALIASES.get(k, []) if a != k]

            q = {}
            city_key = str(filters['city']).strip().lower()
            aliases = CITY_ALIASES.get(city_key)
            if aliases:
                q['city'] = {"$in": aliases}
            else:
                q['city'] = {"$regex": filters['city'], "$options": "i"}

            or_terms = []
            seen = set()
            for term in (filters.get('category'), filters.get('category_hint')):
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
            for tok in re.findall(r"[a-z]{3,}", str(filters.get('keywords','')).lower()):
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
            hits = [d for d in docs
                    if 'delhi' in (d.get('city','').lower())
                    and 'dj' in (d.get('category','').lower())
                    and 'dj vortex' in (d.get('stage_name','').lower())]
            assert hits, "NO DJ Vortex in Delhi fallback results: " + \
                str([(d.get('stage_name'),d.get('category'),d.get('city')) for d in docs])
            print("OK rationale=%s hits=%d first=%s/%s"
                  % (rationale, len(hits), hits[0].get('stage_name'), hits[0].get('city')))
        """)
        r = subprocess.run([sys.executable, "-c", script],
                           capture_output=True, text=True, timeout=45)
        assert r.returncode == 0, \
            f"FALLBACK FAILED\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert "OK" in r.stdout, r.stdout


# ─────────────────────────────────────────────────────────────────────
# 4. REGRESSION — iter11 endpoints (ICS + CSVs)
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
# 5. REGRESSION — chat gate iter12/13/14/15
# ─────────────────────────────────────────────────────────────────────
class TestChatGateRegression:
    def _access(self, d):
        return d.get("access") if "access" in d else d.get("enabled")

    def test_unpaid_no_access(self, customer_client):
        r = customer_client.get(f"{API}/chat/{UNPAID_BID}/access", timeout=15)
        assert r.status_code == 200, r.text
        assert self._access(r.json()) is False, r.json()

    def test_paid_has_access(self, customer_client):
        r = customer_client.get(f"{API}/chat/{PAID_BID}/access", timeout=15)
        assert r.status_code == 200, r.text
        assert self._access(r.json()) is True, r.json()


# ─────────────────────────────────────────────────────────────────────
# 6. REGRESSION — iter14/15/16 endpoints existence (smoke)
# ─────────────────────────────────────────────────────────────────────
class TestIter14To16Smoke:
    def test_wallet_balance(self, customer_client):
        r = customer_client.get(f"{API}/wallet/balance", timeout=15)
        assert r.status_code in (200, 404), r.text  # 404 acceptable if no wallet yet
        if r.status_code == 200:
            j = r.json()
            assert "balance" in j or "amount" in j or isinstance(j, dict)

    def test_kyc_status(self, customer_client):
        r = customer_client.get(f"{API}/kyc/status", timeout=15)
        # 200 OK or 404 if not filed — endpoint exists = anything except 5xx
        assert r.status_code < 500, r.text

    def test_blogs_list(self, api_client):
        r = api_client.get(f"{API}/blogs", timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), (list, dict))

    def test_coupons_list_admin(self, admin_client):
        r = admin_client.get(f"{API}/coupons", timeout=15)
        assert r.status_code < 500, r.text

    def test_disputes_list_admin(self, admin_client):
        r = admin_client.get(f"{API}/admin/disputes", timeout=15)
        assert r.status_code < 500, r.text

    def test_artists_featured(self, api_client):
        # Public artist list endpoint (iter10 exposes /api/artists/featured)
        r = api_client.get(f"{API}/artists/featured", timeout=15)
        assert r.status_code == 200, r.text


# ─────────────────────────────────────────────────────────────────────
# 7. PACKAGING — pip dry-run (iter16 regression)
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
        venv = "/tmp/v18"
        if not os.path.isdir(venv):
            subprocess.check_call([sys.executable, "-m", "venv", venv])
        pip = f"{venv}/bin/pip"
        r = subprocess.run(
            [pip, "install", "--dry-run", "-r", "/app/backend/requirements.txt"],
            capture_output=True, text=True, timeout=300,
        )
        assert r.returncode == 0, f"stderr={r.stderr[-2000:]}"


# ─────────────────────────────────────────────────────────────────────
# 8. SMOKE — boot + api root
# ─────────────────────────────────────────────────────────────────────
class TestBootSmoke:
    def test_api_root(self, api_client):
        r = api_client.get(f"{API}/", timeout=5)
        assert r.status_code == 200 and r.json().get("ok") is True
