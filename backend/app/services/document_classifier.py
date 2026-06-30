"""Document classification per spec §3.2 + §4.

Single-stage pipeline today:

  - Keyword classifier — deterministic fine-grained classification into the
    23 specific document types listed in §4 (12 legal + 11 financial sub-types).
    Uses substring patterns against the OCR'd text. Explainable for underwriters:
    each match contributes evidence.

NOTE: Step 10c originally planned a second LayoutLMv3 stage for RVL-CDIP coarse
classification. After investigation Microsoft has NOT published an RVL-CDIP
fine-tune of LayoutLMv3 on HuggingFace (only the base model). User-approved
deviation: defer LayoutLMv3 to Step 14b, where we fine-tune
`microsoft/layoutlmv3-base` directly on our synthetic Indian doc data so the
model outputs the 23-class label natively (better than RVL-CDIP for our use case).
"""

from __future__ import annotations

import io
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

LAYOUTLMV3_DIR = Path("/data/models/layoutlmv3-trustlens")
LAYOUTLMV3_MAX_DIM = 1024
PDF_TYPE = "application/pdf"
IMAGE_TYPES = {"image/png", "image/jpeg"}


@dataclass(frozen=True)
class DocSpec:
    doc_type: str
    display_name: str
    category: str  # "legal" or "financial"
    patterns: tuple[str, ...]
    # Strong identity phrases — a document's own TITLE / decisive marker. Matched
    # the same way (case-insensitive substring) but weighted higher so a real
    # title beats incidental cross-mentions of a statement name elsewhere on the
    # page (e.g. a cash-flow statement that starts from "profit before tax", or an
    # auditor's report that lists every statement it audited). Keeps the
    # explainable substring approach (spec §3.2) — anchors are reported as
    # evidence too.
    anchors: tuple[str, ...] = ()


# An anchor (title/identity phrase) counts for this many ordinary pattern hits.
ANCHOR_WEIGHT = 3


