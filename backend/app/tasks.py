"""Celery task definitions for TrustLens.

Tasks read the uploaded document from /data/uploads/{job_id}.{ext} (written
by the FastAPI request handler before enqueueing) and call into
app.services.analysis. Result dicts are stored in Redis via the Celery
result backend.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.celery_app import celery_app
from app.services.analysis import run_full_analysis

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("/data/uploads")


@celery_app.task(name="trustlens.analyze_document", bind=True)
def analyze_document_task(
    self, job_id: str, content_type: str, filename: str, upload_path: str
) -> dict:
    """Run the full analysis pipeline on the file at upload_path.

    Returns the AnalyzeResponse dict; Celery stores it in Redis under the
    task ID so the FastAPI /api/jobs/{job_id} endpoint can fetch it.
    """
    p = Path(upload_path)
    if not p.exists():
        raise FileNotFoundError(f"Upload not found at {upload_path}")

    content = p.read_bytes()
    logger.info(
        "Analyzing job_id=%s file=%s size=%d type=%s",
        job_id, filename, len(content), content_type,
    )

    result = run_full_analysis(content, content_type, filename)
    # Tag the result with the original job_id so the frontend can correlate.
    result["job_id"] = job_id

    # Append-only audit record (RBI compliance, spec §3.2/§8).
    from app.audit_sync import write_audit
    write_audit(result)

    # Clean up the upload (heatmap is what we keep — saved separately).
    try:
        p.unlink()
    except OSError:
        pass

    return result
