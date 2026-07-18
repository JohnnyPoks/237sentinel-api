"""Verification engine (brief §6) — the heart of the product.

Combines forensic signals + semantic reading + registry lookup into exactly one
of three verdicts. Design rules that are enforced, not just intended:

  * Not in the registry NEVER means fake. It means UNCONFIRMED. This is the
    honest default and will be the most common result.
  * VERIFIED requires a positive registry match AND no strong manipulation.
  * ALTERED requires strong forensic evidence of synthesis/alteration.
  * Confidence is a band (low/medium/high), never a bare percentage.

All thresholds come from config.Thresholds — no magic numbers here.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Thresholds as T
from app.schemas.analysis import (
    Confidence,
    RegistryMatch,
    SemanticResult,
    Signal,
    Verdict,
)


@dataclass
class VerificationOutcome:
    verdict: Verdict
    confidence: Confidence
    signals: list[Signal]  # contributing signals, for the audit trail
    manipulation_score: float
    risk_score: float


def _strong_manipulation(signals: list[Signal]) -> tuple[bool, float]:
    """Is there strong forensic evidence of synthesis/alteration?

    Only classifier/forensic signals count here. ELA is deliberately weighted
    down (see config) because it is unreliable alone on re-encoded images, so a
    lone high ELA reading cannot by itself produce an ALTERED verdict.
    """
    forensic = [s for s in signals if s.raw.get("forensic")]
    if not forensic:
        return False, 0.0

    weighted = 0.0
    weight_sum = 0.0
    for s in forensic:
        if s.risk < T.ALTERED_IGNORE_BELOW:
            continue
        w = T.ELA_WEIGHT if s.name == "ela" else T.CLASSIFIER_WEIGHT
        weighted += s.risk * w
        weight_sum += w
    score = weighted / weight_sum if weight_sum else 0.0

    # A single ELA signal, however high, is not "strong" on its own.
    non_ela_strong = any(
        s.name != "ela" and s.risk >= T.ALTERED_STRONG for s in forensic
    )
    strong = score >= T.ALTERED_STRONG and (non_ela_strong or len(forensic) >= 2)
    return strong, round(score, 3)


def _aggregate_risk(signals: list[Signal], semantic: SemanticResult) -> float:
    """Overall behavioural risk on 0..1 (scam-pattern / pressure signals)."""
    risks = [s.risk for s in signals if s.direction == "risk"]
    base = max(risks) if risks else 0.0
    # Semantic pressure nudges risk up but never alone decides the verdict.
    pressure = sum(
        [semantic.financial_request, semantic.urgency_pressure]
    ) * 0.15
    return min(1.0, base + pressure)


def _confidence(n_supporting: int) -> Confidence:
    if n_supporting >= T.CONF_HIGH_SIGNALS:
        return Confidence.high
    if n_supporting >= T.CONF_MEDIUM_SIGNALS:
        return Confidence.medium
    return Confidence.low


def decide(
    signals: list[Signal],
    semantic: SemanticResult,
    registry: RegistryMatch,
) -> VerificationOutcome:
    strong_alter, manip_score = _strong_manipulation(signals)
    risk_score = _aggregate_risk(signals, semantic)

    # 1. Strong forensic evidence of alteration wins outright.
    if strong_alter:
        supporting = [
            s for s in signals if s.raw.get("forensic") and s.risk >= T.ALTERED_IGNORE_BELOW
        ]
        return VerificationOutcome(
            verdict=Verdict.altered,
            confidence=_confidence(len(supporting)),
            signals=signals,
            manipulation_score=manip_score,
            risk_score=risk_score,
        )

    # 2. Positive registry match + no strong manipulation => really them.
    if registry.matched and not strong_alter:
        # Trust signals (e.g. matched channel, old domain) raise confidence.
        trust = [s for s in signals if s.direction == "trust"]
        return VerificationOutcome(
            verdict=Verdict.verified,
            confidence=_confidence(len(trust) + 1),  # the match itself counts
            signals=signals,
            manipulation_score=manip_score,
            risk_score=risk_score,
        )

    # 3. Everything else is honestly UNCONFIRMED. Not-in-registry != fake.
    #    Confidence here describes how sure we are of "we can't confirm", which
    #    rises with the number of concrete risk signals we did observe.
    risky = [s for s in signals if s.direction == "risk" and s.risk >= 0.5]
    return VerificationOutcome(
        verdict=Verdict.unconfirmed,
        confidence=_confidence(len(risky)),
        signals=signals,
        manipulation_score=manip_score,
        risk_score=risk_score,
    )
