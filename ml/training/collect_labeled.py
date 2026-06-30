"""Collect analyst-labelled production documents into a training set (#2 flywheel).

Closes the active-learning loop: bankers attach genuine/fraud ground truth to
analysed documents (POST /api/audit/{id}/label -> analyst_labels), and this
script turns those rows into a REAL-WORLD labelled training manifest by pairing
each label with the persisted upload at /data/uploads/{job_id}.*.

Output:
    /data/labeled/<label>/<doc_type>/<job_id><ext>   (the document bytes)
    /data/labeled/labels.jsonl                       (manifest, /data-relative
                                                       paths — same schema as the
                                                       *_eval.jsonl held-out sets)

The manifest is a drop-in real-data source for:
  * build_feature_dataset.py  (add as a labelled clean/tampered source -> #3 retrain)
  * train_layoutlmv3.py       (real classification data for the analyst-confirmed type)
  * benchmark.py              (a real, in-production evaluation slice)

Append-only labels: a correction is a newer row, so we keep the MOST RECENT
label per job_id. Run inside the backend container:
    docker exec trustlens-backend sh -c "cd /ml && python -m training.collect_labeled"
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models import AnalystLabel  # noqa: E402

# Reuse the worker's sync-engine derivation (asyncpg -> psycopg2).
_async_url = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://trustlens:trustlens_dev@postgres:5432/trustlens"
)
SYNC_DATABASE_URL = _async_url.replace("+asyncpg", "+psycopg2")

DATA = Path("/data")
UPLOAD_DIR = DATA / "uploads"
OUT_DIR = DATA / "labeled"
MANIFEST = OUT_DIR / "labels.jsonl"


def _latest_per_job(rows: list[AnalystLabel]) -> list[AnalystLabel]:
    """Most recent label per job_id (append-only corrections win)."""
    rows = sorted(rows, key=lambda r: r.created_at)  # oldest first
    by_job: dict[str, AnalystLabel] = {}
    for r in rows:
        key = r.job_id or r.id
        by_job[key] = r  # later overwrites earlier
    return list(by_job.values())


def _find_upload(job_id: str | None) -> Path | None:
    if not job_id:
        return None
    hits = sorted(UPLOAD_DIR.glob(f"{job_id}.*")) or sorted(UPLOAD_DIR.glob(f"{job_id}"))
    return hits[0] if hits else None


def main() -> None:
    engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True, future=True)
    with Session(engine) as session:
        rows = session.execute(select(AnalystLabel)).scalars().all()

    if not rows:
        print("No analyst labels yet — nothing to collect. "
              "(Bankers create them via POST /api/audit/{id}/label.)")
        return

    labels = _latest_per_job(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    written, missing = 0, 0
    by_label: Counter = Counter()
    by_type: Counter = Counter()
    manifest_lines: list[str] = []

    for lbl in labels:
        src = _find_upload(lbl.job_id)
        if src is None:
            missing += 1
            print(f"  ! upload missing for job_id={lbl.job_id} ({lbl.filename})")
            continue
        doc_type = lbl.true_doc_type or "unknown"
        dest_dir = OUT_DIR / lbl.label / doc_type
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{lbl.job_id}{src.suffix}"
        shutil.copy2(src, dest)
        manifest_lines.append(json.dumps({
            "path": str(dest.relative_to(DATA)),
            "label": lbl.label,
            "doc_type": doc_type,
            "fraud_vector": lbl.fraud_vector,
            "source": "analyst_feedback",
            "job_id": lbl.job_id,
            "reviewer": lbl.reviewer,
        }))
        written += 1
        by_label[lbl.label] += 1
        by_type[doc_type] += 1

    MANIFEST.write_text("\n".join(manifest_lines) + ("\n" if manifest_lines else ""))
    print(f"\nCollected {written} labelled docs ({missing} missing uploads) -> {OUT_DIR}")
    print(f"  by label: {dict(by_label)}")
    print(f"  by type:  {dict(by_type)}")
    print(f"  manifest: {MANIFEST}")


if __name__ == "__main__":
    main()
