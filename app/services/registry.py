"""Registry lookup (brief §6).

Normalises phone numbers, handles, and domains so a message's sender can be
matched against registered organisation channels. A match means "this is really
them". No match means UNCONFIRMED — never "fake". When a message claims an
organisation's identity but matches no channel, we raise an impersonation alert
for that organisation (their reason to pay).
"""
from __future__ import annotations

import re

import tldextract
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import OrgAlert, OrgChannel, Organization
from app.schemas.analysis import RegistryMatch


def normalize_phone(value: str) -> str:
    """Cameroon-aware phone normalisation to +2376XXXXXXXX where possible."""
    digits = re.sub(r"[^\d+]", "", value)
    digits = digits.lstrip("+")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("237"):
        return "+" + digits
    # Local 9-digit Cameroon mobile numbers start with 6 (or legacy 2).
    if len(digits) == 9 and digits[0] in "62":
        return "+237" + digits
    return "+" + digits if digits else value.strip()


def normalize_handle(value: str) -> str:
    return "@" + value.lstrip("@").strip().lower()


def normalize_domain(value: str) -> str:
    ext = tldextract.extract(value)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return value.strip().lower()


def normalize(channel_type: str, value: str) -> str:
    if channel_type == "phone":
        return normalize_phone(value)
    if channel_type == "handle":
        return normalize_handle(value)
    if channel_type in ("domain", "page"):
        return normalize_domain(value)
    return value.strip().lower()


_PHONE_RE = re.compile(r"(?:\+?237)?[\s-]?[62]\d{2}[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{2}")
_HANDLE_RE = re.compile(r"@[A-Za-z0-9_.]{3,}")
_URL_RE = re.compile(r"https?://[^\s)]+", re.I)


def extract_candidates(text: str) -> dict[str, list[str]]:
    """Pull possible sender identifiers out of free text."""
    phones = [normalize_phone(m.group()) for m in _PHONE_RE.finditer(text or "")]
    handles = [normalize_handle(m.group()) for m in _HANDLE_RE.finditer(text or "")]
    domains = [normalize_domain(m.group()) for m in _URL_RE.finditer(text or "")]
    return {
        "phone": sorted(set(phones)),
        "handle": sorted(set(handles)),
        "domain": sorted(set(domains)),
    }


def lookup(db: Session, channel_type: str, value: str) -> RegistryMatch:
    norm = normalize(channel_type, value)
    row = db.execute(
        select(OrgChannel, Organization)
        .join(Organization, OrgChannel.organization_id == Organization.id)
        .where(OrgChannel.channel_type == channel_type)
        .where(OrgChannel.value == norm)
        .where(Organization.is_active.is_(True))
    ).first()
    if not row:
        return RegistryMatch(matched=False)
    channel, org = row
    return RegistryMatch(
        matched=True,
        organization_id=org.id,
        organization_name=org.name,
        organization_slug=org.slug,
        channel_type=channel.channel_type,
        channel_value=channel.value,
    )


def match_any(db: Session, text: str) -> RegistryMatch:
    """Try every identifier found in the text against the registry."""
    cands = extract_candidates(text)
    for ctype in ("domain", "phone", "handle"):
        for value in cands[ctype]:
            m = lookup(db, ctype, value)
            if m.matched:
                return m
    return RegistryMatch(matched=False)


def raise_impersonation_alert(
    db: Session, claimed_identity: str, analysis_id: str | None, reason: str
) -> None:
    """If text claims a known org by name but matched no channel, alert the org.

    Best-effort name match against active organisations; silent if none found.
    """
    if not claimed_identity:
        return
    needle = claimed_identity.lower()
    orgs = db.execute(select(Organization).where(Organization.is_active.is_(True))).scalars()
    for org in orgs:
        if org.name.lower() in needle or needle in org.name.lower():
            db.add(
                OrgAlert(
                    organization_id=org.id,
                    analysis_id=analysis_id,
                    reason=reason,
                    severity="medium",
                )
            )
            db.commit()
            return
