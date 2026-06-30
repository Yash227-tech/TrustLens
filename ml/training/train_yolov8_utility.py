"""Train a 4-field utility-bill detector (Date / KNO / Name / address).

Mirror of train_yolov8_aadhaar.py — same ultralytics YOLOv8n pipeline. Trains on
the real Delhi Jal Board water-bill set (raw/external/water_bill, Roboflow YOLO
format) and saves best weights to /data/models/yolov8-utility/best.pt for the
utility-bill field-extraction module (name + address for address-proof and
cross-document consistency).

Trains on the COMBINED set (data_combined.yaml): real DJB water bills + synthetic
auto-annotated electricity/water/gas bills (ml/data_generators.build_utility_detector_set),
so the detector generalises across providers instead of DJB-water only. To train
on real water alone again, point DATA_YAML back at data_train.yaml.

Run: docker exec trustlens-backend sh -c "cd /ml && python -m training.train_yolov8_utility"
"""

from __future__ import annotations

import shutil
from pathlib import Path

import torch
from ultralytics import YOLO

DATA_YAML = "/data/raw/external/water_bill/data_combined.yaml"  # real DJB water + synthetic 3-type
BASE_MODEL = "yolov8n.pt"
OUT_DIR = Path("/data/models/yolov8-utility")
EPOCHS = 80
IMGSZ = 640
BATCH = 16
PROJECT = "/data/models/yolo_runs"
RUN_NAME = "utility"


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
