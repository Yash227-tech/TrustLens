# TrustLens — Machine-to-Machine Transfer Guide

This bundle reproduces the **entire TrustLens environment** on another machine:
same Docker images (Python / CUDA / dependencies), same config, **and every model
we trained** — so the recipient does **no rebuild, no re-download, and no retraining**.
They just start it.

> ### Why a "Docker image" alone is not enough
> The trained models are **not baked into the images**. In `docker-compose.yml` the
> `data/` and `ml/` folders are *bind-mounted* into the containers at runtime
> (see the `volumes:` sections). So `docker save` of an image carries the code and
> dependencies but **zero trained weights**. This bundle therefore ships four things
> together:
>
> | Piece | Contents | Approx size |
> |-------|----------|-------------|
> | `images/trustlens-images.tar` | All Docker images (backend, worker, ner, gov-mock + postgres/redis/minio/ollama/alpine) | ~18 GB |
> | `trustlens-project-runtime.tar.gz` | Source code, `docker-compose.yml`, **live inference models** (`layoutlmv3-trustlens`, `yolov8-aadhaar/pan/stamps/signatures`, `xgb_risk`) and `ml/*.pt` | ~2.4 GB |
> | `volumes/trustlens_ollama_models.tar` | The `llama3.1:8b` LLM | ~4.9 GB |
> | `volumes/trustlens_hf_cache.tar` | HuggingFace base weights (LayoutLMv3, sentence-transformers, …) | ~0.6 GB |
>
> `manifest.json` lists exactly what was included.

---

## Requirements on the receiving machine

- **Docker Desktop** (or Docker Engine) with the **Compose v2** plugin (`docker compose ...`).
- **NVIDIA GPU + NVIDIA Container Toolkit.** The `worker`, `backend`, and `ollama`
  services request a GPU (`deploy.resources.reservations.devices` in `docker-compose.yml`).
  On a machine with no NVIDIA GPU, `docker compose up` fails on the device reservation.
  To run **CPU-only** (much slower; OCR/LLM heavy steps will crawl), delete the three
  `deploy:` blocks from `docker-compose.yml` before starting.
- `tar.exe` on PATH (ships with Windows 10/11 and Git for Windows).
- Free disk: **~60 GB** (bundle on disk + loaded images + restored volumes).

---

## Sender — create the bundle

From the repo root (`trustlens/`):

```powershell
# Full self-contained bundle (default): images + live models + ollama + hf_cache
.\scripts\export-transfer-bundle.ps1
```

Output goes to `dist\trustlens-transfer-<timestamp>\`. Send that **entire folder**
(external SSD recommended — it is ~26 GB).

### Slimmer variants (for transfer over the internet)

| Flag | Effect | Recipient must then… |
|------|--------|----------------------|
| `-SkipImages` | Omit the ~18 GB image tar | run `docker compose build` (needs internet, ~10–20 min) |
| `-SkipRuntimeVolumes` | Omit ollama + hf_cache (~5.5 GB) | let them re-download on first run (needs internet) — see "Re-pull" below |
| `-NoBuild` | Skip the `docker compose build` step before saving (use existing images) | — |
| `-FullData` | Include the **whole** `data/` folder (all backups, training runs, datasets) | — (bundle becomes ~15 GB+ larger) |
| `-IncludeStateVolumes` | Also export postgres / redis / minio data (prior runs' DB + uploaded docs) | — |

Smallest "they rebuild + re-pull" bundle (~2.4 GB, needs internet on the far side):

```powershell
.\scripts\export-transfer-bundle.ps1 -SkipImages -SkipRuntimeVolumes
```

> **Note:** the default bundle tars the *live* `data/models/layoutlmv3-trustlens`
> folder, which still contains its `checkpoints/` subfolder (~1.5 GB) used only for
> *resuming training*. Inference does not need it. To drop it and save ~1.5 GB, add
> `--exclude=data/models/layoutlmv3-trustlens/checkpoints` to the `tar.exe` arguments
> in `export-transfer-bundle.ps1`.

---

## Recipient — import and run

Open PowerShell **inside the received bundle folder**, then:

```powershell
.\import-transfer-bundle.ps1 -BundleDir . -ProjectDir C:\trustlens -Start
```

This:
1. `docker image load` — restores all images (no rebuild).
2. Extracts source + models to `C:\trustlens`.
3. Restores the `ollama_models` and `hf_cache` volumes.
4. `docker compose up -d`.

Then open:
- **API / app:** http://localhost:8000
- MinIO console: http://localhost:9001 (`trustlens` / `trustlens_dev`)

Import **without** auto-start (inspect first, then start manually):

```powershell
.\import-transfer-bundle.ps1 -BundleDir . -ProjectDir C:\trustlens
cd C:\trustlens
docker compose up -d
```

Flags: `-SkipImages` (you built locally), `-SkipVolumes` (you will re-pull).

---

## If the bundle skipped the volumes (re-pull on the recipient)

```powershell
# LLM
docker exec -it trustlens-ollama ollama pull llama3.1:8b
```
The HuggingFace base weights download automatically into `hf_cache` the first time
the `backend`/`ner` services run inference (needs internet).

---

## Verify it works

```powershell
docker compose ps                 # all services Up / healthy
docker compose logs -f backend    # watch startup
```

The trained models live (inside the containers) at:
- `/data/models/layoutlmv3-trustlens` — document classifier (LayoutLMv3)
- `/data/models/yolov8-aadhaar|pan|stamps|signatures/best.pt` — field/stamp detectors
- `/data/models/xgb_risk/model.json` — risk scorer (XGBoost)

If the API answers on `:8000` and a test document scores end-to-end, the transfer is complete.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `could not select device driver "nvidia"` | No GPU / NVIDIA Container Toolkit. Install it, or remove the `deploy:` blocks for CPU-only. |
| Backend logs `model path not found` | Project archive didn't include `data/models/...`. Re-export without `-Skip... ` clobbering models, or copy the model folders into `C:\trustlens\data\models\`. |
| Ollama errors `model 'llama3.1:8b' not found` | Volume not shipped — run the `ollama pull` above. |
| First inference is very slow | HF weights downloading into `hf_cache`. One-time. |
| Ports already in use | Another service on 8000/5432/6379/9000/11434. Stop it or remap ports in `docker-compose.yml`. |
