"""Admin / moderation (brief §8).

Gated by a single admin token (X-Admin-Token) compared against ADMIN_TOKEN.
If ADMIN_TOKEN is unset, all admin endpoints return 401 — the panel is disabled
by default rather than open. A real deployment should put a proper identity
provider in front; noted in DECISIONS.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import AuthError, NotFoundError
from app.db.session import get_db
from app.models.tables import (
    Analysis,
    CommunityReport,
    OrgAlert,
    Organization,
    ScamPattern,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise AuthError("Admin access denied.")


@router.get("/stats", dependencies=[Depends(require_admin)])
def admin_stats(db: Session = Depends(get_db)) -> dict:
    return {
        "analyses": db.execute(select(func.count(Analysis.id))).scalar() or 0,
        "organizations": db.execute(select(func.count(Organization.id))).scalar() or 0,
        "pending_orgs": db.execute(
            select(func.count(Organization.id)).where(Organization.verified_by == "pending")
        ).scalar() or 0,
        "pending_reports": db.execute(
            select(func.count(CommunityReport.id)).where(CommunityReport.status == "pending")
        ).scalar() or 0,
        "scam_patterns": db.execute(select(func.count(ScamPattern.id))).scalar() or 0,
        "open_alerts": db.execute(
            select(func.count(OrgAlert.id)).where(OrgAlert.status == "new")
        ).scalar() or 0,
    }


@router.get("/reports", dependencies=[Depends(require_admin)])
def pending_reports(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(CommunityReport).where(CommunityReport.status == "pending")
        .order_by(CommunityReport.created_at.desc()).limit(200)
    ).scalars().all()
    return {"items": [
        {"id": r.id, "category": r.category, "body": r.body, "region": r.region,
         "created_at": r.created_at.isoformat()}
        for r in rows
    ]}


@router.post("/reports/{report_id}/moderate", dependencies=[Depends(require_admin)])
def moderate_report(report_id: str, action: str, db: Session = Depends(get_db)) -> dict:
    report = db.get(CommunityReport, report_id)
    if not report:
        raise NotFoundError("No such report.")
    report.status = "approved" if action == "approve" else "rejected"
    db.commit()
    return {"id": report.id, "status": report.status}


@router.post("/organizations/{org_id}/approve", dependencies=[Depends(require_admin)])
def approve_org(org_id: str, db: Session = Depends(get_db)) -> dict:
    org = db.get(Organization, org_id)
    if not org:
        raise NotFoundError("No such organisation.")
    org.verified_by = "admin"
    org.is_active = True
    db.commit()
    return {"id": org.id, "verified_by": org.verified_by}


@router.get("/organizations/pending", dependencies=[Depends(require_admin)])
def pending_orgs(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Organization).where(Organization.verified_by == "pending")
    ).scalars().all()
    return {"items": [
        {"id": o.id, "name": o.name, "kind": o.kind, "region": o.region,
         "created_at": o.created_at.isoformat()}
        for o in rows
    ]}
