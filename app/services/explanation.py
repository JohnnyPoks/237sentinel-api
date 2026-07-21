"""Explanation layer (brief §6).

Turns findings into plain language a person with no technical background can act
on, in English and French. The message is now LLM-generated and TAILORED to the
specific content — not a fixed refrain — with a deterministic template fallback.

Rules the LLM is held to:
  * Say what happened, then what to do. No jargon. Never "AI-generated".
  * The action must fit THIS content: a benign document gets reassurance, not a
    scary "call a number"; a message claiming an organisation we know points to
    that organisation's real official channel; a money/PIN request gets the
    "use a number you already have" advice.
  * If nothing looks like a scam, say so plainly instead of implying danger.
  * Every result ends with a civic line (added outside the LLM).
"""
from __future__ import annotations

import json
import re

from app.schemas.analysis import (
    Explanation,
    RegistryMatch,
    SemanticResult,
    Signal,
    Verdict,
)
from app.services.llm import NO_LLM, get_llm
from app.core.logging import get_logger

log = get_logger("explanation")

CIVIC_EN = "Before you share this, check the source. Reporting this protects other Cameroonians."
CIVIC_FR = "Avant de partager, vérifiez la source. Signaler ceci protège d'autres Camerounais."

# Headlines stay canonical per verdict — the three-verdict framing is the point.
_HEADLINE = {
    Verdict.verified: ("This is really them.", "C'est bien eux."),
    Verdict.unconfirmed: ("We cannot confirm this.", "Nous ne pouvons pas le confirmer."),
    Verdict.altered: ("This was altered.", "Ceci a été modifié."),
}

_EXPLAIN_SYSTEM = """You write the final, user-facing verdict message for a \
verification service used by ordinary people in Cameroon who may have little \
technical knowledge. Plain, calm, concrete language. Never use jargon. Never say \
"AI-generated". You are given the verdict, a structured understanding of the \
content, whether the sender matched a registry of official channels, the real \
official channels of any organisation it claims to be (if we know them), and the \
checks that ran.

Write a SHORT message TAILORED to THIS content — never a generic template.

Return ONLY a JSON object with these keys (both languages, equal care):
{
 "summary_en","summary_fr",   // one plain sentence: what this content is
 "body_en","body_fr",         // 1-2 sentences: why this verdict, specific to it
 "action_en","action_fr"      // ONE relevant next step (see rules)
}

Rules for the action:
- Money/PIN/urgent-payment request: tell them to check with the organisation using \
a number or channel they ALREADY have — not the one in this message.
- It claims to be an organisation we listed real channels for: point them to that \
real channel (e.g. the official website or number) to confirm, instead of trusting \
this message.
- It is a link or claims an organisation we do NOT know: tell them to find that \
organisation's own official website/contact and check there.
- It shows NO sign of a scam (no money request, no impersonation, ordinary topic): \
reassure plainly — say it looks like ordinary content and no action is needed \
beyond normal caution. Do NOT invent danger.
- VERIFIED: it matches the official channel; still confirm any payment directly.
- ALTERED: tell them not to share it.

Rules for the body: be specific to the content. If it is benign, say so ("This \
looks like an ordinary ... We found no signs of a scam."). Do not imply threat \
that the evidence does not support."""


def _extract_json(raw: str) -> dict | None:
    if not raw or raw == NO_LLM:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", cleaned, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _llm_explanation(
    verdict: Verdict,
    semantic: SemanticResult,
    registry: RegistryMatch,
    signals: list[Signal],
    content_type: str,
    checked_en: str,
    checked_fr: str,
    known_org: dict | None,
) -> Explanation | None:
    llm = get_llm()
    risky = [s for s in signals if s.direction == "risk" and s.risk >= 0.5]
    context = {
        "verdict": verdict.value,
        "content_type": content_type,
        "understanding": {
            "summary": semantic.summary,
            "claimed_identity": semantic.claimed_identity,
            "requested_action": semantic.requested_action,
            "financial_request": semantic.financial_request,
            "urgency_pressure": semantic.urgency_pressure,
            "identity_claim": semantic.identity_claim,
            "topic": semantic.topic,
        },
        "registry_match": {
            "matched": registry.matched,
            "organisation": registry.organization_name,
        },
        "known_official_channels": known_org,  # {name, channels:[...]} or None
        "risk_signals": [s.label for s in risky] or ["none"],
    }
    user = json.dumps(context, ensure_ascii=False)

    for attempt in (1, 2):
        raw = llm.complete(_EXPLAIN_SYSTEM, user, want_json=True)
        data = _extract_json(raw)
        if data and all(
            k in data for k in ("summary_en", "body_en", "action_en", "action_fr")
        ):
            h_en, h_fr = _HEADLINE[verdict]
            return Explanation(
                headline_en=h_en, headline_fr=h_fr,
                summary_en=data.get("summary_en", semantic.summary),
                summary_fr=data.get("summary_fr", data.get("summary_en", "")),
                body_en=data["body_en"], body_fr=data.get("body_fr", data["body_en"]),
                action_en=data["action_en"], action_fr=data.get("action_fr", data["action_en"]),
                checked_en=checked_en, checked_fr=checked_fr,
            )
    return None


