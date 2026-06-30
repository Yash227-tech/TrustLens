"""System-level evaluation benchmark (improvement #1).

Runs the FULL single-document pipeline (app.services.analysis.run_full_analysis)
over a labelled manifest of genuine + fraudulent documents and reports the
metrics a bank actually cares about:

  * Fraud recall  — hard-catch (-> RED) and flagged (-> RED or YELLOW=review).
  * Genuine handling — clean-pass (-> GREEN), soft-review (-> YELLOW, bank-safe),
    hard false-positive (-> RED, the costly error we must keep ~0).
  * RED precision / FPR, and ROC-AUC on the trust score.
  * Per-doc-type classification confusion.
  * Per-fraud-vector recall (synthetic metadata tamper, CASIA splice, payslip
    copy-paste, ID photo swap).

TWO tracks, scored separately (genuine specificity is only meaningful on real
documents — CASIA/payslip are generic spliced images, not bank docs):
  * "document"       — real IDs / bank stmts / MOA / partnership / synthetic
                       docs / ID photo-swaps. Drives tier + classification.
  * "image_forensic" — CASIA Au/Tp + payslip genuine/forged. Drives the raw
                       tamper-detector discrimination (AUC / flag rate).

This is the baseline that every later change (#3 XGBoost retrain, #4 forgery
work) is measured against — re-run with a new --tag and it diffs vs baseline.

Run inside the backend container (PowerShell, to avoid Git-Bash path mangling):
    docker exec -e PYTHONUNBUFFERED=1 trustlens-backend `
        sh -c "cd /data && python benchmark.py --tag baseline"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/app")  # make app.* importable (mirrors build_feature_dataset)

from app.services.analysis import run_full_analysis  # noqa: E402

PDF = "application/pdf"
DATA = Path("/data")
EXT = DATA / "raw" / "external"
OUT_DIR = DATA / "benchmark"
SEED = 42

# Per-source caps keep a full run to a few hundred docs (minutes on GPU) while
# staying balanced and multi-vector. Bump for a fuller sweep.
CAP_EVAL = 20          # per real held-out eval manifest
CAP_SYN_CLEAN = 2      # per synthetic doc type
CAP_SYN_TAMP = 3       # per synthetic-tampered doc type
CAP_CASIA = 40         # per CASIA class (Au / Tp)
CAP_PAYSLIP = 20       # per payslip class (cap; there are only ~12 forged)


def ctype_for(path: str | Path) -> str:
    p = str(path).lower()
    if p.endswith(".pdf"):
        return PDF
    if p.endswith(".png"):
        return "image/png"
    return "image/jpeg"  # jpg / tif / bmp -> PIL-decodable as jpeg


def _eval_rows(name: str) -> list[dict]:
    f = EXT / f"{name}_eval.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def build_manifest() -> list[dict]:
    """Each item: {path, ctype, label, vector, expected, track, source}."""
    rng = random.Random(SEED)
    items: list[dict] = []

    def add(path, label, vector, expected, track, source):
        items.append({"path": Path(path), "ctype": ctype_for(path), "label": label,
                      "vector": vector, "expected": expected, "track": track,
                      "source": source})

    # ---------- GENUINE — document track ----------
    # Real, held-out eval manifests (NOT trained on).
    for name, dt in [("aadhaar", "aadhaar"), ("pan", "pan"), ("passport", "passport"),
                     ("bankstmt", "bank_statement"), ("utility", "utility_bill")]:
        rows = [r for r in _eval_rows(name) if r.get("label") == "clean"]
        for r in rng.sample(rows, min(CAP_EVAL, len(rows))):
            add(DATA / r["path"], "genuine", "genuine", dt, "document", f"real_{name}")

    # Real scanned legal/corporate PDFs.
    for p in sorted((EXT / "MOA").glob("*.pdf")):
        add(p, "genuine", "genuine", "moa_aoa", "document", "real_moa")
    for p in sorted((EXT / "Partnership").glob("*.pdf")):
        add(p, "genuine", "genuine", "partnership_deed", "document", "real_partnership")

    # Real BORN-DIGITAL genuine PDFs (financials / annual reports). Critical for an
    # honest genuine-FP rate: the synthetic-clean PDFs trip ManTraNet's whole-image
    # critical (their renders are unnaturally crisp), but REAL born-digital PDFs do
    # NOT (probed 0/24). expected=None — they classify across financial sub-types,
    # so they feed the tier/FP metric, not the per-type confusion.
    for tag, sub in [("real_financials", "real_docs"), ("real_annual_report", "annual_report")]:
        pdfs = sorted((EXT / sub).rglob("*.pdf"))
        for p in rng.sample(pdfs, min(15, len(pdfs))):
            add(p, "genuine", "genuine", None, "document", tag)

    # Synthetic clean — a couple per type (covers rental_agreement / udyam too).
    syn = DATA / "synthetic"
    if syn.exists():
        for d in sorted(syn.iterdir()):
            if not d.is_dir():
                continue
            pdfs = sorted(d.glob("*.pdf"))
            for p in rng.sample(pdfs, min(CAP_SYN_CLEAN, len(pdfs))):
                add(p, "genuine", "genuine", d.name, "document", "syn_clean")

    # Genuine ID photo (original side of the swap pairs).
    for p in sorted((DATA / "photo_swap_samples").glob("*_1_original.png")):
        add(p, "genuine", "genuine", "aadhaar", "document", "photo_swap_orig")

    # ---------- FRAUD — document track ----------
    syn_t = DATA / "synthetic_tampered"
    if syn_t.exists():
        for d in sorted(syn_t.iterdir()):
            if not d.is_dir():
                continue
            pdfs = sorted(d.glob("*.pdf"))
            for p in rng.sample(pdfs, min(CAP_SYN_TAMP, len(pdfs))):
                add(p, "fraud", "synthetic_metadata_tamper", d.name, "document", "syn_tamp")

    # Digitally swapped ID photo (single-document photo manipulation).
    for p in sorted((DATA / "photo_swap_samples").glob("*_2_swapped.png")):
        add(p, "fraud", "photo_swap", "aadhaar", "document", "photo_swap")

    # ---------- image_forensic track (CASIA + payslip) ----------
    casia = EXT / "casia2" / "CASIA2"
    for sub, label, vector in [("Au", "genuine", "genuine"), ("Tp", "fraud", "casia_splice")]:
        folder = casia / sub
        if folder.exists():
            files = [f for f in folder.iterdir()
                     if f.suffix.lower() in (".jpg", ".png", ".tif", ".bmp")]
            for p in rng.sample(files, min(CAP_CASIA, len(files))):
                add(p, label, vector, None, "image_forensic", f"casia_{sub.lower()}")

    payslip = EXT / "payslip_forgery" / "sample_dataset"
    if payslip.exists():
        genuine = [p for p in (payslip / "Genuine").rglob("*.tif") if "__MACOSX" not in str(p)]
        forged = [p for p in payslip.rglob("*.tif")
                  if "__MACOSX" not in str(p) and ("CopyPaste" in str(p) or "Imitation" in str(p))]
        for p in rng.sample(genuine, min(CAP_PAYSLIP, len(genuine))):
            add(p, "genuine", "genuine", None, "image_forensic", "payslip_genuine")
        for p in rng.sample(forged, min(CAP_PAYSLIP, len(forged))):
            add(p, "fraud", "payslip_forgery", None, "image_forensic", "payslip_forged")

    return items


def run(items: list[dict]) -> list[dict]:
    records: list[dict] = []
    n = len(items)
    t0 = time.time()
    for i, it in enumerate(items, 1):
        rec = {**{k: (str(v) if isinstance(v, Path) else v) for k, v in it.items()}}
        try:
            r = run_full_analysis(it["path"].read_bytes(), it["ctype"], it["path"].name)
            rec.update({"ok": True, "predicted": r["document_type"], "tier": r["risk_tier"],
                        "score": r["trust_score"],
                        "criticals": r.get("critical_indicators") or [],
                        "reviews": r.get("review_indicators") or []})
        except Exception as e:
            rec.update({"ok": False, "error": e.__class__.__name__, "tier": None,
                        "score": None, "predicted": None})
        records.append(rec)
        if i % 20 == 0 or i == n:
            rate = i / max(time.time() - t0, 1e-6)
            print(f"  [{i:4d}/{n}] {rate:.1f} docs/s  (eta {int((n - i) / max(rate, 1e-6))}s)",
                  flush=True)
    return records


# ----------------------------- metrics -----------------------------

def _safe_div(a, b):
    return a / b if b else 0.0


def _auc(records: list[dict]) -> float | None:
    """ROC-AUC with fraud as positive, fraud-probability = (100 - trust_score)/100."""
    rows = [(1 if r["label"] == "fraud" else 0, (100 - r["score"]) / 100.0)
            for r in records if r.get("ok") and r["score"] is not None]
    ys = {y for y, _ in rows}
    if len(rows) < 2 or len(ys) < 2:
        return None
    try:
        from sklearn.metrics import roc_auc_score
        return float(roc_auc_score([y for y, _ in rows], [s for _, s in rows]))
    except Exception:
        return None


def _tier_block(records: list[dict]) -> dict:
    """Decision metrics for one set of records (one track)."""
    genuine = [r for r in records if r["label"] == "genuine" and r.get("ok")]
    fraud = [r for r in records if r["label"] == "fraud" and r.get("ok")]

    def cnt(rs, tier):
        return sum(1 for r in rs if r["tier"] == tier)

    g_green, g_yellow, g_red = cnt(genuine, "GREEN"), cnt(genuine, "YELLOW"), cnt(genuine, "RED")
    f_green, f_yellow, f_red = cnt(fraud, "GREEN"), cnt(fraud, "YELLOW"), cnt(fraud, "RED")
    n_red = g_red + f_red
    n_flag_g, n_flag_f = g_yellow + g_red, f_yellow + f_red

    return {
        "n_genuine": len(genuine), "n_fraud": len(fraud),
        "genuine_tiers": {"GREEN": g_green, "YELLOW": g_yellow, "RED": g_red},
        "fraud_tiers": {"GREEN": f_green, "YELLOW": f_yellow, "RED": f_red},
        # bank-safe genuine handling
        "clean_pass_rate": round(_safe_div(g_green, len(genuine)), 4),
        "soft_review_rate": round(_safe_div(g_yellow, len(genuine)), 4),
        "hard_fp_rate": round(_safe_div(g_red, len(genuine)), 4),
        # fraud catching
        "fraud_hardcatch_recall": round(_safe_div(f_red, len(fraud)), 4),
        "fraud_flagged_recall": round(_safe_div(n_flag_f, len(fraud)), 4),
        "fraud_missed": f_green,
        # RED as the positive class
        "red_precision": round(_safe_div(f_red, n_red), 4),
        "red_recall": round(_safe_div(f_red, len(fraud)), 4),
        "flag_precision": round(_safe_div(n_flag_f, n_flag_g + n_flag_f), 4),
        "auc": _auc(records),
    }


def compute(records: list[dict]) -> dict:
    ok = [r for r in records if r.get("ok")]
    errs = [r for r in records if not r.get("ok")]

    out: dict = {
        "n_total": len(records), "n_ok": len(ok), "n_error": len(errs),
        "errors": dict(Counter(r.get("error") for r in errs)),
        "tracks": {},
        "overall": _tier_block(ok),
    }
    for track in ("document", "image_forensic"):
        sub = [r for r in ok if r["track"] == track]
        if sub:
            out["tracks"][track] = _tier_block(sub)

    # Per-fraud-vector recall (across both tracks)
    vec = defaultdict(lambda: {"n": 0, "red": 0, "flagged": 0, "missed": 0})
    for r in ok:
        if r["label"] != "fraud":
            continue
        v = vec[r["vector"]]
        v["n"] += 1
        if r["tier"] == "RED":
            v["red"] += 1
        if r["tier"] in ("RED", "YELLOW"):
            v["flagged"] += 1
        if r["tier"] == "GREEN":
            v["missed"] += 1
    out["fraud_vectors"] = {
        k: {**v, "hardcatch_recall": round(_safe_div(v["red"], v["n"]), 4),
            "flagged_recall": round(_safe_div(v["flagged"], v["n"]), 4)}
        for k, v in sorted(vec.items())}

    # Per-doc-type classification confusion (only where expected is known)
    typed = [r for r in ok if r.get("expected")]
    correct = sum(1 for r in typed if r["predicted"] == r["expected"])
    confusion = defaultdict(Counter)
    for r in typed:
        confusion[r["expected"]][r["predicted"]] += 1
    out["classification"] = {
        "n_typed": len(typed),
        "accuracy": round(_safe_div(correct, len(typed)), 4),
        "confusion": {k: dict(v) for k, v in sorted(confusion.items())},
    }
    return out


def _pct(x):
    return "n/a" if x is None else f"{x * 100:5.1f}%"


def report(metrics: dict):
    print("\n" + "=" * 68)
    print("TRUSTLENS SYSTEM BENCHMARK")
    print("=" * 68)
    print(f"docs: {metrics['n_ok']} ok / {metrics['n_error']} error", flush=True)
    if metrics["errors"]:
        print(f"  errors: {metrics['errors']}")

    for track, blk in metrics["tracks"].items():
        print(f"\n--- track: {track}  (genuine {blk['n_genuine']} / fraud {blk['n_fraud']}) ---")
        print(f"  GENUINE  clean-pass {_pct(blk['clean_pass_rate'])} | "
              f"soft-review {_pct(blk['soft_review_rate'])} | "
              f"HARD-FP {_pct(blk['hard_fp_rate'])}   (tiers {blk['genuine_tiers']})")
        print(f"  FRAUD    hard-catch {_pct(blk['fraud_hardcatch_recall'])} | "
              f"flagged {_pct(blk['fraud_flagged_recall'])} | "
              f"MISSED {blk['fraud_missed']}   (tiers {blk['fraud_tiers']})")
        print(f"  RED precision {_pct(blk['red_precision'])} | "
              f"flag precision {_pct(blk['flag_precision'])} | AUC {_pct(blk['auc'])}")

    print("\n--- per fraud vector (hard-catch / flagged) ---")
    for k, v in metrics["fraud_vectors"].items():
        print(f"  {k:26s} n={v['n']:3d}  hard {_pct(v['hardcatch_recall'])} | "
              f"flagged {_pct(v['flagged_recall'])} | missed {v['missed']}")

    c = metrics["classification"]
    print(f"\n--- doc-type classification: {c['accuracy'] * 100:.1f}% "
          f"on {c['n_typed']} typed docs ---")
    for exp, preds in c["confusion"].items():
        wrong = {k: n for k, n in preds.items() if k != exp}
        flag = f"   MIS-> {wrong}" if wrong else ""
        print(f"  {exp:18s} {dict(preds)}{flag}")
    print("=" * 68, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline", help="name for this run's report file")
    ap.add_argument("--limit", type=int, default=0, help="global cap for a quick smoke run")
    args = ap.parse_args()

    items = build_manifest()
    if args.limit:
        random.Random(SEED).shuffle(items)
        items = items[:args.limit]
    print(f"Manifest: {len(items)} docs "
          f"({sum(1 for i in items if i['label'] == 'genuine')} genuine / "
          f"{sum(1 for i in items if i['label'] == 'fraud')} fraud)", flush=True)
    print(f"  sources: {dict(Counter(i['source'] for i in items))}", flush=True)

    records = run(items)
    metrics = compute(records)
    report(metrics)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.tag}.json").write_text(json.dumps(
        {"tag": args.tag, "metrics": metrics, "records": records}, indent=2))
    print(f"\nSaved -> {OUT_DIR / (args.tag + '.json')}", flush=True)

    # diff vs baseline if this is a comparison run
    base_f = OUT_DIR / "baseline.json"
    if args.tag != "baseline" and base_f.exists():
        base = json.loads(base_f.read_text())["metrics"]
        print("\n--- vs baseline (document track) ---")
        b, n = base["tracks"].get("document", {}), metrics["tracks"].get("document", {})
        for key in ("clean_pass_rate", "hard_fp_rate", "fraud_hardcatch_recall",
                    "fraud_flagged_recall"):
            if key in b and key in n:
                print(f"  {key:24s} {b[key] * 100:5.1f}% -> {n[key] * 100:5.1f}% "
                      f"({(n[key] - b[key]) * 100:+.1f})")


if __name__ == "__main__":
    main()
