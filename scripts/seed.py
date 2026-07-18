"""Idempotent registry + scam-pattern seed (brief §7).

Seeds the registry from PUBLIC information so the free tier is useful on day
one. Every entry is marked source="public_record", verified_by="seed" — these
are NOT customers. Re-running is safe: entries are matched by slug / pattern
name and skipped if present.

Honesty note (see DECISIONS.md): channels here are best-effort public records
verified against the organisations' official websites and public reporting
shortcodes at build time. A production deployment MUST re-confirm each channel
directly with the organisation before it is used to return a VERIFIED verdict,
because a wrong "official" channel is actively harmful. The set is deliberately
limited to well-established government, telecom and public-service channels.

Run:  python -m scripts.seed          (from the repo root, with .env configured)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal, init_db  # noqa: E402
from app.models.tables import Organization, OrgChannel, ScamPattern  # noqa: E402
from app.services import registry as registry_service  # noqa: E402


# (slug, name, kind, region, website, description, [(channel_type, value, label)])
ORGS: list[tuple] = [
    ("antic", "ANTIC — National Agency for ICT", "government", "National",
     "https://www.antic.cm",
     "National agency for ICT. Report cybercrime free, 24/7, on shortcodes "
     "8202 and 8206, or email alerts@cirt.antic.cm.",
     [("domain", "antic.cm", "Website"),
      ("domain", "cirt.cm", "CIRT incident response"),
      ("phone", "8202", "Report cybercrime (toll-free)"),
      ("phone", "8206", "Report cybercrime (toll-free)")]),
    ("minesec", "MINESEC — Ministry of Secondary Education", "government", "National",
     "https://www.minesec.gov.cm",
     "Ministry of Secondary Education. Exams and official communiqués are "
     "published on the ministry website.",
     [("domain", "minesec.gov.cm", "Website")]),
    ("minesup", "MINESUP — Ministry of Higher Education", "government", "National",
     "https://www.minesup.gov.cm",
     "Ministry of Higher Education.",
     [("domain", "minesup.gov.cm", "Website")]),
    ("minsante", "MINSANTE — Ministry of Public Health", "government", "National",
     "https://www.minsante.gov.cm",
     "Ministry of Public Health.",
     [("domain", "minsante.gov.cm", "Website")]),
    ("minpostel", "MINPOSTEL — Ministry of Posts and Telecommunications",
     "government", "National", "https://www.minpostel.gov.cm",
     "Ministry of Posts and Telecommunications.",
     [("domain", "minpostel.gov.cm", "Website")]),
    ("spm", "Services du Premier Ministre", "government", "National",
     "https://spm.gov.cm",
     "Prime Minister's Office. Official decrees and communiqués.",
     [("domain", "spm.gov.cm", "Website")]),
    ("prc", "Présidence de la République du Cameroun", "government", "National",
     "https://www.prc.cm",
     "Presidency of the Republic of Cameroon.",
     [("domain", "prc.cm", "Website")]),
    ("mtn-cameroon", "MTN Cameroon", "telecom", "National", "https://mtn.cm",
     "Mobile operator. Customer care shortcode: 8787. MTN never asks for your "
     "Mobile Money PIN.",
     [("domain", "mtn.cm", "Website"),
      ("phone", "8787", "Customer care")]),
    ("orange-cameroon", "Orange Cameroun", "telecom", "National",
     "https://www.orange.cm",
     "Mobile operator. Customer care shortcode: 950. Orange never asks for your "
     "Orange Money secret code.",
     [("domain", "orange.cm", "Website"),
      ("phone", "950", "Customer care")]),
    ("camtel", "CAMTEL — Cameroon Telecommunications", "telecom", "National",
     "https://www.camtel.cm",
     "National telecommunications operator.",
     [("domain", "camtel.cm", "Website")]),
    ("afriland-first-bank", "Afriland First Bank", "bank", "National",
     "https://www.afrilandfirstbank.com",
     "Commercial bank. A bank never asks for your full PIN or card code by "
     "message.",
     [("domain", "afrilandfirstbank.com", "Website")]),
    ("ecobank-cameroon", "Ecobank Cameroon", "bank", "National",
     "https://ecobank.com",
     "Commercial bank.",
     [("domain", "ecobank.com", "Website")]),
    ("cameroon-tribune", "Cameroon Tribune", "media", "National",
     "https://www.cameroon-tribune.cm",
     "National daily newspaper (public record source).",
     [("domain", "cameroon-tribune.cm", "Website")]),
    ("crtv", "CRTV — Cameroon Radio Television", "media", "National",
     "https://www.crtv.cm",
     "National public broadcaster.",
     [("domain", "crtv.cm", "Website")]),
]


# Real observed scam patterns (brief §7). weight is 0..1 risk contribution.
PATTERNS: list[dict] = [
    {"name": "Mobile Money PIN validation loop", "category": "payment",
     "pattern": r"(pin|code\s*secret|secret\s*code).{0,40}(valider|confirm|verify|"
                r"validate|activer|activate|d[eé]bloquer|unblock)",
     "is_regex": True, "language": "mixed", "weight": 0.9,
     "explanation": "No operator or bank asks you to share your PIN or secret code "
                    "to validate, unblock or confirm anything."},
    {"name": "Fixed-return investment solicitation", "category": "investment",
     "pattern": r"(\d{2,3}\s?%|double[rz]?|triple[rz]?).{0,40}"
                r"(profit|return|rendement|gain|b[eé]n[eé]fice|par\s*jour|per\s*day|"
                r"par\s*semaine|per\s*week|garanti|guaranteed)",
     "is_regex": True, "language": "mixed", "weight": 0.85,
     "explanation": "Guaranteed high fixed returns in a short time are the signature "
                    "of Ponzi and investment scams."},
    {"name": "Advance fee for prize, job or scholarship", "category": "recruitment",
     "pattern": r"(frais|fee|payer|pay|versement|deposit).{0,40}"
                r"(inscription|dossier|registration|activation|traitement|"
                r"processing|d[eé]blocage)",
     "is_regex": True, "language": "mixed", "weight": 0.8,
     "explanation": "Being asked to pay a fee up front to receive a prize, job or "
                    "scholarship is a classic advance-fee scam."},
    {"name": "Lottery or prize win notification", "category": "prize",
     "pattern": r"(f[eé]licitations|congratulations|you\s*(have\s*)?won|vous\s*avez\s*"
                r"gagn[eé]|gagnant|winner|tirage|lottery|loterie)",
     "is_regex": True, "language": "mixed", "weight": 0.7,
     "explanation": "Unexpected prize wins from lotteries you never entered are used "
                    "to hook victims into paying 'release fees'."},
    {"name": "Account suspension pressure", "category": "phishing",
     "pattern": r"(compte|account).{0,30}(bloqu[eé]|suspend|suspendu|d[eé]sactiv|"
                r"blocked|closed|ferm[eé]).{0,60}(cliqu|click|lien|link|confirm|v[eé]rifi)",
     "is_regex": True, "language": "mixed", "weight": 0.8,
     "explanation": "Threats that your account will be blocked unless you click a link "
                    "and confirm details are used to steal logins."},
    {"name": "Fake official communiqué framing", "category": "announcement",
     "pattern": r"(communiqu[eé]|d[eé]cret|arr[eê]t[eé]|note\s*de\s*service|press\s*"
                r"release).{0,80}(minist|gouvernement|government|officiel|official)",
     "is_regex": True, "language": "mixed", "weight": 0.5,
     "explanation": "Forged communiqués imitate ministry letterhead. Always confirm on "
                    "the organisation's own website before sharing."},
    {"name": "Urgency deadline pressure", "category": "urgency",
     "pattern": r"(avant|before|dans les|within).{0,15}(24\s?h|48\s?h|\d+\s*"
                r"(heures?|hours?|minutes?|jours?|days?))",
     "is_regex": True, "language": "mixed", "weight": 0.45,
     "explanation": "Tight deadlines are engineered to make you act before you think."},
]


def seed() -> None:
    init_db()
    db = SessionLocal()
    created_orgs = created_channels = created_patterns = 0
    try:
        for slug, name, kind, region, website, desc, channels in ORGS:
            org = db.execute(
                select(Organization).where(Organization.slug == slug)
            ).scalar_one_or_none()
            if not org:
                org = Organization(
                    slug=slug, name=name, kind=kind, region=region, website=website,
                    description=desc, source="public_record", verified_by="seed",
                    is_active=True,
                )
                db.add(org)
                db.flush()
                created_orgs += 1
            for ctype, value, label in channels:
                norm = registry_service.normalize(ctype, value)
                exists = db.execute(
                    select(OrgChannel)
                    .where(OrgChannel.organization_id == org.id)
                    .where(OrgChannel.channel_type == ctype)
                    .where(OrgChannel.value == norm)
                ).scalar_one_or_none()
                if not exists:
                    db.add(OrgChannel(
                        organization_id=org.id, channel_type=ctype, value=norm,
                        label=label, verified=True,
                    ))
                    created_channels += 1

        for p in PATTERNS:
            exists = db.execute(
                select(ScamPattern).where(ScamPattern.name == p["name"])
            ).scalar_one_or_none()
            if not exists:
                db.add(ScamPattern(
                    name=p["name"], category=p["category"], pattern=p["pattern"],
                    is_regex=p["is_regex"], language=p["language"], weight=p["weight"],
                    explanation=p["explanation"], source="public_record",
                ))
                created_patterns += 1

        db.commit()
        print(
            f"Seed complete: +{created_orgs} orgs, +{created_channels} channels, "
            f"+{created_patterns} scam patterns."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
