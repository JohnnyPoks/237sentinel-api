"""Organization endpoints (brief §6).

Public: searchable registry, public profile, verify-sender.
Authenticated (X-API-Key): the org's own channels, alerts, API keys, dashboard.
Self-registration creates an org in `pending` state (admin approves) and returns
one API key, shown once.
"""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import hash_key, require_org
from app.core.errors import NotFoundError, SentinelError
from app.db.session import get_db
from app.models.tables import (
    ApiKey,
    OrgAlert,
    OrgChannel,
    Organization,
    UsageEvent,
)
from app.schemas.analysis import RegistryMatch
from app.services import registry as registry_service

router = APIRouter(prefix="/api/v1", tags=["organizations"])


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return base or secrets.token_hex(4)


def _new_api_key(db: Session, org_id: str, label: str | None = None) -> str:
    raw = "sk_" + secrets.token_urlsafe(24)
    db.add(ApiKey(
        organization_id=org_id, key_hash=hash_key(raw), key_prefix=raw[:8], label=label
    ))
    db.commit()
    return raw


# --- Schemas ---------------------------------------------------------------
class ChannelIn(BaseModel):
    channel_type: str = Field(pattern="^(phone|handle|domain|page)$")
    value: str
    label: str | None = None


class OrgRegister(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    kind: str = Field(default="other", max_length=40)
    description: str | None = None
    region: str | None = None
    website: str | None = None
    channels: list[ChannelIn] = Field(default_factory=list)


class VerifySenderIn(BaseModel):
    channel_type: str = Field(pattern="^(phone|handle|domain|page)$")
    value: str


def _org_public(org: Organization) -> dict:
    return {
        "id": org.id,
        "slug": org.slug,
        "name": org.name,
        "kind": org.kind,
        "description": org.description,
        "region": org.region,
        "website": org.website,
        "source": org.source,
        "verified_by": org.verified_by,
        "channels": [
            {"channel_type": c.channel_type, "value": c.value, "label": c.label,
             "verified": c.verified}
            for c in org.channels
        ],
    }


# --- Public ----------------------------------------------------------------
@router.get("/organizations")
def list_orgs(q: str | None = None, limit: int = 30, offset: int = 0,
              db: Session = Depends(get_db)) -> dict:
    stmt = select(Organization).where(Organization.is_active.is_(True))
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q}%"))
    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar() or 0
    rows = db.execute(
        stmt.order_by(Organization.name).limit(min(limit, 100)).offset(offset)
    ).scalars().all()
    return {"total": total, "items": [_org_public(o) for o in rows]}


@router.get("/organizations/{slug_or_id}")
def get_org(slug_or_id: str, db: Session = Depends(get_db)) -> dict:
    org = db.execute(
        select(Organization).where(
            (Organization.slug == slug_or_id) | (Organization.id == slug_or_id)
        )
    ).scalar_one_or_none()
    if not org or not org.is_active:
        raise NotFoundError("No organisation with that name.")
    return _org_public(org)


@router.post("/organizations")
def register_org(payload: OrgRegister, db: Session = Depends(get_db)) -> dict:
    slug = _slugify(payload.name)
    if db.execute(select(Organization).where(Organization.slug == slug)).scalar_one_or_none():
        slug = f"{slug}-{secrets.token_hex(2)}"
    org = Organization(
        slug=slug, name=payload.name, kind=payload.kind,
        description=payload.description, region=payload.region,
        website=payload.website, source="self", verified_by="pending",
    )
    db.add(org)
    db.flush()
    for ch in payload.channels:
        db.add(OrgChannel(
            organization_id=org.id, channel_type=ch.channel_type,
            value=registry_service.normalize(ch.channel_type, ch.value), label=ch.label,
        ))
    db.commit()
    db.refresh(org)
    api_key = _new_api_key(db, org.id, label="initial")
    return {
        "organization": _org_public(org),
        "api_key": api_key,
        "note": "Save this key now — it is shown only once. Your organisation is pending admin review.",
    }


@router.post("/verify-sender")
def verify_sender(payload: VerifySenderIn, db: Session = Depends(get_db)) -> RegistryMatch:
    return registry_service.lookup(db, payload.channel_type, payload.value)


# --- Authenticated (owner) -------------------------------------------------
@router.get("/organizations/me/dashboard")
def my_dashboard(org: Organization = Depends(require_org),
                 db: Session = Depends(get_db)) -> dict:
    alerts = db.execute(
        select(func.count(OrgAlert.id)).where(OrgAlert.organization_id == org.id)
    ).scalar() or 0
    new_alerts = db.execute(
        select(func.count(OrgAlert.id))
        .where(OrgAlert.organization_id == org.id)
        .where(OrgAlert.status == "new")
    ).scalar() or 0
    queries = db.execute(
        select(func.count(UsageEvent.id)).where(UsageEvent.kind == "verify")
    ).scalar() or 0
    return {
        "organization": _org_public(org),
        "alerts_total": alerts,
        "alerts_new": new_alerts,
        "verification_queries": queries,
    }


@router.get("/organizations/me/alerts")
def my_alerts(org: Organization = Depends(require_org),
              db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(OrgAlert).where(OrgAlert.organization_id == org.id)
        .order_by(OrgAlert.created_at.desc()).limit(200)
    ).scalars().all()
    return {"items": [
        {"id": a.id, "reason": a.reason, "severity": a.severity,
         "status": a.status, "analysis_id": a.analysis_id,
         "created_at": a.created_at.isoformat()}
        for a in rows
    ]}


@router.get("/organizations/me/channels")
def my_channels(org: Organization = Depends(require_org)) -> dict:
    return {"items": [
        {"id": c.id, "channel_type": c.channel_type, "value": c.value,
         "label": c.label, "verified": c.verified}
        for c in org.channels
    ]}


@router.post("/organizations/me/channels")
def add_channel(payload: ChannelIn, org: Organization = Depends(require_org),
                db: Session = Depends(get_db)) -> dict:
    ch = OrgChannel(
        organization_id=org.id, channel_type=payload.channel_type,
        value=registry_service.normalize(payload.channel_type, payload.value),
        label=payload.label,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return {"id": ch.id, "channel_type": ch.channel_type, "value": ch.value}


@router.delete("/organizations/me/channels/{channel_id}")
def delete_channel(channel_id: str, org: Organization = Depends(require_org),
                   db: Session = Depends(get_db)) -> dict:
    ch = db.get(OrgChannel, channel_id)
    if not ch or ch.organization_id != org.id:
        raise NotFoundError("No such channel.")
    db.delete(ch)
    db.commit()
    return {"deleted": channel_id}


@router.get("/organizations/me/api-keys")
def my_api_keys(org: Organization = Depends(require_org),
                db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(ApiKey).where(ApiKey.organization_id == org.id)
    ).scalars().all()
    return {"items": [
        {"id": k.id, "prefix": k.key_prefix, "label": k.label,
         "is_active": k.is_active, "created_at": k.created_at.isoformat()}
        for k in rows
    ]}


@router.post("/organizations/me/api-keys")
def create_api_key(org: Organization = Depends(require_org),
                   db: Session = Depends(get_db), label: str | None = None) -> dict:
    raw = _new_api_key(db, org.id, label=label)
    return {"api_key": raw, "note": "Shown only once. Store it securely."}
