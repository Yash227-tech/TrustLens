"""Build a YOLOv8 signature dataset from the Roboflow class-0 (signature) labels.

The Roboflow document dataset has 2 classes: 0 = signature, 1 = stamp/seal.
We already used class 1 for the stamp detector; here we keep ONLY class 0
(signatures), remap to our single 'signature' class (id 0), and write a fresh
Ultralytics dataset at /data/yolo_signatures for a dedicated signature detector.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SRC = Path("/data/raw/external/roboflow_stamps")
DST = Path("/data/yolo_signatures")
KEEP_SOURCE_CLASS = "0"  # signatures
VAL_EVERY = 6


def remap(text: str) -> str:
    out = []
    for line in text.splitlines():
        p = line.split()
        if len(p) >= 5 and p[0] == KEEP_SOURCE_CLASS:
            out.append("0 " + " ".join(p[1:5]))
    return "\n".join(out) + ("\n" if out else "")


def find_pairs(root: Path):
    pairs = []
    for split in ["train", "valid", "val", "test"]:
        img_dir, lbl_dir = root / split / "images", root / split / "labels"
        if not img_dir.exists():
            continue
        for img in img_dir.iterdir():
            if img.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"):
                lbl = lbl_dir / (img.stem + ".txt")
                if lbl.exists():
                    pairs.append((img, lbl))
    return pairs


def main():
    if not SRC.exists():
        raise SystemExit(f"Not found: {SRC}")
    pairs = find_pairs(SRC)
    if DST.exists():
        shutil.rmtree(DST)
    kept = n_train = n_val = skipped = 0
    for img, lbl in pairs:
        txt = remap(lbl.read_text())
        if not txt.strip():
            skipped += 1
            continue
        split = "val" if kept % VAL_EVERY == 0 else "train"
        (DST / "images" / split).mkdir(parents=True, exist_ok=True)
        (DST / "labels" / split).mkdir(parents=True, exist_ok=True)
        stem = f"sig_{kept:05d}"
        shutil.copy(img, DST / "images" / split / f"{stem}{img.suffix.lower()}")
        (DST / "labels" / split / f"{stem}.txt").write_text(txt)
        kept += 1
        n_val += split == "val"
        n_train += split == "train"
    (DST / "data.yaml").write_text(
        "path: /data/yolo_signatures\ntrain: images/train\nval: images/val\n"
        "nc: 1\nnames: ['signature']\n"
    )
    print(f"Scanned {len(pairs)}; {skipped} had no signatures (skipped).")
    print(f"Signature dataset: {n_train} train, {n_val} val -> {DST}")


if __name__ == "__main__":
    main()
