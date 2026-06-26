"""Merge a real Roboflow stamp dataset into our YOLO training set (Step 25+).

Roboflow exports (YOLOv8 format) typically look like:
    roboflow_stamps/
      train/images/*.jpg   train/labels/*.txt
      valid/images/*.jpg   valid/labels/*.txt
      test/images/*.jpg    test/labels/*.txt   (sometimes)
      data.yaml

This script copies all real image/label pairs into our dataset at
/data/yolo_stamps (train + val), remapping EVERY class id to 0 ("stamp") so
real stamps/seals merge with our synthetic single-class set. Real files are
prefixed `rf_` to avoid name clashes. After running, retrain with
training.train_yolov8_stamps.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SRC = Path("/data/raw/external/roboflow_stamps")
DST = Path("/data/yolo_stamps")
VAL_EVERY = 6  # send ~1 in 6 real images to val, rest to train

# This Roboflow dataset has 2 classes: 0 = signature, 1 = stamp/seal.
# We only want stamps. Keep ONLY this source class and relabel it to our
# single "stamp" class (id 0). Signatures are handled by the ELA module.
KEEP_SOURCE_CLASS = "1"


def remap_label(text: str) -> str:
    """Keep only KEEP_SOURCE_CLASS boxes; relabel them to our class 0 ('stamp')."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == KEEP_SOURCE_CLASS:
            out.append("0 " + " ".join(parts[1:5]))
    return "\n".join(out) + ("\n" if out else "")


def find_pairs(root: Path) -> list[tuple[Path, Path]]:
    """Find (image, label) pairs across train/valid/test subfolders."""
    pairs = []
    for split in ["train", "valid", "val", "test"]:
        img_dir = root / split / "images"
        lbl_dir = root / split / "labels"
        if not img_dir.exists():
            continue
        for img in img_dir.iterdir():
            if img.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
                continue
            lbl = lbl_dir / (img.stem + ".txt")
            if lbl.exists():
                pairs.append((img, lbl))
    return pairs


def main():
    if not SRC.exists():
        raise SystemExit(f"Not found: {SRC} — download a Roboflow stamp dataset there first.")
    pairs = find_pairs(SRC)
    if not pairs:
        raise SystemExit(f"No image/label pairs found under {SRC} (expected train/images + train/labels).")

    n_train = n_val = n_skipped = 0
    kept = 0
    for img, lbl in pairs:
        label_text = remap_label(lbl.read_text())
        if not label_text.strip():
            n_skipped += 1  # no stamp boxes (signature-only image) — skip
            continue
        split = "val" if kept % VAL_EVERY == 0 else "train"
        stem = f"rf_{kept:05d}"
        (DST / "images" / split).mkdir(parents=True, exist_ok=True)
        (DST / "labels" / split).mkdir(parents=True, exist_ok=True)
        shutil.copy(img, DST / "images" / split / f"{stem}{img.suffix.lower()}")
        (DST / "labels" / split / f"{stem}.txt").write_text(label_text)
        kept += 1
        if split == "val":
            n_val += 1
        else:
            n_train += 1

    print(f"Scanned {len(pairs)} images; {n_skipped} had no stamps (skipped).")
    print(f"Merged {kept} real stamp images: +{n_train} train, +{n_val} val")
    print(f"Now retrain: docker exec trustlens-backend sh -c 'cd /ml && python -m training.train_yolov8_stamps'")


if __name__ == "__main__":
    main()
