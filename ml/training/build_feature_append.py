"""Append-only feature extraction (#3, efficient retrain).

A full rebuild recomputes ~2500 forensic passes (~2h). Instead we APPEND only the
NEW rows to the existing /data/models/xgb_features.csv, then retrain:

  * in-domain Indian-doc tampers (build_tamper_set.py) — DETECTABLE vectors only
    (copy_move / splice_crude / photo_swap) as tampered(1); seamless EXCLUDED
    (forensically near-invisible -> would teach clean=fraud). Matched originals
    deduped as genuine(0).
  * the 2 new synthetic clean doc types (rental_agreement, udyam_certificate)
    that did not exist when the CSV was last built.

Sound because the 7 CSV features (pdf/font/sig/stamp/bank/ela/mantranet) are
deterministic and unaffected by this session's entity/photo changes, so the
existing rows stay valid. Run inside the backend container:
  docker exec trustlens-backend sh -c "cd /ml && python -m training.build_feature_append"
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from training.build_feature_dataset import features_for_image, features_for_pdf  # noqa: E402
from app.services.risk_features import FEATURE_NAMES  # noqa: E402

CSV = Path("/data/models/xgb_features.csv")
DATA = Path("/data")
TAMPER_MANIFEST = DATA / "synthetic_tamper" / "manifest.jsonl"
TRAINABLE_VECTORS = {"copy_move", "splice_crude", "photo_swap"}
NEW_CLEAN_TYPES = ["rental_agreement", "udyam_certificate"]
PER_TYPE_CLEAN = 18


def main():
    new_rows: list[tuple[list[float], int, str]] = []

    # in-domain tampers
    if TAMPER_MANIFEST.exists():
        rows = [json.loads(l) for l in TAMPER_MANIFEST.read_text().splitlines() if l.strip()]
        seen_orig: set[str] = set()
        nt = no = 0
        for r in rows:
            if r["vector"] not in TRAINABLE_VECTORS:
                continue
            try:
                new_rows.append((features_for_image((DATA / r["image"]).read_bytes(), "image/png"),
                                 1, f"indoc_{r['vector']}"))
                nt += 1
                if r["original"] not in seen_orig:
                    seen_orig.add(r["original"])
                    new_rows.append((features_for_image((DATA / r["original"]).read_bytes(), "image/png"),
                                     0, "indoc_orig"))
                    no += 1
            except Exception as e:
                print(f"  ! {r.get('image')}: {e.__class__.__name__}", flush=True)
        print(f"in-domain tamper: {nt} tampered / {no} originals", flush=True)

    # new synthetic clean doc types
    for t in NEW_CLEAN_TYPES:
        d = DATA / "synthetic" / t
        n = 0
        for p in sorted(d.glob("*.pdf"))[:PER_TYPE_CLEAN]:
            try:
                new_rows.append((features_for_pdf(p.read_bytes()), 0, "syn_clean"))
                n += 1
            except Exception as e:
                print(f"  ! {p.name}: {e.__class__.__name__}", flush=True)
        print(f"syn_clean {t}: {n}", flush=True)

    # append (header already present, same column order)
    before = sum(1 for _ in CSV.open()) - 1
    with CSV.open("a", newline="") as f:
        w = csv.writer(f)
        for feats, label, tag in new_rows:
            w.writerow([f"{x:.5f}" for x in feats] + [label, tag])
    after = before + len(new_rows)
    print(f"\nAppended {len(new_rows)} rows: {before} -> {after} total -> {CSV}", flush=True)
    assert FEATURE_NAMES  # ensure import is consistent


if __name__ == "__main__":
    main()
