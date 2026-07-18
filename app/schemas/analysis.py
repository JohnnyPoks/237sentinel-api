"""Pydantic schemas for the analysis pipeline.

`SemanticResult` is the strict JSON contract the semantic LLM must satisfy
(brief §5). `Signal` is the common currency every service speaks so the
verification engine can aggregate them uniformly.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ContentType(str, Enum):
    link = "link"
    text = "text"
    image = "image"
    audio = "audio"
    video = "video"
    document = "document"


class Verdict(str, Enum):
    verified = "VERIFIED"
    unconfirmed = "UNCONFIRMED"
    altered = "ALTERED"


class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Signal(BaseModel):
    """One piece of evidence. `risk` is 0..1 where 1 = strongly suspicious.

    `direction` says whether the signal argues for authenticity or against it,
    so the engine never treats "domain is 8 years old" as a risk.
    """

    name: str
    # human-readable, non-technical where possible
    label: str
    risk: float = Field(ge=0.0, le=1.0)
    direction: Literal["risk", "trust", "neutral"] = "risk"
    detail: str | None = None
    # raw value for the technical/expandable panel
    raw: dict[str, Any] = Field(default_factory=dict)


class SemanticResult(BaseModel):
    """Strict output contract for the semantic layer LLM (brief §5)."""

    summary: str
    claimed_identity: str | None = None
    requested_action: str | None = None
    financial_request: bool = False
    urgency_pressure: bool = False
    identity_claim: bool = False
    topic: Literal[
        "investment",
        "recruitment",
        "scholarship",
        "payment",
        "announcement",
        "other",
    ] = "other"
    language_detected: Literal["en", "fr", "mixed"] = "mixed"
    reasoning: str = ""


class RegistryMatch(BaseModel):
    matched: bool = False
    organization_id: str | None = None
    organization_name: str | None = None
    organization_slug: str | None = None
    channel_type: str | None = None
    channel_value: str | None = None


class Explanation(BaseModel):
    """Citizen-facing, plain-language output (brief §6). EN + FR."""

    headline_en: str
    headline_fr: str
    body_en: str
    body_fr: str
    action_en: str
    action_fr: str
    checked_en: str  # "we checked the link, the writing, and the stamp"
    checked_fr: str


class ServiceOutput(BaseModel):
    """What each per-modality service returns into the pipeline."""

    content_type: ContentType
    extracted_text: str | None = None
    signals: list[Signal] = Field(default_factory=list)
    # nested outputs (e.g. video -> audio -> text), for the audit trail
    sub_outputs: list["ServiceOutput"] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """The full response returned by POST /api/v1/analyze."""

    id: str
    content_type: ContentType
    verdict: Verdict
    confidence: Confidence
    summary: str
    semantic: SemanticResult
    registry: RegistryMatch
    explanation: Explanation
    signals: list[Signal]
    checked: list[str]  # machine list of what ran, for the "what we checked" line
    created_at: str


class AnalyzeTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    consent_store: bool = False


ServiceOutput.model_rebuild()
