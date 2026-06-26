import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.celery_app import celery_app
from app.schemas import AnalyzeResponse, JobResponse, JobStatus
from app.storage import UPLOAD_BUCKET, put_object
from app.tasks import analyze_document_task

router = APIRouter(prefix="/api", tags=["analyze"])

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
IMAGE_TYPES = {"image/png", "image/jpeg"}
ALLOWED_TYPES = {PDF_TYPE, DOCX_TYPE, *IMAGE_TYPES}

EXT_FOR_TYPE = {
    PDF_TYPE: ".pdf",
    DOCX_TYPE: ".docx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}

UPLOAD_DIR = Path("/data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/analyze", response_model=JobResponse)
async def analyze(file: UploadFile = File(...)) -> JobResponse:
    """Save the upload to /data/uploads and enqueue a Celery task.

    Returns a JobResponse with the job_id; the client polls /api/jobs/{job_id}
    until status == "completed" or "failed".
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. Allowed: PDF, DOCX, PNG, JPEG.",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    job_id = str(uuid.uuid4())
    ext = EXT_FOR_TYPE.get(file.content_type) or mimetypes.guess_extension(file.content_type) or ""
    upload_path = UPLOAD_DIR / f"{job_id}{ext}"
    upload_path.write_bytes(content)
    # Persist to MinIO object storage (spec §8); disk stays as the worker's cache.
    put_object(UPLOAD_BUCKET, f"{job_id}{ext}", content, file.content_type)

    # Enqueue and pin the Celery task ID to our job_id so the client can poll either.
    analyze_document_task.apply_async(
        args=[job_id, file.content_type, file.filename or "unknown", str(upload_path)],
        task_id=job_id,
    )

    return JobResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(timezone.utc),
    )


def _celery_state_to_status(state: str) -> JobStatus:
    """Map Celery's internal state names to our user-facing JobStatus."""
    if state in {"PENDING", "RECEIVED"}:
        return JobStatus.QUEUED
    if state in {"STARTED", "RETRY"}:
        return JobStatus.RUNNING
    if state == "SUCCESS":
        return JobStatus.COMPLETED
    if state in {"FAILURE", "REVOKED"}:
        return JobStatus.FAILED
    return JobStatus.QUEUED


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    """Poll for job state. Returns the full AnalyzeResponse once completed."""
    result = AsyncResult(job_id, app=celery_app)
    status = _celery_state_to_status(result.state)
    submitted_at = datetime.now(timezone.utc)  # exact submit time isn't persisted; use now

    if status == JobStatus.COMPLETED:
        payload = result.result
        if not isinstance(payload, dict):
            return JobResponse(
                job_id=job_id,
                status=JobStatus.FAILED,
                submitted_at=submitted_at,
                error=f"Worker returned an unexpected payload type: {type(payload).__name__}",
            )
        try:
            analyze = AnalyzeResponse.model_validate(payload)
        except Exception as e:  # pragma: no cover — defensive
            return JobResponse(
                job_id=job_id,
                status=JobStatus.FAILED,
                submitted_at=submitted_at,
                error=f"Result schema validation failed: {e.__class__.__name__}: {e}",
            )
        return JobResponse(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            submitted_at=submitted_at,
            result=analyze,
        )

    if status == JobStatus.FAILED:
        err = result.result
        return JobResponse(
            job_id=job_id,
            status=JobStatus.FAILED,
            submitted_at=submitted_at,
            error=str(err) if err else "Unknown failure",
        )

    return JobResponse(job_id=job_id, status=status, submitted_at=submitted_at)
