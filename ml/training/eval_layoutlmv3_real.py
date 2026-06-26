"""Evaluate a fine-tuned LayoutLMv3 on the REAL annual-report statement pages.

Measures doc-type accuracy on the 107 genuine financial-statement pages
extracted from public annual reports (the 4 financial-statement classes).
Run it against the new model and the backup to see the before/after of adding
real data to training.

Usage (inside backend container):
    python -m training.eval_layoutlmv3_real /data/models/layoutlmv3-trustlens
    python -m training.eval_layoutlmv3_real /data/models/layoutlmv3-trustlens.bak
"""

from __future__ import annotations

import glob
import sys
from collections import Counter
from pathlib import Path

import fitz
import torch
from PIL import Image
from transformers import LayoutLMv3ForSequenceClassification, LayoutLMv3Processor

REAL_ROOT = Path("/data/raw/external/real_docs")
TYPES = ("balance_sheet", "profit_and_loss", "cash_flow_statement", "audited_financials")
RENDER_DPI = 150
MAX_DIM = 1024


def render(pdf_path: str) -> Image.Image:
    with fitz.open(pdf_path) as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if max(img.size) > MAX_DIM:
        s = MAX_DIM / max(img.size)
        img = img.resize((int(img.width * s), int(img.height * s)), Image.Resampling.LANCZOS)
    return img


def main(model_dir: str):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    processor = LayoutLMv3Processor.from_pretrained(model_dir, apply_ocr=True)
    model = LayoutLMv3ForSequenceClassification.from_pretrained(model_dir).to(device).eval()
    id2label = model.config.id2label

    print(f"\n=== {model_dir} on REAL statement pages ===")
    ok = tot = 0
    conf_sum = 0.0
    confusions: Counter = Counter()
    for dt in TYPES:
        files = sorted(glob.glob(str(REAL_ROOT / dt / "*.pdf")))
        c = 0
        for fp in files:
            enc = processor(render(fp), return_tensors="pt", truncation=True,
                            padding="max_length", max_length=512)
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.no_grad():
                probs = torch.softmax(model(**enc).logits, dim=-1)[0]
            idx = int(probs.argmax())
            pred = id2label[idx]
            conf_sum += float(probs[idx])
            if pred == dt:
                c += 1
            else:
                confusions[(dt, pred)] += 1
        print(f"  {dt:22s} {c}/{len(files)}")
        ok += c
        tot += len(files)
    print(f"  TOTAL {ok}/{tot} = {100*ok/tot:.1f}%   mean confidence {conf_sum/tot:.2f}")
    if confusions:
        print("  confusions:", confusions.most_common(8))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/data/models/layoutlmv3-trustlens")
