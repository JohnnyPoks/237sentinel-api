"""Tests for registry normalisation and candidate extraction."""
from __future__ import annotations

from app.services.registry import (
    extract_candidates,
    normalize_domain,
    normalize_handle,
    normalize_phone,
)


def test_phone_normalisation_local_to_e164():
    assert normalize_phone("677 12 34 56") == "+237677123456"
    assert normalize_phone("+237 677123456") == "+237677123456"
    assert normalize_phone("00237677123456") == "+237677123456"


def test_shortcode_preserved():
    # 4-digit shortcodes are not 9-digit mobiles; keep them intact-ish.
    assert normalize_phone("8202").endswith("8202")


def test_domain_normalisation_strips_subdomain_and_path():
    assert normalize_domain("https://www.minesec.gov.cm/exams") == "minesec.gov.cm"
    assert normalize_domain("MINESEC.GOV.CM") == "minesec.gov.cm"


def test_handle_normalisation():
    assert normalize_handle("MINESEC_Cmr") == "@minesec_cmr"
    assert normalize_handle("@Orange") == "@orange"


def test_extract_candidates_from_message():
    text = ("Contactez le +237 677 12 34 56 ou visitez https://pay.example.cm "
            "ou @FakeMinesec")
    cands = extract_candidates(text)
    assert "+237677123456" in cands["phone"]
    assert "example.cm" in cands["domain"]
    assert "@fakeminesec" in cands["handle"]
