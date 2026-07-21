"""Semantic layer (brief §5) — the core.

Answers "what is this content about, who does it claim to be, and what does it
want?" — not "was AI involved?". Combines with forensic signals downstream.

Uses the configured LLM with a strict JSON contract (SemanticResult). Retries
once on parse failure, then degrades to a deterministic heuristic pass so the
request never crashes because the model rambled or no key is set.
"""
from __future__ import annotations

import json
import re

from app.schemas.analysis import SemanticResult, Signal
from app.services.llm import NO_LLM, get_llm
from app.core.logging import get_logger

log = get_logger("semantic")

SYSTEM_PROMPT = """You are the semantic analysis layer of a digital verification \
service for Cameroon. You are given the text content of something a citizen \
received (a message, a transcript, or text read from an image/document) and a \
short list of forensic findings. Your job is NOT to decide if it is fake. Your \
job is to describe, in neutral terms, what the content is, who it claims to be \
from, and what it asks the person to do.

Return ONLY a single JSON object, no prose, with exactly these keys:
{
 "summary": "one plain sentence describing what this content is",
 "claimed_identity": "the ORGANISATION or official body it claims to be from \
(e.g. a bank, a ministry, an operator), or null. A document author's personal \
name is NOT a claimed identity — use null for that.",
 "requested_action": "what it wants the person to do, or null",
 "financial_request": true or false,
 "urgency_pressure": true or false,
 "identity_claim": true only if it claims to be an official body/organisation; \
false for ordinary personal or informational content,
 "topic": "investment|recruitment|scholarship|payment|announcement|other",
 "language_detected": "en|fr|mixed",
 "reasoning": "one short sentence for the audit trail"
}
Do not invent suspicion. Ordinary, informational or personal content with no \
money request and no official impersonation is normal — reflect that honestly. \
Never output the words "AI-generated". Describe what is happening, not how it \
was made."""


# --- Heuristic fallback lexicons (EN + FR). Deliberately conservative. --------
_MONEY = re.compile(
    r"\b(fcfa|xaf|cfa|frs?|francs?|money|argent|payer?|pay|transfer|"
    r"mobile\s?money|momo|orange\s?money|deposit|dép[oô]t|frais|fee|"
    r"virement|recharge|montant|\d[\d\s.,]{2,}\s?(?:fcfa|xaf|cfa|frs?))\b",
    re.I,
)
_URGENCY = re.compile(
    r"\b(urgent|immediately|imm[eé]diat|maintenant|now|today|aujourd|deadline|"
    r"d[eé]lai|avant|before|expire|derni[eè]re chance|last chance|vite|quick|"
    r"48\s?h|24\s?h|dernier délai)\b",
    re.I,
)
_IDENTITY = re.compile(
    r"\b(minist[eè]re|ministry|minesec|minesup|minsante|minpostel|antic|"
    r"gouvernement|government|official|officiel|direction|banque|bank|mtn|"
    r"orange|crtv|president|pr[eé]sident|ambassad|scholarship|bourse|concours|"
    r"recrutement|recruitment)\b",
    re.I,
)
_CREDENTIAL = re.compile(
    r"\b(pin|code|password|mot de passe|otp|c[oô]de secret|validate|valider|"
    r"confirm your|confirmez|identifiant|login|connectez)\b",
    re.I,
)
_FR_HINT = re.compile(
    r"\b(le|la|les|des|vous|votre|bonjour|merci|payer|argent|s'il|"
    r"veuillez|nous|pour|avec|dans)\b",
    re.I,
)
_EN_HINT = re.compile(
    r"\b(the|you|your|please|money|pay|hello|thanks|we|for|with|and|this)\b", re.I
)

_TOPIC_RULES = [
    ("investment", re.compile(r"\b(invest|placement|rendement|return|profit|roi|"
                              r"trading|crypto|forex|b[eé]n[eé]fice)\b", re.I)),
    ("scholarship", re.compile(r"\b(scholarship|bourse|[eé]tude|study|university|"
                               r"universit[eé]|exam|concours)\b", re.I)),
    ("recruitment", re.compile(r"\b(recruit|recrut|job|emploi|hiring|embauche|"
                               r"candidat|poste|vacancy)\b", re.I)),
    ("payment", re.compile(r"\b(pay|payer|momo|mobile money|transfer|virement|"
                           r"frais|fee|deposit)\b", re.I)),
    ("announcement", re.compile(r"\b(communiqu[eé]|announce|annonce|notice|avis|"
                                r"press|d[eé]cret|arr[eê]t[eé])\b", re.I)),
]


