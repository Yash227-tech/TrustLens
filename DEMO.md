# TrustLens — 5-Minute Demo Walkthrough

A reliable, repeatable live demo. All files are pre-staged in **`demo_data/`**.

## Before you start (1 min)

```powershell
cd d:\Canara_bank_hackathon\trustlens
docker compose start                 # if not already running
cd frontend ; npm run dev
```
Open **http://localhost:5173**.

⚠️ **Warm-up:** upload `demo_data/01_genuine_payslip.pdf` ONCE before judges arrive.
The first analysis loads the ML models + LLM into VRAM (~30–60s). Every analysis
after that is fast (a few seconds).

---

## The 30-second pitch (say this first)

> "Banks lose money to forged loan documents — edited PDFs, pasted signatures, fake
> stamps, fabricated income. Manual verification takes 3–7 days and misses
> sophisticated forgeries. TrustLens analyses every document in seconds, gives the
> underwriter a Trust Score with visual evidence and a plain-language report, and
> routes by risk — Green, Yellow, Red. It never auto-rejects; it makes the human
> faster and more confident. And it runs **100% on-premise** — no customer data
> ever leaves the bank."

---

## Demo 1 — Genuine document (≈45s)  →  Analyze tab

**Upload:** `demo_data/01_genuine_payslip.pdf`

Point at:
- **Trust Score 100 · GREEN · Fast-Track** badge.
- **Document type** chip: "Salary Slip / Payslip" — with "✓ LayoutLMv3 agrees"
  (dual classifier: keyword + fine-tuned transformer).
- **Signals tab** — all 7 forensic checks green.
- **Evidence tab** — the AI report written by the local Llama 3.1 model.

> "A clean, system-generated payslip. Every forensic check passes, both classifiers
> agree, and the on-device LLM explains why — fast-tracked."

---

## Demo 2 — The same payslip, edited in Word (≈75s)  →  Analyze tab

**Upload:** `demo_data/02_word_edited_payslip.pdf`
(This is file 01, opened in Microsoft Word, amount changed, re-saved.)

Point at:
- **Trust Score 0 · RED · Fraud Escalation.**
- **Critical Forgery Indicators** panel: *"Font: subset duplication (Word/office
  editor fingerprint)."*
- **Why (SHAP) tab** — bar chart: **PDF Metadata** pushes strongly toward fraud (red).
- **Heatmap tab** — PDF.js render with the forgery heatmap overlaid (toggle it).
- **Evidence tab** — LLM report naming the Word fingerprint.

> "Same payslip — but edited in Word. TrustLens catches it three independent ways:
> the PDF producer is now Microsoft Word, Word split the font into duplicate
> subsets — a tell-tale edit fingerprint — and the XGBoost scorer shows exactly
> which signal drove the decision. Auto-escalated to the fraud team."

---

## Demo 3 — Identity fraud caught by cross-source (≈45s)  →  Analyze tab

**Upload:** `demo_data/03_pan_name_mismatch.pdf`
(A PAN card with a **real** PAN number but the **wrong** name.)

Point at:
- **RED**, critical indicator: *"Cross-source: name mismatch vs authoritative record."*
- **Signals → Cross-Source Verification**: "DigiLocker says Rahul Verma."

> "Here the document uses a valid PAN — but TrustLens cross-checks it against
> DigiLocker's authoritative record and finds the name doesn't match. That's
> identity fraud a human reviewer would easily miss."

---

## Demo 4 — Cross-document consistency (≈75s)  →  Cases tab

1. Click **Cases** → **Create Case** (name: "Rahul Verma").
2. **Add document** → `demo_data/04_case_pan_rahul.pdf`
3. **Add document** → `demo_data/05_case_itr_rahul_same.pdf`
   - Watch the **Cross-Document Consistency** panel: **Consistent**, PAN + name
     match across both documents.
4. **Add document** → `demo_data/06_case_pan_suresh_conflict.pdf`
   - Panel flips to **Critical**: *"Conflicting PAN values across documents"* +
     *"Multiple distinct applicant names."*

> "A real loan application is a bundle of documents. TrustLens groups them as a
> case and checks the applicant's identity is consistent across all of them — using
> phonetic + fuzzy matching for Indian names. The moment a document with a
> different identity is added, it flags a critical inconsistency."

---

## Demo 5 — Audit trail (≈30s)  →  Audit tab

Click **Audit**.

> "Every decision is written to an append-only audit log — timestamp, document,
> score, tier, critical flags — immutable, for RBI compliance. Nothing is ever
> edited or deleted."

---

## If asked about accuracy / models (optional)

- **LayoutLMv3** (doc classification) fine-tuned on RTX 4060 — 100% val (synthetic).
- **YOLOv8** (stamp detection) — mAP50 0.995.
- **XGBoost** (Trust Score) — 84% acc / 0.94 ROC-AUC on a **real + synthetic** mix
  (CASIA 2.0 real tampering). SHAP gives per-document explainability.
- **ManTraNet** — pretrained copy-move/splicing CNN from the original paper.
- Be honest: synthetic-only metrics are optimistic; the XGBoost mixed-data figure
  is the representative one, and real documents already score correctly (Demos 1–2).

## If asked "why local LLM / on-premise?"

> "Customer financial data never leaves the bank — DPDP-Act and RBI friendly by
> design. No third-party API, no data egress. A cloud LLM is a drop-in option for
> banks that want it."

## Bonus fixture
`demo_data/07_reused_stamp.jpg` — a doc where the **same stamp is pasted twice**;
Stamp Authentication (YOLOv8 + SIFT) flags the reuse. Good for a forensics deep-dive.

---

## Recovery (if something hiccups live)
- LLM slow / report shows "template": the model is still loading — the rest of the
  analysis is unaffected; mention it falls back to a deterministic report.
- A service down: `docker compose start` brings everything back.
- Always have Demo 1 pre-warmed so the first on-stage upload is fast.
