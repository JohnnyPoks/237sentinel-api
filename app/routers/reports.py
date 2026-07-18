"""Community reports (brief §6 / §8).

Anonymous posting, a paginated anonymised feed, and "this happened to me too"
confirmations deduped by hashed IP. Bodies are lightly redacted at write time
so we never store personal identifiers in the community feed.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import ip_hash, rate_limit
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models.tables import CommunityReport, ReportConfirmation

router = APIRouter(prefix="/api/v1", tags=["reports"])

# Redact phone numbers and emails from community bodies.
_PHONE = re.compile(r"(?:\+?237)?[\s-]?[62]\d{2}[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{2}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _redact(text: str) -> str:
    text = _PHONE.sub("[number]", text)
    text = _EMAIL.sub("[email]", text)
    return text.strip()


class ReportIn(BaseModel):
    category: str = Field(max_length=40)
    body: str = Field(min_length=5, max_length=2000)
    region: str | None = None
    linked_analysis_id: str | None = None


@router.post("/reports")
def create_report(payload: ReportIn, request: Request,
                  db: Session = Depends(get_db)) -> dict:
    rate_limit(request, "report", limit=10)
    report = CommunityReport(
        category=payload.category,
        body=_redact(payload.body),
        region=payload.region,
        linked_analysis_id=payload.linked_analysis_id,
        status="pending",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"id": report.id, "status": report.status}


@router.get("/reports")
def list_reports(limit: int = 20, offset: int = 0, region: str | None = None,
                 db: Session = Depends(get_db)) -> dict:
    stmt = select(CommunityReport).where(CommunityReport.status == "approved")
    if region:
        stmt = stmt.where(CommunityReport.region == region)
    rows = db.execute(
        stmt.order_by(CommunityReport.created_at.desc())
        .limit(min(limit, 50)).offset(offset)
    ).scalars().all()
    return {"items": [
        {"id": r.id, "category": r.category, "body": r.body, "region": r.region,
         "confirmations": r.confirmations, "created_at": r.created_at.isoformat()}
        for r in rows
    ]}


@router.post("/reports/{report_id}/confirm")
def confirm_report(report_id: str, request: Request,
                   db: Session = Depends(get_db)) -> dict:
    report = db.get(CommunityReport, report_id)
    if not report:
        raise NotFoundError("No such report.")
    actor = ip_hash(request)
    exists = db.execute(
        select(ReportConfirmation)
        .where(ReportConfirmation.report_id == report_id)
        .where(ReportConfirmation.ip_hash == actor)
    ).scalar_one_or_none()
    if exists:
        return {"confirmations": report.confirmations, "already": True}
    db.add(ReportConfirmation(report_id=report_id, ip_hash=actor))
    report.confirmations += 1
    db.commit()
    return {"confirmations": report.confirmations, "already": False}
