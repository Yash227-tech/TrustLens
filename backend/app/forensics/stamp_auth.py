"""Stamp Authentication (spec §5 #6).

Three checks working together, exactly as the spec describes:
  1. YOLOv8 detects stamps/seals on the document (fine-tuned in Step 15).
  2. SIFT/ORB feature matching compares every detected stamp against the others
     in the same document — a high inlier ratio between two stamps means the
     SAME stamp image was copy-pasted in two places (classic forgery).
  3. Edge-sharpness analysis (Laplacian variance) flags stamps that are blurry
     / low-quality — the hallmark of a printed or photocopied fake.

Returns the standard forensic dict {score, passed, detail, flags, info} plus a
list of detected stamp boxes for optional overlay.
"""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

YOLO_WEIGHTS = Path("/data/models/yolov8-stamps/best.pt")
RENDER_DPI = 150
MAX_DIM = 1280
YOLO_CONF = 0.35

# SIFT reuse detection: two crops with >= this many RANSAC inliers AND a decent
# inlier ratio are treated as the same stamp pasted twice.
REUSE_MIN_INLIERS = 15
REUSE_MIN_RATIO = 0.25

# Edge sharpness: Laplacian variance below this (on a normalised crop) suggests
# a blurry / printed forgery. Calibrated to be bank-safe (flag when in doubt).
SHARPNESS_MIN_VAR = 60.0

PDF_TYPE = "application/pdf"
IMAGE_TYPES = {"image/png", "image/jpeg"}

_model = None
_model_lock = threading.Lock()
_unavailable = False


def _get_model():
    global _model, _unavailable
    if _model is not None:
        return _model
    if _unavailable:
        return None
    with _model_lock:
        if _model is not None:
            return _model
        if not YOLO_WEIGHTS.exists():
            logger.info("YOLOv8 stamp weights not found at %s — stamp check disabled.", YOLO_WEIGHTS)
            _unavailable = True
            return None
        try:
            from ultralytics import YOLO
            _model = YOLO(str(YOLO_WEIGHTS))
            logger.info("YOLOv8 stamp detector loaded.")
            return _model
        except Exception as e:
            logger.warning("YOLOv8 load failed: %s", e)
            _unavailable = True
            return None


def _load_bgr(content: bytes, content_type: str) -> np.ndarray | None:
    if content_type == PDF_TYPE:
        try:
            with fitz.open(stream=content, filetype="pdf") as doc:
                if len(doc) == 0:
                    return None
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72), alpha=False)
                rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    if content_type in IMAGE_TYPES:
        try:
            img = Image.open(io.BytesIO(content)).convert("RGB")
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    return None


def _downscale(img: np.ndarray, max_dim: int) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) <= max_dim:
        return img
    s = max_dim / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def _sift_reuse_score(a_gray: np.ndarray, b_gray: np.ndarray) -> tuple[int, float]:
    """Return (RANSAC inliers, inlier ratio) between two stamp crops."""
    sift = cv2.SIFT_create(nfeatures=400)
    k1, d1 = sift.detectAndCompute(a_gray, None)
    k2, d2 = sift.detectAndCompute(b_gray, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return 0, 0.0
    bf = cv2.BFMatcher(cv2.NORM_L2)
    matches = bf.knnMatch(d1, d2, k=2)
    good = []
    for pair in matches:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:
            good.append(m)
    if len(good) < 8:
        return 0, 0.0
    src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if mask is None:
        return 0, 0.0
    inliers = int(mask.sum())
    ratio = inliers / max(1, min(len(k1), len(k2)))
    return inliers, ratio


def _sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def analyze_stamp_auth(content: bytes, content_type: str) -> dict:
    model = _get_model()
    if model is None:
        return {
            "score": 1.0, "passed": True,
            "detail": "Stamp detector unavailable — check skipped.",
            "flags": [], "info": {"stamps": 0},
        }

    bgr = _load_bgr(content, content_type)
    if bgr is None:
        return {
            "score": 1.0, "passed": True,
            "detail": "Could not render document for stamp check.",
            "flags": [], "info": {"stamps": 0},
        }

    bgr = _downscale(bgr, MAX_DIM)
    try:
        results = model.predict(bgr, conf=YOLO_CONF, verbose=False)
    except Exception as e:
        logger.warning("YOLO predict failed: %s", e)
        return {
            "score": 1.0, "passed": True,
            "detail": f"Stamp detection failed: {e.__class__.__name__}",
            "flags": [], "info": {"stamps": 0},
        }

    boxes = []
    for r in results:
        for b in r.boxes:
            x1, y1, x2, y2 = (int(v) for v in b.xyxy[0].tolist())
            conf = float(b.conf[0].item())
            boxes.append((x1, y1, x2, y2, conf))

    n = len(boxes)
    if n == 0:
        return {
            "score": 1.0, "passed": True,
            "detail": "No stamps detected.",
            "flags": [], "info": {"stamps": 0, "boxes": []},
        }

    gray_full = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    crops = []
    for (x1, y1, x2, y2, _c) in boxes:
        x1, y1 = max(0, x1), max(0, y1)
        crop = gray_full[y1:y2, x1:x2]
        if crop.size > 0:
            crops.append(crop)

    flags: list[str] = []
    score = 1.0

    # Check 2: SIFT reuse between every pair
    reuse_pairs = []
    for i in range(len(crops)):
        for j in range(i + 1, len(crops)):
            inliers, ratio = _sift_reuse_score(crops[i], crops[j])
            if inliers >= REUSE_MIN_INLIERS and ratio >= REUSE_MIN_RATIO:
                reuse_pairs.append((i + 1, j + 1, inliers, ratio))
    if reuse_pairs:
        score -= 0.45
        worst = max(reuse_pairs, key=lambda p: p[2])
        flags.append(f"reused_stamp(#{worst[0]}&#{worst[1]}, {worst[2]} inliers)")

    # Check 3: edge sharpness on each stamp
    blurry = []
    for idx, crop in enumerate(crops, 1):
        if crop.shape[0] >= 20 and crop.shape[1] >= 20:
            var = _sharpness(crop)
            if var < SHARPNESS_MIN_VAR:
                blurry.append((idx, var))
    if blurry:
        score -= min(0.30, 0.15 * len(blurry))
        flags.append(f"low_sharpness({len(blurry)} stamp(s) blurry/printed)")

    score = max(0.0, min(1.0, score))
    passed = score >= 0.7

    if flags:
        detail = f"{n} stamp(s) detected. Flagged: " + "; ".join(flags)
    else:
        detail = f"{n} stamp(s) detected — authentic (no reuse, sharp edges)."

    return {
        "score": score,
        "passed": passed,
        "detail": detail,
        "flags": flags,
        "info": {
            "stamps": n,
            "boxes": [[x1, y1, x2, y2] for (x1, y1, x2, y2, _c) in boxes],
            "reuse_pairs": reuse_pairs,
        },
    }
