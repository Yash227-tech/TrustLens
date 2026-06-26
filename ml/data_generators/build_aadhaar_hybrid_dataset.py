"""Build the HYBRID 6-field Aadhaar YOLO dataset (user-approved approach).

Combines the two reliable sources, each where it is strong:
  - number / name / DOB / gender  -> the dataset's HAND-DRAWN boxes (accurate even
    on blurry phone photos where OCR fails). Verified correct on samples.
  - photo / QR                    -> our own visual detectors (the fields the
    dataset lacked): OpenCV face detector + densest-edge-square QR localiser.

Our 6 classes:  0 photo  1 qr_code  2 aadhaar_number  3 name  4 dob  5 gender
Their classes:  0 number 1 dob 2 gender 3 name 4 address(rare,drop)

Output: /data/yolo_aadhaar/{images,labels}/{train,val} + data.yaml
"""

from __future__ import annotations

import glob
import shutil
from pathlib import Path

import cv2

from data_generators.auto_annotate_aadhaar import detect_photo, detect_qr, _norm_box

SRC_IMG = Path("/data/raw/external/roboflow_aadhaar/train/images")
SRC_LBL = Path("/data/raw/external/roboflow_aadhaar/train/labels")
DST = Path("/data/yolo_aadhaar")
CLASSES = ["photo", "qr_code", "aadhaar_number", "name", "dob", "gender"]
REMAP = {0: 2, 1: 4, 2: 5, 3: 3}  # their class -> ours; their 4 (address) dropped
VAL_EVERY = 6


def main():
    if DST.exists():
        shutil.rmtree(DST)
    for split in ("train", "val"):
        (DST / "images" / split).mkdir(parents=True, exist_ok=True)
        (DST / "labels" / split).mkdir(parents=True, exist_ok=True)

    imgs = sorted(glob.glob(str(SRC_IMG / "*.jpg")))
    kept = 0
    field_counts = {c: 0 for c in CLASSES}
    for ip in imgs:
        lf = SRC_LBL / (Path(ip).stem + ".txt")
        if not lf.exists():
            continue
        img = cv2.imread(ip)
        if img is None:
            continue
        H, W = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        lines: list[str] = []
        have_number = False
        for ln in lf.read_text().splitlines():
            p = ln.split()
            if len(p) < 5:
                continue
            try:
                c = int(p[0])
            except ValueError:
                continue
            if c not in REMAP:
                continue
            nc = REMAP[c]
            lines.append(f"{nc} {p[1]} {p[2]} {p[3]} {p[4]}")
            field_counts[CLASSES[nc]] += 1
            if nc == 2:
                have_number = True

        photo = detect_photo(gray, W, H)
        if photo is None or not have_number:
            continue  # require a real front Aadhaar: a face AND a number
        lines.append("0 " + " ".join(f"{v:.6f}" for v in _norm_box(*photo, W, H)))
        field_counts["photo"] += 1
        qr = detect_qr(img, gray, W, H)
        if qr is not None:
            lines.append("1 " + " ".join(f"{v:.6f}" for v in _norm_box(*qr, W, H)))
            field_counts["qr_code"] += 1

        split = "val" if kept % VAL_EVERY == 0 else "train"
        stem = f"aadhaar_{kept:05d}"
        cv2.imwrite(str(DST / "images" / split / f"{stem}.jpg"), img)
        (DST / "labels" / split / f"{stem}.txt").write_text("\n".join(lines) + "\n")
        kept += 1

    (DST / "data.yaml").write_text(
        f"path: {DST}\ntrain: images/train\nval: images/val\n"
        f"nc: {len(CLASSES)}\nnames: {CLASSES}\n")
    print(f"Hybrid Aadhaar dataset: kept {kept} / {len(imgs)} images -> {DST}")
    print("Field label counts:", field_counts)


if __name__ == "__main__":
    main()
