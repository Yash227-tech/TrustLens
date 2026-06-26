"""Synthetic Indian document generator (spec §4, Step 14a).

Generates N clean PDFs per document type into:
    /data/synthetic/<doc_type>/<NNN>.pdf
and writes a sidecar label file:
    /data/synthetic/labels.jsonl   (one JSON object per generated doc)

Run inside the backend container:
    docker exec trustlens-backend python -m ml.generate_all --per-type 50

The labels.jsonl is the training manifest for LayoutLMv3 fine-tuning (Step 14b)
and the document pool for the XGBoost tamper dataset (Step 19).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `python -m ml.generate_all` with /ml mounted.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_generators import indian_data as D  # noqa: E402
from data_generators.templates import TEMPLATES  # noqa: E402

OUT_ROOT = Path("/data/synthetic")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=50, help="docs per doc type")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--only", type=str, default="", help="comma-separated doc_types to limit to")
    args = ap.parse_args()

    D.seed(args.seed)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_ROOT / "labels.jsonl"

    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    total = 0

    with manifest_path.open("w", encoding="utf-8") as manifest:
        for doc_type, (fn, category) in TEMPLATES.items():
            if only and doc_type not in only:
                continue
            out_dir = OUT_ROOT / doc_type
            out_dir.mkdir(parents=True, exist_ok=True)
            for i in range(args.per_type):
                try:
                    pdf_bytes, fields = fn()
                except Exception as e:
                    print(f"  ! {doc_type} #{i} failed: {e.__class__.__name__}: {e}")
                    continue
                fname = f"{i:03d}.pdf"
                (out_dir / fname).write_bytes(pdf_bytes)
                manifest.write(json.dumps({
                    "path": f"synthetic/{doc_type}/{fname}",
                    "doc_type": doc_type,
                    "category": category,
                    "fields": fields,
                    "label": "clean",
                }) + "\n")
                total += 1
            print(f"  {doc_type:22s} [{category:9s}] -> {args.per_type} docs")

    print(f"\nDone. {total} documents across {len(only) if only else len(TEMPLATES)} types.")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
