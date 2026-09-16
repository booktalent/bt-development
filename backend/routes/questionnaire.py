"""
Dynamic Artist Onboarding Questionnaire.

Layer 1: universal questions asked of every artist (10 sections).
Layer 2: category-specific questions asked in addition, based on the artist's
         chosen category (Singer, DJ, Comedian, Dancer, etc.).

Both layers are metadata-driven so admins can add / edit questions from the
Admin panel without touching code. Answers live on `artist_profiles.answers`
as a `{ question_id: answer_value }` map.

Question types accepted by the wizard:
    text | textarea | number | price | date | time | url | tel
    select (single) | multiselect | toggle (yes/no) | file

Iter 49 — seed rewritten to match the "Interactive Dynamic Artist Onboarding"
PRD delivered by the product team. Every question below is an exact 1:1 port
of that doc so the wizard reads back correctly during profile completion and
package creation.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel


# ───────────────────────────── UNIVERSAL (LAYER 1) ─────────────────────────
UNIVERSAL_QUESTIONS: List[Dict[str, Any]] = [
    # ── SECTION 1 · Tell us about yourself ──────────────────────────────
    {"section": "Tell us about yourself", "id": "stage_name",     "label": "Stage Name", "type": "text", "order": 10},
    {"section": "Tell us about yourself", "id": "legal_name",     "label": "Legal Name", "type": "text", "order": 20},
    {"section": "Tell us about yourself", "id": "category",       "label": "Which category best describes you?", "type": "select",
     "options": ["Singer", "DJ", "Band", "Dancer", "Stand-up Comedian", "Magician",
                 "Anchor / Emcee", "Motivational Speaker", "Influencer", "Celebrity",
                 "Instrumentalist", "Kids Entertainer", "Other"],
     "description": "Adjusts the category-specific questions in the last step.", "order": 30},
    {"section": "Tell us about yourself", "id": "years_experience", "label": "Years of Experience", "type": "select",
     "options": ["Less than 1 year", "1–3 years", "3–5 years", "5–10 years", "10+ years"], "order": 40},
    {"section": "Tell us about yourself", "id": "languages",      "label": "Which languages do you speak?", "type": "multiselect",
     "options": ["Hindi", "English", "Punjabi", "Gujarati", "Marathi", "Bengali",
                 "Tamil", "Telugu", "Kannada", "Malayalam", "Other"], "order": 50},
    {"section": "Tell us about yourself", "id": "base_city",      "label": "Base City", "type": "text", "order": 60},
    {"section": "Tell us about yourself", "id": "about",          "label": "Tell customers about yourself", "type": "textarea", "order": 70},
    {"section": "Tell us about yourself", "id": "profile_photo",  "label": "Upload Profile Photo", "type": "file", "order": 80},
    {"section": "Tell us about yourself", "id": "cover_photo",    "label": "Cover Photo", "type": "file", "order": 90},
    {"section": "Tell us about yourself", "id": "gallery_images", "label": "Gallery Images", "type": "file", "multiple": True, "order": 100},
    {"section": "Tell us about yourself", "id": "intro_video",    "label": "Introduction Video", "type": "file", "order": 110},
    {"section": "Tell us about yourself", "id": "performance_videos", "label": "Performance Videos", "type": "file", "multiple": True, "order": 120},

    # ── SECTION 2 · Performance Packages ────────────────────────────────
    {"section": "Performance Packages", "id": "package_count", "label": "How many packages do you want to offer?", "type": "number",
     "description": "Artist can create unlimited packages. Each package captures its own name, price, duration, capacity, inclusions and extra-hour rate on the Packages screen.", "order": 200},

    # ── SECTION 3 · Travel ─────────────────────────────────────────────
    {"section": "Travel", "id": "travel_scope", "label": "Will you travel for performances?", "type": "select",
     "options": ["Only within my city", "Within my state", "Anywhere in India", "International"], "order": 300},
    {"section": "Travel", "id": "travel_who_pays", "label": "Who usually pays for travel?", "type": "select",
     "options": ["Customer", "I include travel charges in my package", "Depends on the event"], "order": 310},
    {"section": "Travel", "id": "travel_modes", "label": "Preferred mode of travel", "type": "multiselect",
     "options": ["Flight", "Train", "Cab", "Personal Vehicle", "No Preference"], "order": 320},
    {"section": "Travel", "id": "flight_class", "label": "Preferred Flight Class", "type": "select",
     "options": ["Economy", "Premium Economy", "Business", "No Preference"], "order": 330},
    {"section": "Travel", "id": "train_class", "label": "Preferred Train Class", "type": "select",
     "options": ["AC Chair Car", "3AC", "2AC", "1AC", "No Preference"], "order": 340},
    {"section": "Travel", "id": "hotel_required", "label": "Hotel Required?", "type": "select",
     "options": ["Always", "Only for outstation events", "No"], "order": 350},
    {"section": "Travel", "id": "hotel_category", "label": "Preferred Hotel Category", "type": "select",
     "options": ["3 ★", "4 ★", "5 ★", "No Preference"], "order": 360},
    {"section": "Travel", "id": "travel_party_size", "label": "How many people usually travel?", "type": "select",
     "options": ["Only me", "2", "3", "4", "5+"], "order": 370},
    {"section": "Travel", "id": "travel_charge_model", "label": "How should travel charges be calculated?", "type": "select",
     "options": ["Included in package", "Customer pays actual expenses", "Flat travel fee", "Free within certain distance"], "order": 380},
    {"section": "Travel", "id": "travel_flat_fee", "label": "Flat travel fee (₹)", "type": "price",
     "show_if": {"travel_charge_model": "Flat travel fee"}, "order": 390},
    {"section": "Travel", "id": "travel_free_distance_km", "label": "Free within distance (km)", "type": "number",
     "show_if": {"travel_charge_model": "Free within certain distance"}, "order": 395},
    {"section": "Travel", "id": "travel_per_km_fee", "label": "After that — per-km fee (₹)", "type": "price",
     "show_if": {"travel_charge_model": "Free within certain distance"}, "order": 397},
    {"section": "Travel", "id": "travel_notes", "label": "Anything customers should know?", "type": "textarea", "order": 399},

    # ── SECTION 4 · Technical Requirements ─────────────────────────────
    {"section": "Technical Requirements", "id": "sound_provider", "label": "Who provides the sound system?", "type": "select",
     "options": ["Artist", "Customer"], "order": 400},
    {"section": "Technical Requirements", "id": "artist_brings", "label": "What do you usually bring?", "type": "multiselect",
     "options": ["Microphones", "Guitar", "Keyboard", "DJ Console", "Mixer", "Laptop",
                 "Drum Kit", "Instruments", "Nothing", "Other"], "order": 410},
    {"section": "Technical Requirements", "id": "customer_arranges", "label": "What should the customer arrange?", "type": "multiselect",
     "options": ["Stage", "Sound System", "LED Wall", "Lighting", "Generator", "Green Room",
                 "Extension Boards", "Chairs", "Dressing Mirror", "Drinking Water", "Power Backup"], "order": 420},
    {"section": "Technical Requirements", "id": "speaker_brand", "label": "Preferred Speaker Brand", "type": "multiselect",
     "options": ["No Preference", "JBL", "Bose", "RCF", "L-Acoustics", "d&b", "Other"], "order": 430},
    {"section": "Technical Requirements", "id": "mixer_brand", "label": "Preferred Mixer Brand", "type": "multiselect",
     "options": ["No Preference", "Yamaha", "Allen & Heath", "Soundcraft", "Other"], "order": 440},
    {"section": "Technical Requirements", "id": "wireless_mic", "label": "Wireless Microphone Required?", "type": "toggle", "order": 450},
    {"section": "Technical Requirements", "id": "mic_count", "label": "Number of Microphones", "type": "select",
     "options": ["1", "2", "3", "4+"], "order": 460},
    {"section": "Technical Requirements", "id": "stage_length_ft", "label": "Minimum stage length (ft)", "type": "number", "order": 470},
    {"section": "Technical Requirements", "id": "stage_width_ft",  "label": "Minimum stage width (ft)", "type": "number", "order": 475},
    {"section": "Technical Requirements", "id": "stage_height_ft", "label": "Minimum stage height (ft)", "type": "number", "order": 480},
    {"section": "Technical Requirements", "id": "power", "label": "Power Requirement", "type": "select",
     "options": ["Normal", "Three Phase", "Generator"], "order": 490},
    {"section": "Technical Requirements", "id": "technical_notes", "label": "Anything else?", "type": "textarea", "order": 499},

    # ── SECTION 5 · Performance ────────────────────────────────────────
    {"section": "Performance", "id": "arrive_before", "label": "How early do you arrive?", "type": "select",
     "options": ["30 mins", "60 mins", "90 mins", "2 Hours"], "order": 500},
    {"section": "Performance", "id": "soundcheck_required", "label": "Soundcheck Required?", "type": "toggle", "order": 510},
    {"section": "Performance", "id": "soundcheck_duration", "label": "Soundcheck Duration", "type": "select",
     "options": ["15 mins", "30 mins", "45 mins", "60 mins"],
     "show_if": {"soundcheck_required": True}, "order": 515},
    {"section": "Performance", "id": "max_continuous", "label": "Maximum continuous performance", "type": "select",
     "options": ["30 mins", "45 mins", "60 mins", "90 mins", "2 Hours"], "order": 520},
    {"section": "Performance", "id": "song_requests", "label": "Can customers request songs?", "type": "select",
     "options": ["Yes", "Only before event", "No"], "order": 530},
    {"section": "Performance", "id": "playlist_share", "label": "Can customers share playlist?", "type": "toggle", "order": 540},
    {"section": "Performance", "id": "dress_code_ok", "label": "Do you accept dress code requests?", "type": "toggle", "order": 550},
    {"section": "Performance", "id": "performance_notes", "label": "Additional Notes", "type": "textarea", "order": 560},

    # ── SECTION 6 · Hospitality ────────────────────────────────────────
    {"section": "Hospitality", "id": "hospitality_needs", "label": "What do you require?", "type": "multiselect",
     "options": ["Mineral Water", "Tea", "Coffee", "Snacks", "Vegetarian Meal",
                 "Non-Vegetarian Meal", "Jain Meal", "Green Room", "Private Washroom",
                 "AC Room", "Other"], "order": 600},

    # ── SECTION 7 · Commercial ─────────────────────────────────────────
    {"section": "Commercial", "id": "min_booking_amount", "label": "Minimum Booking Amount (₹)", "type": "price", "order": 700},
    {"section": "Commercial", "id": "advance_pct", "label": "Advance Required", "type": "select",
     "options": ["25%", "50%", "75%", "100%"], "order": 710},
    {"section": "Commercial", "id": "extra_hour_charge", "label": "Extra Hour Charges (₹)", "type": "price", "order": 720},
    {"section": "Commercial", "id": "waiting_charge_per_hour", "label": "Waiting Charges (₹ per Hour)", "type": "price", "order": 730},
    {"section": "Commercial", "id": "late_night", "label": "Late Night Charges?", "type": "toggle", "order": 740},
    {"section": "Commercial", "id": "late_night_after", "label": "Late night — after", "type": "time",
     "show_if": {"late_night": True}, "order": 745},
    {"section": "Commercial", "id": "late_night_extra", "label": "Late night — extra charges (₹)", "type": "price",
     "show_if": {"late_night": True}, "order": 747},
    {"section": "Commercial", "id": "peak_season_pricing", "label": "Peak Season Pricing?", "type": "toggle", "order": 750},
    {"section": "Commercial", "id": "commercial_notes", "label": "Additional Notes", "type": "textarea", "order": 760},

    # ── SECTION 8 · Event Types ────────────────────────────────────────
    {"section": "Event Types", "id": "event_types", "label": "Where do you perform?", "type": "multiselect",
     "options": ["Wedding", "Reception", "Sangeet", "Birthday", "Corporate Event", "College Fest",
                 "School Event", "Government Event", "Religious Event", "Festival",
                 "Private Party", "Club", "Luxury Event", "Brand Launch"], "order": 800},

    # ── SECTION 9 · Legal ──────────────────────────────────────────────
    {"section": "Legal", "id": "gst_invoice", "label": "Will you provide GST Invoice?", "type": "toggle", "order": 900},
    {"section": "Legal", "id": "nda_ok", "label": "Will you sign NDA?", "type": "toggle", "order": 910},
    {"section": "Legal", "id": "video_recording", "label": "Can customers record videos?", "type": "select",
     "options": ["Yes", "Only Short Videos", "No"], "order": 920},
    {"section": "Legal", "id": "livestream_ok", "label": "Can customers livestream?", "type": "select",
     "options": ["Yes", "No"], "order": 930},
    {"section": "Legal", "id": "media_reuse", "label": "Can customers use photos/videos for promotion?", "type": "select",
     "options": ["Yes", "Only with Permission", "No"], "order": 940},

    # ── SECTION 10 · Availability (functional pointer only) ────────────
    {"section": "Availability", "id": "availability_calendar", "label": "Interactive Availability Calendar",
     "type": "info",
     "description": "Managed on the Availability Calendar screen — Block Dates, Weekend Pricing, Festival Pricing and Peak Season Pricing are all editable there.",
     "order": 1000},
]


# ───────────────────────────── CATEGORY (LAYER 2) ──────────────────────────
CATEGORY_QUESTIONS: Dict[str, List[Dict[str, Any]]] = {
    "Singer": [
        {"id": "singer_style", "label": "What type of singer are you?", "type": "multiselect",
         "options": ["Bollywood", "Punjabi", "Classical", "Ghazal", "Sufi", "Devotional",
                     "Retro", "Western", "Fusion", "Folk", "Other"], "order": 10},
        {"id": "singer_setup", "label": "How do you usually perform?", "type": "select",
         "options": ["Solo", "Guitar", "Keyboard", "Karaoke", "Live Band", "Orchestra"], "order": 20},
        {"id": "karaoke_usage", "label": "Do you perform with karaoke tracks?", "type": "select",
         "options": ["Always", "Sometimes", "Never"], "order": 30},
        {"id": "hire_solo_ok", "label": "Can customers hire only you?", "type": "select", "options": ["Yes", "No"], "order": 40},
        {"id": "musicians_travelling", "label": "How many musicians travel with you?", "type": "select",
         "options": ["None", "1", "2", "3", "4+"], "order": 50},
        {"id": "song_request_policy", "label": "Can customers request songs?", "type": "select",
         "options": ["Yes", "Only if informed in advance", "No"], "order": 60},
        {"id": "singer_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "DJ": [
        {"id": "dj_genres", "label": "Music Genres", "type": "multiselect",
         "options": ["Bollywood", "EDM", "House", "Techno", "Commercial", "Punjabi",
                     "Hip-Hop", "Retro", "Other"], "order": 10},
        {"id": "own_controller", "label": "Do you bring your own controller?", "type": "toggle", "order": 20},
        {"id": "own_laptop", "label": "Do you bring your own laptop?", "type": "toggle", "order": 30},
        {"id": "own_lighting", "label": "Do you bring lighting?", "type": "toggle", "order": 40},
        {"id": "dj_booth_required", "label": "Do you require a DJ booth?", "type": "toggle", "order": 50},
        {"id": "outdoor_ok", "label": "Can you perform outdoors?", "type": "toggle", "order": 60},
        {"id": "dj_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Band": [
        {"id": "band_members", "label": "Number of Members", "type": "select",
         "options": ["2", "3", "4", "5", "6+"], "order": 10},
        {"id": "band_composition", "label": "Band Includes", "type": "multiselect",
         "options": ["Singer", "Guitar", "Keyboard", "Drums", "Bass", "Percussion", "Sound Engineer"], "order": 20},
        {"id": "all_members_travel", "label": "Do all members travel?", "type": "toggle", "order": 30},
        {"id": "separate_green_rooms", "label": "Separate Green Rooms Required?", "type": "toggle", "order": 40},
        {"id": "band_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Dancer": [
        {"id": "dance_styles", "label": "Dance Styles", "type": "multiselect",
         "options": ["Bollywood", "Hip Hop", "Contemporary", "Kathak", "Bharatnatyam",
                     "Bhangra", "Salsa", "Other"], "order": 10},
        {"id": "dancer_composition", "label": "Solo or Group?", "type": "select",
         "options": ["Solo", "Duo", "Group"], "order": 20},
        {"id": "changing_room", "label": "Changing Room Required?", "type": "toggle", "order": 30},
        {"id": "dance_floor", "label": "Dance Floor Required?", "type": "toggle", "order": 40},
        {"id": "dancer_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Stand-up Comedian": [
        {"id": "comedy_style", "label": "Comedy Style", "type": "select",
         "options": ["Clean", "Adult", "Corporate", "Roast", "Crowd Work"], "order": 10},
        {"id": "recording_allowed", "label": "Audience Recording Allowed?", "type": "select",
         "options": ["Yes", "No"], "order": 20},
        {"id": "custom_material", "label": "Can material be customised?", "type": "toggle", "order": 30},
        {"id": "comedian_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Anchor / Emcee": [
        {"id": "events_hosted", "label": "Events Hosted", "type": "multiselect",
         "options": ["Wedding", "Corporate", "College", "Awards", "Government"], "order": 10},
        {"id": "script_customisation", "label": "Script Customisation?", "type": "toggle", "order": 20},
        {"id": "teleprompter", "label": "Teleprompter Required?", "type": "toggle", "order": 30},
        {"id": "anchor_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Magician": [
        {"id": "magic_type", "label": "Performance Type", "type": "multiselect",
         "options": ["Stage Magic", "Close-up Magic", "Illusion", "Mentalism"], "order": 10},
        {"id": "assistant_required", "label": "Assistant Required?", "type": "toggle", "order": 20},
        {"id": "audience_participation", "label": "Audience Participation?", "type": "toggle", "order": 30},
        {"id": "magician_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Motivational Speaker": [
        {"id": "speaker_topics", "label": "Topics", "type": "multiselect",
         "options": ["Leadership", "Sales", "AI", "Entrepreneurship", "Education", "Motivation", "Other"], "order": 10},
        {"id": "session_format", "label": "Session Format", "type": "select",
         "options": ["Keynote", "Workshop", "Interactive Q&A"], "order": 20},
        {"id": "handouts_included", "label": "Handouts / Slides Included?", "type": "toggle", "order": 30},
        {"id": "speaker_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Celebrity": [
        {"id": "meet_greet", "label": "Meet & Greet Included?", "type": "toggle", "order": 10},
        {"id": "photo_session", "label": "Photo Session Included?", "type": "toggle", "order": 20},
        {"id": "media_interaction", "label": "Media Interaction Allowed?", "type": "toggle", "order": 30},
        {"id": "security_required", "label": "Security Required?", "type": "toggle", "order": 40},
        {"id": "team_travels", "label": "Personal Team Travels?", "type": "toggle", "order": 50},
        {"id": "team_size", "label": "Number of Team Members", "type": "number",
         "show_if": {"team_travels": True}, "order": 55},
        {"id": "celebrity_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Influencer": [
        {"id": "platforms", "label": "Platforms", "type": "multiselect",
         "options": ["Instagram", "YouTube", "Facebook", "LinkedIn", "Snapchat"], "order": 10},
        {"id": "deliverables", "label": "Deliverables", "type": "multiselect",
         "options": ["Appearance", "Story", "Reel", "Feed Post", "Live Session", "Meet & Greet"], "order": 20},
        {"id": "repost_policy", "label": "Can customer repost content?", "type": "select",
         "options": ["Yes", "Only with Credit", "No"], "order": 30},
        {"id": "influencer_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Kids Entertainer": [
        {"id": "kids_performance", "label": "Performance Type", "type": "multiselect",
         "options": ["Magic", "Puppet Show", "Balloon Art", "Mascot", "Games", "Face Painting"], "order": 10},
        {"id": "age_group", "label": "Suitable Age Group", "type": "multiselect",
         "options": ["2–5 Years", "5–8 Years", "8–12 Years", "All Ages"], "order": 20},
        {"id": "indoor_outdoor", "label": "Indoor or Outdoor?", "type": "multiselect",
         "options": ["Indoor", "Outdoor", "Both"], "order": 30},
        {"id": "kids_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    "Instrumentalist": [
        {"id": "primary_instrument", "label": "Primary Instrument", "type": "text", "order": 10},
        {"id": "performs_solo", "label": "Do you perform solo?", "type": "toggle", "order": 20},
        {"id": "performs_with_band", "label": "Do you perform with a band?", "type": "toggle", "order": 30},
        {"id": "own_instrument", "label": "Do you bring your own instrument?", "type": "toggle", "order": 40},
        {"id": "amplifier_required", "label": "Amplifier Required?", "type": "toggle", "order": 50},
        {"id": "instrumentalist_notes", "label": "Anything else?", "type": "text", "order": 99},
    ],
    # Legacy slugs kept alive so old artists don't lose their answers.
    "Bollywood Vocalist":  [],  # deprecated → mapped to "Singer"
    "Classical Vocalist":  [],  # deprecated → mapped to "Singer"
    "DJ / Music Producer": [],  # deprecated → mapped to "DJ"
    "Dancer / Troupe":     [],  # deprecated → mapped to "Dancer"
    "Live Band":           [],  # deprecated → mapped to "Band"
    "Folk Artist":         [],  # deprecated → covered by Singer > "Folk"
}


class AnswerBody(BaseModel):
    """Answers coming in from the artist onboarding wizard."""
    answers: Dict[str, Any]


def make_router(*, get_current_user: Callable, admin_only: Callable, db: Any, clean: Callable, utcnow: Callable, **_: Any) -> APIRouter:
    r = APIRouter()

    # ── Iter 76.6 ────────────────────────────────────────────────────────
    # Shared alias resolver used by BOTH the artist-facing wizard endpoint
    # AND the customer-facing /about renderer. Previously only /about had
    # the alias logic, so artists with rich category names like
    # "Bollywood Vocalist" or "DJ / Music Producer" would get an empty
    # Layer 2 in the wizard — even though the same artist's customer
    # profile page rendered the questions correctly.
    _ALIASES = {
        "vocalist": "Singer", "singer": "Singer",
        "dj": "DJ", "band": "Band", "dancer": "Dancer",
        "comedian": "Stand-up Comedian",
        "emcee": "Anchor / Emcee", "anchor": "Anchor / Emcee", "host": "Anchor / Emcee",
        "magic": "Magician", "influencer": "Influencer",
        "instrumentalist": "Instrumentalist", "sitar": "Instrumentalist",
        "tabla": "Instrumentalist", "guitar": "Instrumentalist",
        "kid": "Kids Entertainer", "children": "Kids Entertainer",
        "motivational": "Motivational Speaker", "speaker": "Motivational Speaker",
        "celebrity": "Celebrity",
    }

    async def _resolve_category_questions(cat_raw: str):
        """Return the best-matching Layer 2 questions list for a free-form
        category label. Order: DB override by slug → DB override by full
        label → exact seed key → substring alias."""
        if not cat_raw:
            return []
        cat_raw = cat_raw.strip()
        candidate_slug = cat_raw.lower().replace(" ", "-").replace("/", "-")
        m = await db.questionnaire_meta.find_one({"id": f"cat:{candidate_slug}"})
        if m and m.get("questions"):
            return sorted(m["questions"], key=lambda q: q.get("order", 999))
        m = await db.questionnaire_meta.find_one({"id": f"cat:{cat_raw}"})
        if m and m.get("questions"):
            return sorted(m["questions"], key=lambda q: q.get("order", 999))
        if cat_raw in CATEGORY_QUESTIONS and CATEGORY_QUESTIONS[cat_raw]:
            return sorted(CATEGORY_QUESTIONS[cat_raw], key=lambda q: q.get("order", 999))
        cat_lo = cat_raw.lower()
        for alias, target in _ALIASES.items():
            if alias in cat_lo and target in CATEGORY_QUESTIONS and CATEGORY_QUESTIONS[target]:
                return sorted(CATEGORY_QUESTIONS[target], key=lambda q: q.get("order", 999))
        return []

    @r.get("/questionnaire/universal")
    async def get_universal() -> List[Dict[str, Any]]:
        """Public read of Layer 1 questions. Prefers DB overrides if seeded."""
        override = await db.questionnaire_meta.find_one({"id": "universal"})
        if override and override.get("questions"):
            return sorted(override["questions"], key=lambda q: q.get("order", 999))
        return UNIVERSAL_QUESTIONS

    @r.get("/questionnaire/category/{slug:path}")
    async def get_category(slug: str) -> List[Dict[str, Any]]:
        """Public read of Layer 2 questions for a category label. Aliases
        rich names ('Bollywood Vocalist' → Singer, 'DJ / Music Producer'
        → DJ, 'Dancer / Troupe' → Dancer, etc.) so every artist reaches
        the right Layer 2 no matter how their profile category is worded.

        Uses `:path` so category labels containing a slash — like
        "DJ / Music Producer" — round-trip cleanly through the URL."""
        return await _resolve_category_questions(slug)

    @r.get("/questionnaire/categories")
    async def list_categories() -> List[str]:
        """List every category with an available Layer 2 questionnaire (non-empty)."""
        db_ids: set = set()
        async for m in db.questionnaire_meta.find({"id": {"$regex": "^cat:"}}):
            db_ids.add(m["id"].split(":", 1)[1])
        seeded = {k for k, v in CATEGORY_QUESTIONS.items() if v}
        return sorted(list(seeded | db_ids))

    @r.post("/questionnaire/answers")
    async def submit_answers(body: AnswerBody, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        """Artist submits (partial) answers — merged into their profile.answers."""
        if user["role"] != "artist":
            raise HTTPException(403, "Artist only")
        await db.artist_profiles.update_one(
            {"user_id": user["id"]},
            {"$set": {**{f"answers.{k}": v for k, v in body.answers.items()},
                       "answers_updated_at": utcnow()}},
        )
        return {"ok": True, "saved_keys": list(body.answers.keys())}

    @r.get("/questionnaire/answers/mine")
    async def my_answers(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        if user["role"] != "artist":
            raise HTTPException(403, "Artist only")
        prof = await db.artist_profiles.find_one({"user_id": user["id"]}) or {}
        return prof.get("answers", {})

    # ── Iter 55: Public artist profile "About" data ──────────────────────
    # Renders the artist's questionnaire answers as ordered {question,
    # answer, type} triples grouped by universal / category so the profile
    # page can display everything the artist declared without hunting through
    # a raw JSON blob.
    @r.get("/artists/{artist_id}/about")
    async def artist_about(artist_id: str) -> Dict[str, Any]:
        prof = await db.artist_profiles.find_one({"user_id": artist_id})
        # Return 404 for unknown OR suspended profiles — same as the main
        # artist detail endpoint.
        if not prof or prof.get("suspended"):
            raise HTTPException(404, "Artist not found")
        answers = prof.get("answers") or {}
        # Layer 1 — universal questions
        uni_override = await db.questionnaire_meta.find_one({"id": "universal"})
        universal = (uni_override or {}).get("questions") or UNIVERSAL_QUESTIONS
        universal = sorted(universal, key=lambda q: q.get("order", 999))
        # Layer 2 — questions for the artist's category (if any).
        category_slug = None
        category = []
        cat_raw = (prof.get("category") or "").strip()
        if cat_raw:
            # Category matching is fuzzy on purpose: the seed dict uses labels
            # like "Singer" / "DJ" / "Band" while profiles may store richer
            # labels ("Bollywood Vocalist"). Match on exact key, then on
            # substring (case-insensitive).
            candidate_slug = cat_raw.lower().replace(" ", "-").replace("/", "-")

            async def _find_qs():
                # 1) DB override by slug.
                m = await db.questionnaire_meta.find_one({"id": f"cat:{candidate_slug}"})
                if m and m.get("questions"):
                    return candidate_slug, m["questions"]
                # 2) Exact dict key.
                if cat_raw in CATEGORY_QUESTIONS and CATEGORY_QUESTIONS[cat_raw]:
                    return cat_raw, CATEGORY_QUESTIONS[cat_raw]
                # 3) Fuzzy substring against dict keys.
                cat_lo = cat_raw.lower()
                # Aliases for common human-readable categories.
                _ALIASES = {"vocalist": "Singer", "singer": "Singer", "dj": "DJ",
                            "band": "Band", "dancer": "Dancer", "comedian": "Stand-up Comedian",
                            "emcee": "Anchor / Emcee", "anchor": "Anchor / Emcee",
                            "host": "Anchor / Emcee"}
                for alias, target in _ALIASES.items():
                    if alias in cat_lo and target in CATEGORY_QUESTIONS and CATEGORY_QUESTIONS[target]:
                        return target, CATEGORY_QUESTIONS[target]
                return None, []

            category_slug, category = await _find_qs()
            category = sorted(category, key=lambda q: q.get("order", 999))

        def _render(qs):
            out = []
            for q in qs:
                key = q.get("id") or q.get("key")
                if not key:
                    continue
                val = answers.get(key)
                if val is None or val == "" or val == []:
                    continue
                out.append({
                    "id": key,
                    "question": q.get("label") or q.get("question") or key,
                    "type": q.get("type", "text"),
                    "answer": val,
                    "section": q.get("section"),
                    "options": q.get("options"),
                })
            return out

        universal_rendered = _render(universal)
        category_rendered = _render(category)

        # ── Iter 56 — Media-linked answers ────────────────────────────────
        # For every media-type question the artist answered, attach the
        # newest matching media asset so the About tab renders thumbnail
        # chips instead of a generic hint. Mapping is heuristic — we match
        # by the question id hinting a specific media 'type' (see the
        # mongo `media.type` values: profile/cover/gallery/clip/press_kit
        # /brand_deck/audio/document).
        MEDIA_QTYPES = {"file", "photo", "photos", "video", "videos", "media", "attachment", "image"}
        _QID_TO_MTYPE = [
            ("profile_photo", ["profile"]),
            ("cover_photo",   ["cover"]),
            ("cover",         ["cover"]),
            ("gallery",       ["gallery"]),
            ("photo",         ["gallery", "profile"]),
            ("image",         ["gallery"]),
            ("intro_video",   ["clip"]),
            ("performance_video", ["clip"]),
            ("video",         ["clip"]),
            ("press_kit",     ["press_kit"]),
            ("brand_deck",    ["brand_deck"]),
            ("audio",         ["audio"]),
            ("demo",          ["audio", "clip"]),
        ]

        def _match_media_types(qid: str):
            qid_lo = qid.lower()
            for token, mtypes in _QID_TO_MTYPE:
                if token in qid_lo:
                    return mtypes
            return ["gallery"]

        media_matches: List[Dict[str, Any]] = []
        media_qs = [a for a in universal_rendered + category_rendered if (a["type"] or "").lower() in MEDIA_QTYPES]
        if media_qs:
            # Iter 56 perf polish — Instead of one Mongo query per media
            # question, fetch the artist's newest few media docs across all
            # relevant types in a single call and match in Python.
            wanted_types = set()
            for a in media_qs:
                wanted_types.update(_match_media_types(a["id"]))
            media_docs = await db.media.find(
                {"user_id": artist_id, "type": {"$in": list(wanted_types)}},
                projection={"data": 0},
                sort=[("created_at", -1)],
            ).to_list(200)
            for a in media_qs:
                wanted = _match_media_types(a["id"])
                m = next((d for d in media_docs if d.get("type") in wanted), None)
                if m:
                    media_matches.append({
                        "question_id": a["id"],
                        "question": a["question"],
                        "media_id": m["id"],
                        "media_type": m.get("type"),
                        "mime": m.get("mime"),
                        "title": m.get("title"),
                    })

        # ── Iter 56 — Completion stats for the onboarding nudge ────────────
        # Count DISTINCT sections in the union of universal+category
        # questions and how many have at least one answer.
        def _sections_of(qs):
            return {q.get("section") or "Details" for q in qs if q.get("id") or q.get("key")}

        sections_available = _sections_of(universal) | _sections_of(category)
        sections_answered = {a["section"] or "Details" for a in universal_rendered + category_rendered}

        return {
            "universal": universal_rendered,
            "category": category_rendered,
            "category_slug": category_slug,
            "raw_answers_count": len(answers),
            "media_matches": media_matches,
            "completion": {
                "sections_total": len(sections_available),
                "sections_answered": len(sections_answered),
                "sections_missing": sorted(sections_available - sections_answered),
                "questions_total": len([q for q in universal + category if q.get("id") or q.get("key")]),
                "questions_answered": len(universal_rendered) + len(category_rendered),
            },
        }

    # ── Iter 56 — Completion nudge for the artist dashboard ─────────────
    # Returns just the completion block from the About endpoint so the
    # dashboard banner can render without pulling every answer.
    @r.get("/questionnaire/completion/mine")
    async def my_completion(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        if user["role"] != "artist":
            raise HTTPException(403, "Artist only")
        # Delegate to the public endpoint's logic to avoid drift.
        try:
            about = await artist_about(user["id"])  # type: ignore
        except HTTPException as e:
            if e.status_code == 404:
                return {"sections_total": 0, "sections_answered": 0,
                        "sections_missing": [], "questions_total": 0, "questions_answered": 0}
            raise
        return about["completion"]

    # ── Admin CRUD for question metadata (rename/reorder/add/remove) ─────
    class _MetaBody(BaseModel):
        questions: List[Dict[str, Any]]

    @r.put("/admin/questionnaire/universal")
    async def admin_set_universal(body: _MetaBody, _: dict = Depends(admin_only)) -> Dict[str, Any]:
        await db.questionnaire_meta.update_one(
            {"id": "universal"},
            {"$set": {"id": "universal", "questions": body.questions, "updated_at": utcnow()}},
            upsert=True,
        )
        return {"ok": True, "count": len(body.questions)}

    @r.put("/admin/questionnaire/category/{slug}")
    async def admin_set_category(slug: str, body: _MetaBody, _: dict = Depends(admin_only)) -> Dict[str, Any]:
        await db.questionnaire_meta.update_one(
            {"id": f"cat:{slug}"},
            {"$set": {"id": f"cat:{slug}", "slug": slug, "questions": body.questions, "updated_at": utcnow()}},
            upsert=True,
        )
        return {"ok": True, "count": len(body.questions)}

    return r
