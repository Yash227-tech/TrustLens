"""ELA-based signature region analysis (spec §10 substitute for SigNet).

The original spec §5 called for SigNet (Siamese CNN signature verification
against a KYC reference). Spec §10 places SigNet out-of-scope for the MVP and
substitutes "ELA-based signature region analysis": find the signature regions
on a document via OCR labels, run targeted ELA on each, and flag any region
whose noise exceeds the document baseline by a large factor — that's the
hallmark of a pasted-in or photocopied signature.

Detection pipeline:
  1. Render the document to an image (for PDFs, first page).
  2. Compute a baseline ELA noise level for the whole page.
  3. OCR via Tesseract with word-level bounding boxes.
  4. Locate signature labels ("Signature", "Authorised Signatory", etc.).
  5. Define an inferred signature region above each label (where signatures
     are conventionally written).
  6. Run ELA on each region.
  7. Flag any region whose noise > THRESHOLD × baseline AND > absolute floor.

This is intentionally heuristic (the spec acknowledged it's an MVP substitute);
post-Step-14b we may add layout-aware detection.
"""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

import fitz
import numpy as np
import pytesseract
from PIL import Image, ImageChops

logger = logging.getLogger(__name__)

# Trained YOLOv8 signature detector (real Roboflow signature labels). When
# present, signatures are located VISUALLY anywhere on the page; the label-based
# OCR heuristic below is the fallback if the model is unavailable.
SIG_YOLO_WEIGHTS = Path("/data/models/yolov8-signatures/best.pt")
SIG_YOLO_CONF = 0.35
_sig_model = None
_sig_lock = threading.Lock()
_sig_unavailable = False


def _get_sig_model():
    global _sig_model, _sig_unavailable
    if _sig_model is not None:
        return _sig_model
    if _sig_unavailable:
        return None
    with _sig_lock:
        if _sig_model is not None:
            return _sig_model
        if not SIG_YOLO_WEIGHTS.exists():
            _sig_unavailable = True
            return None
        try:
            from ultralytics import YOLO
            _sig_model = YOLO(str(SIG_YOLO_WEIGHTS))
            logger.info("YOLOv8 signature detector loaded.")
            return _sig_model
        except Exception as e:
            logger.warning("Signature YOLO load failed: %s", e)
            _sig_unavailable = True
            return None


def _yolo_regions(image: Image.Image) -> list[dict]:
    """Detect signature boxes visually with the trained YOLO model."""
    model = _get_sig_model()
    if model is None:
        return []
    try:
        import numpy as _np
        res = model.predict(_np.array(image)[:, :, ::-1], conf=SIG_YOLO_CONF, verbose=False)
        out = []
        for r in res:
            for bx in r.boxes:
                x1, y1, x2, y2 = (int(v) for v in bx.xyxy[0].tolist())
                if x2 - x1 >= 10 and y2 - y1 >= 8:
                    out.append({"label": "signature", "x": x1, "y": y1,
                                "w": x2 - x1, "h": y2 - y1})
        return out
    except Exception as e:
        logger.warning("Signature YOLO predict failed: %s", e)
        return []

# Words/phrases that typically sit BELOW a hand-signed region.
SIGNATURE_LABELS: tuple[str, ...] = (
    "signature",
    "signatory",
    "authorised signatory",
    "authorized signatory",
    "applicant signature",
    "directors signature",
    "approved by",
    "for and on behalf",
    "signed",
)

# Geometry — where to look relative to the matched label.
REGION_WIDTH_MULT = 3.0      # ~3× the width of the label word
REGION_HEIGHT_MULT = 2.5     # ~2.5× the height of the label word
REGION_OFFSET_Y_FACTOR = -2.0  # vertical offset above the label

# Sensitivity (bank-safe but credible — see feedback_bank_safe_calibration).
# Calibration target: genuine ink signatures show ~3-5× baseline ELA on real
# scanned documents; truly pasted/photocopied signatures show 5-10×. We pick
# 5.0× as the flag boundary so credible hand-signed docs pass cleanly.
ELA_QUALITY = 90
ELA_NOISE_RATIO_THRESHOLD = 5.0  # region/baseline ratio that triggers a flag
ELA_NOISE_ABS_FLOOR = 1.0        # absolute floor (avoid noise on pristine docs)
ELA_CRITICAL_RATIO = 8.0         # ratio that escalates to critical indicator

MAX_DIMENSION = 1600

PDF_TYPE = "application/pdf"
IMAGE_TYPES = {"image/png", "image/jpeg"}


def _load_pil(content: bytes, content_type: str) -> Image.Image | None:
    if content_type == PDF_TYPE:
        try:
            with fitz.open(stream=content, filetype="pdf") as doc:
                if len(doc) == 0:
                    return None
                page = doc[0]
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception:
            return None
    if content_type in IMAGE_TYPES:
        try:
            return Image.open(io.BytesIO(content)).convert("RGB")
        except Exception:
            return None
    return None


