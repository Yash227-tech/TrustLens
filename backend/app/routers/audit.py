"""Read-only audit-trail endpoint (Step 23, RBI compliance).

Exposes the append-only audit_log. There is intentionally NO create/update/
delete endpoint — rows are written only by the worker after each analysis.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AuditLog, CaseDocument

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEntry(BaseModel):
    id: str
    created_at: datetime
    document_id: str | None
    filename: str
    document_type: str | None
    trust_score: int | None
    risk_tier: str | None
    routing: str | None
    scorer: str | None
    critical_indicators: list[str] = []


class AuditPage(BaseModel):
    total: int
    entries: list[AuditEntry]


class AuditDetail(BaseModel):
    id: str
    created_at: datetime
    document_id: str | None
    job_id: str | None
    filename: str
    document_type: str | None
    trust_score: int | None
    risk_tier: str | None
    routing: str | None
    scorer: str | None
    critical_indicators: list[str] = []
    report: dict | None = None      # full AnalyzeResponse, frozen at decision time
    report_available: bool = False
    decision: dict | None = None     # set for underwriter-decision rows


@router.get("", response_model=AuditPage)
async def list_audit(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> AuditPage:
    total = (await session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    rows = (
        await session.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    entries = [
        AuditEntry(
            id=r.id, created_at=r.created_at, document_id=r.document_id,
            filename=r.filename, document_type=r.document_type,
            trust_score=r.trust_score, risk_tier=r.risk_tier, routing=r.routing,
            scorer=r.scorer,
            # decision rows store a dict here, not a flag list — keep the list view robust.
            critical_indicators=r.critical_indicators if isinstance(r.critical_indicators, list) else [],
        )
        for r in rows
    ]
    return AuditPage(total=total, entries=entries)


@router.get("/{audit_id}", response_model=AuditDetail)
async def get_audit_detail(
    audit_id: str, session: AsyncSession = Depends(get_session)
) -> AuditDetail:
    """Return one audit record WITH its full analysis report, so a banker can
    reopen the exact evidence that produced the decision (read-only)."""
    row = await session.get(AuditLog, audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Audit record not found")

    # Underwriter-decision rows store the decision in critical_indicators (a dict),
    # not a list of flags. Separate the two so each renders cleanly.
    crit = row.critical_indicators
    decision = crit if isinstance(crit, dict) else None
    crit_list = crit if isinstance(crit, list) else []

    report = row.report
    # Fallback for rows written before the report column existed: recover the full
    # report from the matching case document, if this analysis belonged to a case.
    if report is None and row.job_id:
        cd = (
            await session.execute(
                select(CaseDocument).where(CaseDocument.job_id == row.job_id)
            )
        ).scalars().first()
        if cd is not None and cd.result:
            report = cd.result

    return AuditDetail(
        id=row.id, created_at=row.created_at, document_id=row.document_id,
        job_id=row.job_id, filename=row.filename, document_type=row.document_type,
        trust_score=row.trust_score, risk_tier=row.risk_tier, routing=row.routing,
        scorer=row.scorer, critical_indicators=crit_list,
        report=report, report_available=report is not None, decision=decision,
    )
