"""Explanation layer (brief §6).

Turns findings into plain language a person with no technical background can act
on, in English and French. Rules:
  * Say what happened, then what to do.
  * No jargon: never "ELA", "wav2vec2", "confidence score", "synthetic artifacts".
  * Never "AI-generated" — say what it means for the person.
  * Every result ends with a civic line.

The deterministic templates below ARE the product's voice and are the default
(no LLM required). When an LLM is configured it may rephrase the body to weave
in the specific semantic finding, but it can never change the verdict, the
headline, or the recommended action, and it is constrained by the same rules.
"""
from __future__ import annotations

from app.schemas.analysis import (
    Explanation,
    RegistryMatch,
    SemanticResult,
    Verdict,
)

CIVIC_EN = "Before you share this, check the source. Reporting this protects other Cameroonians."
CIVIC_FR = "Avant de partager, vérifiez la source. Signaler ceci protège d'autres Camerounais."


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


def build(
    verdict: Verdict,
    semantic: SemanticResult,
    registry: RegistryMatch,
    checked_human_en: str,
    checked_human_fr: str,
    corroboration: int = 0,
) -> Explanation:
    org = registry.organization_name or "the organisation"

    if verdict == Verdict.verified:
        return Explanation(
            headline_en="This is really them.",
            headline_fr="C'est bien eux.",
            body_en=(
                f"This matches a channel registered to {org}. "
                "The sender is who they claim to be."
            ),
            body_fr=(
                f"Ceci correspond à un canal enregistré par {org}. "
                "L'expéditeur est bien celui qu'il prétend être."
            ),
            action_en=f"Still confirm any payment with {org} directly.",
            action_fr=f"Confirmez tout de même chaque paiement directement avec {org}.",
            checked_en=checked_human_en,
            checked_fr=checked_human_fr,
        )

    if verdict == Verdict.altered:
        extra_en = (
            f" {corroboration} other people reported something similar."
            if corroboration
            else ""
        )
        extra_fr = (
            f" {corroboration} autres personnes ont signalé la même chose."
            if corroboration
            else ""
        )
        return Explanation(
            headline_en="This was altered.",
            headline_fr="Ceci a été modifié.",
            body_en=(
                "Part of this does not match the rest — it looks like it was "
                "changed or added from somewhere else." + extra_en
            ),
            body_fr=(
                "Une partie ne correspond pas au reste : elle semble avoir été "
                "modifiée ou ajoutée depuis un autre document." + extra_fr
            ),
            action_en="Do not share this. Sharing it spreads the panic.",
            action_fr="Ne partagez pas ceci. Le partager propage la panique.",
            checked_en=checked_human_en,
            checked_fr=checked_human_fr,
        )

    # UNCONFIRMED — the honest default.
    clause_en = _semantic_clause_en(semantic)
    clause_fr = _semantic_clause_fr(semantic)
    body_en = "We found no proof this is fake, and no proof it is real."
    body_fr = "Nous n'avons aucune preuve que c'est faux, ni aucune preuve que c'est vrai."
    if clause_en:
        body_en += " " + clause_en
        body_fr += " " + clause_fr
    return Explanation(
        headline_en="We cannot confirm this.",
        headline_fr="Nous ne pouvons pas le confirmer.",
        body_en=body_en,
        body_fr=body_fr,
        action_en=(
            "Call them on a number you already have. Do not use the number in "
            "this message."
        ),
        action_fr=(
            "Appelez-les sur un numéro que vous avez déjà. N'utilisez pas le "
            "numéro indiqué dans ce message."
        ),
        checked_en=checked_human_en,
        checked_fr=checked_human_fr,
    )
