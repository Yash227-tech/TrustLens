"""Measure the forgery localiser on the Indian-doc tamper set (improvement #4).

Reads /data/synthetic_tamper/manifest.jsonl (build_tamper_set.py) and scores the
ManTraNet heatmap against each ground-truth mask, per fraud vector:

  pixel_auc      — ROC-AUC of forgery probability vs the mask (localisation quality)
  inmask_p95     — 95th-pct ManTraNet response INSIDE the tampered region
  outmask_p95    — 95th-pct response OUTSIDE it (clean baseline)
  separation     — inmask_p95 / outmask_p95 (>1 means the forgery stands out)

and, for photo_swap, the production photo_forensics verdict (recall on swaps vs
false-positive rate on the matched genuine originals).

This turns "ManTraNet seems to work" into numbers, and tells us honestly which
vectors it catches (crude splice / copy-move / photo swap) vs misses (seamless
Poisson-blended splice). Run inside the backend container:
  docker exec trustlens-backend sh -c "cd /ml && python -m training.eval_tamper"
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, "/app")

DATA = Path("/data")
MANIFEST = DATA / "synthetic_tamper" / "manifest.jsonl"


def _mantranet_mask(bgr_path: Path) -> np.ndarray | None:
    try:
        from app.forensics.mantranet.wrapper import _get_model
        model, device = _get_model()
        im = Image.open(bgr_path).convert("RGB")
        arr = np.array(im)
        t = torch.from_numpy(arr).float().unsqueeze(0).permute(0, 3, 1, 2).contiguous().to(device)
        with torch.no_grad():
            m = model(t)[0, 0].cpu().numpy()
        return np.clip(m, 0.0, 1.0)
    except Exception as e:
        print(f"  ! ManTraNet failed: {e.__class__.__name__}")
        return None


def _pixel_auc(prob: np.ndarray, gt: np.ndarray) -> float | None:
    y = (gt.reshape(-1) > 127).astype(int)
    s = prob.reshape(-1)
    if y.min() == y.max():
        return None
    # subsample for speed (masks are dense enough)
    if len(y) > 60000:
        idx = np.random.RandomState(0).choice(len(y), 60000, replace=False)
        y, s = y[idx], s[idx]
    try:
        from sklearn.metrics import roc_auc_score
        return float(roc_auc_score(y, s))
    except Exception:
        return None


def main():
    if not MANIFEST.exists():
        print(f"No tamper set at {MANIFEST} — run build_tamper_set.py first.")
        return
    rows = [json.loads(l) for l in MANIFEST.read_text().splitlines() if l.strip()]
    print(f"Evaluating {len(rows)} tampered images", flush=True)

    agg: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for i, r in enumerate(rows, 1):
        vec = r["vector"]
        prob = _mantranet_mask(DATA / r["image"])
        if prob is None:
            continue
        gt = np.array(Image.open(DATA / r["mask"]).convert("L"))
        if gt.shape != prob.shape:
            gt = np.array(Image.fromarray(gt).resize((prob.shape[1], prob.shape[0])))
        m = gt > 127
        if m.sum() == 0 or (~m).sum() == 0:
            continue
        agg[vec]["auc"].append(_pixel_auc(prob, gt))
        agg[vec]["inmask"].append(float(np.percentile(prob[m], 95)))
        agg[vec]["outmask"].append(float(np.percentile(prob[~m], 95)))
        if i % 25 == 0:
            print(f"  [{i}/{len(rows)}]", flush=True)

    print("\n" + "=" * 64)
    print("MANTRANET LOCALISATION vs GROUND-TRUTH MASK (per fraud vector)")
    print("=" * 64)
    print(f"{'vector':18s} {'n':>4s} {'pixel_auc':>10s} {'inmask_p95':>11s} "
          f"{'outmask_p95':>12s} {'separation':>11s}")
    summary = {}
    for vec in sorted(agg):
        aucs = [a for a in agg[vec]["auc"] if a is not None]
        auc = float(np.mean(aucs)) if aucs else float("nan")
        inm = float(np.mean(agg[vec]["inmask"]))
        outm = float(np.mean(agg[vec]["outmask"]))
        sep = inm / max(outm, 1e-3)
        n = len(agg[vec]["inmask"])
        print(f"{vec:18s} {n:4d} {auc:10.3f} {inm:11.3f} {outm:12.3f} {sep:11.2f}")
        summary[vec] = {"n": n, "pixel_auc": auc, "inmask_p95": inm,
                        "outmask_p95": outm, "separation": sep}

    # photo_forensics production recall on the photo_swap vector (and FP on originals)
    swaps = [r for r in rows if r["vector"] == "photo_swap"]
    if swaps:
        from app.forensics.photo_forensics import analyze_photo_region
        tp = fp = n_sw = n_or = 0
        for r in swaps:
            dt = r["doc_type"]
            sw = analyze_photo_region((DATA / r["image"]).read_bytes(), "image/png", dt)
            if sw.get("checked"):
                n_sw += 1
                tp += int(sw["verdict"] == "tampered")
            orig = analyze_photo_region((DATA / r["original"]).read_bytes(), "image/png", dt)
            if orig.get("checked"):
                n_or += 1
                fp += int(orig["verdict"] == "tampered")
        print("\n--- photo_forensics (production detector) on photo_swap ---")
        print(f"  swap recall:        {tp}/{n_sw}"
              f"  ({(tp / n_sw * 100) if n_sw else 0:.0f}%)")
        print(f"  original false-pos: {fp}/{n_or}"
              f"  ({(fp / n_or * 100) if n_or else 0:.0f}%)")
        summary["photo_forensics"] = {"swap_recall": f"{tp}/{n_sw}",
                                      "original_fp": f"{fp}/{n_or}"}

    out = DATA / "synthetic_tamper" / "mantranet_eval.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"\nSaved -> {out}")
    print("=" * 64)


if __name__ == "__main__":
    main()
