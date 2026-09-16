"""
Iter 46 — AI Event Planner
--------------------------------
Given an event brief (event_type, guests, budget, city, date), return a
smart recommendation of artist categories + suggested add-ons so the customer
can jump-start their multi-artist cart in one click.

Powered by Claude Sonnet 4.6 via Emergent Universal LLM key. Deterministic
rule-based fallback guarantees the endpoint never 500s if the LLM is down.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter(prefix="/event-planner", tags=["event-planner"])


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────
class EventBrief(BaseModel):
    event_type: str = Field(..., description="Wedding, Sangeet, Corporate, Birthday, etc.")
    guests: Optional[int] = Field(None, description="Approximate guest count")
    budget_min: Optional[int] = Field(None, description="Total budget in INR (lower bound)")
    budget_max: Optional[int] = Field(None, description="Total budget in INR (upper bound)")
    city: Optional[str] = None
    event_date: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=400, description="Free-text vibe / theme")


class PlannedCategory(BaseModel):
    category: str
    reason: str
    priority: int  # 1 = must-have, 3 = optional


class PlannedAddon(BaseModel):
    name: str
    reason: str


class EventPlan(BaseModel):
    headline: str
    rationale: str
    categories: List[PlannedCategory]
    addons: List[PlannedAddon]
    approx_budget: Optional[str] = None
    source: str = "llm"  # "llm" | "fallback"


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic fallback rule table
# ─────────────────────────────────────────────────────────────────────────────
_RULES = {
    "wedding": {
        "headline": "The classic Indian wedding line-up",
        "categories": [
            ("Singer / Vocalist",  "Anchors the sangeet and reception with signature performances.", 1),
            ("DJ",                 "Keeps the dance floor packed after dinner.", 1),
            ("Anchor / MC",        "Threads the events together — welcomes, games, thank-yous.", 2),
            ("Dhol Artist",        "Iconic baraat and jaimala moments — non-negotiable for many families.", 2),
        ],
        "addons": [
            ("Extended sound + lighting", "For a 200+ guest venue you'll want a rig that projects clearly."),
            ("Extra hour",                "Weddings routinely run over — book a buffer."),
        ],
    },
    "sangeet": {
        "headline": "A high-energy sangeet setup",
        "categories": [
            ("Singer / Vocalist",  "For live jaimalas and family performances.", 1),
            ("DJ",                 "Handles the choreographed dance segments.", 1),
            ("Anchor / MC",        "Runs games and family intros.", 2),
        ],
        "addons": [
            ("Extra hour", "Sangeet always overshoots — plan for it."),
        ],
    },
    "corporate": {
        "headline": "A polished corporate line-up",
        "categories": [
            ("Anchor / MC",        "Emcees keynotes, awards and Q&A crisply.", 1),
            ("Singer / Vocalist",  "Post-dinner unwind — light, non-intrusive.", 2),
            ("Comedian",           "For the after-party or awards night.", 3),
        ],
        "addons": [
            ("Professional PA + wireless mics", "Corporate venues expect broadcast-quality audio."),
        ],
    },
    "birthday": {
        "headline": "A joyful birthday show",
        "categories": [
            ("DJ",                 "The engine of any birthday party.", 1),
            ("Anchor / MC",        "Runs games, birthday rituals, gift moments.", 2),
            ("Magician",           "Especially for kids' birthdays — total crowd-pleaser.", 3),
        ],
        "addons": [
            ("Party lighting",  "Turn a hall into a club — instantly."),
        ],
    },
}


def _fallback_plan(brief: EventBrief) -> EventPlan:
    """Deterministic rule-based fallback that never fails."""
    key = None
    et = (brief.event_type or "").lower()
    for k in _RULES:
        if k in et:
            key = k
            break
    if not key:
        key = "wedding"  # sensible default
    r = _RULES[key]
    return EventPlan(
        headline=r["headline"],
        rationale=(
            f"A {brief.guests or 'medium-sized'}-guest {brief.event_type or 'event'} "
            f"in {brief.city or 'your city'} typically needs the mix below. "
            f"You can add or drop any artist right from the cart."
        ),
        categories=[PlannedCategory(category=c, reason=why, priority=p) for c, why, p in r["categories"]],
        addons=[PlannedAddon(name=n, reason=why) for n, why in r["addons"]],
        approx_budget=_budget_hint(brief),
        source="fallback",
    )


def _budget_hint(brief: EventBrief) -> Optional[str]:
    if brief.budget_min or brief.budget_max:
        lo, hi = brief.budget_min or 0, brief.budget_max or (brief.budget_min or 0) * 2
        return f"₹{lo:,} – ₹{hi:,}" if hi else f"₹{lo:,}+"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LLM planner (Claude Sonnet 4.6 via emergentintegrations)
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are the BookTalent Event Planner — a warm, expert Indian event curator.
Given a customer's event brief, recommend a curated artist mix and add-ons.

STRICT OUTPUT RULES:
- Reply with a SINGLE JSON object matching the schema below — no markdown fences, no prose.
- Choose from these Artist Category labels ONLY: "Singer / Vocalist", "DJ", "Anchor / MC",
  "Dhol Artist", "Band", "Instrumentalist", "Sufi Vocalist", "Classical Vocalist",
  "Comedian", "Magician", "Dancer / Choreography", "Poet / Shayar", "Emcee (Corporate)".
- Priority: 1 = must-have, 2 = strong pick, 3 = optional
- Recommend 3-5 categories and 2-4 add-ons total.
- Rationale + reasons must be crisp — 1 sentence each, no fluff.
- Never mention prices, invoices or GST — that's handled elsewhere.
- Never invent artist names. Categories only.

SCHEMA:
{
  "headline": "6-8 word punchy line-up title",
  "rationale": "1-2 sentence intro that ties the picks to the event brief",
  "categories": [
    {"category": "<one of the allowed labels>", "reason": "<1 sentence>", "priority": 1|2|3},
    ...
  ],
  "addons": [
    {"name": "<add-on name>", "reason": "<1 sentence>"},
    ...
  ]
}
"""


