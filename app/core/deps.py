"""Request dependencies: IP hashing, rate limiting, API-key auth.

Rate limiting is in-memory (per-process) — fine for a single Space instance and
the demo. A multi-instance production deployment should move this to Redis; noted
in the README. We never store a raw IP: only a salted hash, used for rate limits,
"me too" dedupe, and usage events.
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import AuthError, RateLimitedError
from app.db.session import get_db
from app.models.tables import ApiKey, Organization

# Process-local salt so hashes are not linkable across restarts.
_SALT = hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]

# actor -> list[timestamps] within the window
_hits: dict[str, list[float]] = defaultdict(list)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def hash_ip(ip: str) -> str:
    return hashlib.sha256((_SALT + ip).encode()).hexdigest()


def ip_hash(request: Request) -> str:
    return hash_ip(client_ip(request))


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def rate_limit(request: Request, kind: str = "analyze", limit: int | None = None) -> None:
    actor = ip_hash(request)
    per_hour = limit if limit is not None else settings.rate_limit_per_hour
    now = time.time()
    window_start = now - 3600
    bucket = _hits[f"{actor}:{kind}"]
    bucket[:] = [t for t in bucket if t > window_start]
    if len(bucket) >= per_hour:
        raise RateLimitedError(
            "You have reached the free hourly limit. Please try again later."
        )
    bucket.append(now)


def rate_limit_analyze(request: Request) -> None:
    rate_limit(request, "analyze", settings.rate_limit_per_hour)


def rate_limit_video(request: Request) -> None:
    rate_limit(request, "video", settings.rate_limit_video_per_hour)


def require_org(
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Organization:
    """Resolve an organisation from its API key, or 401."""
    if not x_api_key:
        raise AuthError("Missing API key. Send it in the X-API-Key header.")
    row = db.execute(
        select(ApiKey).where(ApiKey.key_hash == hash_key(x_api_key)).where(
            ApiKey.is_active.is_(True)
        )
    ).scalar_one_or_none()
    if not row:
        raise AuthError("Invalid or inactive API key.")
    org = db.get(Organization, row.organization_id)
    if not org or not org.is_active:
        raise AuthError("Organisation not found or inactive.")
    return org
