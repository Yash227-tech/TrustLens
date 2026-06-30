"""Utility-bill field extraction via the trained YOLOv8 detector (extraction
robustness for address proof — NOT a new forensic).

A utility bill (electricity / water / gas) is the most common address proof and a
prime mule-account vector. This module locates the consumer NAME, ADDRESS,
connection/consumer number and bill date by SIGHT, then OCRs just those crops — so
the NAME feeds the cross-document identity-consistency check and the ADDRESS is
recovered as address-proof, even when whole-page OCR is noisy. Tamper detection
stays with ManTraNet/ELA (already in the pipeline).

Detector: /data/models/yolov8-utility/best.pt (trained on real Delhi Jal Board
water bills; see project_new_doc_types_plan). Mirrors pan_fields.py / aadhaar_fields.py.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
from pathlib import Path

import fitz
import numpy as np
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

WEIGHTS = Path("/data/models/yolov8-utility/best.pt")
CONF = 0.35
# index order the detector was trained with (water_bill/data_train.yaml)
CLASS_NAMES = ["Date", "KNO", "Name", "address"]
MAX_DIM = 1600
# Utility bills are routinely bilingual (Hindi/Gujarati + English); match the
# whole-page OCR languages so consumer name/address crops read on regional bills.
OCR_LANGS = os.environ.get("OCR_LANGUAGES", "eng+hin+guj")

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
            logger.info("Utility-bill field detector loaded.")
            return _model
        except Exception as e:
            logger.warning("Utility detector load failed: %s", e)
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


def _ocr(image: Image.Image, box: tuple, multiline: bool = False) -> str:
    x1, y1, x2, y2 = box
    if x2 - x1 < 8 or y2 - y1 < 6:
        return ""
    crop = image.crop((x1, y1, x2, y2))
    if max(crop.size) < 600:  # upscale small crops — Tesseract reads big text far better
        f = max(2, round(600 / max(crop.size)))
        crop = crop.resize((crop.width * f, crop.height * f), Image.Resampling.LANCZOS)
    cfg = "--psm 6" if multiline else "--psm 7"
    try:
        return pytesseract.image_to_string(crop, lang=OCR_LANGS, config=cfg).strip()
    except Exception:
        return ""


def _clean(s: str) -> str:
    # Drop a leading "Label:" prefix (e.g. "Name(नाम):"), collapse whitespace.
    if ":" in s[:30]:
        s = s.split(":", 1)[1]
    return re.sub(r"\s+", " ", s).strip(" :,-")


def _clean_addr(s: str) -> str:
    out = []
    for ln in s.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ":" in ln[:30]:
            ln = ln.split(":", 1)[1]
        ln = re.sub(r"\s+", " ", ln).strip(" :,-")
        if ln:
            out.append(ln)
    return ", ".join(out).strip(" :,-")


def _empty() -> dict:
    return {"detected": [], "name": None, "address": None,
            "consumer_no": None, "date": None}


def extract_utility_fields(content: bytes, content_type: str) -> dict:
    """Locate + OCR the utility-bill fields. Returns recovered values (best-effort)."""
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
    if not boxes:
        return _empty()

    out = _empty()
    out["detected"] = sorted(boxes.keys())
    if "Name" in boxes:
        t = _ocr(image, boxes["Name"]) or _ocr(image, boxes["Name"], multiline=True)
        out["name"] = _clean(t) or None
    if "address" in boxes:
        out["address"] = _clean_addr(_ocr(image, boxes["address"], multiline=True)) or None
    if "KNO" in boxes:
        raw = _ocr(image, boxes["KNO"])
        digits = re.sub(r"\D", "", raw)
        out["consumer_no"] = digits or (_clean(raw) or None)
    if "Date" in boxes:
        out["date"] = _clean(_ocr(image, boxes["Date"])) or None
    return out
