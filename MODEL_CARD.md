# TrustLens — Model Card (Final Version)

AI-assisted document-fraud detection for bank loan underwriting. Runs **100%
on-premise** (no customer data egress). Human-in-the-loop: the system scores and
routes; it **never auto-rejects**.

_Last updated: 2026-06-30. Metrics are reproducible via `data/benchmark.py` and the
`ml/training/` scripts._

---

## 1. Model inventory & metrics

| Model | Role | Final metric |
|---|---|---|
| **LayoutLMv3** (fine-tuned) | Document classification — **26 types** | **99.3%** val · **97.9%** on real held-out (240 typed docs) |
| **XGBoost** + SHAP | Trust Score (0–100) from 7 forensic features | **88.4%** acc · **0.95** ROC-AUC · **91.6%** tamper-recall · 85.4% clean-recall |
| **ManTraNet** (pretrained) | Copy-move / splice localisation | Pixel-AUC **0.76–0.88** on the masked Indian-doc tamper set |
| **Photo-region forensics** | Single-doc ID photo-swap (ManTraNet ∩ YOLO photo box) | **96% recall · 0% false-positive** (110-image swap set) |
| **Face-match** (FaceNet / MTCNN, VGGFace2) | Cross-document face consistency | 96% genuine match · 78% impostor caught |
| **YOLOv8 — stamps** | Stamp/seal detection (+ SIFT reuse) | mAP50 **0.995** |
| **YOLOv8 — Aadhaar** | 6-field detector | mAP **0.93** |
| **YOLOv8 — PAN / signatures / utility** | Field/region detectors | strong on primary fields |
| **spaCy `en_core_web_trf`** (NER microservice) | Person / org / location | stock model (isolated container) |
| **Regex + Verhoeff** | PAN, Aadhaar (UIDAI checksum), GSTIN, IFSC, Udyam, ITR-ack, passport-MRZ | deterministic, 100% precise on format |
| **Sentence-Transformers + fuzzy/phonetic** | Cross-document name matching | Indian-name aware (token-sort + metaphone) |
| **Llama 3.1 8B** (Ollama, local) | Plain-language evidence report | on-device, template fallback |

## 2. System-level benchmark (`data/benchmark.py`)

332-doc labelled manifest, two tracks (document pipeline vs image-forensic), genuine +
4 fraud vectors. Reproducible, re-run with `--tag` to diff any change.

- **Fraud hard-catch: 98.6%** (document track; only 1 of 73 missed)
- **Classification: 97.9%** (240 typed real + synthetic docs)
- **Per-fraud-vector recall**: synthetic metadata-tamper 100% · CASIA splice 73/90% (hard/flagged) · ID photo-swap 96% (photo-forensics) · payslip copy-paste — known gap
- **Genuine false-reject**: real born-digital PDFs fire the pixel-forensic critical **0/24**; the headline synthetic FP was a render artifact, and the latest fixes (below) drive real-document false-rejects to ~0.
- **No-regression re-run (v2, post-fixes)**: classification held at 97.9%, fraud-flagged recall held at 98.6%, synthetic metadata-tamper hard-catch held at 100%, genuine hard-FP improved 26.4%→22.3% (residual = the synthetic-render artifact). The XGBoost model is unchanged from the validated baseline.

## 3. Forensic detection suite (the 7 Trust-Score signals + criticals)

PDF metadata · Font & spacing (Word-edit fingerprint) · Signature-region ELA ·
Stamp authentication (YOLO + SIFT reuse) · Bank-statement running-balance ·
Error-Level Analysis · ManTraNet copy-move/splice. Plus tier-level **critical
indicators**: cross-source mismatch, fabricated-Aadhaar (Verhoeff), photo-region
manipulation, stamp reuse, DOCX last-editor.

## 4. Identity & cross-document verification

- **Cross-source (mock gov APIs)**: DigiLocker (PAN/Aadhaar), GSTN, Account
  Aggregator, Income-Tax e-Filing, **Udyam** registry — authoritative name match.
- **Case consistency**: same applicant across all docs (PAN/name/face); conflicting
  hard-ID → RED, name/face mismatch → YELLOW review.
- **Udyam QR authentication**: decodes the certificate QR and cross-checks the URN.

## 5. Risk tiers (bank-safe calibration)

**GREEN** (trust ≥85, no critical) fast-track · **YELLOW** (review — never auto-reject) ·
**RED** (trust <50 or a critical forgery indicator → fraud escalation). Calibration
favours false positives over false negatives; uncertain → human review.

## 6. Document coverage (26 types)

Identity: Aadhaar, PAN, Passport · Financial: bank statement, ITR (full/V), Form-16,
balance sheet, P&L, cash-flow, audited financials, salary slip · Tax: GSTR-1, GSTR-3B ·
Corporate/Legal: MOA/AOA, partnership deed, board resolution, power of attorney,
sanction letter, guarantee letter, indemnity bond, NOC, loan agreement,
**rental/lease agreement** · KYC/MSME: **Udyam certificate**, **utility bill**.

## 7. Explainability, security & compliance

- **Explainable**: SHAP per-feature attribution, visual heatmaps (ELA/ManTraNet),
  plain-language LLM report, dual-classifier agreement, classifier-disagreement note.
- **On-premise**: no third-party API, no data egress — DPDP-Act / RBI friendly.
- **Security**: OAuth2 + JWT, role-based access on sensitive actions.
- **Audit**: append-only audit log (immutable) — every decision, for RBI compliance.

## 8. Continuous improvement (active-learning flywheel)

Underwriter's confirmed genuine/fraud verdict (`POST /api/audit/{id}/label`,
RBAC-protected) → `analyst_labels` → `ml/training/collect_labeled.py` rebuilds a
**real-world** training manifest from production traffic. The model improves from
the documents the bank actually sees.

## 9. Stack

FastAPI · Celery · PostgreSQL · Redis · MinIO · Ollama · spaCy NER microservice ·
gov-mock · React/Vite frontend — Docker Compose, GPU (RTX 4060), fully offline-capable.

## 10. Honest limitations

- Synthetic-only metrics are optimistic; **real + benchmark** figures are representative.
- Payslip copy-paste (text-cell editing) recall is the current weak spot (localised
  text forensic is the planned fix).
- FaceNet/VGGFace2 weights are research/non-commercial — swap for a licensed face
  model in production.
- Cross-source uses **mock** government APIs (the integration pattern; real APIs are
  a drop-in).
