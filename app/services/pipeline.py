"""Pipeline orchestrator (brief §4).

Dispatches to the right per-modality service, gathers every signal and the
extracted semantic text, runs the semantic layer, matches the registry, decides
the verdict, builds the plain-language explanation, persists the analysis, and
returns the full result. Individual service failures degrade to signals; they
never crash the request.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import UnsupportedContentError
from app.core.logging import get_logger
from app.models.tables import Analysis
from app.schemas.analysis import (
    AnalysisResult,
    ContentType,
    ServiceOutput,
    Signal,
)
from app.services import (
    audio as audio_service,
    document as document_service,
    explanation as explanation_service,
    image as image_service,
    link as link_service,
    registry as registry_service,
    semantic as semantic_service,
    text as text_service,
    verification as verification_engine,
    video as video_service,
)

log = get_logger("pipeline")

# Which human-readable "we checked ..." phrase each content type contributes.
_CHECKED_EN = {
    ContentType.link: "the link",
    ContentType.text: "the writing",
    ContentType.image: "the image and any stamp on it",
    ContentType.document: "the document and its stamps",
    ContentType.audio: "the voice recording",
    ContentType.video: "the video and its sound",
}
_CHECKED_FR = {
    ContentType.link: "le lien",
    ContentType.text: "le texte",
    ContentType.image: "l'image et son éventuel cachet",
    ContentType.document: "le document et ses cachets",
    ContentType.audio: "l'enregistrement vocal",
    ContentType.video: "la vidéo et son audio",
}


def _flatten_signals(out: ServiceOutput) -> list[Signal]:
    signals = list(out.signals)
    for sub in out.sub_outputs:
        signals.extend(_flatten_signals(sub))
    # Deduplicate by (name, label) keeping the highest risk.
    best: dict[tuple[str, str], Signal] = {}
    for s in signals:
        key = (s.name, s.label)
        if key not in best or s.risk > best[key].risk:
            best[key] = s
    return list(best.values())


def _gather_text(out: ServiceOutput) -> str:
    parts = [out.extracted_text or ""]
    for sub in out.sub_outputs:
        parts.append(_gather_text(sub))
    return "\n".join(p for p in parts if p).strip()


def _checked_lists(content_type: ContentType, text: str) -> tuple[list[str], str, str]:
    types = {content_type}
    if text:
        types.add(ContentType.text)
    en = [_CHECKED_EN[t] for t in types if t in _CHECKED_EN]
    fr = [_CHECKED_FR[t] for t in types if t in _CHECKED_FR]
    human_en = "We checked " + _join_en(en) + "."
    human_fr = "Nous avons vérifié " + _join_fr(fr) + "."
    return sorted(t.value for t in types), human_en, human_fr


def _join_en(items: list[str]) -> str:
    items = sorted(set(items))
    if len(items) <= 1:
        return items[0] if items else "the content"
    return ", ".join(items[:-1]) + " and " + items[-1]


def _join_fr(items: list[str]) -> str:
    items = sorted(set(items))
    if len(items) <= 1:
        return items[0] if items else "le contenu"
    return ", ".join(items[:-1]) + " et " + items[-1]


_MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf",
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".mp3": "audio/mpeg",
    ".wav": "audio/wav", ".m4a": "audio/mp4", ".opus": "audio/ogg",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    ".3gp": "video/3gpp",
}
_DEFAULT_MIME = {
    ContentType.image: "image/jpeg", ContentType.document: "application/pdf",
    ContentType.audio: "audio/ogg", ContentType.video: "video/mp4",
}


def _media_mime(content_type: ContentType, suffix: str) -> str | None:
    if content_type not in _DEFAULT_MIME:
        return None
    return _MIME_BY_SUFFIX.get((suffix or "").lower(), _DEFAULT_MIME[content_type])


def _dispatch(
    content_type: ContentType,
    *,
    text: str | None,
    file_bytes: bytes | None,
    suffix: str,
    db: Session,
) -> ServiceOutput:
    if content_type == ContentType.link:
        return link_service.analyze(text or "")
    if content_type == ContentType.text:
        return text_service.analyze(text or "", db)
    if content_type == ContentType.image:
        return image_service.analyze(file_bytes or b"", db)
    if content_type == ContentType.document:
        return document_service.analyze(file_bytes or b"", db)
    if content_type == ContentType.audio:
        return audio_service.analyze(file_bytes or b"", suffix or ".ogg", db)
    if content_type == ContentType.video:
        return video_service.analyze(file_bytes or b"", suffix or ".mp4", db)
    raise UnsupportedContentError(f"Unsupported content type: {content_type}")


def run(
    db: Session,
    content_type: ContentType,
    *,
    text: str | None = None,
    file_bytes: bytes | None = None,
    suffix: str = "",
    consent_store: bool = False,
) -> AnalysisResult:
    output = _dispatch(
        content_type, text=text, file_bytes=file_bytes, suffix=suffix, db=db
    )
    # If a caption/message was sent alongside a media file, analyse it too — the
    # attached message may be harmful even when the file is not (and vice versa).
    if text and content_type in (
        ContentType.image, ContentType.audio, ContentType.video, ContentType.document
    ):
        try:
            output.sub_outputs.append(text_service.analyze(text, db))
            output.notes.append("accompanying message also analysed")
        except Exception as exc:  # noqa: BLE001
            log.warning("caption analysis failed: %s", exc)

    signals = _flatten_signals(output)
    gathered_text = _gather_text(output)

    # For media, let the semantic layer read the file itself (Gemini multimodal).
    media_mime = _media_mime(content_type, suffix) if file_bytes else None
    semantic = semantic_service.analyze(
        gathered_text, signals,
        media_bytes=file_bytes if media_mime else None,
        media_mime=media_mime,
    )
    from app.services.llm import get_llm

    llm_used = get_llm().last_used or "rule-based"
    registry = registry_service.match_any(db, gathered_text)

    outcome = verification_engine.decide(signals, semantic, registry)
    checked_machine, checked_en, checked_fr = _checked_lists(content_type, gathered_text)

    # If the content claims to be a known organisation, fetch its real channels
    # so the explanation can point the user to the genuine contact.
    known_org = None
    if semantic.claimed_identity and not registry.matched:
        known_org = registry_service.find_org_by_name(db, semantic.claimed_identity)
    elif registry.matched and registry.organization_name:
        known_org = registry_service.find_org_by_name(db, registry.organization_name)

    explanation = explanation_service.build(
        outcome.verdict, semantic, registry, checked_en, checked_fr,
        signals=signals, content_type=content_type.value, known_org=known_org,
    )

    # Persist (redacted preview only; raw media stored only with consent).
    analysis_id = _persist(
        db, content_type, outcome, semantic, explanation, signals, checked_machine,
        gathered_text, consent_store,
    )

    # If the message claimed a known org but did not match a channel, alert it.
    if semantic.identity_claim and not registry.matched and semantic.claimed_identity:
        registry_service.raise_impersonation_alert(
            db, semantic.claimed_identity, analysis_id,
            f"Content claimed identity '{semantic.claimed_identity}' with no matching channel.",
        )

    return AnalysisResult(
        id=analysis_id,
        content_type=content_type,
        verdict=outcome.verdict,
        confidence=outcome.confidence,
        summary=semantic.summary,
        semantic=semantic,
        registry=registry,
        explanation=explanation,
        signals=signals,
        checked=checked_machine,
        llm_used=llm_used,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _persist(
    db, content_type, outcome, semantic, explanation, signals, checked, text, consent
) -> str:
    preview = (text or "")[:180]
    purge_after = None
    if consent and settings.store_media:
        purge_after = datetime.now(timezone.utc) + timedelta(
            days=settings.media_retention_days
        )
    row = Analysis(
        content_type=content_type.value,
        content_preview=preview or None,
        verdict=outcome.verdict.value,
        confidence=outcome.confidence.value,
        result={
            "semantic": semantic.model_dump(),
            "explanation": explanation.model_dump(),
            "signals": [s.model_dump() for s in signals],
            "checked": checked,
            "manipulation_score": outcome.manipulation_score,
            "risk_score": outcome.risk_score,
        },
        purge_after=purge_after,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id
