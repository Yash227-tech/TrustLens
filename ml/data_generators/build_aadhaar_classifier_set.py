"""Build a LayoutLMv3 classification subset of REAL Aadhaar card photos.

The roboflow_aadhaar dataset is a field-DETECTION set (boxes around the Aadhaar
number/name/DOB/gender). For the doc-type CLASSIFIER we ignore the boxes and use
the whole-card images, all labelled `aadhaar`. Measured fact: the synthetic-only
LayoutLMv3 classifies real Aadhaar photos as `aadhaar` 0% of the time, so these
real images are genuinely needed (unlike the financial-statement pages).

Splits a deterministic sample into:
  - TRAIN manifest  -> mixed into LayoutLMv3 training (raw/external/roboflow_aadhaar/labels_classify.jsonl)
  - EVAL  manifest  -> held out, never trained on (raw/external/aadhaar_eval.jsonl)

We keep the count moderate so `aadhaar` doesn't swamp the other 22 classes.
"""

from __future__ import annotations

import glob
import json
import random
from pathlib import Path

IMG_DIR = Path("/data/raw/external/roboflow_aadhaar/train/images")
TRAIN_MANIFEST = Path("/data/raw/external/roboflow_aadhaar/labels_classify.jsonl")
EVAL_MANIFEST = Path("/data/raw/external/aadhaar_eval.jsonl")
N_TRAIN = 150
N_EVAL = 50
SEED = 42


def _row(path: Path) -> dict:
    return {
        "path": f"raw/external/roboflow_aadhaar/train/images/{path.name}",
        "doc_type": "aadhaar", "category": "legal",
        "label": "clean", "source": "real_aadhaar",
    }


def main():
    imgs = sorted(glob.glob(str(IMG_DIR / "*.jpg")))
    if len(imgs) < N_TRAIN + N_EVAL:
        raise SystemExit(f"Only {len(imgs)} images, need {N_TRAIN + N_EVAL}")
    rng = random.Random(SEED)
    picks = rng.sample(imgs, N_TRAIN + N_EVAL)
    train_imgs = picks[:N_TRAIN]
    eval_imgs = picks[N_TRAIN:N_TRAIN + N_EVAL]

    with TRAIN_MANIFEST.open("w", encoding="utf-8") as f:
        for p in train_imgs:
            f.write(json.dumps(_row(Path(p))) + "\n")
    with EVAL_MANIFEST.open("w", encoding="utf-8") as f:
        for p in eval_imgs:
            f.write(json.dumps(_row(Path(p))) + "\n")

    print(f"Real Aadhaar classifier set from {len(imgs)} images:")
    print(f"  train: {len(train_imgs)} -> {TRAIN_MANIFEST}")
    print(f"  eval : {len(eval_imgs)} -> {EVAL_MANIFEST}  (held out)")


if __name__ == "__main__":
    main()