def _detect_language(text: str) -> str:
    fr = len(_FR_HINT.findall(text))
    en = len(_EN_HINT.findall(text))
    if fr and en and abs(fr - en) <= max(2, min(fr, en)):
        return "mixed"
    if fr > en:
        return "fr"
    if en > fr:
        return "en"
    return "mixed"


def _heuristic(text: str, findings: list[Signal]) -> SemanticResult:
    """Deterministic fallback when no LLM is available or parsing fails."""
    t = text or ""
    financial = bool(_MONEY.search(t))
    urgency = bool(_URGENCY.search(t))
    identity = bool(_IDENTITY.search(t))
    topic = "other"
    for name, rx in _TOPIC_RULES:
        if rx.search(t):
            topic = name
            break
    snippet = " ".join(t.split())[:140]
    summary = (
        f"A {topic} message"
        + (" that asks for money" if financial else "")
        + (" and creates time pressure" if urgency else "")
        + (f": “{snippet}”" if snippet else ".")
    )
    action = None
    if financial:
        action = "send money or make a payment"
    elif _CREDENTIAL.search(t):
        action = "share a secret code, PIN or password"
    return SemanticResult(
        summary=summary,
        claimed_identity=None if not identity else "an official-sounding sender",
        requested_action=action,
        financial_request=financial,
        urgency_pressure=urgency,
        identity_claim=identity,
        topic=topic,  # type: ignore[arg-type]
        language_detected=_detect_language(t),  # type: ignore[arg-type]
        reasoning="Rule-based fallback (no LLM configured or parse failed).",
    )


def _extract_json(raw: str) -> dict | None:
    if not raw or raw == NO_LLM:
        return None
    # Strip code fences and grab the first {...} block.
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _media_semantic(
    text: str, findings: list[Signal], media_bytes: bytes, media_mime: str
) -> SemanticResult | None:
    """Read the media (image/PDF/...) directly through the LLM chain's vision
    path (Gemini vision -> HF router vision). Understands a forged communiqué or
    a cloned voice note far better than the extracted text alone. Returns None to
    fall back to the text path."""
    findings_summary = "; ".join(f"{s.name}={s.risk:.2f}" for s in findings) or "none"
    prompt = (
        SYSTEM_PROMPT
        + "\n\nThe user forwarded this media file. Extracted text (may be empty): "
        + f"\n{text[:3000]}\n\nForensic findings: {findings_summary}\n\n"
        "Look at the media itself and return the JSON object now."
    )
    raw = get_llm().complete_vision(prompt, media_bytes, media_mime, want_json=True)
    data = _extract_json(raw)
    if data is None:
        return None
    try:
        return SemanticResult.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("media semantic invalid: %s", exc)
        return None


def analyze(
    text: str,
    findings: list[Signal],
    media_bytes: bytes | None = None,
    media_mime: str | None = None,
) -> SemanticResult:
    """Return a SemanticResult for the given extracted text + forensic findings.

    When a media file and a Gemini key are available, Gemini reads the media
    directly (multimodal); otherwise we use the configured text LLM, and finally
    the deterministic heuristic.
    """
    if media_bytes and media_mime:
        via_media = _media_semantic(text, findings, media_bytes, media_mime)
        if via_media is not None:
            return via_media

    llm = get_llm()

    findings_summary = "; ".join(
        f"{s.name}={s.risk:.2f}({s.direction})" for s in findings
    ) or "none"
    user = (
        f"CONTENT:\n{text[:6000]}\n\n"
        f"FORENSIC FINDINGS: {findings_summary}\n\n"
        "Return the JSON object now."
    )

    for attempt in (1, 2):
        raw = llm.complete(SYSTEM_PROMPT, user, want_json=True)
        data = _extract_json(raw)
        if data is not None:
            try:
                return SemanticResult.model_validate(data)
            except Exception as exc:  # noqa: BLE001
                log.warning("semantic parse invalid (attempt %s): %s", attempt, exc)
        if attempt == 1:
            user += "\n\nYour previous reply was not valid JSON. Return ONLY the JSON."

    log.warning("semantic layer degraded to heuristic after 2 failed attempts")
    return _heuristic(text, findings)