# Patterns are matched case-insensitively against the OCR'd text.
# Order doesn't matter; the strongest-match wins.
DOC_SPECS: tuple[DocSpec, ...] = (
    # --- LEGAL ---
    DocSpec("loan_agreement", "Loan Agreement", "legal",
            ("loan agreement", "principal sum", "borrower and the lender",
             "loan account", "tenure of the loan", "rate of interest")),
    DocSpec("sanction_letter", "Sanction Letter", "legal",
            ("sanction letter", "sanctioned amount", "loan sanction",
             "letter of sanction", "we are pleased to inform")),
    DocSpec("noc", "No Objection Certificate (NOC)", "legal",
            ("no objection certificate", "we have no objection",
             "this is to certify that", " noc ", "n.o.c.")),
    DocSpec("board_resolution", "Board Resolution", "legal",
            ("passed at the meeting", "certified true copy",
             "duly convened", "quorum"),
            anchors=("board resolution", "resolved that", "resolution passed")),
    DocSpec("partnership_deed", "Partnership Deed", "legal",
            ("partnership deed", "profit sharing ratio", "the partners",
             "indian partnership act")),
    DocSpec("moa_aoa", "Memorandum / Articles of Association", "legal",
            (" moa ", " aoa ", "object clauses", "companies act, 2013"),
            anchors=("memorandum of association", "articles of association")),
    DocSpec("power_of_attorney", "Power of Attorney", "legal",
            ("power of attorney", "attorney in fact", "constitute and appoint",
             " poa ", "lawful attorney")),
    DocSpec("indemnity_bond", "Indemnity Bond", "legal",
            ("indemnity bond", "indemnify", "hold harmless", "indemnifier",
             "indemnified party")),
    DocSpec("guarantee_letter", "Guarantee Letter", "legal",
            ("guarantee letter", "letter of guarantee", "guarantor",
             "we hereby guarantee")),
    DocSpec("rental_agreement", "Rental / Lease Agreement", "legal",
            ("lessor", "lessee", "said premises", "monthly rent", "security deposit",
             "rental deposit", "fixtures and fittings", "sub-lease", "tenant", "landlord",
             "residential purposes", "leave and license", "notice in writing"),
            anchors=("residential rental agreement", "rental agreement", "lease agreement",
                     "lease deed", "rent agreement", "leave and licence agreement",
                     "apartment lease agreement")),
    DocSpec("udyam_certificate", "Udyam / MSME Registration Certificate", "kyc",
            ("name of enterprise", "type of enterprise", "major activity",
             "social category of entrepreneur", "national industry classification",
             "date of udyam registration", "date of incorporation", "name of unit",
             "micro, small and medium enterprises", "udyamregistration.gov.in",
             "enterprise type", "nic"),
            anchors=("udyam registration certificate", "udyam registration number",
                     "udyam-", "udyog aadhaar", "ministry of micro, small and medium enterprises")),
    DocSpec("aadhaar", "Aadhaar Card", "legal",
            ("aadhaar", "uidai", "unique identification authority",
             "your aadhaar no", "आधार")),
    DocSpec("pan", "PAN Card", "legal",
            ("permanent account number", "income tax department",
             "pan card", " pan: ", "नोकरीदाताचा कर")),
    DocSpec("passport", "Passport", "legal",
            ("republic of india passport", "type/प्रकार", "passport no",
             "place of birth", "place of issue")),

    # --- FINANCIAL ---
    DocSpec("bank_statement", "Bank Statement", "financial",
            ("statement of account", "account statement", "transaction date",
             "running balance", "opening balance", "closing balance",
             "ifsc code", "micr code")),
    DocSpec("salary_slip", "Salary Slip / Payslip", "financial",
            ("salary slip", "payslip", "pay slip", "earnings", "deductions",
             "net pay", "net payable", "basic salary", "hra", "lop days")),
    DocSpec("form_16", "Form 16 (TDS Certificate)", "financial",
            ("form no. 16", "form 16", "tds certificate", "deductor",
             "tax deducted at source", "section 203")),
    DocSpec("itr_v", "ITR-V (Acknowledgement)", "financial",
            ("itr-v", "itr v", "acknowledgement number",
             "indian income tax return acknowledgement",
             "verification form")),
    DocSpec("itr_full", "Income Tax Return", "financial",
            ("income tax return", "assessment year", "previous year",
             "gross total income", "total taxable income", "itr-1", "itr-2",
             "itr-3", "itr-4")),
    DocSpec("gstr_1", "GSTR-1", "financial",
            ("gstr-1", "gstr 1", "outward supplies", "tax invoice",
             "b2b invoices", "hsn code")),
    DocSpec("gstr_3b", "GSTR-3B", "financial",
            ("gstr-3b", "gstr 3b", "summary return", "outward taxable",
             "inward supplies liable to reverse charge")),
    DocSpec("balance_sheet", "Balance Sheet", "financial",
            ("as at 31st march", "as at march 31", "non-current assets",
             "current liabilities", "equity and liabilities", "share capital",
             "total equity and liabilities", "total assets",
             "capital and liabilities",  # banking-form balance sheet
             "schedules referred to above", "non-current liabilities"),
            anchors=("balance sheet",)),
    DocSpec("profit_and_loss", "Profit & Loss Statement", "financial",
            ("profit & loss", "revenue from operations", "earnings per share",
             "profit before tax", "total income", "total expenses",
             "profit for the year", "other comprehensive income",
             "interest earned", "interest expended",  # banking-form P&L
             "exceptional items"),
            anchors=("statement of profit and loss", "profit and loss account",
                     "statement of profit or loss", "statement of profit")),
    DocSpec("audited_financials", "Audited Financial Statements", "financial",
            ("audit report", "audited financial statements", "in our opinion",
             "key audit matters", "basis for opinion", "true and fair view",
             "report on the audit of"),
            anchors=("independent auditor", "auditor's report", "auditors' report")),
    DocSpec("cash_flow_statement", "Cash Flow Statement", "financial",
            ("cash flow from operating", "cash flow from investing",
             "cash flow from financing", "net increase in cash",
             "cash flows from operating activities",
             "net cash from operating activities",
             "net cash used in investing activities", "cash and cash equivalents"),
            anchors=("cash flow statement", "statement of cash flows",
                     "statement of cash flow")),

    # --- KYC / ADDRESS PROOF ---
    DocSpec("utility_bill", "Utility Bill (Electricity / Water / Gas)", "kyc",
            ("consumer no", "consumer number", "consumer name", "consumer category",
             "units consumed", "meter reading", "meter no", "billing period",
             "bill cycle", "amount payable", "bill amount", "bill due date",
             "due date", "sanctioned load", "energy charges", "consumption charges",
             "sewerage", "mmbtu", "billing address", "disconnection of supply"),
            anchors=("electricity bill", "water bill", "gas bill", "energy bill",
                     "water supply bill", "piped natural gas", "delhi jal board",
                     "gujarat gas")),
)


def _normalise_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return " " + text + " "  # pad so " noc " etc. match at the edges


