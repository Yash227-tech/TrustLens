"""ManTraNet inference wrapper.

Loads the pretrained PyTorch model once on first call (singleton), accepts
raw bytes + content type, returns a forgery probability heatmap and a
trust score derived from it.

Output shape parallels app.forensics.ela.analyze_ela().
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

import fitz  # PyMuPDF — render PDF first page to image
import numpy as np
import torch
from PIL import Image, ImageEnhance

from app.forensics.mantranet.model import MantraNet

WEIGHTS_PATH = Path(__file__).parent / "weights" / "MantraNetv4.pt"
MAX_DIMENSION = 1024  # Larger inputs blow up GPU memory; ManTraNet was trained around this size.

_model: MantraNet | None = None
_model_lock = threading.Lock()
_device: torch.device | None = None


def _get_model() -> tuple[MantraNet, torch.device]:
    """Lazy-load the model once. Thread-safe."""
    global _model, _device
    if _model is not None:
        return _model, _device  # type: ignore[return-value]
    with _model_lock:
        if _model is not None:
            return _model, _device  # type: ignore[return-value]
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = MantraNet(device=_device)
        state = torch.load(WEIGHTS_PATH, map_location=_device, weights_only=False)
        model.load_state_dict(state)
        model.to(_device)
        model.eval()
        _model = model
        return _model, _device


def _pdf_first_page_to_pil(content: bytes, dpi: int = 150) -> Image.Image | None:
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


def _load_pil(content: bytes, content_type: str) -> Image.Image | None:
    if content_type == "application/pdf":
        return _pdf_first_page_to_pil(content)
    try:
        return Image.open(io.BytesIO(content)).convert("RGB")
    except Exception:
        return None


def _downscale(img: Image.Image, max_dim: int) -> Image.Image:
    if max(img.size) <= max_dim:
        return img
    scale = max_dim / max(img.size)
    new_size = (int(img.width * scale), int(img.height * scale))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def analyze_mantranet(content: bytes, content_type: str) -> dict:
    pil = _load_pil(content, content_type)
    if pil is None:
        return {
            "score": 0.5,
            "passed": False,
            "detail": "Could not load image for ManTraNet.",
            "heatmap_bytes": None,
        }

    pil = _downscale(pil, MAX_DIMENSION)
    model, device = _get_model()

    arr = np.array(pil)  # H, W, 3
    tensor = torch.from_numpy(arr).float().unsqueeze(0)  # 1, H, W, 3
    tensor = tensor.permute(0, 3, 1, 2).contiguous()      # 1, 3, H, W
    tensor = tensor.to(device)

    with torch.no_grad():
        output = model(tensor)  # 1, 1, H, W — forgery probability mask

    mask = output[0, 0].cpu().numpy()  # H, W
    mask = np.clip(mask, 0.0, 1.0)

    mean_prob = float(mask.mean())
    max_prob = float(mask.max())
    p95_prob = float(np.percentile(mask, 95))
    forged_pct = float((mask > 0.2).mean() * 100.0)

    # Score using p95 of the forgery probability mask. ManTraNet was trained
    # on natural photos; on document images it has elevated baseline activations,
    # so thresholds are calibrated higher than a typical natural-image setup:
    #   p95 ≤ 0.30 → clean (matches real Zoho PDFs at 0.31)
    #   p95 ≈ 0.50 → suspect (paper's known-forgery samples land here)
    #   p95 ≥ 0.80 → strong forgery signal
    tampering = min(1.0, max(0.0, (p95_prob - 0.30) / 0.50))
    trust = max(0.0, 1.0 - tampering)
    passed = trust >= 0.7

    # Build a visualisation heatmap (grayscale → amplified for visibility).
    vis = (mask * 255).astype(np.uint8)
    heatmap_pil = Image.fromarray(vis, mode="L").convert("RGB")
    if max_prob < 1.0 and max_prob > 0:
        # Stretch contrast so even faint signals are visible.
        heatmap_pil = ImageEnhance.Brightness(heatmap_pil).enhance(min(2.5, 1.0 / max_prob))
    buf = io.BytesIO()
    heatmap_pil.save(buf, "PNG", optimize=True)

    if passed:
        detail = (
            f"Forgery mask p95={p95_prob:.2f}, mean={mean_prob:.2f}, "
            f"{forged_pct:.1f}% of pixels above 0.2 threshold — no copy-move/splicing."
        )
    else:
        detail = (
            f"Forgery mask p95={p95_prob:.2f}, max={max_prob:.2f}, "
            f"{forged_pct:.1f}% of pixels flagged — likely copy-move or splicing."
        )

    return {
        "score": trust,
        "passed": passed,
        "detail": detail,
        "heatmap_bytes": buf.getvalue(),
    }
