"""Health + public stats."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import APP_NAME
from app.db.session import get_db
from app.models.tables import Analysis, CommunityReport, Organization
from app.services.llm import get_llm

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "app": APP_NAME, "llm": get_llm().name}


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
