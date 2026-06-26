"""Build a LayoutLMv3 classification subset of REAL PAN card photos.

Measured: the current classifier reads real PAN cards as `aadhaar` 96% of the
time (both are blue Indian ID cards and we trained heavily on real Aadhaar).
These real PAN images, labelled `pan`, fix that — same approach as Aadhaar.

  TRAIN manifest -> mixed into LayoutLMv3 training (raw/external/pancard/labels_classify.jsonl)
  EVAL  manifest -> held out, never trained on (raw/external/pan_eval.jsonl)
"""

from __future__ import annotations

import glob
import json
import random
from pathlib import Path

IMG_DIR = Path("/data/raw/external/pancard/train/images")
TRAIN_MANIFEST = Path("/data/raw/external/pancard/labels_classify.jsonl")
EVAL_MANIFEST = Path("/data/raw/external/pan_eval.jsonl")
N_TRAIN = 150
N_EVAL = 50
SEED = 42


def _row(p: Path) -> dict:
    return {"path": f"raw/external/pancard/train/images/{p.name}",
            "doc_type": "pan", "category": "legal",
            "label": "clean", "source": "real_pan"}


def main():
    imgs = sorted(glob.glob(str(IMG_DIR / "*")))
    imgs = [i for i in imgs if i.lower().endswith((".jpg", ".jpeg", ".png"))]
    if len(imgs) < N_TRAIN + N_EVAL:
        raise SystemExit(f"Only {len(imgs)} images, need {N_TRAIN + N_EVAL}")
    rng = random.Random(SEED)
    picks = rng.sample(imgs, N_TRAIN + N_EVAL)
    with TRAIN_MANIFEST.open("w", encoding="utf-8") as f:
        for p in picks[:N_TRAIN]:
            f.write(json.dumps(_row(Path(p))) + "\n")
    with EVAL_MANIFEST.open("w", encoding="utf-8") as f:
        for p in picks[N_TRAIN:N_TRAIN + N_EVAL]:
            f.write(json.dumps(_row(Path(p))) + "\n")
    print(f"Real PAN classifier set from {len(imgs)} images:")
    print(f"  train: {N_TRAIN} -> {TRAIN_MANIFEST}")
    print(f"  eval : {N_EVAL} -> {EVAL_MANIFEST}  (held out)")


if __name__ == "__main__":
    main()