# --- Deterministic fallback (used when the LLM is unavailable) ---------------
def _semantic_clause_en(s: SemanticResult) -> str:
    bits = []
    if s.financial_request:
        bits.append("It asks you to pay or send money")
    if s.urgency_pressure:
        bits.append("it pressures you to act quickly")
    if s.identity_claim and s.claimed_identity:
        bits.append(f"it presents itself as {s.claimed_identity}")
    if not bits:
        return ""
    clause = ", and ".join(bits) if len(bits) > 1 else bits[0]
    return clause[0].upper() + clause[1:] + "."


def _semantic_clause_fr(s: SemanticResult) -> str:
    bits = []
    if s.financial_request:
        bits.append("Il vous demande de payer ou d'envoyer de l'argent")
    if s.urgency_pressure:
        bits.append("il vous presse d'agir vite")
    if s.identity_claim and s.claimed_identity:
        bits.append("il se présente comme une source officielle")
    if not bits:
        return ""
    clause = ", et ".join(bits) if len(bits) > 1 else bits[0]
    return clause + "."


def _template_explanation(
    verdict: Verdict,
    semantic: SemanticResult,
    registry: RegistryMatch,
    checked_en: str,
    checked_fr: str,
    corroboration: int,
) -> Explanation:
    org = registry.organization_name or "the organisation"
    h_en, h_fr = _HEADLINE[verdict]

    if verdict == Verdict.verified:
        return Explanation(
            headline_en=h_en, headline_fr=h_fr,
            summary_en=semantic.summary, summary_fr=semantic.summary,
            body_en=f"This matches a channel registered to {org}. The sender is who they claim to be.",
            body_fr=f"Ceci correspond à un canal enregistré par {org}. L'expéditeur est bien celui qu'il prétend être.",
            action_en=f"Still confirm any payment with {org} directly.",
            action_fr=f"Confirmez tout de même chaque paiement directement avec {org}.",
            checked_en=checked_en, checked_fr=checked_fr,
        )
    if verdict == Verdict.altered:
        extra_en = f" {corroboration} other people reported something similar." if corroboration else ""
        extra_fr = f" {corroboration} autres personnes ont signalé la même chose." if corroboration else ""
        return Explanation(
            headline_en=h_en, headline_fr=h_fr,
            summary_en=semantic.summary, summary_fr=semantic.summary,
            body_en="Part of this does not match the rest — it looks like it was changed or added from somewhere else." + extra_en,
            body_fr="Une partie ne correspond pas au reste : elle semble avoir été modifiée ou ajoutée depuis un autre document." + extra_fr,
            action_en="Do not share this. Sharing it spreads the panic.",
            action_fr="Ne partagez pas ceci. Le partager propage la panique.",
            checked_en=checked_en, checked_fr=checked_fr,
        )

    clause_en = _semantic_clause_en(semantic)
    clause_fr = _semantic_clause_fr(semantic)
    body_en = "We found no proof this is fake, and no proof it is real."
    body_fr = "Nous n'avons aucune preuve que c'est faux, ni aucune preuve que c'est vrai."
    if clause_en:
        body_en += " " + clause_en
        body_fr += " " + clause_fr
    # Only give the "call a number" advice when it actually fits (a request).
    if semantic.financial_request or semantic.requested_action:
        action_en = "Call them on a number you already have. Do not use the number in this message."
        action_fr = "Appelez-les sur un numéro que vous avez déjà. N'utilisez pas le numéro indiqué dans ce message."
    else:
        action_en = "Verify anything important through an official source you already trust before acting on it."
        action_fr = "Vérifiez tout élément important via une source officielle que vous connaissez déjà avant d'agir."
    return Explanation(
        headline_en=h_en, headline_fr=h_fr,
        summary_en=semantic.summary, summary_fr=semantic.summary,
        body_en=body_en, body_fr=body_fr,
        action_en=action_en, action_fr=action_fr,
        checked_en=checked_en, checked_fr=checked_fr,
    )


def build(
    verdict: Verdict,
    semantic: SemanticResult,
    registry: RegistryMatch,
    checked_en: str,
    checked_fr: str,
    signals: list[Signal] | None = None,
    content_type: str = "text",
    known_org: dict | None = None,
    corroboration: int = 0,
) -> Explanation:
    try:
        via_llm = _llm_explanation(
            verdict, semantic, registry, signals or [], content_type,
            checked_en, checked_fr, known_org,
        )
        if via_llm is not None:
            return via_llm
    except Exception as exc:  # noqa: BLE001
        log.warning("llm explanation failed, using template: %s", exc)
    return _template_explanation(
        verdict, semantic, registry, checked_en, checked_fr, corroboration
    )
