"""Case endpoints (Step 17a) — group documents and cross-check them.

Flow:
  POST /api/cases                      -> create a case
  POST /api/cases/{id}/documents       -> add a doc (enqueues analysis)
  GET  /api/cases/{id}                 -> case + per-doc status + cross-doc report

The Celery worker performs analysis (incl. entity extraction); this router
persists each completed result into Postgres on poll and recomputes the
cross-document consistency report over all completed docs.
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_role
from app.celery_app import celery_app
from app.db import get_session
from app.models import AuditLog, Case, CaseDocument
from app.schemas import (
    CaseDocumentSummary,
    CaseResponse,
    CaseSummary,
    CrossDocConsistency,
)
from app.services.cross_doc import analyze_case_consistency
from app.tasks import analyze_document_task

router = APIRouter(prefix="/api/cases", tags=["cases"])

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED_TYPES = {PDF_TYPE, DOCX_TYPE, "image/png", "image/jpeg"}
EXT_FOR_TYPE = {PDF_TYPE: ".pdf", DOCX_TYPE: ".docx", "image/png": ".png", "image/jpeg": ".jpg"}
UPLOAD_DIR = Path("/data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("", response_model=CaseResponse)
async def create_case(
    applicant_name: str | None = Form(None),
    note: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> CaseResponse:
    case = Case(applicant_name=applicant_name, note=note)
    session.add(case)
    await session.commit()
    await session.refresh(case)
    return CaseResponse(id=case.id, applicant_name=case.applicant_name, note=case.note)


_TIER_RANK = {"RED": 3, "YELLOW": 2, "GREEN": 1}


@router.get("", response_model=list[CaseSummary])
async def list_cases(session: AsyncSession = Depends(get_session)) -> list[CaseSummary]:
    """All cases, newest first — backs the Cases list / dashboard Recent Cases."""
    cases = (
        await session.execute(select(Case).order_by(Case.created_at.desc()))
    ).scalars().all()

    out: list[CaseSummary] = []
    for c in cases:
        docs = c.documents  # eager (lazy="selectin")
        scores = [d.trust_score for d in docs if d.trust_score is not None]
        tiers = [d.risk_tier for d in docs if d.risk_tier]
        worst = max(tiers, key=lambda t: _TIER_RANK.get(t, 0)) if tiers else None
        out.append(CaseSummary(
            id=c.id, applicant_name=c.applicant_name, created_at=c.created_at,
            document_count=len(docs),
            trust_score=min(scores) if scores else None,  # most conservative
            risk_tier=worst,
        ))
    return out


@router.post("/{case_id}/documents", response_model=CaseDocumentSummary)
async def add_document(
    case_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> CaseDocumentSummary:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    job_id = str(uuid.uuid4())
    ext = EXT_FOR_TYPE.get(file.content_type, mimetypes.guess_extension(file.content_type) or "")
    upload_path = UPLOAD_DIR / f"{job_id}{ext}"
    upload_path.write_bytes(content)

    analyze_document_task.apply_async(
        args=[job_id, file.content_type, file.filename or "unknown", str(upload_path)],
        task_id=job_id,
    )

    doc = CaseDocument(
        case_id=case_id, job_id=job_id, filename=file.filename or "unknown", status="queued"
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return CaseDocumentSummary(id=doc.id, filename=doc.filename, status=doc.status)


def _celery_status(state: str) -> str:
    if state in {"PENDING", "RECEIVED"}:
        return "queued"
    if state in {"STARTED", "RETRY"}:
        return "running"
    if state == "SUCCESS":
        return "completed"
    if state in {"FAILURE", "REVOKED"}:
        return "failed"
    return "queued"


async def _sync_document(doc: CaseDocument, session: AsyncSession) -> None:
    """If a doc is still pending, poll Celery and persist the result when ready."""
    if doc.status in {"completed", "failed"} or not doc.job_id:
        return
    res = AsyncResult(doc.job_id, app=celery_app)
    status = _celery_status(res.state)
    if status == "completed":
        payload = res.result
        if isinstance(payload, dict):
            doc.status = "completed"
            doc.document_type = payload.get("document_type")
            doc.trust_score = payload.get("trust_score")
            doc.risk_tier = payload.get("risk_tier")
            doc.entities = payload.get("entities") or {}
            doc.result = payload
        else:
            doc.status = "failed"
    elif status == "failed":
        doc.status = "failed"
    else:
        doc.status = status
    await session.commit()


@router.get("/{case_id}", response_model=CaseResponse)
async def get_case(case_id: str, session: AsyncSession = Depends(get_session)) -> CaseResponse:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    result = await session.execute(
        select(CaseDocument).where(CaseDocument.case_id == case_id).order_by(CaseDocument.created_at)
    )
    docs = list(result.scalars().all())

    for doc in docs:
        await _sync_document(doc, session)

    summaries = [
        CaseDocumentSummary(
            id=d.id, filename=d.filename, status=d.status,
            document_type=d.document_type, trust_score=d.trust_score,
            risk_tier=d.risk_tier, entities=d.entities,
        )
        for d in docs
    ]

    completed = [
        {"filename": d.filename, "document_type": d.document_type, "entities": d.entities or {}}
        for d in docs if d.status == "completed"
    ]
    consistency = None
    if len(completed) >= 2:
        consistency = CrossDocConsistency(**analyze_case_consistency(completed))

    return CaseResponse(
        id=case.id, applicant_name=case.applicant_name, note=case.note,
        documents=summaries, consistency=consistency,
    )


class DecisionRequest(BaseModel):
    decision: str          # "approved" | "rejected" | "escalated" | "reviewed"
    tier: str | None = None
    notes: str | None = None


@router.post("/{case_id}/decision")
async def record_decision(
    case_id: str,
    body: DecisionRequest,
    session: AsyncSession = Depends(get_session),
    user: dict = Depends(require_role("underwriter", "admin")),
):
    """Record the underwriter's final call — the SENSITIVE action, RBAC-protected
    (spec §8). Appended to the immutable audit log for RBI compliance; only an
    'underwriter' or 'admin' (valid JWT) may write it."""
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    session.add(AuditLog(
        filename=f"case:{case_id} ({case.applicant_name or 'n/a'})",
        document_type="underwriter_decision",
        risk_tier=body.tier,
        routing=body.decision,
        critical_indicators={"actor": user["username"], "role": user["role"],
                             "decision": body.decision, "notes": body.notes},
    ))
    await session.commit()
    return {"recorded": True, "case_id": case_id, "decision": body.decision,
            "by": user["username"], "role": user["role"]}
