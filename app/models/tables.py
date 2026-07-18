"""Database tables (brief §6).

Personal identifiers are kept out of anything that feeds the pattern layer:
`Analysis.content_preview` is a short, redacted snippet only, and raw media is
stored only with explicit consent (default off) and auto-purged at 30 days.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    content_type: Mapped[str] = mapped_column(String(16))  # link/text/image/...
    # Redacted, truncated preview only. Never the full submission.
    content_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str] = mapped_column(String(16))  # VERIFIED/UNCONFIRMED/ALTERED
    confidence: Mapped[str] = mapped_column(String(8))  # low/medium/high
    # Full structured result payload (signals, semantic, explanation).
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    # Only set when the user consented to media storage. Path or null.
    media_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))  # ministry/bank/school/...
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # public_record for seeded entries, self for registered customers.
    source: Mapped[str] = mapped_column(String(40), default="self")
    verified_by: Mapped[str] = mapped_column(String(40), default="pending")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    channels: Mapped[list["OrgChannel"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["OrgAlert"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class OrgChannel(Base):
    __tablename__ = "org_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    channel_type: Mapped[str] = mapped_column(String(20))  # phone/handle/domain/page
    # Normalised value used for exact matching (see services/registry.py).
    value: Mapped[str] = mapped_column(String(255), index=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    organization: Mapped[Organization] = relationship(back_populates="channels")


class OrgAlert(Base):
    __tablename__ = "org_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    # An analysis that claimed this org's identity but did not match a channel.
    analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="new")  # new/seen/closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    organization: Mapped[Organization] = relationship(back_populates="alerts")


class CommunityReport(Base):
    __tablename__ = "community_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)  # anonymised at write time
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    linked_analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # moderation
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ReportConfirmation(Base):
    __tablename__ = "report_confirmations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("community_reports.id"), index=True
    )
    # Hashed IP so we can dedupe "me too" without storing the address.
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ScamPattern(Base):
    __tablename__ = "scam_patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40))
    # Regex or phrase list, matched by the text service.
    pattern: Mapped[str] = mapped_column(Text)
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(8), default="mixed")
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="public_record")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    # Only the hash is stored; the plaintext is shown once at creation.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12))  # for display, e.g. sk_ab12
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Hashed IP or api key id — never a raw address.
    actor: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # analyze/report/verify/...
    content_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
