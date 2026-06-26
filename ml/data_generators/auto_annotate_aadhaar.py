"""Auto-annotate real Aadhaar card photos from SCRATCH (ignore dataset labels).

Builds our own YOLO labels for the 6 regions we actually need for fraud work:

    0 photo          face detector (OpenCV Haar)        -> photo-swap ELA
    1 qr_code        OpenCV QRCodeDetector               -> QR tamper / parse
    2 aadhaar_number OCR word-boxes, 12-digit run        -> localized OCR + Verhoeff
    3 name           OCR line above DOB, alphabetic      -> cross-doc name match
    4 dob            OCR date pattern                     -> age / consistency
    5 gender         OCR male/female/transgender token    -> demographic

Weak-supervision: each detector is independent; we keep whatever we find per
image and KEEP an image only if it has a face AND (number OR qr) — i.e. it really
is a readable Aadhaar. Degraded images that yield nothing are dropped (quality
over quantity; 2.6k images to draw from).

Run a preview first:  python -m data_generators.auto_annotate_aadhaar --limit 40
Full run:             python -m data_generators.auto_annotate_aadhaar
"""

from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytesseract

SRC = Path("/data/raw/external/roboflow_aadhaar/train/images")
DST = Path("/data/yolo_aadhaar")
PREVIEW = Path("/data/raw/external/_aadhaar_annot_preview")
VAL_EVERY = 6
CLASSES = ["photo", "qr_code", "aadhaar_number", "name", "dob", "gender"]
COLORS = [(255, 0, 0), (0, 165, 255), (0, 0, 255), (255, 0, 255), (0, 200, 0), (200, 200, 0)]

GENDER_WORDS = {"male", "female", "transgender", "purush", "mahila"}
_face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_qr = cv2.QRCodeDetector()
DATE_RE = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b")


def _norm_box(x, y, w, h, W, H):
    return [(x + w / 2) / W, (y + h / 2) / H, w / W, h / H]


def detect_photo(gray, W, H):
    faces = _face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                           minSize=(int(W * 0.06), int(H * 0.06)))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])  # largest face
    # pad to capture the photo box, not just the face
    px, py = int(w * 0.25), int(h * 0.35)
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(W, x + w + px), min(H, y + h + py)
    return (x0, y0, x1 - x0, y1 - y0)


QR_EDGE_DENSITY = 0.13  # QR module grid => ~13%+ of pixels are Canny edges


