"""SQLAlchemy models for cases and their documents (Step 17a)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    applicant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    documents: Mapped[list["CaseDocument"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )


class CaseDocument(Base):
    __tablename__ = "case_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filename: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued/running/completed/failed
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trust_score: Mapped[int | None] = mapped_column(nullable=True)
    risk_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    entities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped["Case"] = relationship(back_populates="documents")


class AuditLog(Base):
    """Append-only record of every analysis decision (spec §3.2/§8, RBI compliance).

    Insert-only by policy — the application never updates or deletes these rows.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filename: Mapped[str] = mapped_column(String(512))
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trust_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    routing: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scorer: Mapped[str | None] = mapped_column(String(16), nullable=True)
    critical_indicators: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Full analysis report, frozen at decision time so the banker can reopen the
    # exact evidence later (signals, SHAP, entities, evidence report, heatmap URL).
    # Append-only like the rest of the row — never updated.
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AnalystLabel(Base):
    """Ground-truth verdict an analyst attaches to an analysed document — the
    active-learning flywheel (improvement #2).

    Distinct from the workflow decision (approved/rejected in cases.record_decision):
    this is the ML ground truth — "is this document genuine or a forgery" — used to
    grow a REAL-WORLD training set from production traffic. ml/training/
    collect_labeled.py joins these rows to the persisted upload
    (/data/uploads/{job_id}.*) and emits a labelled training manifest.

    Append-only by policy (like AuditLog) — corrections are new rows; the
    collection script takes the most recent label per job_id.
    """

    __tablename__ = "analyst_labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    audit_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filename: Mapped[str] = mapped_column(String(512))
    # analyst-confirmed TRUE document type (may differ from the model's prediction)
    true_doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(16))           # "genuine" | "fraud"
    fraud_vector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