def keyword_classify(text: str) -> dict:
    """Score every DocSpec; return best match + confidence + evidence."""
    if not text or not text.strip():
        return {
            "doc_type": "unknown",
            "display_name": "Unknown",
            "category": "unknown",
            "confidence": 0.0,
            "matches": [],
            "all_scores": {},
        }

    norm = _normalise_text(text)

    # Weighted score per type: anchors (title/identity phrases) count ANCHOR_WEIGHT
    # each, ordinary patterns count 1. Anchor matches are listed first as evidence.
    scores: dict[str, tuple[int, list[str]]] = {}
    for spec in DOC_SPECS:
        anchor_hits = [p for p in spec.anchors if p in norm]
        pattern_hits = [p for p in spec.patterns if p in norm]
        if anchor_hits or pattern_hits:
            score = len(anchor_hits) * ANCHOR_WEIGHT + len(pattern_hits)
            scores[spec.doc_type] = (score, anchor_hits + pattern_hits)

    if not scores:
        return {
            "doc_type": "unknown",
            "display_name": "Unknown",
            "category": "unknown",
            "confidence": 0.0,
            "matches": [],
            "all_scores": {},
        }

    # Disambiguation: an Independent Auditor's Report is the only document that
    # combines "in our opinion" with auditor phrasing. Its body lists every other
    # statement it audited ("...the Balance Sheet, the Statement of Profit and
    # Loss, the Cash Flow Statement..."), which would otherwise let those titles
    # tie or win. This rule forces the correct, unambiguous label.
    auditor_phrasing = any(a in norm for a in (
        "independent auditor", "auditor's report", "auditors' report",
        "report on the audit of"))
    force_type = None
    if "in our opinion" in norm and auditor_phrasing:
        force_type = "audited_financials"

    # MOA/AOA vs a board resolution that merely MENTIONS them. A real MOA/AOA
    # filing carries both titles AND constitutional BODY content (object clauses,
    # Table F/A, authorised share capital, the regulations contained in...). An
    # IPO/DRHP/scheme board resolution references "the Memorandum and Articles of
    # Association" but has NO such body — so title-mention alone must NOT pull it
    # to moa_aoa (that wrongly grabbed real board resolutions).
    moa_titles = "memorandum of association" in norm and "articles of association" in norm
    # Uniquely-MOA STRUCTURAL content (NOT capital/liability phrasing, which IPO/
    # scheme board resolutions also discuss — verified: all 17 real MOA docs carry
    # one of these; a DRHP-consent board resolution carries none).
    moa_body = any(m in norm for m in (
        "object clauses", "table f", "table a", "the regulations contained in",
        "subscribers to the memorandum", "registered office of the company is"))
    br_anchors = any(a in norm for a in ("board resolution", "resolved that", "resolution passed"))
    if force_type is None and "moa_aoa" in scores and moa_titles and moa_body:
        force_type = "moa_aoa"          # genuine MOA/AOA (titles + constitutional body)
    elif (force_type is None and "board_resolution" in scores and br_anchors
          and moa_titles and not moa_body):
        force_type = "board_resolution"  # a resolution that only references the MOA/AOA

    sorted_scores = sorted(scores.items(), key=lambda x: -x[1][0])
    best_type, (best_score, best_matches) = sorted_scores[0]
    second_score = sorted_scores[1][1][0] if len(sorted_scores) > 1 else 0
    margin = best_score - second_score

    # Confidence: high if the (weighted) best score is large AND there's a margin.
    confidence = min(1.0, (best_score + margin) / 6.0)

    if force_type is not None and best_type != force_type and force_type in scores:
        best_type = force_type
        best_score, best_matches = scores[force_type]
        confidence = max(confidence, 0.9)  # the rule is decisive

    spec_by_type = {s.doc_type: s for s in DOC_SPECS}
    best_spec = spec_by_type[best_type]

    return {
        "doc_type": best_type,
        "display_name": best_spec.display_name,
        "category": best_spec.category,
        "confidence": confidence,
        "matches": best_matches[:6],  # cap for response size
        "all_scores": {k: v[0] for k, v in sorted_scores[:5]},  # top 5 for transparency
    }


# ----------------- LayoutLMv3 (fine-tuned, 23-class, Step 14b) -----------------

_lmv3_model = None
_lmv3_processor = None
_lmv3_device = None
_lmv3_lock = threading.Lock()
_lmv3_unavailable = False  # set True if load fails, to avoid retry storms

_DISPLAY_BY_TYPE = {s.doc_type: s.display_name for s in DOC_SPECS}
_CATEGORY_BY_TYPE = {s.doc_type: s.category for s in DOC_SPECS}


