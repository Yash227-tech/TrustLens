"""Indian-document tamper generator with ground-truth masks (improvement #4).

CASIA is generic spliced photos; we need IN-DOMAIN tampering — forged Indian IDs —
with pixel masks so we can MEASURE the forgery localiser (ManTraNet) instead of
eyeballing it, and so #3 can train the photo-region feature on real ID swaps.

For each genuine Aadhaar/PAN it emits matched (original, tampered, mask) triples
for several fraud vectors:

  copy_move      — a patch copied elsewhere in the SAME card (classic forgery;
                   ManTraNet/copy-move is designed to catch this).
  splice_crude   — a patch from a DIFFERENT card pasted in (hard edges -> visible
                   to ELA/ManTraNet).
  splice_seamless— same, via cv2.seamlessClone (Poisson blend -> the HARD case
                   ManTraNet largely cannot see; reported separately, honestly).
  photo_swap     — the PORTRAIT (located by the Aadhaar/PAN YOLO photo box) is
                   replaced with another card's portrait — the realistic ID fraud
                   that drives photo_forensics + face_match.

Output (container paths):
  /data/synthetic_tamper/<vector>/<id>.png         tampered image
  /data/synthetic_tamper/<vector>/<id>_orig.png    the untampered original (label 0)
  /data/synthetic_tamper/<vector>/<id>_mask.png    binary mask (255 = tampered px)
  /data/synthetic_tamper/manifest.jsonl            one row per tampered image

Run inside the backend container (GPU available for the photo-box detector):
  docker exec trustlens-backend sh -c "cd /ml && python -m training.build_tamper_set --per-class 40"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, "/app")

DATA = Path("/data")
EXT = DATA / "raw" / "external"
OUT = DATA / "synthetic_tamper"
SEED = 42
MAX_DIM = 1024  # align with photo_forensics / ManTraNet processing size

SOURCES = {
    "aadhaar": EXT / "roboflow_aadhaar",
    "pan": EXT / "pancard",
}
DETECTOR_WEIGHTS = {
    "aadhaar": DATA / "models" / "yolov8-aadhaar" / "best.pt",
    "pan": DATA / "models" / "yolov8-pan" / "best.pt",
}
PHOTO_CLASS = 0

_detectors: dict[str, object] = {}


def _load(path: Path) -> np.ndarray | None:
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None
    if max(im.size) > MAX_DIM:
        s = MAX_DIM / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.Resampling.LANCZOS)
    return np.array(im)[:, :, ::-1].copy()  # RGB->BGR for cv2


def _save(bgr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), bgr)


def _detector(doc_type: str):
    if doc_type in _detectors:
        return _detectors[doc_type]
    w = DETECTOR_WEIGHTS.get(doc_type)
    det = None
    if w and w.exists():
        try:
            from ultralytics import YOLO
            det = YOLO(str(w))
        except Exception:
            det = None
    _detectors[doc_type] = det
    return det


def _photo_box(doc_type: str, bgr: np.ndarray):
    det = _detector(doc_type)
    if det is None:
        return None
    try:
        res = det.predict(bgr, conf=0.35, verbose=False)
    except Exception:
        return None
    best, best_c = None, 0.0
    for r in res:
        for b in r.boxes:
            if int(b.cls) == PHOTO_CLASS and float(b.conf) > best_c:
                best_c = float(b.conf)
                best = tuple(int(v) for v in b.xyxy[0].tolist())
    return best


def _rand_patch(h: int, w: int, rng: random.Random, frac=(0.12, 0.22)):
    ph = int(h * rng.uniform(*frac))
    pw = int(w * rng.uniform(*frac))
    ph, pw = max(ph, 16), max(pw, 16)
    y = rng.randint(0, max(h - ph, 0))
    x = rng.randint(0, max(w - pw, 0))
    return x, y, pw, ph


def _mask_for(shape, box) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    x, y, w, h = box
    m[y:y + h, x:x + w] = 255
    return m


def copy_move(bgr, rng):
    h, w = bgr.shape[:2]
    x, y, pw, ph = _rand_patch(h, w, rng)
    patch = bgr[y:y + ph, x:x + pw].copy()
    for _ in range(20):  # find a non-overlapping destination
        dx = rng.randint(0, max(w - pw, 0))
        dy = rng.randint(0, max(h - ph, 0))
        if abs(dx - x) > pw or abs(dy - y) > ph:
            break
    out = bgr.copy()
    out[dy:dy + ph, dx:dx + pw] = patch
    return out, _mask_for(bgr.shape, (dx, dy, pw, ph))


def splice(bgr, donor, rng, seamless: bool):
    h, w = bgr.shape[:2]
    dh, dw = donor.shape[:2]
    x, y, pw, ph = _rand_patch(h, w, rng)
    pw, ph = min(pw, dw), min(ph, dh)
    sx = rng.randint(0, max(dw - pw, 0))
    sy = rng.randint(0, max(dh - ph, 0))
    patch = donor[sy:sy + ph, sx:sx + pw]
    out = bgr.copy()
    if seamless:
        cx, cy = x + pw // 2, y + ph // 2
        cx = min(max(cx, pw // 2 + 1), w - pw // 2 - 1)
        cy = min(max(cy, ph // 2 + 1), h - ph // 2 - 1)
        try:
            out = cv2.seamlessClone(patch, out, np.full(patch.shape[:2], 255, np.uint8),
                                    (cx, cy), cv2.NORMAL_CLONE)
        except Exception:
            out[y:y + ph, x:x + pw] = patch
    else:
        out[y:y + ph, x:x + pw] = patch
    return out, _mask_for(bgr.shape, (x, y, pw, ph))


def photo_swap(bgr, doc_type, donor, donor_type, rng):
    box = _photo_box(doc_type, bgr)
    if box is None:
        return None
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    if bw < 24 or bh < 24:
        return None
    dbox = _photo_box(donor_type, donor)
    if dbox:  # paste the donor's portrait
        dx1, dy1, dx2, dy2 = dbox
        face = donor[dy1:dy2, dx1:dx2]
    else:     # fall back to the donor's centre crop
        dh, dw = donor.shape[:2]
        face = donor[dh // 4:3 * dh // 4, dw // 4:3 * dw // 4]
    if face.size == 0:
        return None
    face = cv2.resize(face, (bw, bh))
    out = bgr.copy()
    out[y1:y2, x1:x2] = face
    return out, _mask_for(bgr.shape, (x1, y1, bw, bh))


def _gather(doc_type: str, n: int, rng: random.Random) -> list[Path]:
    root = SOURCES[doc_type]
    if not root.exists():
        return []
    imgs = [p for p in root.rglob("*.jpg") if "__MACOSX" not in str(p)]
    imgs += [p for p in root.rglob("*.png") if "__MACOSX" not in str(p)]
    rng.shuffle(imgs)
    return imgs[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=40, help="genuine images per doc type")
    ap.add_argument("--vectors", default="copy_move,splice_crude,splice_seamless,photo_swap")
    args = ap.parse_args()
    vectors = set(args.vectors.split(","))
    rng = random.Random(SEED)

    pool: dict[str, list[Path]] = {dt: _gather(dt, args.per_class, rng) for dt in SOURCES}
    for dt, ps in pool.items():
        print(f"{dt}: {len(ps)} genuine source images", flush=True)

    manifest: list[str] = []
    counts: dict[str, int] = {v: 0 for v in vectors}

    for doc_type, paths in pool.items():
        donors = [p for d in pool.values() for p in d]  # any card can donate
        for i, p in enumerate(paths):
            bgr = _load(p)
            if bgr is None:
                continue
            base_id = f"{doc_type}_{i:03d}"

            def emit(vector, result):
                if result is None:
                    return
                out_img, mask = result
                d = OUT / vector
                _save(bgr, d / f"{base_id}_orig.png")
                _save(out_img, d / f"{base_id}.png")
                _save(mask, d / f"{base_id}_mask.png")
                manifest.append(json.dumps({
                    "image": str((d / f"{base_id}.png").relative_to(DATA)),
                    "original": str((d / f"{base_id}_orig.png").relative_to(DATA)),
                    "mask": str((d / f"{base_id}_mask.png").relative_to(DATA)),
                    "vector": vector, "doc_type": doc_type,
                }))
                counts[vector] += 1

            if "copy_move" in vectors:
                emit("copy_move", copy_move(bgr, rng))
            if "splice_crude" in vectors or "splice_seamless" in vectors:
                donor = _load(rng.choice(donors))
                if donor is not None:
                    if "splice_crude" in vectors:
                        emit("splice_crude", splice(bgr, donor, rng, seamless=False))
                    if "splice_seamless" in vectors:
                        emit("splice_seamless", splice(bgr, donor, rng, seamless=True))
            if "photo_swap" in vectors:
                donor_type = rng.choice(list(SOURCES))
                donor_paths = pool[donor_type]
                if donor_paths:
                    donor = _load(rng.choice(donor_paths))
                    if donor is not None:
                        emit("photo_swap", photo_swap(bgr, doc_type, donor, donor_type, rng))
            if (i + 1) % 20 == 0:
                print(f"  {doc_type}: {i + 1}/{len(paths)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.jsonl").write_text("\n".join(manifest) + ("\n" if manifest else ""))
    print(f"\nWrote {len(manifest)} tampered triples -> {OUT}")
    print(f"  per vector: {counts}")
    print(f"  manifest: {OUT / 'manifest.jsonl'}")


if __name__ == "__main__":
    main()
