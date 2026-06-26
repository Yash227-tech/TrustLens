"""Build a LayoutLMv3 classification subset of REAL bank-statement page images.

The synthetic-only model misreads real bank statements (it called a genuine IDFC
statement `profit_and_loss`). These real images, labelled `bank_statement`, teach
the real layout — same approach as Aadhaar (0->100%), PAN (0->98%), Passport (0->100%).

Source: a Roboflow bank-statement dataset (train/ + test/ splits, leakage-free).
  TRAIN manifest -> mixed into LayoutLMv3 training (Bankstatments/labels_classify.jsonl)
  EVAL  manifest -> held out, never trained on (raw/external/bankstmt_eval.jsonl)

Run:
    docker exec trustlens-backend sh -c "cd /ml && python -m data_generators.build_bankstmt_classifier_set"
"""

from __future__ import annotations

import glob
import json
import random
from pathlib import Path

ROOT = Path("/data/raw/external/Bankstatments")
TRAIN_IMG = ROOT / "train" / "images"
EVAL_IMG = ROOT / "test" / "images"
TRAIN_MANIFEST = ROOT / "labels_classify.jsonl"
EVAL_MANIFEST = Path("/data/raw/external/bankstmt_eval.jsonl")
N_TRAIN = 180
N_EVAL = 60
SEED = 42


def _row(p: Path, split: str) -> dict:
    return {"path": f"raw/external/Bankstatments/{split}/images/{p.name}",
            "doc_type": "bank_statement", "category": "financial",
            "label": "clean", "source": "real_bankstmt"}


def _imgs(d: Path) -> list[str]:
    return sorted(g for g in glob.glob(str(d / "*"))
                  if g.lower().endswith((".jpg", ".jpeg", ".png")))


def main():
    rng = random.Random(SEED)
    train_imgs = _imgs(TRAIN_IMG)
    eval_imgs = _imgs(EVAL_IMG)
    if len(train_imgs) < N_TRAIN or len(eval_imgs) < N_EVAL:
        raise SystemExit(f"need {N_TRAIN}+{N_EVAL}, have train={len(train_imgs)} test={len(eval_imgs)}")
    train_pick = rng.sample(train_imgs, N_TRAIN)
    eval_pick = rng.sample(eval_imgs, N_EVAL)
    with TRAIN_MANIFEST.open("w", encoding="utf-8") as f:
        for p in train_pick:
            f.write(json.dumps(_row(Path(p), "train")) + "\n")
    with EVAL_MANIFEST.open("w", encoding="utf-8") as f:
        for p in eval_pick:
            f.write(json.dumps(_row(Path(p), "test")) + "\n")
    print(f"Real bank-statement classifier set:")
    print(f"  train: {N_TRAIN} (of {len(train_imgs)}) -> {TRAIN_MANIFEST}")
    print(f"  eval : {N_EVAL} (of {len(eval_imgs)}) -> {EVAL_MANIFEST}  (held out, leak-free test split)")


if __name__ == "__main__":
    main()
