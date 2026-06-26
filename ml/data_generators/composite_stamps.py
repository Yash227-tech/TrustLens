"""Composite synthetic stamps onto clean docs → YOLOv8 training set (Step 14c).

For each output image:
  1. Pick a random clean synthetic doc, render first page to an image.
  2. Paste 1-3 stamps (from the stamp library) at random positions — biased
     toward the lower half where signatures/seals usually go — with random
     rotation, scale, and opacity.
  3. Record a tight YOLO bbox for every pasted stamp (class 0 = "stamp").

Outputs an Ultralytics-style dataset:
    /data/yolo_stamps/images/{train,val}/*.jpg
    /data/yolo_stamps/labels/{train,val}/*.txt
    /data/yolo_stamps/data.yaml

The stamp library is read from /data/synthetic_stamps/lib AND, if present,
/data/raw/external/stamps (so real Roboflow stamps can augment later).
"""

from __future__ import annotations

import random
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

SYNTH_DOCS = Path("/data/synthetic")
STAMP_LIB_DIRS = [Path("/data/synthetic_stamps/lib"), Path("/data/raw/external/stamps")]
OUT_ROOT = Path("/data/yolo_stamps")
RENDER_MAX = 1024
N_TRAIN = 1500
N_VAL = 250
SEED = 13


def list_clean_pdfs() -> list[Path]:
    pdfs = []
    for d in sorted(SYNTH_DOCS.iterdir()):
        if d.is_dir() and d.name != "models":
            pdfs.extend(sorted(d.glob("*.pdf")))
    return pdfs


def list_stamps() -> list[Path]:
    stamps = []
    for d in STAMP_LIB_DIRS:
        if d.exists():
            stamps.extend(sorted(d.glob("*.png")))
            stamps.extend(sorted(d.glob("*.jpg")))
    return stamps


def render_doc(pdf: Path) -> Image.Image | None:
    try:
        with fitz.open(pdf) as doc:
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except Exception:
        return None
    if max(img.size) > RENDER_MAX:
        s = RENDER_MAX / max(img.size)
        img = img.resize((int(img.width * s), int(img.height * s)), Image.Resampling.LANCZOS)
    return img


def place_stamp(canvas: Image.Image, stamp: Image.Image) -> tuple[float, float, float, float] | None:
    cw, ch = canvas.size
    # random scale relative to canvas width
    target_w = random.randint(int(cw * 0.10), int(cw * 0.28))
    scale = target_w / stamp.width
    s = stamp.resize((max(8, int(stamp.width * scale)), max(8, int(stamp.height * scale))),
                     Image.Resampling.LANCZOS)
    # random rotation
    s = s.rotate(random.uniform(-30, 30), expand=True, resample=Image.BICUBIC)
    # random opacity
    if random.random() < 0.8:
        alpha = s.split()[3].point(lambda a: int(a * random.uniform(0.6, 0.95)))
        s.putalpha(alpha)
    # tight bbox from alpha
    bbox = s.split()[3].getbbox()
    if bbox is None:
        return None
    s = s.crop(bbox)
    sw, sh = s.size
    if sw >= cw or sh >= ch:
        return None
    # bias position toward lower half
    x = random.randint(0, cw - sw)
    y = random.randint(int(ch * 0.35), ch - sh)
    canvas.paste(s, (x, y), s)
    xc = (x + sw / 2) / cw
    yc = (y + sh / 2) / ch
    return xc, yc, sw / cw, sh / ch


def build_split(name: str, count: int, pdfs: list[Path], stamps: list[Path]) -> int:
    img_dir = OUT_ROOT / "images" / name
    lbl_dir = OUT_ROOT / "labels" / name
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    attempts = 0
    while made < count and attempts < count * 3:
        attempts += 1
        canvas = render_doc(random.choice(pdfs))
        if canvas is None:
            continue
        boxes = []
        for _ in range(random.choice([1, 1, 2, 2, 3])):
            stamp = Image.open(random.choice(stamps)).convert("RGBA")
            box = place_stamp(canvas, stamp)
            if box:
                boxes.append(box)
        if not boxes:
            continue
        stem = f"{name}_{made:05d}"
        canvas.convert("RGB").save(img_dir / f"{stem}.jpg", "JPEG", quality=88)
        with (lbl_dir / f"{stem}.txt").open("w") as f:
            for xc, yc, w, h in boxes:
                f.write(f"0 {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n")
        made += 1
        if made % 200 == 0:
            print(f"  {name}: {made}/{count}")
    return made


def main():
    random.seed(SEED)
    pdfs = list_clean_pdfs()
    stamps = list_stamps()
    print(f"{len(pdfs)} source docs, {len(stamps)} stamps in library")
    if not stamps:
        raise SystemExit("No stamps found. Run stamps.py first.")

    n_train = build_split("train", N_TRAIN, pdfs, stamps)
    n_val = build_split("val", N_VAL, pdfs, stamps)

    (OUT_ROOT / "data.yaml").write_text(
        "path: /data/yolo_stamps\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 1\n"
        "names: ['stamp']\n"
    )
    print(f"\nDone. train={n_train} val={n_val}")
    print(f"Dataset: {OUT_ROOT}/data.yaml")


if __name__ == "__main__":
    main()
