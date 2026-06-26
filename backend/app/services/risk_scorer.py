"""Live XGBoost risk scorer + SHAP attribution (Step 19).

Loads the trained model from /data/models/xgb_risk and converts a document's
forensic feature vector into a Trust Score (0-100) plus per-feature SHAP
contributions for the evidence report. Falls back to None if the model is
absent, so analysis.py can use its normalised-weight scoring instead.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

from app.services.risk_features import FEATURE_NAMES, features_from_signals

logger = logging.getLogger(__name__)

MODEL_DIR = Path("/data/models/xgb_risk")

_booster = None
_explainer = None
_lock = threading.Lock()
_unavailable = False


def _load():
    global _booster, _explainer, _unavailable
    if _booster is not None or _unavailable:
        return
    with _lock:
        if _booster is not None or _unavailable:
            return
        model_path = MODEL_DIR / "model.json"
        if not model_path.exists():
            logger.info("XGBoost model not found at %s — using weighted scoring.", model_path)
            _unavailable = True
            return
        try:
            import xgboost as xgb
            booster = xgb.Booster()
            booster.load_model(str(model_path))
            _booster = booster
            try:
                import shap
                _explainer = shap.TreeExplainer(booster)
            except Exception as e:
                logger.warning("SHAP explainer unavailable: %s", e)
                _explainer = None
            logger.info("XGBoost risk scorer loaded.")
        except Exception as e:
            logger.warning("XGBoost load failed: %s", e)
            _unavailable = True


def score_from_signals(signals: list[dict]) -> dict | None:
    """Return {trust_score, contributions} or None if the model is unavailable."""
    _load()
    if _booster is None:
        return None
    try:
        import xgboost as xgb
        vec = features_from_signals(signals)
        arr = np.array([vec], dtype=np.float32)
        dmat = xgb.DMatrix(arr, feature_names=FEATURE_NAMES)
        prob_tampered = float(_booster.predict(dmat)[0])
        trust_score = int(round((1.0 - prob_tampered) * 100))

        contributions = {}
        if _explainer is not None:
            try:
                sv = _explainer.shap_values(arr)
                vals = sv[0] if isinstance(sv, list) is False else sv[0]
                contributions = {
                    FEATURE_NAMES[i]: float(np.ravel(vals)[i]) for i in range(len(FEATURE_NAMES))
                }
            except Exception as e:
                logger.warning("SHAP attribution failed: %s", e)

        return {"trust_score": trust_score, "prob_tampered": prob_tampered, "contributions": contributions}
    except Exception as e:
        logger.warning("XGBoost scoring failed: %s", e)
        return None
