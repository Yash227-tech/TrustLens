"""Synchronous audit-log writer for the Celery worker (Step 23).

The worker runs in a sync context, so it uses a dedicated psycopg2 engine
(separate from the backend's async asyncpg engine) to insert one immutable
audit row per completed analysis. Insert-only by policy — no updates/deletes.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Derive a sync URL from the async DATABASE_URL (asyncpg -> psycopg2).
_async_url = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://trustlens:trustlens_dev@postgres:5432/trustlens"
)
SYNC_DATABASE_URL = _async_url.replace("+asyncpg", "+psycopg2")

_engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True, future=True)


def write_audit(result: dict) -> None:
    """Insert one append-only audit row. Best-effort: never raises into the task."""
    from app.models import AuditLog

    try:
        with Session(_engine) as session:
            session.add(AuditLog(
                document_id=result.get("document_id"),
                job_id=result.get("job_id"),
                filename=result.get("filename") or "unknown",
                document_type=result.get("document_type"),
                trust_score=result.get("trust_score"),
                risk_tier=result.get("risk_tier"),
                routing=result.get("routing"),
                scorer=result.get("scorer"),
                critical_indicators=result.get("critical_indicators") or [],
                report=result,
            ))
            session.commit()
    except Exception as e:
        logger.warning("Audit write failed (non-fatal): %s", e.__class__.__name__)
