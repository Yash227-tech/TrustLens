"""Real Delhi Jal Board water-bill images for the `utility_bill` class.

Mirrors build_bankstmt_classifier_set.py: maps the Roboflow water-bill images
(raw/external/water_bill, train/valid splits) to doc_type=utility_bill so
LayoutLMv3 learns a real utility-bill layout (address proof), not just synthetic.
The Roboflow train/valid split is by source image, so the valid split is a
leak-free held-out eval set.

  TRAIN -> raw/external/water_bill/labels_classify.jsonl  (mixed into training)
  EVAL  -> raw/external/utility_eval.jsonl                (held out, never trained)

Run:
    docker exec trustlens-backend sh -c "cd /ml && python -m data_generators.build_utility_classifier_set"
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path("/data/raw/external/water_bill")
TRAIN_IMG = ROOT / "train" / "images"
EVAL_IMG = ROOT / "valid" / "images"
TRAIN_MANIFEST = ROOT / "labels_classify.jsonl"
EVAL_MANIFEST = Path("/data/raw/external/utility_eval.jsonl")


def _imgs(d: Path) -> list[str]:
    return sorted(g for g in glob.glob(str(d / "*"))
                  if g.lower().endswith((".jpg", ".jpeg", ".png")))


def _row(p: Path, split: str, sub: str = "water") -> dict:
    return {"path": f"raw/external/water_bill/{split}/images/{p.name}",
            "doc_type": "utility_bill", "category": "kyc",
            "label": "clean", "source": "real_water_djb", "sub_type": sub}


def main():
    tr = _imgs(TRAIN_IMG)
    ev = _imgs(EVAL_IMG)
    if not tr:
        raise SystemExit(f"no images under {TRAIN_IMG}")
    with TRAIN_MANIFEST.open("w", encoding="utf-8") as f:
        for p in tr:
            f.write(json.dumps(_row(Path(p), "train")) + "\n")
    with EVAL_MANIFEST.open("w", encoding="utf-8") as f:
        for p in ev:
            f.write(json.dumps(_row(Path(p), "valid")) + "\n")
    print("Real utility-bill (DJB water) classifier set:")
    print(f"  train: {len(tr)} -> {TRAIN_MANIFEST}")
    print(f"  eval : {len(ev)} -> {EVAL_MANIFEST}  (held out, leak-free valid split)")


if __name__ == "__main__":
    main()
