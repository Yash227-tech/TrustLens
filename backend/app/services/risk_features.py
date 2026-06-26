"""Shared feature specification for the XGBoost risk scorer (Step 19).

Both the training pipeline (ml/training) and the live scorer (risk_scorer.py)
import FEATURE_NAMES and build_feature_vector from here, guaranteeing the
features are identical at train time and serve time (no train/serve skew).

Each feature is a forensic signal's trust sub-score in [0,1] where 1.0 = clean.

Cross-Source Verification and DOCX Metadata are deliberately NOT in this trained
vector — they feed the risk TIER via critical indicators (analysis.py), not the
XGBoost score, and that is the bank-safe design (not a stub/omission):

  * Cross-Source — its FRAUD outcomes (authoritative name mismatch, fabricated
    Aadhaar failing the Verhoeff checksum) force RED as critical indicators
    regardless of score. Its COMMON outcome is the neutral 0.85 ("no authoritative
    record to confirm" — true for almost every genuine document against the mock
    sources); folding that into the score would penalise every unverifiable but
    genuine doc and manufacture false positives. So a degraded cross-source result
    escalates the tier; a neutral one must not drag the score down.
  * DOCX Metadata — its fraud signals (different last-editor, high revision count)
    are critical indicators; the rest of its metadata is already captured by the
    converted PDF's pdf_metadata. DOCX uploads are also rare.

Keeping the trained vector to the 7 pixel/structural forensics avoids a near-
constant feature in training and keeps train/serve parity with risk_scorer.py.
"""

from __future__ import annotations

# ELA stays in the trained score because it's essential for IMAGE tampering
# (CASIA splices, photoshopped IDs) — removing it craters tamper recall. But ELA
# is NOISY on document graphics (logos/stamps/scans), so analysis.py NEUTRALISES
# the ela feature at scoring time for PDF inputs (where it's noise) while keeping
# it for image uploads (where it's the detector). See _score_signals there.
FEATURE_NAMES = [
    "pdf_metadata",
    "font_spacing",
    "signature_region",
    "stamp_auth",
    "bank_statement",
    "ela",
    "mantranet",
]

# Map the human signal name used in analysis.py to the feature key here.
SIGNAL_TO_FEATURE = {
    "PDF Metadata": "pdf_metadata",
    "Font & Spacing": "font_spacing",
    "Signature Region (ELA)": "signature_region",
    "Stamp Authentication": "stamp_auth",
    "Bank Statement Analysis": "bank_statement",
    "Error Level Analysis": "ela",
    "Copy-Move Detection": "mantranet",
}


def build_feature_vector(scores: dict[str, float]) -> list[float]:
    """scores: feature_key -> score. Missing features default to 1.0 (neutral-clean)."""
    return [float(scores.get(name, 1.0)) for name in FEATURE_NAMES]


def features_from_signals(signals: list[dict]) -> list[float]:
    """Build the vector from a list of analysis.py signal dicts ({name, score, ...})."""
    scores: dict[str, float] = {}
    for s in signals:
        key = SIGNAL_TO_FEATURE.get(s["name"])
        if key:
            scores[key] = s["score"]
    return build_feature_vector(scores)
