"""Build a LayoutLMv3 classification subset of REAL passport photos.

The synthetic-only classifier has never seen a real Indian passport, so it
mislabels them. These real images, labelled `passport`, teach the real layout —
same approach as Aadhaar (0->100%) and PAN (0->98%).

  TRAIN manifest -> mixed into LayoutLMv3 training (raw/external/passport/labels_classify.jsonl)
  EVAL  manifest -> held out, never trained on (raw/external/passport_eval.jsonl)

Run after download_passport.py:
    docker exec trustlens-backend sh -c "cd /ml && python -m data_generators.build_passport_classifier_set"
"""

from __future__ import annotations

import glob
import json
import random
from pathlib import Path

IMG_DIR = Path("/data/raw/external/passport/images")
TRAIN_MANIFEST = Path("/data/raw/external/passport/labels_classify.jsonl")
EVAL_MANIFEST = Path("/data/raw/external/passport_eval.jsonl")
N_TRAIN = 150
N_EVAL = 50
SEED = 42


def _row(p: Path) -> dict:
    return {"path": f"raw/external/passport/images/{p.name}",
            "doc_type": "passport", "category": "legal",
            "label": "clean", "source": "real_passport"}


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
    print(f"Real passport classifier set from {len(imgs)} images:")
    print(f"  train: {N_TRAIN} -> {TRAIN_MANIFEST}")
    print(f"  eval : {N_EVAL} -> {EVAL_MANIFEST}  (held out)")


if __name__ == "__main__":
    main()
