"""Link service (brief §6).

Extracts the root domain, checks registration age (a domain under 30 days old
is a strong risk signal), runs the urlbert classifier, checks HTTPS
reachability, and detects typosquatting against a seed list of known-good
Cameroonian domains. Every step degrades to an "unknown" signal on failure —
a WHOIS timeout must not fail the whole analysis.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import Thresholds as T
from app.core.logging import get_logger
from app.schemas.analysis import ContentType, ServiceOutput, Signal
from app.services.tld import extract as tld_extract

log = get_logger("link")

# Known-good Cameroonian domains used as the typosquatting reference set.
KNOWN_GOOD = [
    "spm.gov.cm", "prc.cm", "minsante.gov.cm", "minesec.gov.cm", "minesup.gov.cm",
    "minpostel.gov.cm", "antic.cm", "cirt.cm", "impots.cm",
    "mtn.cm", "orange.cm", "afrilandfirstbank.com", "ecobank.com",
    "camtel.cm", "eneo.cm", "camwater.cm",
    "cameroon-tribune.cm", "crtv.cm", "camair-co.com", "univ-yaounde1.cm",
    "univ-buea.cm",
]


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(
                min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            )
        prev = cur
    return prev[-1]


def _root_domain(url: str) -> str:
    ext = tld_extract(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return url.strip().lower()


def _typosquat_signal(domain: str) -> Signal | None:
    """Flag domains that are one or two edits from a known-good domain."""
    if domain in KNOWN_GOOD:
        return Signal(
            name="known_domain",
            label="Matches a known official domain",
            risk=0.0,
            direction="trust",
            detail=f"{domain} is a recognised official domain.",
            raw={"domain": domain},
        )
    for good in KNOWN_GOOD:
        dist = _levenshtein(domain, good)
        if 0 < dist <= 2 and abs(len(domain) - len(good)) <= 3:
            return Signal(
                name="typosquat",
                label="Looks like a copy of a real address",
                risk=0.85,
                direction="risk",
                detail=f"'{domain}' closely resembles the official '{good}'.",
                raw={"domain": domain, "resembles": good, "distance": dist},
            )
    return None


def _whois_age_signal(domain: str) -> Signal:
    try:
        import whois  # python-whois

        data = whois.whois(domain)
        created = data.creation_date
        if isinstance(created, list):
            created = created[0]
        if not isinstance(created, datetime):
            raise ValueError("no creation date")
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).days
        if age_days < T.DOMAIN_AGE_RISK_DAYS:
            return Signal(
                name="domain_age",
                label="This address was created very recently",
                risk=0.8,
                direction="risk",
                detail=f"The domain is only {age_days} days old.",
                raw={"age_days": age_days, "created": str(created.date())},
            )
        return Signal(
            name="domain_age",
            label="This address has existed for a while",
            risk=0.1,
            direction="trust",
            detail=f"The domain is about {age_days} days old.",
            raw={"age_days": age_days, "created": str(created.date())},
        )
    except Exception as exc:  # noqa: BLE001
        log.info("whois unavailable for %s: %s", domain, exc)
        return Signal(
            name="domain_age",
            label="We could not check how old this address is",
            risk=0.3,
            direction="neutral",
            detail="Registration date could not be retrieved.",
            raw={"error": str(exc)[:120]},
        )


def _classifier_signal(url: str) -> Signal:
    try:
        from app.services.model_loader import link_classifier

        clf = link_classifier()
        preds = clf(url)
        if preds and isinstance(preds[0], list):
            preds = preds[0]
        scores = {p["label"].lower(): float(p["score"]) for p in preds}
        malicious = sum(
            v for k, v in scores.items()
            if any(bad in k for bad in ("phish", "malware", "defac"))
        )
        # binary fallback model uses labels like LABEL_1 / benign / malicious
        if not any(
            bad in k for k in scores for bad in ("phish", "malware", "defac", "benign")
        ):
            malicious = max(
                (v for k, v in scores.items() if k in ("label_1", "malicious")),
                default=0.0,
            )
        risk = min(1.0, malicious)
        return Signal(
            name="url_classifier",
            label=(
                "This link looks dangerous"
                if risk >= T.LINK_RISK
                else "This link does not look obviously dangerous"
            ),
            risk=risk,
            direction="risk" if risk >= T.LINK_RISK else "neutral",
            detail="Automated link check.",
            raw={"scores": scores},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("link classifier unavailable: %s", exc)
        return Signal(
            name="url_classifier",
            label="Automated link check was unavailable",
            risk=0.3,
            direction="neutral",
            detail="The link model could not be loaded.",
            raw={"error": str(exc)[:120]},
        )


def _https_signal(url: str) -> Signal:
    try:
        import httpx

        target = url if url.startswith(("http://", "https://")) else f"http://{url}"
        r = httpx.get(target, timeout=8.0, follow_redirects=True)
        secure = str(r.url).startswith("https://")
        return Signal(
            name="https",
            label="Uses a secure connection" if secure else "Not a secure connection",
            risk=0.0 if secure else 0.4,
            direction="trust" if secure else "risk",
            detail=f"Final URL scheme: {'https' if secure else 'http'}.",
            raw={"final_url": str(r.url), "status": r.status_code},
        )
    except Exception as exc:  # noqa: BLE001
        return Signal(
            name="https",
            label="The site could not be reached",
            risk=0.35,
            direction="neutral",
            detail="No response from the address.",
            raw={"error": str(exc)[:120]},
        )


def analyze(url: str) -> ServiceOutput:
    domain = _root_domain(url)
    signals: list[Signal] = []

    typo = _typosquat_signal(domain)
    if typo:
        signals.append(typo)
    signals.append(_whois_age_signal(domain))
    signals.append(_classifier_signal(url))
    signals.append(_https_signal(url))

    return ServiceOutput(
        content_type=ContentType.link,
        extracted_text=url,
        signals=signals,
        notes=[f"root domain: {domain}"],
    )
