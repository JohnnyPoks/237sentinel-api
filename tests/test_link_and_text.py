"""Tests for pure-logic parts of the link and text services (no model load)."""
from __future__ import annotations

from app.services.link import KNOWN_GOOD, _levenshtein, _typosquat_signal
from app.services.text import _extract_urls


def test_typosquat_detects_near_miss_of_known_domain():
    sig = _typosquat_signal("0range.cm")  # zero instead of o
    assert sig is not None
    assert sig.name == "typosquat"
    assert sig.direction == "risk"


def test_exact_known_domain_is_trusted_not_flagged():
    sig = _typosquat_signal("orange.cm")
    assert sig is not None
    assert sig.direction == "trust"
    assert "orange.cm" in KNOWN_GOOD


def test_unrelated_domain_no_typosquat():
    assert _typosquat_signal("some-random-shop.example") is None


def test_levenshtein_basic():
    assert _levenshtein("mtn", "mtn") == 0
    assert _levenshtein("mtn.cm", "rntn.cm") == 2


def test_extract_urls_from_text():
    urls = _extract_urls("go to https://a.cm and www.b.cm now")
    assert "https://a.cm" in urls
    assert any(u.startswith("http://www.b.cm") for u in urls)