def detect_qr(img, gray, W, H):
    """Locate the Aadhaar secure-QR by texture: the densest square block of edges
    on the card (cv2's decoder can't read the dense secure-QR, but we only need
    the location for tamper-ELA). Integral image => fast densest-square search."""
    edges = (cv2.Canny(gray, 50, 150) > 0).astype(np.float32)
    integ = cv2.integral(edges)  # (H+1, W+1)
    best = None
    best_dens = QR_EDGE_DENSITY
    m = min(W, H)
    for s in (int(m * 0.16), int(m * 0.20), int(m * 0.25), int(m * 0.30)):
        if s < 20 or s >= min(W, H):
            continue
        stride = max(8, s // 4)
        for y in range(0, H - s, stride):
            for x in range(0, W - s, stride):
                tot = (integ[y + s, x + s] - integ[y, x + s]
                       - integ[y + s, x] + integ[y, x])
                dens = tot / (s * s)
                if dens > best_dens:
                    best_dens = dens
                    best = (x, y, s, s)
    if best:
        return best
    try:
        ok, pts = _qr.detect(img)
        if ok and pts is not None:
            p = pts.reshape(-1, 2)
            x0, y0, x1, y1 = p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()
            if (x1 - x0) >= W * 0.04 and (y1 - y0) >= H * 0.04:
                return (int(x0), int(y0), int(x1 - x0), int(y1 - y0))
    except Exception:
        pass
    return None


def _words(img):
    data = pytesseract.image_to_data(img, lang="eng+hin",
                                     output_type=pytesseract.Output.DICT)
    out = []
    for i in range(len(data["text"])):
        t = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1
        if t and conf > 20:
            out.append({"t": t, "x": int(data["left"][i]), "y": int(data["top"][i]),
                        "w": int(data["width"][i]), "h": int(data["height"][i]),
                        "line": (data["block_num"][i], data["par_num"][i], data["line_num"][i])})
    return out


def detect_number(words):
    """12-digit Aadhaar: on each OCR line, concatenate the digits across all
    digit-bearing tokens; a line totalling exactly 12 digits is the number
    (DOB lines total 8, VID lines 16). Prefer the bottom-most such line."""
    by_line: dict = {}
    for w in words:
        if re.search(r"\d", w["t"]):
            by_line.setdefault(w["line"], []).append(w)
    cands = []
    for line, grp in by_line.items():
        grp = sorted(grp, key=lambda w: w["x"])
        digits = "".join(re.sub(r"\D", "", w["t"]) for w in grp)
        if len(digits) == 12:
            x0 = min(w["x"] for w in grp); y0 = min(w["y"] for w in grp)
            x1 = max(w["x"] + w["w"] for w in grp); y1 = max(w["y"] + w["h"] for w in grp)
            cands.append((y0, (x0, y0, x1 - x0, y1 - y0)))
    if cands:
        return max(cands, key=lambda c: c[0])[1]  # bottom-most
    for w in words:  # single 12-digit token fallback
        if len(re.sub(r"\D", "", w["t"])) == 12:
            return (w["x"], w["y"], w["w"], w["h"])
    return None


def _group_lines(words):
    """Group OCR words into text lines: {line_key: {'text','words','box'}}."""
    lines: dict = {}
    for w in words:
        lines.setdefault(w["line"], []).append(w)
    out = []
    for key, grp in lines.items():
        grp = sorted(grp, key=lambda w: w["x"])
        x0 = min(w["x"] for w in grp); y0 = min(w["y"] for w in grp)
        x1 = max(w["x"] + w["w"] for w in grp); y1 = max(w["y"] + w["h"] for w in grp)
        out.append({"text": " ".join(w["t"] for w in grp), "words": grp,
                    "box": (x0, y0, x1 - x0, y1 - y0), "y": y0})
    return sorted(out, key=lambda l: l["y"])


YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
HEADER_KW = ("government", "india", "bharat", "sarkar", "aadhaar", "uidai",
             "मेरा", "आधार", "सरकार", "भारत")


def detect_dob(lines):
    """DOB / Year of Birth line (handles 'DOB: 01/01/1990' and 'Year of Birth: 1995')."""
    for ln in lines:
        low = ln["text"].lower()
        is_dob = (DATE_RE.search(ln["text"]) or "dob" in low
                  or ("year" in low and "birth" in low)
                  or ("birth" in low and YEAR_RE.search(ln["text"]))
                  or ("जन्म" in ln["text"]))
        if is_dob:
            return ln["box"], ln["y"]
    return None, None


def detect_gender(lines):
    for ln in lines:
        for w in ln["words"]:
            if re.sub(r"[^a-z]", "", w["t"].lower()) in GENDER_WORDS:
                return (w["x"], w["y"], w["w"], w["h"])
    return None


RELATION_KW = ("father", "mother", "husband", "wife", "guardian", "care of",
               "c/o", "s/o", "d/o", "w/o", "pita", "father's")


def detect_name(lines, dob_y, W, H):
    """Name = the TOP-most alphabetic line below the header and above the DOB,
    excluding relationship lines (Father/S-o/D-o) and gender."""
    if dob_y is None:
        dob_y = H * 0.45
    cands = []
    for ln in lines:
        if ln["y"] >= dob_y or ln["y"] < H * 0.04:
            continue
        low = ln["text"].lower()
        alpha = re.sub(r"[^A-Za-z]", "", ln["text"])
        if len(alpha) < 3:
            continue
        if any(k in low for k in HEADER_KW) or any(k in low for k in RELATION_KW):
            continue
        if re.sub(r"[^a-z]", "", low) in GENDER_WORDS:
            continue
        cands.append(ln)
    if not cands:
        return None
    return min(cands, key=lambda l: l["y"])["box"]  # top-most = cardholder name


def annotate(path: str):
    img = cv2.imread(path)
    if img is None:
        return None, None
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    words = _words(img)

    lines = _group_lines(words)
    boxes: dict[int, tuple] = {}
    p = detect_photo(gray, W, H)
    if p: boxes[0] = p
    q = detect_qr(img, gray, W, H)
    if q: boxes[1] = q
    num = detect_number(words)
    if num: boxes[2] = num
    dob, dob_y = detect_dob(lines)
    if dob: boxes[4] = dob
    g = detect_gender(lines)
    if g: boxes[5] = g
    nm = detect_name(lines, dob_y, W, H)
    if nm: boxes[3] = nm

    # keep only real, readable Aadhaar cards
    if 0 not in boxes or (2 not in boxes and 1 not in boxes):
        return None, (W, H)
    return boxes, (W, H)


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    imgs = sorted(glob.glob(str(SRC / "*.jpg")))
    if limit:
        import random
        random.Random(7).shuffle(imgs)
        imgs = imgs[:limit]
        PREVIEW.mkdir(parents=True, exist_ok=True)

    kept = 0
    field_counts = {c: 0 for c in CLASSES}
    if not limit:
        for split in ("train", "val"):
            (DST / "images" / split).mkdir(parents=True, exist_ok=True)
            (DST / "labels" / split).mkdir(parents=True, exist_ok=True)

    for idx, ip in enumerate(imgs):
        boxes, dims = annotate(ip)
        if not boxes:
            continue
        W, H = dims
        for cls in boxes:
            field_counts[CLASSES[cls]] += 1
        if limit:  # preview mode — draw boxes, don't write dataset
            im = cv2.imread(ip)
            for cls, (x, y, w, h) in boxes.items():
                cv2.rectangle(im, (x, y), (x + w, y + h), COLORS[cls], 2)
                cv2.putText(im, CLASSES[cls], (x, max(12, y - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLORS[cls], 1)
            cv2.imwrite(str(PREVIEW / f"annot_{kept:02d}.png"), im)
        else:
            split = "val" if kept % VAL_EVERY == 0 else "train"
            stem = f"aadhaar_{kept:05d}"
            cv2.imwrite(str(DST / "images" / split / f"{stem}.jpg"), cv2.imread(ip))
            lines = [f"{cls} " + " ".join(f"{v:.6f}" for v in _norm_box(*box, W, H))
                     for cls, box in sorted(boxes.items())]
            (DST / "labels" / split / f"{stem}.txt").write_text("\n".join(lines) + "\n")
        kept += 1

    if not limit:
        (DST / "data.yaml").write_text(
            f"path: {DST}\ntrain: images/train\nval: images/val\n"
            f"nc: {len(CLASSES)}\nnames: {CLASSES}\n")
    print(f"Scanned {len(imgs)} images; kept {kept} as readable Aadhaar.")
    print("Field detections:", field_counts)
    if limit:
        print(f"Preview boxes -> {PREVIEW}")
    else:
        print(f"YOLO dataset -> {DST}")


if __name__ == "__main__":
    main()
