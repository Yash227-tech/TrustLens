"""Build the HYBRID 5-field PAN YOLO dataset (same approach as Aadhaar).

Sources merged from multiple Roboflow PAN datasets under raw/external/pancard.
The bulk train/valid/test set uses the panocr 4-class scheme; we keep those
verified hand-drawn boxes for the text fields and ADD the photo by sight (no
source annotates it), exactly like the Aadhaar hybrid build.

Our 5 classes:  0 photo  1 pan_number  2 name  3 father  4 dob
panocr classes: 0 dob  1 father  2 name  3 pan   (4 = stray, dropped)

Output: /data/yolo_pan/{images,labels}/{train,val} + data.yaml
"""

from __future__ import annotations

import glob
import shutil
from pathlib import Path

import cv2

from data_generators.auto_annotate_aadhaar import detect_photo, detect_qr, _norm_box

SRC = Path("/data/raw/external/pancard")
SPLITS = ("train", "valid", "test")
DST = Path("/data/yolo_pan")
# QR auto-detection verified on real PANs: 88% recall, ignores the hologram.
# Signature is BOOTSTRAPPED (user-approved): auto-label with the existing
# signature detector at a precision-favouring threshold (clean labels matter
# more than coverage for self-training), then the in-domain PAN model should
# generalise to the unlabelled ones. Weakest class — measured after training.
CLASSES = ["photo", "pan_number", "name", "father", "dob", "qr_code", "signature"]
REMAP = {0: 4, 1: 3, 2: 2, 3: 1}  # panocr -> ours; panocr 4 (stray) dropped
SIG_WEIGHTS = "/data/models/yolov8-signatures/best.pt"
SIG_CONF = 0.20  # precision over recall for clean bootstrap labels
VAL_EVERY = 6

_sig_model = None


def _sig_box(img):
    """Best-confidence ink-signature box from the existing detector, or None.
    (Trained on ink signatures, so it ignores e-PAN 'digitally signed' text.)"""
    global _sig_model
    if _sig_model is None:
        from ultralytics import YOLO
        _sig_model = YOLO(SIG_WEIGHTS)
    res = _sig_model.predict(img, conf=SIG_CONF, verbose=False)
    best, best_c = None, 0.0
    for r in res:
        for b in r.boxes:
            c = float(b.conf)
            if c > best_c:
                best_c = c
                x1, y1, x2, y2 = (int(v) for v in b.xyxy[0].tolist())
                best = (x1, y1, x2 - x1, y2 - y1)
    return best


def main():
    if DST.exists():
        shutil.rmtree(DST)
    for split in ("train", "val"):
        (DST / "images" / split).mkdir(parents=True, exist_ok=True)
        (DST / "labels" / split).mkdir(parents=True, exist_ok=True)

    pairs = []
    for sp in SPLITS:
        for ip in glob.glob(str(SRC / sp / "images" / "*")):
            if not ip.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            lf = SRC / sp / "labels" / (Path(ip).stem + ".txt")
            if lf.exists():
                pairs.append((ip, lf))

    kept = 0
    field_counts = {c: 0 for c in CLASSES}
    for ip, lf in pairs:
        img = cv2.imread(ip)
        if img is None:
            continue
        H, W = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        lines, have_pan = [], False
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
            if nc == 1:  # pan_number
                have_pan = True

        photo = detect_photo(gray, W, H)
        if photo is None or not have_pan:
            continue  # require a face AND a PAN code to be a usable PAN front
        lines.append("0 " + " ".join(f"{v:.6f}" for v in _norm_box(*photo, W, H)))
        field_counts["photo"] += 1
        qr = detect_qr(img, gray, W, H)
        if qr is not None:
            lines.append("5 " + " ".join(f"{v:.6f}" for v in _norm_box(*qr, W, H)))
            field_counts["qr_code"] += 1
        sig = _sig_box(img)
        if sig is not None:
            lines.append("6 " + " ".join(f"{v:.6f}" for v in _norm_box(*sig, W, H)))
            field_counts["signature"] += 1

        split = "val" if kept % VAL_EVERY == 0 else "train"
        stem = f"pan_{kept:05d}"
        cv2.imwrite(str(DST / "images" / split / f"{stem}.jpg"), img)
        (DST / "labels" / split / f"{stem}.txt").write_text("\n".join(lines) + "\n")
        kept += 1

    (DST / "data.yaml").write_text(
        f"path: {DST}\ntrain: images/train\nval: images/val\n"
        f"nc: {len(CLASSES)}\nnames: {CLASSES}\n")
    print(f"Hybrid PAN dataset: kept {kept} / {len(pairs)} images -> {DST}")
    print("Field label counts:", field_counts)


if __name__ == "__main__":
    main()
