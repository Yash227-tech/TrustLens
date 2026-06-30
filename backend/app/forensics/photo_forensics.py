"""Single-document photo-region tamper check (digital photo edit / superimposition).

Face-matching (forensics/face_match) needs TWO ID docs to compare. This catches an
edited / swapped photo on a SINGLE card, by intersecting the ManTraNet forgery
heatmap with the photo region located by the Aadhaar/PAN YOLO detector:

  in-box p95 forgery probability, and its ratio to the rest of the card.

Why this works where ELA fails: a face photo is naturally HIGH-ELA (genuine photos
are 2-4x the card baseline -> ELA-on-photo is 100% false positive). ManTraNet does
NOT do that — on real cards the genuinely-printed photo region stays moderate while
a spliced/edited photo SATURATES it. On the masked tamper set (eval_tamper.py): 51
ID photo-swaps had in-box p95 ~1.0 (ratio 5-46x the card) vs 59 genuine real cards
mostly <0.55 with ratio <2. So a HIGH-AND-LOCALISED in-box response is a real
photo-substitution signal — and it catches small photo edits that the WHOLE-IMAGE
ManTraNet average dilutes/misses (see thresholds below).

Only aadhaar/pan (which have a YOLO `photo` detector, class 0). Bank-safe: flags as
tamper only well above the genuine range, with a wide margin.
"""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

import fitz
import numpy as np
import torch
from PIL import Image

logger = logging.getLogger(__name__)

# doc_type -> YOLO weights that expose a `photo` box at class index 0.
_DETECTOR_WEIGHTS = {
    "aadhaar": Path("/data/models/yolov8-aadhaar/best.pt"),
    "pan": Path("/data/models/yolov8-pan/best.pt"),
}
PHOTO_CLASS = 0
CONF = 0.35
MAX_DIM = 1024  # match the ManTraNet processing size so box/mask coords align

PDF_TYPE = "application/pdf"
IMAGE_TYPES = {"image/png", "image/jpeg"}

# RE-CALIBRATED 2026-06-29 on the masked tamper set (eval_tamper.py): 59 genuine
# real Aadhaar/PAN photos vs 51 ID photo-swaps. The original 0.30 was tuned on
# only 20 Aadhaar; the larger, mixed set showed genuine in-box p95 reaches ~0.64
# on some real cards, so 0.30 false-flagged 7% of genuine IDs (4/59) -> false RED.
# Grid search: inbox>=0.55 AND ratio>=2.0 gives 0/59 genuine FP with 48/51 (94%)
# swap recall — bank-safe ([[feedback_bank_safe_calibration]]): zero false
# rejections, the 2-3 missed swaps are subtle blends still backstopped by
# case-level face-match. Swaps sit far above this (in-box p95 ~1.0, ratio 5-46x).
TAMPER_INBOX_P95 = 0.55
TAMPER_RATIO = 2.0

_detectors: dict[str, object] = {}
_lock = threading.Lock()


def _get_detector(doc_type: str):
    if doc_type not in _DETECTOR_WEIGHTS:
        return None
    if doc_type in _detectors:
        return _detectors[doc_type]
    with _lock:
        if doc_type in _detectors:
            return _detectors[doc_type]
        w = _DETECTOR_WEIGHTS[doc_type]
        if not w.exists():
            _detectors[doc_type] = None
            return None
        try:
            from ultralytics import YOLO
            _detectors[doc_type] = YOLO(str(w))
        except Exception as e:
            logger.warning("Photo-forensics detector (%s) load failed: %s", doc_type, e.__class__.__name__)
            _detectors[doc_type] = None
        return _detectors[doc_type]


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


def _downscale(img: Image.Image) -> Image.Image:
    if max(img.size) <= MAX_DIM:
        return img
    s = MAX_DIM / max(img.size)
    return img.resize((int(img.width * s), int(img.height * s)), Image.Resampling.LANCZOS)


def _mantranet_mask(image: Image.Image) -> np.ndarray | None:
    """Forgery-probability mask (H,W) for the given (already-downscaled) image.
    Reuses the shared ManTraNet singleton — the model is NOT reloaded."""
    try:
        from app.forensics.mantranet.wrapper import _get_model
        model, device = _get_model()
        arr = np.array(image.convert("RGB"))
        t = torch.from_numpy(arr).float().unsqueeze(0).permute(0, 3, 1, 2).contiguous().to(device)
        with torch.no_grad():
            m = model(t)[0, 0].cpu().numpy()
        return np.clip(m, 0.0, 1.0)
    except Exception as e:
        logger.warning("Photo-forensics ManTraNet inference failed: %s", e.__class__.__name__)
        return None


def _photo_box(detector, image: Image.Image):
    try:
        res = detector.predict(np.array(image)[:, :, ::-1], conf=CONF, verbose=False)
    except Exception:
        return None
    best, best_c = None, 0.0
    for r in res:
        for b in r.boxes:
            if int(b.cls) == PHOTO_CLASS and float(b.conf) > best_c:
                best_c = float(b.conf)
                best = tuple(int(v) for v in b.xyxy[0].tolist())
    return best


def _empty(detail: str = "") -> dict:
    return {"checked": False, "verdict": "n/a", "inbox_p95": None,
            "outside_p95": None, "ratio": None, "detail": detail}


def analyze_photo_region(content: bytes, content_type: str, doc_type: str) -> dict:
    """Locate the photo region and score ManTraNet forgery probability inside it.

    verdict: "tampered" (confident photo edit/splice) | "clean" | "n/a"/no-op.
    """
    det = _get_detector(doc_type)
    if det is None:
        return _empty()
    image = _load_pil(content, content_type)
    if image is None:
        return _empty()
    image = _downscale(image)
    box = _photo_box(det, image)
    if box is None:
        return _empty("No photo region located.")
    x1, y1, x2, y2 = box
    if x2 - x1 < 16 or y2 - y1 < 16:
        return _empty("Photo region too small to assess.")
    mask = _mantranet_mask(image)
    if mask is None or mask.shape[:2] != (image.height, image.width):
        return _empty("Forgery mask unavailable.")

    inb = mask[y1:y2, x1:x2]
    outm = mask.copy()
    outm[y1:y2, x1:x2] = np.nan
    inbox_p95 = float(np.percentile(inb, 95))
    out_p95 = float(np.nanpercentile(outm, 95))
    if not np.isfinite(out_p95):
        out_p95 = 0.0
    ratio = inbox_p95 / max(out_p95, 1e-3)

    tampered = inbox_p95 >= TAMPER_INBOX_P95 and ratio >= TAMPER_RATIO
    if tampered:
        detail = (f"Photo region forgery probability p95={inbox_p95:.2f} "
                  f"({ratio:.1f}x the rest of the card) — localized manipulation, "
                  f"likely a substituted/edited photo.")
    else:
        detail = (f"Photo region forgery p95={inbox_p95:.2f} ({ratio:.1f}x card baseline) "
                  f"— within the genuine range.")
    return {"checked": True, "verdict": "tampered" if tampered else "clean",
            "inbox_p95": round(inbox_p95, 3), "outside_p95": round(out_p95, 3),
            "ratio": round(ratio, 2), "detail": detail}
