"""PAN card rule-based validation + confidence boosting.

The AI (NER) stays the PRIMARY extractor for names. These deterministic rules
CROSS-CHECK and BOOST confidence — and catch tampering — they do NOT replace it.

Three jobs:
  1. PAN structure (the code itself carries fixed rules):
       - 4th char  = holder type (P=Individual, C=Company, ...).
       - 5th char  = first letter of the surname → cross-checked against the name
         (catches a tampered name OR a tampered PAN — the two stop agreeing).
  2. Identity confirmation: a real PAN *card* has the Income-Tax header AND an
     actual PAN code — NOT just the words "Permanent Account Number" (which every
     loan / KYC / ITR form also contains). Stops text-only false positives.
  3. Label-anchored Name / Father's Name / DOB / Signature (modern labelled
     format) used to CROSS-CHECK the AI extraction; agreement boosts confidence.

Bank-safe: a mismatch is a soft REVIEW signal (Indian name order varies + OCR is
imperfect), never an automatic hard reject.
"""

from __future__ import annotations

import io
import logging
import re

import fitz
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
PAN_HOLDER_TYPES = {
    "P": "Individual", "C": "Company", "H": "HUF (Hindu Undivided Family)",
    "F": "Firm / LLP", "A": "Association of Persons", "T": "Trust",
    "B": "Body of Individuals", "L": "Local Authority",
    "J": "Artificial Juridical Person", "G": "Government",
}
HEADER_MARKERS = ("income tax department", "permanent account number", "आयकर विभाग")

PDF_TYPE = "application/pdf"
IMAGE_TYPES = {"image/png", "image/jpeg"}

# Modern bilingual labels -> field key
LABELS = {
    "name": ("name", "नाम"),
    "father": ("father", "पिता"),
    "dob": ("date of birth", "जन्म"),
    "signature": ("signature", "हस्ताक्षर"),
}


def validate_pan(pan: str, name: str | None = None) -> dict:
    """Validate the internal structure of a PAN code. `name` (from AI) lets us
    cross-check the 5th letter against the surname."""
    pan = (pan or "").strip().upper()
    out: dict = {"pan": pan, "valid_format": bool(PAN_RE.fullmatch(pan))}
    if not out["valid_format"]:
        return out
    out["holder_type"] = PAN_HOLDER_TYPES.get(pan[3], "Unknown")
    out["surname_initial"] = pan[4]
    if name:
        # Indian name order varies (surname first OR last), so accept the 5th
        # letter matching the first letter of ANY name token.
        initials = {t[0].upper() for t in re.findall(r"[A-Za-z]+", name) if t}
        out["surname_match"] = pan[4] in initials if initials else None
    return out


def _load_image(content: bytes, content_type: str) -> Image.Image | None:
    if content_type == PDF_TYPE:
        try:
            with fitz.open(stream=content, filetype="pdf") as d:
                if len(d) == 0:
                    return None
                pix = d[0].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
                return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception:
            return None
    if content_type in IMAGE_TYPES:
        try:
            return Image.open(io.BytesIO(content)).convert("RGB")
        except Exception:
            return None
    return None


def _label_anchored_fields(image: Image.Image) -> dict[str, str]:
    """Modern labelled format: read the line just BELOW each label. Best-effort —
    returns only what it confidently finds (old unlabelled cards yield nothing)."""
    try:
        data = pytesseract.image_to_data(
            image, lang="eng+hin", output_type=pytesseract.Output.DICT)
    except Exception:
        return {}
    lines: dict = {}
    for i in range(len(data["text"])):
        t = (data["text"][i] or "").strip()
        if not t:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, {"text": [], "top": data["top"][i], "left": data["left"][i]})
        lines[key]["text"].append(t)
    ordered = sorted(([" ".join(v["text"]), v["top"], v["left"]] for v in lines.values()),
                     key=lambda r: r[1])
    found: dict[str, str] = {}
    for field, kws in LABELS.items():
        for idx, (txt, top, left) in enumerate(ordered):
            low = txt.lower()
            if any(k in low for k in kws):
                # value is the next line below with similar left margin
                for j in range(idx + 1, min(idx + 3, len(ordered))):
                    vtxt, vtop, vleft = ordered[j]
                    if vtop > top and abs(vleft - left) < 60 and len(vtxt.strip()) >= 2:
                        if field != "signature":  # signature is handwriting, not text
                            found[field] = re.sub(r"^[:/\-\s]+", "", vtxt).strip()
                        else:
                            found["signature"] = "present"
                        break
                break
    # signature label alone is enough to mark presence
    if "signature" not in found:
        for txt, _, _ in ordered:
            if any(k in txt.lower() for k in LABELS["signature"]):
                found["signature"] = "present"
                break
    return found


