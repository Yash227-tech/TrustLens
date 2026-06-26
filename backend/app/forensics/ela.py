"""Error Level Analysis.

Saves the input image as JPEG at known quality, computes the pixel-wise
difference between the original and the resaved copy, amplifies the diff
into a heatmap, and scores the document based on how uniformly the diff
is distributed. Edited regions show as bright clusters because they
carry different compression history.
"""

from __future__ import annotations

import io

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageChops, ImageEnhance

MAX_RENDER_DIMENSION = 1600
ELA_QUALITY = 90
TAMPERING_DIVISOR = 8.0  # Higher = less sensitive. Tuned for demo.


def _pdf_first_page_to_image(content: bytes, dpi: int = 150) -> Image.Image | None:
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            if len(doc) == 0:
                return None
            page = doc[0]
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except Exception:
        return None


def _load_image(content: bytes, content_type: str) -> Image.Image | None:
    if content_type == "application/pdf":
        return _pdf_first_page_to_image(content)
    try:
        return Image.open(io.BytesIO(content)).convert("RGB")
    except Exception:
        return None


def _downscale(img: Image.Image, max_dim: int) -> Image.Image:
    if max(img.size) <= max_dim:
        return img
    ratio = max_dim / max(img.size)
    new_size = (int(img.width * ratio), int(img.height * ratio))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def _compute_ela(image: Image.Image) -> tuple[float, Image.Image]:
    original = _downscale(image.convert("RGB"), MAX_RENDER_DIMENSION)

    buf = io.BytesIO()
    original.save(buf, "JPEG", quality=ELA_QUALITY)
    buf.seek(0)
    resaved = Image.open(buf).convert("RGB")

    diff = ImageChops.difference(original, resaved)

    # Heatmap: amplify diff so even small differences are visible.
    extrema = diff.getextrema()
    max_diff = max(e[1] for e in extrema) or 1
    scale_factor = min(255.0 / max_diff, 30.0)
    heatmap = ImageEnhance.Brightness(diff).enhance(scale_factor)

    arr = np.array(diff).max(axis=2).astype(np.float32)
    mean_intensity = float(arr.mean())

    # LOCALISED-anomaly scoring (bank-safe, user-approved). A genuine splice/edit
    # shows ELA noise CONCENTRATED in a region that is much brighter than the rest
    # of the page. A scanned / photocopied page has UNIFORM noise everywhere (the
    # whole page was re-compressed once) — high global mean but no local contrast,
    # which is benign. So we score on how far the WORST region exceeds the TYPICAL
    # region, not on the global level. Uniform noise (any level) -> clean; a bright
    # localised cluster on an otherwise-clean page -> tampered.
    H, W = arr.shape
    grid = 16
    bh, bw = max(1, H // grid), max(1, W // grid)
    block_means = [
        float(arr[i:i + bh, j:j + bw].mean())
        for i in range(0, H - bh + 1, bh)
        for j in range(0, W - bw + 1, bw)
    ]
    blocks = np.array(block_means) if block_means else np.array([mean_intensity])
    typical = float(np.percentile(blocks, 50))   # robust page baseline
    worst = float(np.percentile(blocks, 98))      # worst region
    local_excess = max(0.0, worst - typical)      # how much a region spikes above the page

    # Same calibration shape as before, but on the LOCAL EXCESS rather than the
    # global mean: excess ≤ 0.3 → untouched; ≈ 1.0 → suspect; ≥ 2.0 → tampered.
    tampering = min(1.0, max(0.0, (local_excess - 0.3) / 1.7))
    trust = max(0.0, 1.0 - tampering)
    # Critical only when the spike is both strong AND clearly localised (not a
    # uniformly noisy scan). worst must clear an absolute floor too.
    localized_anomaly = tampering >= 0.6 and worst >= 1.0 and (worst >= 2.0 * (typical + 0.3))

    info = {
        "global_mean": round(mean_intensity, 3),
        "typical_region": round(typical, 3),
        "worst_region": round(worst, 3),
        "local_excess": round(local_excess, 3),
        "localized_anomaly": localized_anomaly,
        "uniform_noise": mean_intensity > 1.0 and not localized_anomaly,
    }
    return trust, heatmap, info


def analyze_ela(content: bytes, content_type: str) -> dict:
    image = _load_image(content, content_type)
    if image is None:
        return {
            "score": 0.5,
            "passed": False,
            "detail": "Could not load image for ELA.",
            "heatmap_bytes": None,
        }

    score, heatmap, info = _compute_ela(image)
    passed = score >= 0.7

    buf = io.BytesIO()
    heatmap.save(buf, "PNG", optimize=True)

    if info.get("localized_anomaly"):
        detail = (
            f"Localised ELA anomaly: a region is {info['worst_region']:.1f} vs page "
            f"baseline {info['typical_region']:.1f} — possible edited region (check heatmap)."
        )
    elif info.get("uniform_noise"):
        detail = (
            f"Uniform re-compression noise (global {info['global_mean']:.1f}, no localised "
            "spike) — consistent with a scan/photocopy, not tampering."
        )
    else:
        detail = "ELA clean — no localised re-compression anomaly."

    return {
        "score": score,
        "passed": passed,
        "detail": detail,
        "heatmap_bytes": buf.getvalue(),
        "localized_anomaly": bool(info.get("localized_anomaly")),
        "info": info,
    }
