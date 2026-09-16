"""Iter 78 — Per-IP sliding-window rate limiter.

Simple in-memory limiter — no Redis dependency, no external service. Good
enough to block scripted brute-force + Gmail-quota abuse from a single
attacker. If we ever move to multiple backend replicas we'd swap the
storage for Redis, but the public API here stays the same.
"""
from __future__ import annotations

import time
import threading
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request

# key -> deque[timestamp]
_hits: Dict[str, Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """Best-effort client IP that respects the trusted proxy chain.

    Ingress in front of our backend appends the real client IP to
    ``X-Forwarded-For``, so we take the first entry. Falls back to the raw
    socket peer when the header is missing (local dev).
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    return request.client.host if request.client else "unknown"


def check(
    request: Request,
    bucket: str,
    limit: int,
    window_seconds: int,
    key_extra: str = "",
    error_msg: str = "Too many requests — please try again shortly.",
) -> None:
    """Raise HTTP 429 when the caller has exceeded ``limit`` hits within
    ``window_seconds`` for the given ``bucket``.

    ``key_extra`` lets callers scope the bucket by a second identifier
    (typically the target email address) on top of the IP.
    """
    ip = _client_ip(request)
    key = f"{bucket}:{ip}:{key_extra}"
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        q = _hits[key]
        # drop expired hits
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            retry_after = max(1, int(q[0] + window_seconds - now))
            raise HTTPException(
                status_code=429,
                detail=error_msg,
                headers={"Retry-After": str(retry_after)},
            )
        q.append(now)


def reset(bucket: str, ip: str, key_extra: str = "") -> None:
    """Clear the counter for a specific caller — used after a successful
    action so a legitimate user's next request isn't punished."""
    key = f"{bucket}:{ip}:{key_extra}"
    with _lock:
        _hits.pop(key, None)


def ip_of(request: Request) -> str:
    """Public helper so callers can pass the same IP to :func:`reset`."""
    return _client_ip(request)
