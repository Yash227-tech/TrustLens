"""PAN field extraction via the trained YOLOv8 detector (spec-supporting use:
EXTRACTION ROBUSTNESS, not a new forensic).

Whole-page OCR silently fails on bad PAN phone photos (tilted, low-res), so the
regex finds no PAN number and DigiLocker verification can't run. This module
locates the fields by SIGHT, then OCRs just those clean crops — recovering the
PAN (and name/father/DOB) so verification + the rule checks still work.

Uses only the 5 reliable fields (photo/pan_number/name/father/dob). The QR and
signature classes in the weights are intentionally ignored — not spec-required
and low accuracy (see project_pan_real_data).
"""

from __future__ import annotations

import io
import logging
import re
import threading
from pathlib import Path

import fitz
import numpy as np
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

WEIGHTS = Path("/data/models/yolov8-pan/best.pt")
CONF = 0.35
# index order the detector was trained with
CLASS_NAMES = ["photo", "pan_number", "name", "father", "dob", "qr_code", "signature"]
USE_TEXT = ("pan_number", "name", "father", "dob")  # fields we OCR
PAN_RE = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
MAX_DIM = 1600

PDF_TYPE = "application/pdf"
IMAGE_TYPES = {"image/png", "image/jpeg"}

_model = None
_lock = threading.Lock()
_unavailable = False


def _get_model():
    global _model, _unavailable
    if _model is not None:
        return _model
    if _unavailable:
        return None
    with _lock:
        if _model is not None:
            return _model
        if not WEIGHTS.exists():
            _unavailable = True
            return None
        try:
            from ultralytics import YOLO
            _model = YOLO(str(WEIGHTS))
            logger.info("PAN field detector loaded.")
            return _model
        except Exception as e:
            logger.warning("PAN detector load failed: %s", e)
            _unavailable = True
            return None


def _load_pil(content: bytes, content_type: str) -> Image.Image | None:
    if content_type == PDF_TYPE:
        try:
            with fitz.open(stream=content, filetype="pdf") as d:
                if len(d) == 0:
                    return None
                pix = d[0].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
                return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception:
            return None
    if content_type in IMAGE_TYPES:
        try:
            return Image.open(io.BytesIO(content)).convert("RGB")
        except Exception:
            return None
    return None


def _detect(model, image: Image.Image) -> dict[str, tuple]:
    res = model.predict(np.array(image)[:, :, ::-1], conf=CONF, verbose=False)
    best: dict[str, tuple] = {}
    best_c: dict[str, float] = {}
    for r in res:
        for b in r.boxes:
            cls = CLASS_NAMES[int(b.cls)]
            c = float(b.conf)
            if c > best_c.get(cls, 0):
                best_c[cls] = c
                best[cls] = tuple(int(v) for v in b.xyxy[0].tolist())
    return best


# PAN positional fix-up: positions 1-5 + 10 are letters, 6-9 are digits.
# Map the common Tesseract confusions in the wrong direction back.
_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
             "A": "4", "S": "5", "G": "6", "B": "8", "T": "7"}


def _fix_pan(s: str) -> str | None:
    s = re.sub(r"[^A-Z0-9]", "", s.upper())
    if len(s) != 10:
        return None
    out = []
    for i, c in enumerate(s):
        if i < 5 or i == 9:  # letter positions
            out.append(_TO_LETTER.get(c, c) if c.isdigit() else c)
        else:                # digit positions 6-9
            out.append(_TO_DIGIT.get(c, c) if c.isalpha() else c)
    r = "".join(out)
    return r if PAN_RE.fullmatch(r) else None


def _ocr(image: Image.Image, box: tuple, pan: bool = False) -> str:
    x1, y1, x2, y2 = box
    if x2 - x1 < 8 or y2 - y1 < 6:
        return ""
    crop = image.crop((x1, y1, x2, y2))
    if max(crop.size) < 600:  # upscale small crops — Tesseract reads big text far better
        f = max(2, round(600 / max(crop.size)))
        crop = crop.resize((crop.width * f, crop.height * f), Image.Resampling.LANCZOS)
    cfg = "--psm 7"
    if pan:
        cfg += " -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    try:
        return pytesseract.image_to_string(crop, config=cfg).strip()
    except Exception:
        return ""


def _empty() -> dict:
    return {"detected": [], "pan_number": None, "name": None,
            "father": None, "dob": None, "photo_present": False}


def extract_pan_fields(content: bytes, content_type: str) -> dict:
    """Locate + OCR the PAN fields. Returns recovered field values (best-effort)."""
    model = _get_model()
    if model is None:
        return _empty()
    image = _load_pil(content, content_type)
    if image is None:
        return _empty()
    if max(image.size) > MAX_DIM:
        s = MAX_DIM / max(image.size)
        image = image.resize((int(image.width * s), int(image.height * s)), Image.Resampling.LANCZOS)

    boxes = _detect(model, image)
    if "pan_number" not in boxes and "photo" not in boxes:
        return _empty()

    out = _empty()
    out["detected"] = sorted(k for k in boxes if k in ("photo", *USE_TEXT))
    out["photo_present"] = "photo" in boxes
    if "pan_number" in boxes:
        raw = re.sub(r"[^A-Z0-9]", "", _ocr(image, boxes["pan_number"], pan=True).upper())
        m = PAN_RE.search(raw)
        out["pan_number"] = m.group(0) if m else _fix_pan(raw)  # positional fix-up fallback
    for f in ("name", "father", "dob"):
        if f in boxes:
            txt = _ocr(image, boxes[f])
            if txt:
                out[f] = re.sub(r"^[:/\-\s]+", "", txt)
    return out
