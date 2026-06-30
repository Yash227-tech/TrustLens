"""Cross-document face matching — photo-superimposition / mixed-identity detection.

The #1 ID-card tamper is swapping the face photo. ELA on the photo crop is useless
for this (a genuine face is naturally 2-4x the card's ELA baseline -> 100% false
positive; see aadhaar_fields). Instead we compare the FACE itself across the
applicant's own identity documents in a case: detect the face on each ID
(Aadhaar / PAN / passport), embed it (FaceNet / InceptionResnetV1, VGGFace2), and
compare embeddings. Two ID docs whose faces don't match => a swapped photo or two
different people's IDs stitched into one identity.

This is an EXTRACTION + COMPARISON helper, not a single-image forensic: the per-doc
side only produces an embedding; the cross-document decision lives in cross_doc.py
(it has the case context) and follows bank-safe calibration — a clear mismatch is
YELLOW review (escalates to RED only alongside a name / hard-ID conflict), never an
auto-reject; uncertain / low-quality / no-face is neutral.

Model: MTCNN (face detect+align) + InceptionResnetV1(pretrained='vggface2'), CPU-ok,
weights baked into the image for offline use. Reuses the main torch 2.2.2 stack —
no version conflict, so it runs in-process (unlike the NER microservice).

Thresholds calibrated on REAL roboflow Aadhaar (same source card vs different card);
see the project memory. HONEST CAVEAT: genuine calibration pairs are the same PHOTO
(different augmentation), not the same person photographed twice — real
same-person-different-photo scores lower, so thresholds are deliberately
conservative (wide uncertain band, mismatch is review-only).
"""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# --- calibrated cosine thresholds (see project_face_match memory) ---
MATCH_THRESHOLD = 0.55      # >= -> same person (reinforces identity, helps GREEN)
MISMATCH_THRESHOLD = 0.30   # <  -> different person (possible photo swap -> review)
MIN_FACE_PROB = 0.92        # MTCNN detection confidence floor; below = low quality
IMG_SIZE = 160
MARGIN = 14

PDF_TYPE = "application/pdf"
IMAGE_TYPES = {"image/png", "image/jpeg"}
PDF_RENDER_DPI = 200

_mtcnn = None
_embedder = None
_device = "cpu"
_lock = threading.Lock()
_unavailable = False


def _load() -> bool:
    global _mtcnn, _embedder, _device, _unavailable
    if _mtcnn is not None and _embedder is not None:
        return True
    if _unavailable:
        return False
    with _lock:
        if _mtcnn is not None and _embedder is not None:
            return True
        try:
            import torch
            from facenet_pytorch import MTCNN, InceptionResnetV1

            _device = "cuda" if torch.cuda.is_available() else "cpu"
            _mtcnn = MTCNN(image_size=IMG_SIZE, margin=MARGIN, keep_all=False,
                           post_process=True, device=_device)
            _embedder = InceptionResnetV1(pretrained="vggface2").eval().to(_device)
            logger.info("Face-match model loaded (device=%s).", _device)
            return True
        except Exception as e:  # missing weights/lib -> never take the pipeline down
            logger.warning("Face-match unavailable (%s) — skipping face checks.",
                           e.__class__.__name__)
            _unavailable = True
            return False


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


def extract_face_embedding(content: bytes, content_type: str) -> dict:
    """Detect the largest face and return its L2-normalised FaceNet embedding.

    Returns {"embedding": list[float] | None, "prob": float, "quality": str}
    quality: "ok" (usable) | "low" (face too uncertain) | "none" (no face) |
             "unavailable" (model/render not available).
    """
    if not _load():
        return {"embedding": None, "prob": 0.0, "quality": "unavailable"}
    image = _load_pil(content, content_type)
    if image is None:
        return {"embedding": None, "prob": 0.0, "quality": "none"}
    try:
        import torch
        face, prob = _mtcnn(image, return_prob=True)
        if face is None or prob is None:
            return {"embedding": None, "prob": 0.0, "quality": "none"}
        prob = float(prob)
        if prob < MIN_FACE_PROB:
            return {"embedding": None, "prob": round(prob, 3), "quality": "low"}
        with torch.no_grad():
            emb = _embedder(face.unsqueeze(0).to(_device))[0]
            emb = torch.nn.functional.normalize(emb, dim=0).cpu().numpy()
        return {"embedding": [round(float(x), 5) for x in emb],
                "prob": round(prob, 3), "quality": "ok"}
    except Exception as e:
        logger.warning("Face embedding failed: %s", e.__class__.__name__)
        return {"embedding": None, "prob": 0.0, "quality": "none"}


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def compare_faces(emb_a: list[float], emb_b: list[float]) -> dict:
    """Compare two embeddings. verdict: match | mismatch | uncertain."""
    sim = cosine(emb_a, emb_b)
    if sim >= MATCH_THRESHOLD:
        verdict = "match"
    elif sim < MISMATCH_THRESHOLD:
        verdict = "mismatch"
    else:
        verdict = "uncertain"
    return {"similarity": round(sim, 3), "verdict": verdict}