def _downscale(img: Image.Image, max_dim: int) -> Image.Image:
    if max(img.size) <= max_dim:
        return img
    scale = max_dim / max(img.size)
    return img.resize(
        (int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS
    )


def _ela_mean(image: Image.Image) -> float:
    rgb = image.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=ELA_QUALITY)
    buf.seek(0)
    resaved = Image.open(buf).convert("RGB")
    diff = ImageChops.difference(rgb, resaved)
    return float(np.array(diff).mean())


def _find_label_regions(image: Image.Image) -> list[dict]:
    """Find inferred signature regions by locating label words via OCR."""
    try:
        data = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT, lang="eng"
        )
    except Exception as e:
        logger.warning("Tesseract image_to_data failed: %s", e)
        return []

    img_w, img_h = image.size

    words: list[dict] = []
    n = len(data["text"])
    for i in range(n):
        txt = (data["text"][i] or "").strip().lower()
        if not txt:
            continue
        try:
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
        except (ValueError, KeyError):
            continue
        if w <= 0 or h <= 0:
            continue
        words.append({"text": txt, "x": x, "y": y, "w": w, "h": h})

    regions: list[dict] = []
    seen_anchors: set[tuple[int, int]] = set()  # dedupe nearby matches

    for i, word in enumerate(words):
        single = word["text"]
        pair = single + " " + words[i + 1]["text"] if i + 1 < len(words) else single

        label_matched = None
        for label in SIGNATURE_LABELS:
            if label in single or label in pair:
                label_matched = label
                break
        if label_matched is None:
            continue

        # Anchor: round-down to nearest 30 px to deduplicate label hits in same area.
        anchor = (word["x"] // 30, word["y"] // 30)
        if anchor in seen_anchors:
            continue
        seen_anchors.add(anchor)

        rx = max(0, word["x"] - int(word["w"] * 0.5))
        ry = max(0, word["y"] + int(word["h"] * REGION_OFFSET_Y_FACTOR))
        rw = min(img_w - rx, int(word["w"] * REGION_WIDTH_MULT))
        rh = min(word["y"] - ry, int(word["h"] * REGION_HEIGHT_MULT))
        if rw < 30 or rh < 20:
            continue

        regions.append(
            {
                "label": label_matched,
                "x": rx,
                "y": ry,
                "w": rw,
                "h": rh,
            }
        )

    return regions


def analyze_signature_regions(content: bytes, content_type: str) -> dict:
    image = _load_pil(content, content_type)
    if image is None:
        return {
            "score": 1.0,
            "passed": True,
            "detail": "Could not load image for signature analysis.",
            "flags": [],
            "info": {"regions": []},
        }

    image = _downscale(image, MAX_DIMENSION)

    baseline_noise = _ela_mean(image)
    # Primary: visual YOLO detection (finds signatures anywhere). Fallback: OCR labels.
    regions = _yolo_regions(image)
    detect_mode = "YOLO" if regions else "labels"
    if not regions:
        regions = _find_label_regions(image)

    if not regions:
        return {
            "score": 1.0,
            "passed": True,
            "detail": (
                f"No signatures detected (baseline ELA {baseline_noise:.2f})."
            ),
            "flags": [],
            "info": {"regions": [], "baseline_noise": round(baseline_noise, 3),
                     "detect_mode": detect_mode},
        }

    flagged: list[dict] = []
    region_records: list[dict] = []
    for r in regions:
        crop = image.crop((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]))
        region_noise = _ela_mean(crop)
        ratio = region_noise / max(baseline_noise, 0.1)
        record = {
            "label": r["label"],
            "noise": round(region_noise, 2),
            "ratio": round(ratio, 2),
        }
        region_records.append(record)
        if ratio >= ELA_NOISE_RATIO_THRESHOLD and region_noise >= ELA_NOISE_ABS_FLOOR:
            flagged.append(record)

    flags: list[str] = []
    score = 1.0
    if flagged:
        max_ratio = max(r["ratio"] for r in flagged)
        # Penalty grows with how badly the worst region exceeds the threshold.
        penalty = 0.20 + 0.10 * max(0.0, max_ratio - ELA_NOISE_RATIO_THRESHOLD)
        score -= min(0.60, penalty)
        flags.append(f"elevated_signature_region({len(flagged)} of {len(regions)})")
        if max_ratio >= ELA_CRITICAL_RATIO:
            flags.append(f"critical_signature_ratio({max_ratio:.1f}x)")

    score = max(0.0, min(1.0, score))
    passed = score >= 0.7

    if flags:
        worst = max(flagged, key=lambda r: r["ratio"])
        detail = (
            f"{len(regions)} signature region(s) detected; "
            f"{len(flagged)} flagged. Worst near '{worst['label']}': "
            f"{worst['noise']:.2f} vs baseline {baseline_noise:.2f} "
            f"({worst['ratio']:.1f}× — possible pasted signature)."
        )
    else:
        detail = (
            f"{len(regions)} signature(s) detected ({detect_mode}) — all within baseline "
            f"noise ({baseline_noise:.2f})."
        )

    return {
        "score": score,
        "passed": passed,
        "detail": detail,
        "flags": flags,
        "info": {
            "baseline_noise": round(baseline_noise, 3),
            "regions": region_records,
            "detect_mode": detect_mode,
        },
    }
