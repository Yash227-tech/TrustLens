"""Synthetic utility-bill images + YOLO labels to broaden the field detector.

The real detector training set (raw/external/water_bill) is Delhi-Jal-Board WATER
only, so localization is weak on gas / electricity layouts. The synthetic
`utility_bill()` generator knows the EXACT draw position of every field, so it can
emit YOLO boxes for free (see templates._ybox). This renders a balanced set of
electricity / water / gas bills to images and writes YOLO labels, to be COMBINED
with the real DJB water set when retraining yolov8-utility.

Classes match the real DJB detector exactly: 0=Date, 1=KNO, 2=Name, 3=address.

Caveat: synthetic teaches MY template layout — it improves gas/electricity
transfer but is bounded until a real box-annotated gas bill exists. The real DJB
water images stay in the mix so real-water performance is preserved.

  OUT -> /data/yolo_utility_syn/{train,valid}/{images,labels}

Run:
    docker exec trustlens-backend sh -c "cd /ml && python -m data_generators.build_utility_detector_set --per-type 100"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF

# Allow running as `python -m data_generators.build_utility_detector_set` from /ml.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_generators import indian_data as D  # noqa: E402
from data_generators.templates import utility_bill  # noqa: E402

OUT_ROOT = Path("/data/yolo_utility_syn")
SUBS = ["electricity", "water", "gas"]
DPI = 150


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _render_png(pdf_bytes: bytes) -> bytes:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(DPI / 72, DPI / 72), alpha=False)
        return pix.tobytes("png")


def _label_lines(boxes: list) -> str:
    out = []
    for cls, cx, cy, w, h in boxes:
        cx, cy = _clamp01(cx), _clamp01(cy)
        w, h = _clamp01(w), _clamp01(h)
        if w <= 0 or h <= 0:
            continue
        out.append(f"{int(cls)} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return "\n".join(out) + ("\n" if out else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=100, help="bills per sub-type (elec/water/gas)")
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=20260627)
    args = ap.parse_args()

    D.seed(args.seed)
    for split in ("train", "valid"):
        (OUT_ROOT / split / "images").mkdir(parents=True, exist_ok=True)
        (OUT_ROOT / split / "labels").mkdir(parents=True, exist_ok=True)

    val_every = max(2, round(1 / args.val_frac))  # every Nth doc -> valid
    counts = {"train": 0, "valid": 0}
    skipped = 0
    idx = 0
    for sub in SUBS:
        for i in range(args.per_type):
            try:
                pdf_bytes, fields = utility_bill(sub=sub)
            except Exception as e:
                print(f"  ! {sub} #{i} failed: {e.__class__.__name__}: {e}")
                continue
            boxes = fields.get("_boxes") or []
            lab = _label_lines(boxes)
            if not lab.strip():
                skipped += 1
                continue
            split = "valid" if (idx % val_every == 0) else "train"
            stem = f"syn_{sub}_{i:04d}"
            (OUT_ROOT / split / "images" / f"{stem}.png").write_bytes(_render_png(pdf_bytes))
            (OUT_ROOT / split / "labels" / f"{stem}.txt").write_text(lab, encoding="utf-8")
            counts[split] += 1
            idx += 1
        print(f"  {sub:12s} -> {args.per_type} generated")

    print(f"\nSynthetic utility detector set -> {OUT_ROOT}")
    print(f"  train: {counts['train']}   valid: {counts['valid']}   skipped(no boxes): {skipped}")


if __name__ == "__main__":
    main()
