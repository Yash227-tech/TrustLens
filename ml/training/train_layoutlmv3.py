"""Fine-tune microsoft/layoutlmv3-base on the 23 synthetic Indian doc types.

Step 14b. Reads the manifest at /data/synthetic/labels.jsonl, renders each PDF's
first page to an image, runs the LayoutLMv3 processor (internal Tesseract OCR +
layout), and fine-tunes a 23-class sequence classifier on the RTX 4060.

Run inside the backend container (GPU passthrough already configured):
    docker exec trustlens-backend sh -c "cd /ml && python -m training.train_layoutlmv3"

Outputs the fine-tuned model + processor to /data/models/layoutlmv3-trustlens/.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
import torch
from PIL import Image
from transformers import (
    LayoutLMv3ForSequenceClassification,
    LayoutLMv3Processor,
    Trainer,
    TrainingArguments,
)

DATA_ROOT = Path("/data")
MANIFEST = DATA_ROOT / "synthetic" / "labels.jsonl"
# Real financial-statement pages extracted from public annual reports
# (extract_annual_report_pages.py). Mixed into the synthetic pool so the 4
# financial-statement classes train on genuine layouts, not just synthetic.
REAL_MANIFEST = DATA_ROOT / "raw" / "external" / "real_docs" / "labels.jsonl"
# Real Aadhaar card photos for the `aadhaar` class — the synthetic-only model
# classified real Aadhaar 0% correctly, so these genuinely teach real layouts.
REAL_AADHAAR_MANIFEST = DATA_ROOT / "raw" / "external" / "roboflow_aadhaar" / "labels_classify.jsonl"
# Real PAN card photos for the `pan` class — real PANs were read as `aadhaar`
# 96% of the time (both blue ID cards); these teach the real PAN layout.
REAL_PAN_MANIFEST = DATA_ROOT / "raw" / "external" / "pancard" / "labels_classify.jsonl"
# Real Indian passport photos for the `passport` class (akashsalmuthe/ind_passport)
# — the synthetic-only model has never seen a real passport, so these teach the
# real layout (same real-data fix as Aadhaar and PAN).
REAL_PASSPORT_MANIFEST = DATA_ROOT / "raw" / "external" / "passport" / "labels_classify.jsonl"
# Real bank-statement page images for the `bank_statement` class — the synthetic
# model read a genuine statement as profit_and_loss (13% on held-out real); these
# teach the real layout (Roboflow bank-statement dataset, leak-free train split).
REAL_BANKSTMT_MANIFEST = DATA_ROOT / "raw" / "external" / "Bankstatments" / "labels_classify.jsonl"
OUT_DIR = DATA_ROOT / "models" / "layoutlmv3-trustlens"
MODEL_ID = "microsoft/layoutlmv3-base"
RENDER_DPI = 150
EPOCHS = 8
VAL_FRACTION = 0.2
SEED = 42


def render_first_page(pdf_path: Path, dpi: int = RENDER_DPI) -> Image.Image:
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_manifest() -> list[dict]:
    rows = _read_jsonl(MANIFEST)
    n_syn = len(rows)
    n_real = n_aadhaar = 0
    if REAL_MANIFEST.exists():
        real = _read_jsonl(REAL_MANIFEST)
        rows.extend(real)
        n_real = len(real)
    if REAL_AADHAAR_MANIFEST.exists():
        aad = _read_jsonl(REAL_AADHAAR_MANIFEST)
        rows.extend(aad)
        n_aadhaar = len(aad)
    n_pan = 0
    if REAL_PAN_MANIFEST.exists():
        pan = _read_jsonl(REAL_PAN_MANIFEST)
        rows.extend(pan)
        n_pan = len(pan)
    n_passport = 0
    if REAL_PASSPORT_MANIFEST.exists():
        passport = _read_jsonl(REAL_PASSPORT_MANIFEST)
        rows.extend(passport)
        n_passport = len(passport)
    n_bankstmt = 0
    if REAL_BANKSTMT_MANIFEST.exists():
        bs = _read_jsonl(REAL_BANKSTMT_MANIFEST)
        rows.extend(bs)
        n_bankstmt = len(bs)
    print(f"manifest: {n_syn} synthetic + {n_real} real-financial "
          f"+ {n_aadhaar} real-aadhaar + {n_pan} real-pan "
          f"+ {n_passport} real-passport + {n_bankstmt} real-bankstmt = {len(rows)} docs")
    return rows


class LayoutDataset(torch.utils.data.Dataset):
    """Pre-processes each doc once (OCR + layout) and caches encodings in RAM."""

    def __init__(self, rows: list[dict], processor: LayoutLMv3Processor, label2id: dict):
        self.encodings: list[dict] = []
        self.labels: list[int] = []
        n = len(rows)
        for i, row in enumerate(rows):
            pdf = DATA_ROOT / row["path"]
            try:
                img = render_first_page(pdf)
                enc = processor(
                    img,
                    return_tensors="pt",
                    truncation=True,
                    padding="max_length",
                    max_length=512,
                )
            except Exception as e:
                print(f"  ! skip {row['path']}: {e.__class__.__name__}: {e}")
                continue
            self.encodings.append({k: v.squeeze(0) for k, v in enc.items()})
            self.labels.append(label2id[row["doc_type"]])
            if (i + 1) % 100 == 0:
                print(f"  preprocessed {i + 1}/{n}")

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        item = dict(self.encodings[idx])
        item["labels"] = torch.tensor(self.labels[idx], dtype=torch.long)
        return item


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    acc = float((preds == labels).mean())
    return {"accuracy": acc}


def main():
    random.seed(SEED)
    torch.manual_seed(SEED)

    print(f"CUDA available: {torch.cuda.is_available()} "
          f"({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

    rows = load_manifest()
    doc_types = sorted({r["doc_type"] for r in rows})
    label2id = {t: i for i, t in enumerate(doc_types)}
    id2label = {i: t for t, i in label2id.items()}
    print(f"{len(rows)} docs across {len(doc_types)} classes")

    random.shuffle(rows)
    n_val = int(len(rows) * VAL_FRACTION)
    val_rows, train_rows = rows[:n_val], rows[n_val:]
    print(f"train={len(train_rows)} val={len(val_rows)}")

    processor = LayoutLMv3Processor.from_pretrained(MODEL_ID, apply_ocr=True)

    print("Preprocessing train set...")
    train_ds = LayoutDataset(train_rows, processor, label2id)
    print("Preprocessing val set...")
    val_ds = LayoutDataset(val_rows, processor, label2id)

    model = LayoutLMv3ForSequenceClassification.from_pretrained(
        MODEL_ID, num_labels=len(doc_types), label2id=label2id, id2label=id2label
    )

    args = TrainingArguments(
        output_dir=str(OUT_DIR / "checkpoints"),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        gradient_accumulation_steps=4,
        learning_rate=5e-5,
        warmup_ratio=0.1,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        fp16=torch.cuda.is_available(),
        logging_steps=20,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    metrics = trainer.evaluate()
    print(f"\nFinal validation accuracy: {metrics.get('eval_accuracy'):.4f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(OUT_DIR))
    processor.save_pretrained(str(OUT_DIR))
    (OUT_DIR / "label_map.json").write_text(json.dumps({"label2id": label2id, "id2label": id2label}))
    print(f"Saved fine-tuned model to {OUT_DIR}")


if __name__ == "__main__":
    main()