async def _llm_plan(brief: EventBrief) -> EventPlan:
    """Ask Claude Sonnet 4.6 to draft an event plan. Raises on any failure so
    the caller can fall back to the deterministic rule table."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY not configured")

    from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore

    prompt = (
        f"Event type: {brief.event_type}\n"
        f"Guests: {brief.guests or 'not specified'}\n"
        f"Budget: {_budget_hint(brief) or 'not specified'}\n"
        f"City: {brief.city or 'not specified'}\n"
        f"Date: {brief.event_date or 'not specified'}\n"
        f"Notes: {brief.notes or 'none'}\n"
    )

    chat = LlmChat(
        api_key=api_key,
        session_id=f"planner-{(brief.event_type or 'evt').lower()}-{brief.city or 'x'}",
        system_message=_SYSTEM_PROMPT,
    ).with_model("anthropic", "claude-sonnet-4-6")

    raw = await chat.send_message(UserMessage(text=prompt))
    text = str(raw).strip()
    # Strip any accidental markdown fence
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"LLM did not return JSON: {text[:200]}")
    data = json.loads(m.group(0))

    return EventPlan(
        headline=data.get("headline", "Your event line-up"),
        rationale=data.get("rationale", ""),
        categories=[
            PlannedCategory(
                category=c.get("category", ""),
                reason=c.get("reason", ""),
                priority=int(c.get("priority", 2)),
            )
            for c in (data.get("categories") or [])
            if c.get("category")
        ],
        addons=[
            PlannedAddon(name=a.get("name", ""), reason=a.get("reason", ""))
            for a in (data.get("addons") or [])
            if a.get("name")
        ],
        approx_budget=_budget_hint(brief),
        source="llm",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Route
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/suggest", response_model=EventPlan)
async def suggest_plan(brief: EventBrief):
    """Public endpoint — anyone can generate a plan (no auth required). This is
    the anchor for the AI Event Planner CTA on the landing page + inside the
    booking flow. The output is a lightweight blueprint; the customer then
    fills the actual cart via the artist search + Add-to-Event modal."""
    if not brief.event_type or not brief.event_type.strip():
        raise HTTPException(400, "event_type is required")

    try:
        plan = await _llm_plan(brief)
        # Guarantee at least one category — otherwise fall back
        if not plan.categories:
            raise ValueError("LLM returned empty categories")
        return plan
    except Exception as e:
        log.info("Event planner falling back to rules: %s", e)
        return _fallback_plan(brief)


@router.get("/example")
async def example_brief():
    """Returns a sample brief so the frontend can pre-fill the planner form."""
    return {
        "event_type": "Wedding",
        "guests": 400,
        "budget_min": 400000,
        "budget_max": 800000,
        "city": "Mumbai",
        "notes": "Bollywood + Sufi vibe, 3-day multi-function",
    }
