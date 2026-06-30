"""Udyam (MSME) certificate QR + URN extraction (authenticity aid, not a forensic).

A genuine Udyam Registration Certificate carries a QR that encodes the Udyam
Registration Number (URN) and the udyamregistration.gov.in verification URL. We
decode it with OpenCV (already in the stack — no new dependency) and cross-check
the QR's URN against the URN printed on the certificate:

  - QR URN == printed URN          -> consistent (authenticity reinforced)
  - QR URN != printed URN          -> possible tampering (someone edited the
                                       printed text but not the QR, or vice versa)
  - no QR                          -> informational only (scans / prints routinely
                                       drop the QR) — never a penalty (bank-safe)

The URN itself is verified against the (mock) Udyam registry by
verification_service. Mirrors utility_fields / pan_fields.
"""

from __future__ import annotations

import io
import logging
import re

import cv2
import fitz
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

PDF_TYPE = "application/pdf"
IMAGE_TYPES = {"image/png", "image/jpeg"}
PDF_RENDER_DPI = 200
URN_RE = re.compile(r"UDYAM-[A-Z]{2}-\d{2}-\d{7}", re.IGNORECASE)


def _load_pil(content: bytes, content_type: str) -> Image.Image | None:
    if content_type == PDF_TYPE:
        try:
            with fitz.open(stream=content, filetype="pdf") as d:
                if len(d) == 0:
                    return None
                m = PDF_RENDER_DPI / 72
                pix = d[0].get_pixmap(matrix=fitz.Matrix(m, m), alpha=False)
                return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception:
            return None
    if content_type in IMAGE_TYPES:
        try:
            return Image.open(io.BytesIO(content)).convert("RGB")
        except Exception:
            return None
    return None


def _decode_qrs(image: Image.Image) -> list[str]:
    arr = np.array(image)[:, :, ::-1].copy()  # RGB->BGR for cv2
    det = cv2.QRCodeDetector()
    out: list[str] = []
    try:
        ok, decoded, _pts, _ = det.detectAndDecodeMulti(arr)
        if ok and decoded:
            out = [d for d in decoded if d]
    except Exception:
        pass
    if not out:
        try:
            val, _pts, _ = det.detectAndDecode(arr)
            if val:
                out = [val]
        except Exception:
            pass
    return out


def extract_udyam_fields(content: bytes, content_type: str) -> dict:
    """Best-effort QR decode. Returns {qr_present, qr_data, qr_urn}."""
    out = {"qr_present": False, "qr_data": None, "qr_urn": None}
    image = _load_pil(content, content_type)
    if image is None:
        return out
    datas = _decode_qrs(image)
    if not datas and max(image.size) < 1600:  # tiny upload — upscale once and retry
        f = min(3, max(2, round(1600 / max(image.size))))
        datas = _decode_qrs(image.resize((image.width * f, image.height * f),
                                          Image.Resampling.LANCZOS))
    for d in datas:
        out["qr_present"] = True
        out["qr_data"] = d
        m = URN_RE.search(d or "")
        if m:
            out["qr_urn"] = m.group(0).upper()
            break
    return out