def _get_lmv3():
    global _lmv3_model, _lmv3_processor, _lmv3_device, _lmv3_unavailable
    if _lmv3_model is not None:
        return _lmv3_processor, _lmv3_model, _lmv3_device
    if _lmv3_unavailable:
        return None, None, None
    with _lmv3_lock:
        if _lmv3_model is not None:
            return _lmv3_processor, _lmv3_model, _lmv3_device
        if not (LAYOUTLMV3_DIR / "model.safetensors").exists():
            logger.info("Fine-tuned LayoutLMv3 not found at %s — keyword-only mode.", LAYOUTLMV3_DIR)
            _lmv3_unavailable = True
            return None, None, None
        try:
            import torch
            from transformers import LayoutLMv3ForSequenceClassification, LayoutLMv3Processor

            _lmv3_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            _lmv3_processor = LayoutLMv3Processor.from_pretrained(str(LAYOUTLMV3_DIR), apply_ocr=True)
            model = LayoutLMv3ForSequenceClassification.from_pretrained(str(LAYOUTLMV3_DIR))
            model.to(_lmv3_device).eval()
            _lmv3_model = model
            logger.info("Fine-tuned LayoutLMv3 loaded on %s", _lmv3_device)
            return _lmv3_processor, _lmv3_model, _lmv3_device
        except Exception as e:
            logger.warning("LayoutLMv3 load failed: %s", e)
            _lmv3_unavailable = True
            return None, None, None


def _render_for_lmv3(content: bytes, content_type: str):
    from PIL import Image

    if content_type == PDF_TYPE:
        import fitz
        try:
            with fitz.open(stream=content, filetype="pdf") as pdf:
                if len(pdf) == 0:
                    return None
                pix = pdf[0].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception:
            return None
    elif content_type in IMAGE_TYPES:
        try:
            img = Image.open(io.BytesIO(content)).convert("RGB")
        except Exception:
            return None
    else:
        return None

    if max(img.size) > LAYOUTLMV3_MAX_DIM:
        scale = LAYOUTLMV3_MAX_DIM / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
    return img


def layoutlm_classify(content: bytes, content_type: str) -> dict | None:
    """Run the fine-tuned LayoutLMv3. Returns None if model unavailable/unsupported."""
    processor, model, device = _get_lmv3()
    if model is None:
        return None
    img = _render_for_lmv3(content, content_type)
    if img is None:
        return None
    try:
        import torch

        enc = processor(img, return_tensors="pt", truncation=True, padding="max_length", max_length=512)
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            logits = model(**enc).logits
        probs = torch.softmax(logits, dim=-1)[0]
        idx = int(probs.argmax().item())
        doc_type = model.config.id2label[idx]
        return {
            "doc_type": doc_type,
            "display_name": _DISPLAY_BY_TYPE.get(doc_type, doc_type),
            "confidence": float(probs[idx].item()),
        }
    except Exception as e:
        logger.warning("LayoutLMv3 inference failed: %s", e)
        return None


# Below this LayoutLMv3 softmax confidence, the prediction is treated as
# "inconclusive" rather than a confident agree/disagree. A low-confidence
# argmax over 23 classes is the model effectively saying "not sure" — on real
# documents (whose exact layouts differ from synthetic training) this is common,
# so we don't let it raise a misleading disagreement against the keyword result.
LMV3_CONFIDENCE_FLOOR = 0.50


def classify(text: str, content: bytes, content_type: str) -> dict:
    """Dual-classifier: keyword (explainable, primary) + fine-tuned LayoutLMv3 (secondary).

    The keyword result is the authoritative label (deterministic, auditable).
    LayoutLMv3 is a second opinion: only counted as agree/disagree when it is
    sufficiently confident; otherwise reported as inconclusive.
    """
    kw = keyword_classify(text)
    ml = layoutlm_classify(content, content_type)

    result = dict(kw)
    if ml is None:
        result["ml_doc_type"] = None
        result["ml_confidence"] = 0.0
        result["classifier_agreement"] = None
        return result

    result["ml_doc_type"] = ml["doc_type"]
    result["ml_display_name"] = ml["display_name"]
    result["ml_confidence"] = ml["confidence"]

    if ml["confidence"] < LMV3_CONFIDENCE_FLOOR:
        # Not confident enough to count as a second opinion.
        result["classifier_agreement"] = None
        result["ml_inconclusive"] = True
    else:
        result["classifier_agreement"] = (ml["doc_type"] == kw["doc_type"])
        result["ml_inconclusive"] = False
        # Only a CONFIDENT LayoutLMv3 may promote a label when keyword is unsure.
        if kw["doc_type"] == "unknown" and ml["confidence"] >= 0.6:
            result["doc_type"] = ml["doc_type"]
            result["display_name"] = ml["display_name"]
            result["category"] = _CATEGORY_BY_TYPE.get(ml["doc_type"], "unknown")
            result["confidence"] = ml["confidence"]

    return result
