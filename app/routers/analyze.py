"""Analyze endpoints (brief §6).

POST /api/v1/analyze accepts either JSON ({"text": ...}) or multipart (a file,
optional consent). The content router decides the type — the caller never has
to. GET /api/v1/analyze/{id} retrieves a stored result.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import ip_hash, rate_limit_analyze, rate_limit_video
from app.core.errors import NotFoundError, SentinelError
from app.db.session import get_db
from app.models.tables import Analysis, UsageEvent
from app.schemas.analysis import AnalysisResult, ContentType
from app.services import pipeline, router as content_router

router = APIRouter(prefix="/api/v1", tags=["analyze"])

MAX_FILE_MB = 25


def _suffix(filename: str | None) -> str:
    name = filename or ""
    dot = name.rfind(".")
    return name[dot:].lower() if dot != -1 else ""


@router.post("/analyze", response_model=AnalysisResult)
async def analyze(request: Request, db: Session = Depends(get_db)) -> AnalysisResult:
    content_type_header = request.headers.get("content-type", "")

    text: str | None = None
    file_bytes: bytes | None = None
    filename: str | None = None
    consent = False

    if content_type_header.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        text = form.get("text") or None
        consent = str(form.get("consent_store", "")).lower() in ("1", "true", "yes")
        if upload is not None and hasattr(upload, "read"):
            file_bytes = await upload.read()
            filename = upload.filename
            if len(file_bytes) > MAX_FILE_MB * 1024 * 1024:
                raise SentinelError(
                    f"File is larger than {MAX_FILE_MB} MB.", code="content_too_large"
                )
    else:
        body = await request.json()
        text = (body.get("text") or body.get("url") or "").strip() or None
        consent = bool(body.get("consent_store"))

    # Decide the content type.
    if file_bytes is not None:
        kind = content_router.detect_from_file(filename, None)
    elif text:
        kind = content_router.detect_from_text(text)
    else:
        raise SentinelError("Send some text or a file to check.", code="empty_request")

    # Rate limit (video is the expensive path, capped lower).
    if kind == ContentType.video:
        rate_limit_video(request)
    else:
        rate_limit_analyze(request)

    result = pipeline.run(
        db,
        kind,
        text=text,
        file_bytes=file_bytes,
        suffix=_suffix(filename),
        consent_store=consent,
    )

    db.add(UsageEvent(actor=ip_hash(request), kind="analyze", content_type=kind.value))
    db.commit()
    return result


@router.get("/analyze/{analysis_id}", response_model=AnalysisResult)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisResult:
    row = db.get(Analysis, analysis_id)
    if not row:
        raise NotFoundError("No analysis with that id.")
    r = row.result or {}
    return AnalysisResult(
        id=row.id,
        content_type=ContentType(row.content_type),
        verdict=row.verdict,  # type: ignore[arg-type]
        confidence=row.confidence,  # type: ignore[arg-type]
        summary=(r.get("semantic") or {}).get("summary", ""),
        semantic=r.get("semantic") or {},  # type: ignore[arg-type]
        registry={"matched": False},  # type: ignore[arg-type]
        explanation=r.get("explanation") or {},  # type: ignore[arg-type]
        signals=r.get("signals") or [],  # type: ignore[arg-type]
        checked=r.get("checked") or [],
        created_at=row.created_at.isoformat(),
    )
