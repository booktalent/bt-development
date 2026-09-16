"""
BookTalent — per-domain route modules.

Each module exports a `make_xxx_router(**deps) -> APIRouter` factory so that
shared helpers (db, get_current_user, admin_only, utility functions defined in
server.py) can be injected without circular imports.

This split was introduced in Iter 13 to break the monolithic server.py
(~2.8k lines) into smaller, domain-focused files for production maintenance.

Iter 36 (business-model pivot): the wallet router was removed. BookTalent is
a lead-generation marketplace and no longer holds artist funds.
"""
from . import reviews, coupons, blogs, disputes, kyc, uploads, addons, cms_seo, questionnaire

__all__ = ["reviews", "coupons", "blogs", "disputes", "kyc", "uploads", "addons", "cms_seo", "questionnaire"]
