# TrustLens — AI-Assisted Underwriting Intelligence Platform

Real-time document integrity & decision support for banks. TrustLens ingests every
legal and financial document submitted during loan underwriting, runs multi-layered
forensic + AI analysis, and returns a **Trust Score (0–100)**, a **visual anomaly
heatmap**, an **explainable evidence report**, and **risk-tiered routing
(Green / Yellow / Red)** — all within seconds, fully on-premise.

> **Human-in-the-loop by design.** TrustLens never auto-approves or auto-rejects a
> loan. It surfaces evidence and prioritises attention; the underwriter makes the
> final call. This is essential for legal defensibility, RBI compliance, and bank
> adoption.

---

## 1. What it does (pipeline)

```
Upload (PDF / DOCX / image)
  → OCR + Auto-Classification (Tesseract 5 [en+hi+gu] + keyword + fine-tuned LayoutLMv3, 26 types)
  → Forensic Engine
        • PDF metadata analysis        • Font & spacing forensics
        • Error Level Analysis (ELA)   • Signature-region analysis (ELA)
        • Copy-move/splicing (ManTraNet CNN)
        • Stamp authentication (YOLOv8 + SIFT/ORB + edge-sharpness)
        • Photo-region tamper (ManTraNet ∩ ID photo box)  • Udyam QR authentication
  → Financial Analyzer (bank-statement rules, Pandas)
  → Cross-Source Verification (mock DigiLocker / AA / GSTN / IT e-Filing / Udyam)
  → NLP entity extraction (regex IDs + Verhoeff + en_core_web_trf NER microservice)
  → Risk Scoring (XGBoost + SHAP explainability)
  → LLM Evidence Report (LangChain + local Llama 3.1 8B, strict grounding)
  → Risk-Tiered Routing (Green / Yellow / Red)
  → Append-only Audit Log (PostgreSQL, RBI compliance)
```

Multi-document **cases** additionally run **cross-document consistency**: the same
applicant's PAN / name / GSTIN / account is matched across every document
(phonetic + fuzzy matching for Indian names), plus **cross-document face-match**
(FaceNet) to catch a mixed-identity or swapped ID photo.

A reproducible **evaluation benchmark** (`data/benchmark.py`) and an
**active-learning flywheel** (analyst genuine/fraud labels → `ml/training/collect_labeled.py`
→ retraining) round out the system. See **`MODEL_CARD.md`** for full metrics.

---

## 2. Architecture (services)

| Container | Role |
|---|---|
| `backend` | FastAPI API — upload, jobs, cases, audit; orchestrates analysis |
| `worker` | Celery worker — runs the full GPU analysis pipeline per document |
| `redis` | Celery broker + result backend |
| `postgres` | Cases, case-documents, append-only audit log |
| `minio` | S3-compatible object storage |
| `ner` | Isolated spaCy `en_core_web_trf` NER microservice |
| `gov-mock` | Mock DigiLocker / AA / GSTN / IT e-Filing verification APIs |
| `ollama` | Local LLM runtime (Llama 3.1 8B) for evidence reports |

Backend + worker share one image (`trustlens-backend`) and run on the GPU.

---

## 3. Technology stack (spec §8) — status

**Backend:** Python 3.11 ✅ · FastAPI ✅ · Celery + Redis ✅ · PostgreSQL ✅ · MinIO/S3 ✅
**AI/ML:** PyTorch ✅ · OpenCV ✅ · Tesseract 5 ✅ · LayoutLMv3 ✅ (fine-tuned) ·
ManTraNet ✅ · YOLOv8 ✅ · spaCy ✅ · Sentence-Transformers ✅ (installed) · XGBoost ✅ · Pandas ✅
**LLM:** LangChain ✅ + local Llama 3.1 8B via Ollama (approved alternative to cloud Claude/GPT-4) with prompt-grounding guardrails ✅
**Frontend:** React 18 ✅ · TypeScript ✅ · Tailwind ✅ · shadcn/ui ✅ · PDF.js (heatmap overlay) ✅ · Recharts ✅
**Integrations:** DigiLocker / AA (Finvu/OneMoney) / GSTN / IT e-Filing ✅ (mocked per spec §9)

