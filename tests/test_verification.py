"""Tests for the verification engine — the three-verdict logic that must not be
wrong (brief §12). Model inference is not involved here; we feed signals in
directly, which is exactly how the engine is meant to be tested.
"""
from __future__ import annotations

from app.schemas.analysis import (
    Confidence,
    RegistryMatch,
    SemanticResult,
    Signal,
    Verdict,
)
from app.services.verification import decide


def _semantic(**kw) -> SemanticResult:
    base = dict(summary="test", topic="other", language_detected="en")
    base.update(kw)
    return SemanticResult(**base)


def _forensic(name: str, risk: float) -> Signal:
    return Signal(name=name, label=name, risk=risk, direction="risk",
                  raw={"forensic": True})


def test_no_match_no_evidence_is_unconfirmed():
    """The honest default: not in registry != fake."""
    out = decide([], _semantic(), RegistryMatch(matched=False))
    assert out.verdict == Verdict.unconfirmed


def test_registry_match_is_verified():
    reg = RegistryMatch(matched=True, organization_name="MINESEC",
                        organization_slug="minesec")
    out = decide([], _semantic(), reg)
    assert out.verdict == Verdict.verified


def test_registry_match_but_strong_manipulation_is_altered():
    """Forensic evidence overrides a registry match — a hijacked/forged asset."""
    signals = [_forensic("image_classifier", 0.95), _forensic("ela", 0.9)]
    reg = RegistryMatch(matched=True, organization_name="MINESEC")
    out = decide(signals, _semantic(), reg)
    assert out.verdict == Verdict.altered


def test_lone_high_ela_does_not_trigger_altered():
    """ELA alone is unreliable on re-encoded images; it must not decide ALTERED."""
    signals = [_forensic("ela", 0.99)]
    out = decide(signals, _semantic(), RegistryMatch(matched=False))
    assert out.verdict != Verdict.altered
    assert out.verdict == Verdict.unconfirmed


def test_ela_plus_classifier_can_trigger_altered():
    signals = [_forensic("ela", 0.85), _forensic("image_classifier", 0.9)]
    out = decide(signals, _semantic(), RegistryMatch(matched=False))
    assert out.verdict == Verdict.altered


def test_scam_text_without_forensics_stays_unconfirmed_not_altered():
    """A pushy scam message is UNCONFIRMED, never ALTERED — no manipulation of media."""
    signals = [Signal(name="pattern:payment", label="PIN loop", risk=0.9,
                      direction="risk")]
    sem = _semantic(financial_request=True, urgency_pressure=True)
    out = decide(signals, sem, RegistryMatch(matched=False))
    assert out.verdict == Verdict.unconfirmed
    assert out.risk_score > 0.5  # engine still records elevated risk


def test_weak_manipulation_below_floor_ignored():
    signals = [_forensic("image_classifier", 0.4)]
    out = decide(signals, _semantic(), RegistryMatch(matched=False))
    assert out.verdict == Verdict.unconfirmed


def test_confidence_is_a_band():
    out = decide([], _semantic(), RegistryMatch(matched=False))
    assert out.confidence in (Confidence.low, Confidence.medium, Confidence.high)
