"""Text service (brief §6).

Zero-shot classification (mDeBERTa) against curated candidate labels, extraction
of any embedded URLs (handed to the link service), and a scam-pattern lookup.
Returns per-label signals plus matched patterns. Multilingual EN/FR; it does
NOT understand Pidgin or Camfranglais (documented as a limitation).
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEXT_CANDIDATE_LABELS
from app.config import Thresholds as T
from app.core.logging import get_logger
from app.models.tables import ScamPattern
from app.schemas.analysis import ContentType, ServiceOutput, Signal
from app.services import link as link_service

log = get_logger("text")

_URL_RE = re.compile(r"(https?://[^\s)]+|www\.[^\s)]+)", re.I)

# Human phrasing for the zero-shot labels so the citizen never sees jargon.
_LABEL_HUMAN = {
    "monetary demand": "It asks for money",
    "urgency": "It pressures you to act fast",
    "account suspension": "It threatens to block your account",
    "investment offer": "It promises money from an investment",
    "prize or lottery": "It claims you won a prize",
    "recruitment offer": "It offers a job",
    "identity claim": "It claims to be an official body",
    "credential request": "It asks for a code, PIN or password",
}

# Labels that, when present, point toward scam behaviour.
_RISKY_LABELS = {
    "monetary demand", "account suspension", "investment offer",
    "prize or lottery", "credential request",
}

# Fallback scam patterns used when no DB session is provided (e.g. unit tests).
_FALLBACK_PATTERNS: list[dict] = [
    {"name": "Mobile Money PIN validation", "category": "payment",
     "pattern": r"(valider|confirm).{0,20}(pin|code).{0,20}(momo|mobile money|orange money)",
     "is_regex": True, "weight": 0.85,
     "explanation": "Real Mobile Money never asks you to share your PIN to validate."},
    {"name": "Fixed-return investment", "category": "investment",
     "pattern": r"(\d{2,3}\s?%|double|triple).{0,30}(profit|return|rendement|jour|day|week)",
     "is_regex": True, "weight": 0.8,
     "explanation": "Guaranteed high fixed returns are the signature of investment scams."},
    {"name": "Advance fee for prize/job", "category": "recruitment",
     "pattern": r"(frais|fee|payer|pay).{0,25}(inscription|dossier|registration|activation)",
     "is_regex": True, "weight": 0.75,
     "explanation": "Paying a fee to receive a prize or job is a common scam."},
]


def _extract_urls(text: str) -> list[str]:
    urls = []
    for m in _URL_RE.finditer(text or ""):
        u = m.group()
        urls.append(u if u.startswith("http") else "http://" + u)
    return list(dict.fromkeys(urls))  # dedupe, keep order


def _zeroshot_signals(text: str) -> list[Signal]:
    try:
        from app.config import Models
        from app.services import inference

        if inference.use_hf_api():
            out = inference.zero_shot(Models.TEXT_ZEROSHOT, text, TEXT_CANDIDATE_LABELS)
            if not out:
                raise RuntimeError("hf zero-shot unavailable")
        else:
            from app.services.model_loader import text_zeroshot

            clf = text_zeroshot()
            out = clf(text, candidate_labels=TEXT_CANDIDATE_LABELS, multi_label=True)
        signals = []
        for label, score in zip(out["labels"], out["scores"]):
            if score < T.TEXT_LABEL_PRESENT:
                continue
            risky = label in _RISKY_LABELS
            signals.append(
                Signal(
                    name=f"text:{label.replace(' ', '_')}",
                    label=_LABEL_HUMAN.get(label, label),
                    risk=float(score) if risky else min(0.4, float(score)),
                    direction="risk" if risky else "neutral",
                    detail="Detected from the wording of the message.",
                    raw={"label": label, "score": round(float(score), 3)},
                )
            )
        return signals
    except Exception as exc:  # noqa: BLE001
        log.warning("zero-shot text model unavailable: %s", exc)
        return [
            Signal(
                name="text:unavailable",
                label="Automated wording check was unavailable",
                risk=0.2,
                direction="neutral",
                detail="The text model could not be loaded.",
                raw={"error": str(exc)[:120]},
            )
        ]


def _pattern_signals(text: str, db: Session | None) -> list[Signal]:
    patterns = _FALLBACK_PATTERNS
    if db is not None:
        try:
            rows = [
                {
                    "name": p.name, "category": p.category, "pattern": p.pattern,
                    "is_regex": p.is_regex, "weight": p.weight,
                    "explanation": p.explanation,
                }
                for p in db.execute(select(ScamPattern)).scalars()
            ]
            if rows:
                patterns = rows
        except Exception as exc:  # noqa: BLE001 — table missing / DB down: use fallback
            log.info("scam_patterns query failed, using fallback: %s", exc)
            db.rollback()

    signals: list[Signal] = []
    low = (text or "").lower()
    for p in patterns:
        try:
            hit = (
                re.search(p["pattern"], low, re.I | re.S)
                if p["is_regex"]
                else p["pattern"].lower() in low
            )
        except re.error:
            hit = p["pattern"].lower() in low
        if hit:
            signals.append(
                Signal(
                    name=f"pattern:{p['category']}",
                    label=p["name"],
                    risk=float(p["weight"]),
                    direction="risk",
                    detail=p.get("explanation") or "Matches a known scam pattern.",
                    raw={"pattern_name": p["name"]},
                )
            )
    return signals


def analyze(text: str, db: Session | None = None) -> ServiceOutput:
    signals: list[Signal] = []
    signals.extend(_zeroshot_signals(text))
    signals.extend(_pattern_signals(text, db))

    sub_outputs = []
    for url in _extract_urls(text)[:3]:  # cap: don't fan out forever
        try:
            sub_outputs.append(link_service.analyze(url))
        except Exception as exc:  # noqa: BLE001
            log.warning("embedded link analysis failed for %s: %s", url, exc)

    # Bubble embedded-link signals up so the engine sees them.
    for sub in sub_outputs:
        signals.extend(sub.signals)

    return ServiceOutput(
        content_type=ContentType.text,
        extracted_text=text,
        signals=signals,
        sub_outputs=sub_outputs,
    )
