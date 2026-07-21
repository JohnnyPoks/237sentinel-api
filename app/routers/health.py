"""Health + public stats."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import APP_NAME, settings
from app.db.session import get_db
from app.models.tables import Analysis, CommunityReport, Organization
from app.services.llm import get_llm

router = APIRouter()


@router.get("/health")
def health() -> dict:
    # Booleans only — never leak secret values. Lets us confirm what a host has
    # configured (which env vars are set) without exposing keys.
    chain = get_llm()
    return {
        "status": "ok",
        "app": APP_NAME,
        # The fallback chain and which providers are ready (keys present).
        "llm": chain.status(),
        # Provider that answered the most recent analysis (per-request).
        "llm_last_used": chain.last_used or "rule-based",
        "inference_mode": settings.inference_mode,
        "hf_key_set": bool(settings.hf_api_key),
        "gemini_key_set": bool(settings.gemini_api_key),
        "telegram_set": bool(settings.telegram_bot_token),
    }


@router.get("/api/v1/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    analyses = db.execute(select(func.count(Analysis.id))).scalar() or 0
    orgs = db.execute(
        select(func.count(Organization.id)).where(Organization.is_active.is_(True))
    ).scalar() or 0
    reports = db.execute(select(func.count(CommunityReport.id))).scalar() or 0
    by_verdict = dict(
        db.execute(
            select(Analysis.verdict, func.count(Analysis.id)).group_by(Analysis.verdict)
        ).all()
    )
    return {
        "analyses_total": analyses,
        "organizations_registered": orgs,
        "community_reports": reports,
        "verdicts": by_verdict,
    }
