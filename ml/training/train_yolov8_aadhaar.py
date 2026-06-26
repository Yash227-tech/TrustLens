"""Train the 6-field Aadhaar detector (photo/qr/number/name/dob/gender).

Mirror of train_yolov8_stamps.py / train_yolov8_signatures.py — same ultralytics
YOLOv8n pipeline (proven in our stack). Trains on the hybrid dataset
(build_aadhaar_hybrid_dataset.py) and saves best weights to
/data/models/yolov8-aadhaar/best.pt for the Aadhaar field-forensics module.

Run: docker exec trustlens-backend sh -c "cd /ml && python -m training.train_yolov8_aadhaar"
"""

from __future__ import annotations

import shutil
from pathlib import Path

import torch
from ultralytics import YOLO

DATA_YAML = "/data/yolo_aadhaar/data.yaml"
BASE_MODEL = "yolov8n.pt"
OUT_DIR = Path("/data/models/yolov8-aadhaar")
EPOCHS = 80
IMGSZ = 640
BATCH = 16
PROJECT = "/data/models/yolo_runs"
RUN_NAME = "aadhaar"


def main():
    device = 0 if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    model = YOLO(BASE_MODEL)
    model.train(
        data=DATA_YAML, epochs=EPOCHS, imgsz=IMGSZ, batch=BATCH, device=device,
        project=PROJECT, name=RUN_NAME, exist_ok=True, patience=20, workers=4,
        verbose=True, plots=True,
    )
    metrics = model.val()
    print(f"\nmAP50:    {metrics.box.map50:.4f}")
    print(f"mAP50-95: {metrics.box.map:.4f}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    best = Path(PROJECT) / RUN_NAME / "weights" / "best.pt"
    if best.exists():
        shutil.copy(best, OUT_DIR / "best.pt")
        print(f"Saved best weights to {OUT_DIR / 'best.pt'}")


if __name__ == "__main__":
    main()
