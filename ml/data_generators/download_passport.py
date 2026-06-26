"""Download akashsalmuthe/ind_passport (200 real Indian passport images + field
captions) to disk so the LayoutLMv3 classifier can learn the real `passport`
layout — the same real-data fix done for Aadhaar (0->100%) and PAN (0->98%).

Saves:
  /data/raw/external/passport/images/passport_NNN.jpg
  /data/raw/external/passport/captions.jsonl   (image -> ground-truth field text)

Run in the backend container:
    docker exec trustlens-backend sh -c "cd /ml && python -m data_generators.download_passport"
"""
from __future__ import annotations

import json
from pathlib import Path

from datasets import load_dataset

OUT_DIR = Path("/data/raw/external/passport")
IMG_DIR = OUT_DIR / "images"
CAPTIONS = OUT_DIR / "captions.jsonl"


def main():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    ds = load_dataset("akashsalmuthe/ind_passport", split="train")
    n = 0
    with CAPTIONS.open("w", encoding="utf-8") as cf:
        for i, ex in enumerate(ds):
            img = ex["image"].convert("RGB")
            name = f"passport_{i:04d}.jpg"
            img.save(IMG_DIR / name, "JPEG", quality=95)
            cf.write(json.dumps({"image": f"images/{name}",
                                 "caption": ex.get("caption", "")}) + "\n")
            n += 1
    print(f"Saved {n} passport images -> {IMG_DIR}")
    print(f"Captions -> {CAPTIONS}")


if __name__ == "__main__":
    main()
