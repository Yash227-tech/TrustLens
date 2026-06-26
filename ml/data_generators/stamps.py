"""Synthetic stamp/seal library generator (Step 14c).

Produces a small library of transparent-background stamp PNGs resembling the
kinds of stamps found on Indian legal/financial documents:
  - Circular bank seals (double ring + curved text)
  - Notary / company round seals
  - Rectangular rubber stamps: VERIFIED, TRUE COPY, PAID, RECEIVED, ATTESTED

These get composited onto clean docs in composite_stamps.py to build the
YOLOv8 training set. Real Roboflow stamps can be dropped into the same
library folder later (Step 15 retrains on whatever is present).
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path("/data/synthetic_stamps/lib")

INK_COLORS = [
    (180, 20, 20),    # red
    (20, 40, 150),    # blue
    (90, 30, 130),    # violet
    (20, 20, 20),     # black
]

CIRCLE_TOP_TEXTS = [
    "STATE BANK OF INDIA", "CANARA BANK", "HDFC BANK LTD", "ICICI BANK",
    "AXIS BANK", "NOTARY PUBLIC", "GOVT OF INDIA", "PUNJAB NATIONAL BANK",
]
CIRCLE_BOTTOM_TEXTS = ["MUMBAI", "DELHI", "BENGALURU", "CHENNAI", "BRANCH OFFICE", "REGD."]
CIRCLE_CENTER_TEXTS = ["AUTHORISED", "VERIFIED", "SEAL", "OFFICIAL"]

RECT_TEXTS = ["VERIFIED", "TRUE COPY", "PAID", "RECEIVED", "ATTESTED", "APPROVED", "ORIGINAL SEEN"]


def _font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_curved_text(draw, text, cx, cy, radius, color, font, top=True):
    n = len(text)
    if n == 0:
        return
    span = math.radians(min(160, 12 * n))
    start = -math.pi / 2 - span / 2 if top else math.pi / 2 - span / 2
    for i, ch in enumerate(text):
        ang = start + span * (i / max(1, n - 1))
        x = cx + radius * math.cos(ang)
        y = cy + radius * math.sin(ang)
        draw.text((x, y), ch, fill=color, font=font, anchor="mm")


def make_circular_seal(size=220) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = random.choice(INK_COLORS) + (random.randint(180, 245),)
    cx = cy = size // 2
    r = size // 2 - 6
    w = random.choice([3, 4, 5])
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
    d.ellipse([cx - r + 12, cy - r + 12, cx + r - 12, cy + r - 12], outline=color, width=2)
    _draw_curved_text(d, random.choice(CIRCLE_TOP_TEXTS), cx, cy, r - 22, color, _font(15), top=True)
    _draw_curved_text(d, random.choice(CIRCLE_BOTTOM_TEXTS), cx, cy, r - 22, color, _font(14), top=False)
    d.text((cx, cy), random.choice(CIRCLE_CENTER_TEXTS), fill=color, font=_font(16), anchor="mm")
    return img


def make_rect_stamp() -> Image.Image:
    text = random.choice(RECT_TEXTS)
    font = _font(random.choice([22, 26, 30]))
    pad = 14
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bbox = tmp.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    w, h = tw + 2 * pad, th + 2 * pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = random.choice(INK_COLORS) + (random.randint(180, 245),)
    d.rectangle([2, 2, w - 3, h - 3], outline=color, width=random.choice([2, 3]))
    d.text((w // 2, h // 2), text, fill=color, font=font, anchor="mm")
    return img


def generate_library(n_circular=12, n_rect=10) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for i in range(n_circular):
        make_circular_seal(random.choice([180, 200, 220, 240])).save(OUT_DIR / f"circ_{i:02d}.png")
        count += 1
    for i in range(n_rect):
        make_rect_stamp().save(OUT_DIR / f"rect_{i:02d}.png")
        count += 1
    return count


if __name__ == "__main__":
    random.seed(7)
    n = generate_library()
    print(f"Generated {n} synthetic stamps in {OUT_DIR}")
