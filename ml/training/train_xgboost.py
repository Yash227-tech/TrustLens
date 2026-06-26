"""Train the XGBoost risk scorer + SHAP explainer (Step 19).

Reads /data/models/xgb_features.csv, trains a binary classifier
(0=clean, 1=tampered), reports held-out metrics, computes SHAP global feature
importance, and saves:
    /data/models/xgb_risk/model.json        (XGBoost booster)
    /data/models/xgb_risk/feature_names.json
    /data/models/xgb_risk/metrics.json
    /data/models/xgb_risk/shap_importance.json

Run inside the backend container:
    docker exec trustlens-backend sh -c "cd /ml && python -m training.train_xgboost"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

sys.path.insert(0, "/app")
from app.services.risk_features import FEATURE_NAMES  # noqa: E402

CSV = Path("/data/models/xgb_features.csv")
OUT_DIR = Path("/data/models/xgb_risk")
SEED = 42


def main():
    df = pd.read_csv(CSV)
    X = df[FEATURE_NAMES].values
    y = df["label"].values
    print(f"Dataset: {len(df)} rows, {len(FEATURE_NAMES)} features, "
          f"{int((y == 0).sum())} clean / {int((y == 1).sum())} tampered")

    idx = np.arange(len(df))
    idx_tr, idx_te = train_test_split(
        idx, test_size=0.2, random_state=SEED, stratify=y
    )
    X_tr, X_te, y_tr, y_te = X[idx_tr], X[idx_te], y[idx_tr], y[idx_te]

    # Bank-safe: with the added real-clean docs the set is clean-heavy. Up-weight
    # the tampered class so the decision boundary keeps high *recall on fraud*
    # (a missed forgery is far costlier than a false review). scale_pos_weight =
    # n_clean / n_tampered is the XGBoost-recommended imbalance correction.
    n_clean_tr = int((y_tr == 0).sum())
    n_tamp_tr = int((y_tr == 1).sum())
    spw = round(n_clean_tr / max(n_tamp_tr, 1), 3)
    print(f"scale_pos_weight (clean/tampered) = {spw}")

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        scale_pos_weight=spw,
        random_state=SEED,
    )
    model.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)

    proba = model.predict_proba(X_te)[:, 1]
    preds = (proba >= 0.5).astype(int)
    acc = float(accuracy_score(y_te, preds))
    auc = float(roc_auc_score(y_te, proba))
    tamper_recall = float(recall_score(y_te, preds, pos_label=1))
    clean_recall = float(recall_score(y_te, preds, pos_label=0))
    print(f"Held-out accuracy:      {acc:.4f}")
    print(f"Held-out ROC-AUC:       {auc:.4f}")
    print(f"Tamper recall (fraud):  {tamper_recall:.4f}  <-- bank-safe: keep high")
    print(f"Clean recall (genuine): {clean_recall:.4f}  <-- the MOA false-positive fix")
    cm = confusion_matrix(y_te, preds)
    print(f"Confusion matrix [rows=true 0/1, cols=pred 0/1]:\n{cm}")
    print(classification_report(y_te, preds, target_names=["clean", "tampered"]))

    # Per-source recall on the held-out set — confirms real tamper sources
    # (synthetic-tamper, CASIA Tp, payslip-forged) are still caught and the real
    # clean sources (real_*) are now correctly passed.
    if "source" in df.columns:
        src_te = df["source"].values[idx_te]
        print("Per-source held-out accuracy (correct / total):")
        for s in sorted(set(src_te)):
            mask = src_te == s
            correct = int((preds[mask] == y_te[mask]).sum())
            total = int(mask.sum())
            kind = "tampered" if y_te[mask][0] == 1 else "clean"
            print(f"  {s:22s} [{kind:8s}] {correct:4d}/{total:<4d} = {correct / max(total,1):.3f}")


    # SHAP global importance
    shap_importance = {}
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X_te)
        mean_abs = np.abs(sv).mean(axis=0)
        shap_importance = {FEATURE_NAMES[i]: float(mean_abs[i]) for i in range(len(FEATURE_NAMES))}
        ranked = sorted(shap_importance.items(), key=lambda x: -x[1])
        print("SHAP feature importance:")
        for name, val in ranked:
            print(f"  {name:20s} {val:.4f}")
    except Exception as e:
        print(f"SHAP step skipped: {e.__class__.__name__}: {e}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model.get_booster().save_model(str(OUT_DIR / "model.json"))
    (OUT_DIR / "feature_names.json").write_text(json.dumps(FEATURE_NAMES))
    (OUT_DIR / "metrics.json").write_text(json.dumps({
        "accuracy": acc, "roc_auc": auc,
        "tamper_recall": tamper_recall, "clean_recall": clean_recall,
        "scale_pos_weight": spw,
    }))
    (OUT_DIR / "shap_importance.json").write_text(json.dumps(shap_importance))
    print(f"\nSaved model + artifacts to {OUT_DIR}")


if __name__ == "__main__":
    main()
