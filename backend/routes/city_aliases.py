"""
City-alias canonicalisation — Iter 35.

Treats regionally-equivalent city names as the same place so genuine
intra-region events don't wrongly trigger the outstation gate.

Example groupings:
  {"delhi", "new delhi", "delhi ncr", "ncr"}      → "delhi"
  {"bombay", "mumbai"}                            → "mumbai"
  {"bangalore", "bengaluru"}                      → "bengaluru"
  ... etc

The alias table is persisted in `system_settings.city_aliases` as JSON so an
admin can extend it via the existing PUT /admin/settings endpoint without a
redeploy.

Usage:
    from routes.city_aliases import canonical_city, load_alias_map
    m = await load_alias_map(db)
    if canonical_city("Delhi NCR", m) == canonical_city("New Delhi", m):
        ...  # intra-NCR, don't trigger outstation
"""
from __future__ import annotations
from typing import Callable, Dict, Optional

from fastapi import APIRouter, Depends


# ─── Default alias table shipped with the platform ─────────────────────────
# Keys are the canonical form, values are the aliases (lowercased, whitespace
# collapsed). The canonical form is included in its own alias list.
DEFAULT_ALIASES = {
    "delhi": ["delhi", "new delhi", "delhi ncr", "ncr", "dilli"],
    "mumbai": ["mumbai", "bombay", "mumbai suburban", "greater mumbai"],
    "bengaluru": ["bengaluru", "bangalore", "blr"],
    "kolkata": ["kolkata", "calcutta"],
    "chennai": ["chennai", "madras"],
    "pune": ["pune", "poona", "pimpri-chinchwad", "pimpri chinchwad"],
    "hyderabad": ["hyderabad", "secunderabad", "cyberabad"],
    "gurgaon": ["gurgaon", "gurugram"],
    "noida": ["noida", "greater noida"],
    "kochi": ["kochi", "cochin", "ernakulam"],
    "thiruvananthapuram": ["thiruvananthapuram", "trivandrum"],
    "puducherry": ["puducherry", "pondicherry"],
    "vishakhapatnam": ["vishakhapatnam", "visakhapatnam", "vizag"],
    "prayagraj": ["prayagraj", "allahabad"],
    "varanasi": ["varanasi", "banaras", "kashi"],
    "vadodara": ["vadodara", "baroda"],
}


def _normalise(city: Optional[str]) -> str:
    """Whitespace-collapse + lowercase — the shape aliases are compared in."""
    if not city:
        return ""
    return " ".join(city.strip().lower().split())


def _build_reverse_map(alias_table: Dict[str, list]) -> Dict[str, str]:
    """Flatten alias table → {alias_form: canonical_form}."""
    rev: Dict[str, str] = {}
    for canonical, aliases in alias_table.items():
        canonical_n = _normalise(canonical)
        rev[canonical_n] = canonical_n
        for a in aliases:
            rev[_normalise(a)] = canonical_n
    return rev


def canonical_city(city: Optional[str], reverse_map: Optional[Dict[str, str]] = None) -> str:
    """Return the canonical city name for the given input.

    Falls back to the normalised input when no alias matches — this means
    two unknown-but-identical strings still compare equal, and the outstation
    check remains safe."""
    n = _normalise(city)
    if not reverse_map:
        return n
    return reverse_map.get(n, n)


async def load_alias_map(db) -> Dict[str, str]:
    """Load and flatten the alias table from `system_settings.city_aliases`.

    Idempotent: seeds DEFAULT_ALIASES on first call if the setting doesn't
    exist so admins have something to edit right away."""
    doc = await db.system_settings.find_one({"key": "city_aliases"})
    if not doc:
        await db.system_settings.insert_one({"key": "city_aliases", "value": DEFAULT_ALIASES})
        table = DEFAULT_ALIASES
    else:
        raw = doc.get("value") or DEFAULT_ALIASES
        # Support both dict (canonical → aliases) or list of groups formats
        if isinstance(raw, list):
            table = {group[0]: group for group in raw if group}
        else:
            table = raw
    return _build_reverse_map(table)


def make_router(*, db, admin_only, **_extra) -> APIRouter:
    """Small admin router exposing the alias table for inspection / reset."""
    r = APIRouter()

    @r.get("/admin/city-aliases")
    async def admin_get(_: dict = Depends(admin_only)):
        doc = await db.system_settings.find_one({"key": "city_aliases"})
        table = (doc or {}).get("value") or DEFAULT_ALIASES
        return {"aliases": table, "reverse": _build_reverse_map(table) if isinstance(table, dict) else {}}

    @r.post("/admin/city-aliases/reset")
    async def admin_reset(_: dict = Depends(admin_only)):
        await db.system_settings.update_one(
            {"key": "city_aliases"},
            {"$set": {"value": DEFAULT_ALIASES}},
            upsert=True,
        )
        return {"ok": True, "aliases": DEFAULT_ALIASES}

    return r
