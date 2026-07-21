"""Explanation layer (brief §6).

Turns findings into plain language a person with no technical background can act
on, in English and French. It is now a RELIABLE, content-aware renderer driven by
the semantic understanding — not a fixed refrain, and not a second LLM call.

The single LLM call (the semantic layer) provides the intelligence: what this is
(bilingual summary), who it claims to be, what it wants, and whether there is a
money/urgency/identity signal. This layer renders that into a tailored message
whose ACTION fits the content:

  * a benign document gets reassurance, not a scary "call a number";
  * a message claiming an organisation we know points to that organisation's real
    official channel;
  * a money/PIN request gets the "use a number you already have" advice;
  * VERIFIED confirms the match; ALTERED says do not share.

Because there is no LLM call here, the output is consistent and never
quota-limited — which matters on a free host where the LLM may be rate-limited.
"""
from __future__ import annotations

from app.schemas.analysis import (
    Explanation,
    RegistryMatch,
    SemanticResult,
    Signal,
    Verdict,
)

CIVIC_EN = "Before you share this, check the source. Reporting this protects other Cameroonians."
CIVIC_FR = "Avant de partager, vérifiez la source. Signaler ceci protège d'autres Camerounais."

_HEADLINE = {
    Verdict.verified: ("This is really them.", "C'est bien eux."),
    Verdict.unconfirmed: ("We cannot confirm this.", "Nous ne pouvons pas le confirmer."),
    Verdict.altered: ("This was altered.", "Ceci a été modifié."),
}


def _channel_hint(known_org: dict | None) -> tuple[str | None, str | None]:
    if not known_org:
        return None, None
    chans = known_org.get("channels", []) or []
    domain = next((c["value"] for c in chans if c.get("type") in ("domain", "page")), None)
    phone = next((c["value"] for c in chans if c.get("type") == "phone"), None)
    hint = domain or known_org.get("website") or phone
    return known_org.get("name"), hint


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
    h_en, h_fr = _HEADLINE[verdict]
    summary_en = semantic.summary
    summary_fr = semantic.summary_fr or semantic.summary
    org = registry.organization_name or "the organisation"
    signals = signals or []
    risky = [s for s in signals if s.direction == "risk" and s.risk >= 0.5]
    org_name, channel = _channel_hint(known_org)

    def out(body_en, body_fr, action_en, action_fr):
        return Explanation(
            headline_en=h_en, headline_fr=h_fr,
            summary_en=summary_en, summary_fr=summary_fr,
            body_en=body_en, body_fr=body_fr,
            action_en=action_en, action_fr=action_fr,
            checked_en=checked_en, checked_fr=checked_fr,
        )

    # --- VERIFIED ---------------------------------------------------------
    if verdict == Verdict.verified:
        return out(
            f"This matches a channel registered to {org}. The sender is who they claim to be.",
            f"Ceci correspond à un canal enregistré par {org}. L'expéditeur est bien celui qu'il prétend être.",
            f"Still confirm any payment with {org} directly.",
            f"Confirmez tout de même chaque paiement directement avec {org}.",
        )

    # --- ALTERED ----------------------------------------------------------
    if verdict == Verdict.altered:
        extra_en = f" {corroboration} other people reported something similar." if corroboration else ""
        extra_fr = f" {corroboration} autres personnes ont signalé la même chose." if corroboration else ""
        return out(
            "Part of this does not match the rest — it looks like it was changed or added from somewhere else." + extra_en,
            "Une partie ne correspond pas au reste : elle semble avoir été modifiée ou ajoutée depuis un autre document." + extra_fr,
            "Do not share this. Sharing it spreads the panic.",
            "Ne partagez pas ceci. Le partager propage la panique.",
        )

    # --- UNCONFIRMED: branch on what we actually found ---------------------
    money = semantic.financial_request
    has_request = money or bool(semantic.requested_action)
    benign = not risky and not money and not semantic.identity_claim

    # 1) Nothing looks like a scam — reassure, do not invent danger.
    if benign:
        return out(
            "This looks like ordinary content. We found no signs of a scam.",
            "Ceci ressemble à un contenu ordinaire. Nous n'avons trouvé aucun signe d'arnaque.",
            "No urgent action is needed — just verify anything important through a source you already trust.",
            "Aucune action urgente n'est nécessaire — vérifiez simplement tout élément important auprès d'une source que vous connaissez déjà.",
        )

    # 2) It asks for money / a code / a payment.
    if money or "pin" in (semantic.requested_action or "").lower():
        body_en = "We found no proof this is fake, and no proof it is real. It asks you to pay or share money or a secret code"
        body_fr = "Nous n'avons aucune preuve que c'est faux, ni aucune preuve que c'est vrai. Il vous demande de payer ou de partager de l'argent ou un code secret"
        if semantic.urgency_pressure:
            body_en += ", and it pressures you to act quickly"
            body_fr += ", et il vous presse d'agir vite"
        body_en += "."
        body_fr += "."
        if org_name and channel:
            return out(
                body_en, body_fr,
                f"The real {org_name} can be reached at {channel}. Confirm there — never pay or share a code based on this message.",
                f"Le vrai {org_name} est joignable via {channel}. Vérifiez là — ne payez jamais et ne partagez aucun code à cause de ce message.",
            )
        return out(
            body_en, body_fr,
            "Do not pay or share any code. Confirm with the organisation using a number you already have — not the one in this message.",
            "Ne payez rien et ne partagez aucun code. Vérifiez auprès de l'organisation via un numéro que vous avez déjà — pas celui indiqué dans ce message.",
        )

    # 3) It claims to be an organisation (identity claim), no money.
    if semantic.identity_claim:
        claimed = semantic.claimed_identity or "an official body"
        if org_name and channel:
            return out(
                f"This claims to be from {org_name}, but we cannot confirm it actually came from them.",
                f"Ceci prétend venir de {org_name}, mais nous ne pouvons pas confirmer que cela vient réellement d'eux.",
                f"Check with {org_name} directly — their official channel is {channel}. Do not rely on this message alone.",
                f"Vérifiez directement auprès de {org_name} — leur canal officiel est {channel}. Ne vous fiez pas à ce seul message.",
            )
        return out(
            f"This presents itself as {claimed}, but we could not match it to any official channel we know.",
            "Ceci se présente comme une source officielle, mais nous n'avons pu le relier à aucun canal officiel connu.",
            f"Find {claimed}'s own official website or contact and check there before acting.",
            "Trouvez le site ou le contact officiel de cette source et vérifiez-y avant d'agir.",
        )

    # 4) Some risk, but no clear request or identity claim.
    return out(
        "We found no proof this is fake, and no proof it is real.",
        "Nous n'avons aucune preuve que c'est faux, ni aucune preuve que c'est vrai.",
        "Verify anything important through an official source you already trust before acting on it.",
        "Vérifiez tout élément important via une source officielle que vous connaissez déjà avant d'agir.",
    )
