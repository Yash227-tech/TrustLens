"""End-to-end audit: every original real document the user provided + a random
held-out sample of the ID-card / bank-statement datasets, through the full
pipeline. Reports doc_type / tier / score / critical / review."""
import json
import random
from pathlib import Path
from collections import Counter
from app.services.analysis import run_full_analysis

PDF = "application/pdf"
EXT = Path("/data/raw/external")
random.seed(7)

def ctype_for(path: str) -> str:
    p = path.lower()
    if p.endswith(".pdf"): return PDF
    if p.endswith(".png"): return "image/png"
    return "image/jpeg"

# original one-off documents (folders)
GROUPS = [
    ("MOA",         [(p, PDF) for p in sorted((EXT/"MOA").glob("*.pdf"))],            "moa_aoa"),
    ("PARTNERSHIP", [(p, PDF) for p in sorted((EXT/"Partnership").glob("*.pdf"))],    "partnership_deed"),
    ("FORM",        [(p, PDF) for p in sorted((EXT/"Form").glob("*.pdf"))],           None),
    ("BANK(pdf)",   [(p, PDF) for p in sorted((EXT/"Bankstatments").glob("*.pdf"))],  "bank_statement"),
    ("BOARDRES",    [(p, PDF) for p in sorted((EXT/"boardresolution").glob("*.pdf"))],"board_resolution"),
    ("PASSPORT(orig)", [(p, "image/png") for p in sorted((EXT/"passport").glob("*.png"))], "passport"),
]
# random held-out samples from the datasets (NOT trained on)
for name, man, exp in [("AADHAAR(sample)","aadhaar_eval.jsonl","aadhaar"),
                       ("PAN(sample)","pan_eval.jsonl","pan"),
                       ("PASSPORT(sample)","passport_eval.jsonl","passport"),
                       ("BANK(sample)","bankstmt_eval.jsonl","bank_statement")]:
    rows = [json.loads(l) for l in (EXT/man).read_text().splitlines() if l.strip()]
    pick = random.sample(rows, min(15, len(rows)))
    GROUPS.append((name, [(Path("/data")/r["path"], ctype_for(r["path"])) for r in pick], exp))

overall = Counter(); red_docs = []; mis_docs = []; total = 0
for label, items, expected in GROUPS:
    tiers = Counter(); correct = 0
    print(f"\n===== {label} ({len(items)} docs) =====", flush=True)
    for p, ctype in items:
        try:
            r = run_full_analysis(p.read_bytes(), ctype, p.name)
            dt, tier, sc = r["document_type"], r["risk_tier"], r["trust_score"]
            tiers[tier] += 1; overall[tier] += 1; total += 1
            if expected and dt == expected: correct += 1
            if tier == "RED": red_docs.append((label, p.name, r["critical_indicators"]))
            if expected and dt != expected: mis_docs.append((label, p.name, dt))
            mark = "" if (expected is None or dt == expected) else " <-MIS"
            extra = (r["critical_indicators"] or r.get("review_indicators") or [])
            print(f"  {p.name[:36]:36s} | {dt:16s} | {tier:6s} {sc:3d} | {extra}{mark}", flush=True)
        except Exception as e:
            print(f"  {p.name[:36]:36s} | ERROR {e.__class__.__name__}", flush=True)
    cstr = f"{correct}/{len(items)} correct-type, " if expected else ""
    print(f"  -> {cstr}tiers={dict(tiers)}", flush=True)

print("\n" + "="*60, flush=True)
print(f"TOTAL: {total} docs | tiers={dict(overall)}", flush=True)
print(f"RED ({len(red_docs)}):", flush=True)
for lbl,f,c in red_docs: print(f"   [{lbl}] {f[:40]} {c}", flush=True)
print(f"MISCLASSIFIED ({len(mis_docs)}):", flush=True)
for lbl,f,d in mis_docs: print(f"   [{lbl}] {f[:40]} -> {d}", flush=True)
