"""Train a YOLOv8 stamp detector (spec §5 #6, Step 15).

Fine-tunes yolov8n on the synthetic stamp dataset at /data/yolo_stamps and
saves the best weights to /data/models/yolov8-stamps/best.pt.

Run inside the backend container (GPU passthrough configured):
    docker exec trustlens-backend sh -c "cd /ml && python -m training.train_yolov8_stamps"

When real Roboflow stamps are added to /data/raw/external/stamps and the YOLO
dataset is regenerated, just rerun this script (optionally swap yolov8n.pt for
a larger variant).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import torch
from ultralytics import YOLO

DATA_YAML = "/data/yolo_stamps/data.yaml"
BASE_MODEL = "yolov8n.pt"
OUT_DIR = Path("/data/models/yolov8-stamps")
EPOCHS = 100
IMGSZ = 640
BATCH = 16
PROJECT = "/data/models/yolo_runs"
RUN_NAME = "stamps"


def main():
    device = 0 if torch.cuda.is_available() else "cpu"
    print(f"Device: {device} "
          f"({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

    model = YOLO(BASE_MODEL)
    model.train(
        data=DATA_YAML,
        epochs=EPOCHS,
        imgsz=IMGSZ,
        batch=BATCH,
        device=device,
        project=PROJECT,
        name=RUN_NAME,
        exist_ok=True,
        patience=20,          # early-stop if no val improvement for 20 epochs
        workers=4,            # cap DataLoader workers (shm-bounded)
        verbose=True,
        plots=True,
    )

    metrics = model.val()
    print(f"\nmAP50:    {metrics.box.map50:.4f}")
    print(f"mAP50-95: {metrics.box.map:.4f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    best = Path(PROJECT) / RUN_NAME / "weights" / "best.pt"
    if best.exists():
        shutil.copy(best, OUT_DIR / "best.pt")
        print(f"Saved best weights to {OUT_DIR / 'best.pt'}")
    else:
        print(f"WARNING: best.pt not found at {best}")


if __name__ == "__main__":
    main()