### Trained models (on RTX 4060)

| Model | Task | Result |
|---|---|---|
| LayoutLMv3 (fine-tuned) | **26-class** doc classification | **99.3% val · 97.9% real held-out** |
| XGBoost + SHAP | Trust Score from 7 forensic features | **88% acc · 0.95 ROC-AUC · 91.6% tamper-recall** (real CASIA + payslip + synthetic) |
| YOLOv8 ×5 | stamp / Aadhaar / PAN / signature / utility detection | stamps mAP50 **0.995**, Aadhaar mAP **0.93** |
| ManTraNet | copy-move/splicing localisation | pretrained (Wu et al., CVPR 2019); pixel-AUC 0.76–0.88 on Indian-doc tamper set |
| Photo-region forensics | single-doc ID photo-swap | **96% recall · 0% false-positive** |
| FaceNet / MTCNN | cross-document face match | 96% genuine match · 78% impostor caught |

Full benchmark (332 docs, 4 fraud vectors): **98.6% fraud hard-catch**. See `MODEL_CARD.md`.

---

## 4. Document scope (spec §4) — 26 types

**Legal (13):** loan agreement, sanction letter, NOC, board resolution, partnership
deed, MOA/AOA, power of attorney, indemnity bond, guarantee letter, **rental/lease
agreement**, Aadhaar, PAN, passport.

**Financial (11):** bank statement, salary slip, Form 16, ITR-V, full ITR, GSTR-1,
GSTR-3B, balance sheet, profit & loss, audited financials, cash flow statement.

**KYC / MSME (2):** **Udyam (MSME) certificate** (with QR authentication), **utility bill** (water / gas / electricity).

---

## 5. Risk-tiered routing (spec §7)

| Tier | Condition | Routing |
|---|---|---|
| 🟢 GREEN | Trust ≥ 85, no critical indicators | Fast-track |
| 🟡 YELLOW | Trust 50–84 or partial verification failures | Underwriter review |
| 🔴 RED | Trust < 50 **OR** any critical forgery indicator | Fraud escalation |

**Critical indicators** force RED regardless of score (spec §7): suspicious-tool /
office-editor producer, font subset duplication, ManTraNet strong forgery, stamp
reuse, bank running-balance break, cross-source name mismatch, **photo-region
manipulation**, and a **fabricated Aadhaar** (fails the UIDAI Verhoeff checksum).

---

## 6. Running it

Prerequisites: Docker Desktop (with GPU support), Node.js, an NVIDIA GPU, and
[Git LFS](https://git-lfs.com) — the trained model weights are stored via LFS.

### Clone (with model weights)
```bash
git lfs install
git clone https://github.com/Yash227-tech/TrustLens.git
cd TrustLens
git lfs pull   # downloads the LayoutLMv3 / YOLOv8 / ManTraNet weights (~1 GB)
```

> **No NVIDIA GPU?** Remove the three `deploy:` blocks (under `ollama`, `worker`,
> and `backend`) in `docker-compose.yml` — the code auto-falls back to CPU (slower,
> same results).

### First-time / full build
```powershell
# from the repo root
docker compose up -d --build
# one-time: pull the local LLM (~4.7 GB)
docker exec trustlens-ollama ollama pull llama3.1:8b
```

### Frontend
```powershell
cd frontend
npm install
npm run dev    # http://localhost:5173
```

### Resume after a stop
```powershell
# from the repo root
docker compose start
cd frontend; npm run dev
```

### Stop (preserves data, models, images)
```powershell
docker compose stop
```

### Ports
| Service | Port |
|---|---|
| Frontend | 5173 |
| Backend API | 8000 |
| NER microservice | 8500 |
| Gov-mock APIs | 8600 |
| Ollama | 11434 |
| Postgres / Redis / MinIO | 5432 / 6379 / 9000-9001 |
