from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RiskTier(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class ForensicSignal(BaseModel):
    name: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    detail: str


class AnalyzeResponse(BaseModel):
    document_id: str
    filename: str
    trust_score: int = Field(ge=0, le=100)
    risk_tier: RiskTier
    routing: Literal["fast_track", "underwriter_review", "fraud_escalation"]
    signals: list[ForensicSignal]
    evidence_summary: str
    heatmap_url: str | None = None
    critical_indicators: list[str] = []  # §7 RED override per spec
    review_indicators: list[str] = []    # non-critical: caps tier at YELLOW review
    extracted_text: str | None = None
    text_extraction_method: str | None = None
    document_type: str | None = None
    document_display_name: str | None = None
    document_category: str | None = None  # "legal" / "financial" / "unknown"
    classification_confidence: float = 0.0
    classification_matches: list[str] = []
    ml_doc_type: str | None = None
    ml_confidence: float = 0.0
    classifier_agreement: bool | None = None
    ml_inconclusive: bool = False
    entities: dict[str, list[str]] = {}
    scorer: str | None = None  # "xgboost" or "weighted"
    shap_contributions: dict[str, float] = {}
    llm_evidence_report: str | None = None
    llm_report_source: str | None = None  # "llm" or "template"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CaseCreate(BaseModel):
    applicant_name: str | None = None
    note: str | None = None


class CaseDocumentSummary(BaseModel):
    id: str
    filename: str
    status: str
    document_type: str | None = None
    trust_score: int | None = None
    risk_tier: str | None = None
    entities: dict[str, list[str]] | None = None


class ConsistencyFinding(BaseModel):
    field: str
    severity: str  # ok / warning / critical
    detail: str


class CrossDocConsistency(BaseModel):
    consistency_score: float
    passed: bool
    critical: bool
    review_required: bool = False
    findings: list[ConsistencyFinding] = []
    note: str | None = None


class CaseResponse(BaseModel):
    id: str
    applicant_name: str | None = None
    note: str | None = None
    documents: list[CaseDocumentSummary] = []
    consistency: CrossDocConsistency | None = None


class CaseSummary(BaseModel):
    """Lightweight row for the case list (GET /api/cases)."""
    id: str
    applicant_name: str | None = None
    created_at: datetime
    document_count: int
    trust_score: int | None = None   # most conservative (min) across the case's docs
    risk_tier: str | None = None     # worst tier across the case's docs (bank-safe)


class JobResponse(BaseModel):
    """Returned by POST /api/analyze; polled via GET /api/jobs/{job_id}."""

    job_id: str
    status: JobStatus
    submitted_at: datetime
    result: AnalyzeResponse | None = None
    error: str | None = None