def _names_agree(a: str, b: str) -> bool:
    na = {t for t in re.findall(r"[a-z]+", (a or "").lower()) if len(t) > 1}
    nb = {t for t in re.findall(r"[a-z]+", (b or "").lower()) if len(t) > 1}
    return bool(na & nb)


def analyze_pan_card(text: str, entities: dict, content: bytes, content_type: str) -> dict:
    """Confidence-boost + tamper cross-check for a PAN card. AI-extracted name is
    the primary; these rules validate it."""
    low = (text or "").lower()
    pans = entities.get("pan", []) or PAN_RE.findall(text or "")
    ai_names = entities.get("person", [])

    # Identity: header markers present AND a real PAN code present.
    header_hits = [m for m in HEADER_MARKERS if m in low]
    has_real_pan = len(pans) > 0
    is_pan_card = len(header_hits) >= 1 and has_real_pan

    flags: list[str] = []
    info: dict = {"pan_codes": pans, "header_markers": header_hits}

    # Structure validation + surname cross-check (vs the AI name).
    validations = []
    for pan in pans[:1]:
        v = validate_pan(pan, ai_names[0] if ai_names else None)
        validations.append(v)
        if not v["valid_format"]:
            flags.append("pan_invalid_format")
        elif v.get("surname_match") is False:
            flags.append("pan_surname_letter_mismatch")  # soft — review, not reject
    info["pan_validation"] = validations

    # Label-anchored cross-check (modern format). Boosts confidence on agreement.
    image = _load_image(content, content_type)
    label_fields = _label_anchored_fields(image) if image is not None else {}
    info["label_fields"] = label_fields
    name_cross_checked = False
    if label_fields.get("name") and ai_names:
        name_cross_checked = _names_agree(label_fields["name"], ai_names[0])
        info["name_rule_vs_ai_agree"] = name_cross_checked

    # Confidence score: how strongly this is a consistent, genuine PAN card.
    score = 0.5
    if is_pan_card:
        score = 0.8
        if validations and validations[0].get("surname_match"):
            score += 0.1   # PAN code agrees with the name
        if name_cross_checked or label_fields.get("dob") or label_fields.get("signature"):
            score += 0.1   # extra fields corroborate
    if "pan_surname_letter_mismatch" in flags:
        score = min(score, 0.6)  # soft review
    if "pan_invalid_format" in flags:
        score = min(score, 0.4)
    score = max(0.0, min(1.0, score))

    boost_fields = [k for k in ("name", "father", "dob", "signature") if k in label_fields]
    detail = (
        f"PAN card checks: header={'yes' if header_hits else 'no'}, "
        f"PAN code={'yes' if has_real_pan else 'no'}"
        + (f", holder={validations[0].get('holder_type')}" if validations else "")
        + (f", surname-letter {'matches' if validations and validations[0].get('surname_match') else 'check'}"
           if validations and validations[0].get('surname_match') is not None else "")
        + (f", label-extracted {boost_fields}" if boost_fields else "")
        + (". ⚠ " + ", ".join(flags) if flags else ".")
    )
    return {
        "score": score,
        "passed": score >= 0.7,
        "detail": detail,
        "flags": flags,
        "info": info,
    }
