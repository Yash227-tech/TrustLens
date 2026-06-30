"""Append synthetic rental/lease agreements to the LayoutLMv3 training manifest.

Mirrors how utility_bill was added: rather than regenerating the whole synthetic
set (which would re-roll every other type and risk regressing the tuned
classifier), this generates ONLY rental_agreement PDFs into
/data/synthetic/rental_agreement/ and rewrites /data/synthetic/labels.jsonl =
(all existing non-rental rows) + (fresh rental rows). Idempotent — safe to re-run.

The classifier auto-derives its label set from the manifest, so the next
train_layoutlmv3 run becomes a 25-class model with rental_agreement included.

Run:
    docker exec trustlens-backend sh -c "cd /ml && python -m data_generators.build_rental_synthetic --count 60"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_generators import indian_data as D  # noqa: E402
from data_generators.templates import rental_agreement  # noqa: E402

SYN_ROOT = Path("/data/synthetic")
DOC_TYPE = "rental_agreement"
CATEGORY = "legal"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    D.seed(args.seed)
    out_dir = SYN_ROOT / DOC_TYPE
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = SYN_ROOT / "labels.jsonl"

    # keep every existing row that is NOT rental (so a re-run replaces cleanly)
    kept: list[str] = []
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    if json.loads(line).get("doc_type") == DOC_TYPE:
                        continue
                except json.JSONDecodeError:
                    continue
                kept.append(line)

    new_rows: list[str] = []
    for i in range(args.count):
        try:
            pdf_bytes, fields = rental_agreement()
        except Exception as e:
            print(f"  ! #{i} failed: {e.__class__.__name__}: {e}")
            continue
        fname = f"{i:03d}.pdf"
        (out_dir / fname).write_bytes(pdf_bytes)
        new_rows.append(json.dumps({
            "path": f"synthetic/{DOC_TYPE}/{fname}",
            "doc_type": DOC_TYPE,
            "category": CATEGORY,
            "fields": fields,
            "label": "clean",
        }))

    with manifest_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(kept + new_rows) + "\n")

    print(f"kept {len(kept)} existing rows; added {len(new_rows)} {DOC_TYPE} rows")
    print(f"manifest -> {manifest_path} ({len(kept) + len(new_rows)} total)")


if __name__ == "__main__":
    main()
