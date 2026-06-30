"""End-to-end document analysis pipeline.

Pure function callable from either the FastAPI request handler (for sync
testing) or a Celery worker task. Returns a dict matching the public
`AnalyzeResponse` schema (it's converted to the Pydantic model upstream).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.forensics.aadhaar_fields import analyze_aadhaar_fields
from app.forensics.face_match import extract_face_embedding
from app.forensics.photo_forensics import analyze_photo_region
from app.forensics.docx_metadata import analyze_docx_metadata
from app.forensics.bank_statement import analyze_bank_statement
from app.forensics.ela import analyze_ela
from app.forensics.font_spacing import analyze_font_spacing
from app.forensics.mantranet.wrapper import analyze_mantranet
from app.forensics.pdf_metadata import analyze_pdf_metadata
from app.forensics.signature_region import analyze_signature_regions
from app.forensics.stamp_auth import analyze_stamp_auth
from app.services.docx_to_pdf import DocxConversionError, docx_to_pdf_bytes
from app.services.document_classifier import classify as classify_document
from app.services.entity_extraction import extract_entities
from app.services.pan_card import analyze_pan_card
from app.services.pan_fields import extract_pan_fields
from app.services.utility_fields import extract_utility_fields
from app.services.udyam_fields import extract_udyam_fields
from app.services.evidence_report import generate_evidence_report
from app.services.risk_scorer import score_from_signals
from app.services.verification_service import analyze_cross_source
from app.services.text_extraction import extract_text, truncate_for_response
from app.storage import HEATMAP_BUCKET, put_object

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
IMAGE_TYPES = {"image/png", "image/jpeg"}

# ID documents that carry a portrait — embed the face for the case-level
# cross-document photo-match (photo-superimposition / mixed-identity detection).
FACE_DOC_TYPES = {"aadhaar", "pan", "passport", "voter_id", "driving_license"}

# Base weights per signal. Only the signals that actually apply to a given
# document are included at scoring time, then normalised to sum to 1.0. This
# lets signals appear/disappear (DOCX-only, bank-statement-only) cleanly.
WEIGHTS = {
    "DOCX Metadata": 0.14,
    "PDF Metadata": 0.12,
    "Font & Spacing": 0.12,
    "Signature Region (ELA)": 0.10,
    "Stamp Authentication": 0.11,
    "Bank Statement Analysis": 0.12,
    "Error Level Analysis": 0.13,
    "Copy-Move Detection": 0.12,
    "Cross-Source Verification": 0.20,
}

HEATMAP_DIR = Path("/data/heatmaps")
HEATMAP_DIR.mkdir(parents=True, exist_ok=True)


def _tier_for_score(score: int) -> tuple[str, str]:
    if score >= 85:
        return "GREEN", "fast_track"
    if score >= 50:
        return "YELLOW", "underwriter_review"
    return "RED", "fraud_escalation"


def _signal(name: str, score: float, passed: bool, detail: str) -> dict:
    return {"name": name, "score": score, "passed": passed, "detail": detail}


# Document types that are ALWAYS system-generated (payroll / bank / government
# portals) and must never arrive edited in office software — for these an office-
# editor "edit fingerprint" is a hard fraud critical (RED). Every other doc type is
# commonly authored/edited in office software, so the same fingerprint is routed to
# a YELLOW review instead (it cannot tell a benign edit from a fraudulent one).
STRICT_EDIT_DOC_TYPES = {
    "salary_slip", "bank_statement", "form_16", "itr_v", "itr_full",
    "gstr_1", "gstr_3b",
}
# When a critical forgery indicator forces RED, the DISPLAYED Trust Score is forced
# into a low RED band so the UI never shows a contradictory "RED · 100" (a critical
# is a deterministic forgery signal; the XGBoost score is a separate cleanliness
# axis). GRADED, not a flat number: the model's own read is scaled into ~0-20 and
# lowered ~5 per ADDITIONAL independent forgery indicator, so a multi-flag forgery
# scores lower than a single-flag one. CRITICAL_SCORE_BAND = top of that band.
CRITICAL_SCORE_BAND = 20


def _collect_critical_indicators(
    pdf_result: dict | None,
    docx_result: dict | None,
    ela_result: dict | None,
    mt_result: dict | None,
    font_result: dict | None,
    sig_result: dict | None,
    stamp_result: dict | None,
    bank_result: dict | None = None,
    cs_result: dict | None = None,
    aadhaar_result: dict | None = None,
    is_scanned_pdf: bool = False,
    doc_type: str | None = None,
) -> list[str]:
    """See spec §7: RED is triggered by Trust <50 OR critical forgery indicators."""
    indicators: list[str] = []

    if pdf_result is not None:
        pflags = pdf_result.get("flags", [])
        # Benign edit-trace flags (legitimate PDF utilities, a later modified date,
        # a few incremental saves) must NOT stack into a fraud escalation on
        # genuine merged/scanned/edited documents — only STRONG anomalies count.
        benign = ("pdf_utility", "modified_after_creation", "incremental_updates")
        strong = [f for f in pflags if not f.startswith(benign)]
        if any(f.startswith("suspicious_tool") for f in pflags):
            indicators.append("PDF created/edited in suspicious tool")
        elif len(strong) >= 3:
            indicators.append(f"PDF metadata: {len(strong)} concurrent strong flags")

    if docx_result is not None:
        dflags = docx_result.get("flags", [])
        if any(f.startswith("different_editor") for f in dflags):
            indicators.append("DOCX last-modified by different user")
        if any(f.startswith("high_revision") for f in dflags):
            indicators.append("DOCX high revision count (≥5 saves)")
        if len(dflags) >= 3 and not indicators:
            indicators.append(f"DOCX metadata: {len(dflags)} concurrent flags")

    # Font subset-duplication is the office-editor "edit fingerprint" (the same font
    # kept twice after an edit-and-resave). It is a HARD critical (RED) ONLY for doc
    # types that are always system-generated and must never be office-edited
    # (STRICT_EDIT_DOC_TYPES). For everyday doc types that people legitimately author
    # and edit in office software, the same fingerprint cannot distinguish a benign
    # edit from a fraudulent one, so run_full_analysis routes it to a YELLOW review
    # instead — bank-safe (review, never auto-reject a genuine document). Legitimate
    # PDF generators (wkhtmltopdf ITR-V, pdfmake GSTR) also split fonts into subsets,
    # but they are not office-editor producers, so they never reach here.
    if font_result is not None and doc_type in STRICT_EDIT_DOC_TYPES:
        fflags = font_result.get("flags", [])
        office_edited = bool(pdf_result) and any(
            f.startswith("office_editor") for f in pdf_result.get("flags", []))
        if office_edited and any(f.startswith("excessive_subsets") for f in fflags):
            indicators.append("Font: excessive subset duplication (Word-edit fingerprint)")
        elif office_edited and any(f.startswith("subset_duplication") for f in fflags):
            indicators.append("Font: subset duplication (Word/office editor fingerprint)")

    # NOTE: signature-region ELA ratio is NOT a critical (RED-forcing) indicator.
    # The ELA heuristic cannot tell a legitimately embedded scanned signature
    # (routine on certified true copies) from a fraudulent paste — the reliable
    # method (SigNet) is out of scope per spec §10. It is surfaced as a REVIEW
    # signal instead (see _collect_review_indicators) so it caps the tier at
    # YELLOW rather than auto-escalating genuine documents to fraud.

    if stamp_result is not None:
        stflags = stamp_result.get("flags", [])
        if any(f.startswith("reused_stamp") for f in stflags):
            indicators.append("Stamp: same stamp reused/copy-pasted across the document")

    if bank_result is not None:
        bflags = bank_result.get("flags", [])
        if any(f.startswith("balance_mismatch") for f in bflags):
            indicators.append("Bank statement: running-balance break (fabricated/edited transaction)")

    if cs_result is not None:
        if any("name_mismatch" in f for f in cs_result.get("flags", [])):
            indicators.append("Cross-source: name mismatch vs authoritative record (DigiLocker/GSTN/AA)")
        if any("invalid_aadhaar_checksum" in f for f in cs_result.get("flags", [])):
            indicators.append("Aadhaar number fails UIDAI Verhoeff checksum (fabricated number)")

    if aadhaar_result is not None:
        aflags = aadhaar_result.get("flags", [])
        if any(f.startswith("edited_field") for f in aflags):
            edited = [f for f in aflags if f.startswith("edited_field")]
            indicators.append(f"Aadhaar: field edited — ELA spike vs other fields ({', '.join(edited)})")

    # NOTE: ELA is NOT a critical (RED-forcing) indicator. On scanned/photocopied
    # documents, legitimate elements (seals, signatures, logos, photos) are
    # genuinely noisier regions and trip "localised anomaly" detection — false
    # positives. ManTraNet (below) is the spec's authoritative copy-move/splicing
    # detector and stays critical; the ELA score still feeds the XGBoost trust
    # score, and a localised ELA spike is surfaced as a REVIEW signal (caps the
    # tier at YELLOW) via _collect_review_indicators.
    # ManTraNet (the primary copy-move/splicing detector) is critical on born-
    # digital PDFs and uploaded images — where it's reliable and where pasted-image
    # fraud lives. On a SCANNED PDF page it's unreliable both ways (the scan's
    # re-compression mimics splicing → false positives on genuine scans, and a scan
    # smooths over real splices anyway), so there it's a REVIEW signal, not auto-RED.
    if (mt_result is not None and mt_result.get("score", 1.0) < 0.30
            and not is_scanned_pdf):
        indicators.append("ManTraNet: strong forgery probability")

    return indicators


def _collect_review_indicators(
    sig_result: dict | None = None,
    ela_result: dict | None = None,
    font_result: dict | None = None,
    mt_result: dict | None = None,
    is_scanned_pdf: bool = False,
) -> list[str]:
    """Non-critical 'worth a human look' signals. They do NOT force RED, but cap
    the tier at YELLOW (review) so such documents are not GREEN fast-tracked.
    Bank-safe: review, never auto-reject and never auto-approve."""
    review: list[str] = []
    # ManTraNet anomaly on a SCANNED PDF page — unreliable (scan re-compression),
    # so reviewed by a human rather than auto-escalated to fraud.
    if (is_scanned_pdf and mt_result is not None
            and mt_result.get("score", 1.0) < 0.30):
        review.append("Pixel-forensic anomaly on a scanned page — verify source (review)")
    if sig_result is not None:
        sflags = sig_result.get("flags", [])
        if any(f.startswith("critical_signature_ratio") for f in sflags):
            review.append("Signature region: elevated ELA ratio — verify signature (review)")
        elif any(f.startswith("elevated_signature_region") for f in sflags):
            review.append("Signature region: mildly elevated ELA — verify signature (review)")
    if ela_result is not None and ela_result.get("localized_anomaly"):
        review.append("ELA: localised re-compression spike — verify region (review)")
    elif ela_result is not None and ela_result.get("info", {}).get("uniform_noise"):
        review.append("Uniform re-compression noise (scan/photocopy) — verify source (review)")
    # Font subset duplication that ISN'T office-corroborated (handled as a non-
    # critical here) is a benign PDF-generation artifact (wkhtmltopdf/pdfmake) — a
    # review note, not fraud. (When office-edited it is a critical instead.)
    if font_result is not None and any(
        f.startswith(("subset_duplication", "excessive_subsets"))
        for f in font_result.get("flags", [])
    ):
        review.append("Font: subset duplication — likely PDF-generator artifact (review)")
    return review


def run_full_analysis(content: bytes, content_type: str, filename: str) -> dict:
    """Run every forensic + classification pass on a single document.

    Returns a plain dict with the keys of the public AnalyzeResponse schema.
    Safe to invoke from a Celery worker (no FastAPI / UploadFile dependency).
    """
    document_id = str(uuid.uuid4())

    docx_signal = None
    docx_result: dict | None = None
    pdf_result: dict | None = None
    ela_result: dict | None = None
    mt_result: dict | None = None
    font_result: dict | None = None
    sig_result: dict | None = None
    stamp_result: dict | None = None
    forensic_bytes: bytes | None = content
    forensic_type = content_type
    conversion_error = ""

    if content_type == DOCX_TYPE:
        dm = analyze_docx_metadata(content)
        docx_result = dm
        docx_signal = _signal("DOCX Metadata", dm["score"], dm["passed"], dm["detail"])
        try:
            forensic_bytes = docx_to_pdf_bytes(content)
            forensic_type = PDF_TYPE
        except DocxConversionError as e:
            forensic_bytes = None
            conversion_error = str(e)

    if forensic_bytes is not None and forensic_type == PDF_TYPE:
        m = analyze_pdf_metadata(forensic_bytes)
        pdf_result = m
        pdf_signal = _signal("PDF Metadata", m["score"], m["passed"], m["detail"])
    elif forensic_bytes is None:
        pdf_signal = _signal(
            "PDF Metadata", 0.5, False,
            f"DOCX→PDF conversion failed: {conversion_error}",
        )
    else:
        pdf_signal = _signal("PDF Metadata", 1.0, True, "Not a PDF — metadata check skipped.")

    if forensic_bytes is not None and forensic_type in {PDF_TYPE, *IMAGE_TYPES}:
        sig_result = analyze_signature_regions(forensic_bytes, forensic_type)
        sig_signal = _signal(
            "Signature Region (ELA)", sig_result["score"], sig_result["passed"], sig_result["detail"]
        )
    else:
        sig_signal = _signal(
            "Signature Region (ELA)", 1.0, True,
            "Document type not supported for signature region analysis.",
        )

    if forensic_bytes is not None and forensic_type == PDF_TYPE:
        font_result = analyze_font_spacing(forensic_bytes, forensic_type)
        font_signal = _signal(
            "Font & Spacing", font_result["score"], font_result["passed"], font_result["detail"]
        )
    else:
        font_signal = _signal("Font & Spacing", 1.0, True, "Not a PDF — font check skipped.")

    if forensic_bytes is not None and forensic_type in {PDF_TYPE, *IMAGE_TYPES}:
        stamp_result = analyze_stamp_auth(forensic_bytes, forensic_type)
        stamp_signal = _signal(
            "Stamp Authentication", stamp_result["score"], stamp_result["passed"], stamp_result["detail"]
        )
    else:
        stamp_signal = _signal(
            "Stamp Authentication", 1.0, True, "Document type not supported for stamp check."
        )

    if forensic_bytes is not None:
        ela = analyze_ela(forensic_bytes, forensic_type)
        ela_result = ela
        ela_signal = _signal("Error Level Analysis", ela["score"], ela["passed"], ela["detail"])
    else:
        ela = {"heatmap_bytes": None}
        ela_signal = _signal(
            "Error Level Analysis", 0.5, False, "Skipped — DOCX could not be rendered."
        )

    heatmap_url: str | None = None
    if ela.get("heatmap_bytes"):
        heatmap_path = HEATMAP_DIR / f"{document_id}.png"
        heatmap_path.write_bytes(ela["heatmap_bytes"])
        put_object(HEATMAP_BUCKET, f"{document_id}.png", ela["heatmap_bytes"], "image/png")
        heatmap_url = f"/api/heatmap/{document_id}.png"

    if forensic_bytes is not None:
        mt = analyze_mantranet(forensic_bytes, forensic_type)
        mt_result = mt
        mt_signal = _signal(
            "Copy-Move Detection", mt["score"], mt["passed"], mt["detail"]
        )
        if mt.get("heatmap_bytes") and not mt["passed"]:
            heatmap_path = HEATMAP_DIR / f"{document_id}.png"
            heatmap_path.write_bytes(mt["heatmap_bytes"])
            put_object(HEATMAP_BUCKET, f"{document_id}.png", mt["heatmap_bytes"], "image/png")
            heatmap_url = f"/api/heatmap/{document_id}.png"
    else:
        mt_signal = _signal(
            "Copy-Move Detection", 0.5, False, "Skipped — DOCX could not be rendered."
        )

    # ------ Text + classification (needed before the bank-statement analyzer) ------
    text_source_bytes = forensic_bytes if forensic_bytes is not None else content
    text_source_type = forensic_type if forensic_bytes is not None else content_type
    if content_type == DOCX_TYPE:
        extracted_text, text_method = extract_text(content, DOCX_TYPE)
    else:
        extracted_text, text_method = extract_text(text_source_bytes, text_source_type)

    classifier_bytes = forensic_bytes if forensic_bytes is not None else content
    classifier_type = forensic_type if forensic_bytes is not None else content_type
    classification = classify_document(extracted_text, classifier_bytes, classifier_type)
    entities = extract_entities(extracted_text, classification["doc_type"])

    # ------ PAN field detector (extraction robustness, not a forensic) ------
    # On a bad PAN photo whole-page OCR fails -> no PAN -> no DigiLocker check.
    # The detector locates the fields by sight; we OCR the clean PAN crop and
    # recover the number so verification can still run. AI/regex stay primary.
    pan_extract_signal = None
    if classification["doc_type"] == "pan" and forensic_bytes is not None:
        pf = extract_pan_fields(forensic_bytes, forensic_type)
        if pf["detected"]:
            # Recover the PAN ONLY when whole-page OCR found none (the real fail
            # case) — whole-page is more reliable when it does work.
            if pf["pan_number"] and not entities.get("pan"):
                entities["pan"] = [pf["pan_number"]]
            # Recover the cardholder NAME into entities so the cross-document
            # identity check can actually use it — whole-page NER routinely misses
            # an all-caps name buried in noisy ID-card OCR. Only the holder's name
            # (NOT the father's) to avoid manufacturing a spurious second name.
            if pf["name"]:
                persons = entities.get("person", [])
                if not any(pf["name"].strip().lower() == p.strip().lower() for p in persons):
                    entities["person"] = sorted(set(persons) | {pf["name"]})
            recovered = {k: pf[k] for k in ("pan_number", "name", "father", "dob") if pf[k]}
            pan_extract_signal = _signal(
                "PAN Field Detection", 1.0, True,
                f"Located {pf['detected']} by sight; recovered fields: {recovered or 'none'}.")

    # ------ Utility-bill field detector (address-proof extraction, not a forensic) ------
    # A utility bill is the most common address proof. Locate the consumer NAME +
    # ADDRESS by sight and recover them so the cross-document identity check (name)
    # and address-proof (address) work even on noisy scans. Tamper detection stays
    # with ManTraNet/ELA. AI/regex stay primary; this only fills gaps.
    utility_extract_signal = None
    if classification["doc_type"] == "utility_bill" and forensic_bytes is not None:
        uf = extract_utility_fields(forensic_bytes, forensic_type)
        if uf["detected"]:
            if uf["name"]:
                persons = entities.get("person", [])
                if not any(uf["name"].strip().lower() == p.strip().lower() for p in persons):
                    entities["person"] = sorted(set(persons) | {uf["name"]})
            if uf["address"]:
                addrs = entities.get("address", [])
                if uf["address"] not in addrs:
                    entities["address"] = sorted(set(addrs) | {uf["address"]})
            recovered = {k: uf[k] for k in ("name", "address", "consumer_no", "date") if uf[k]}
            utility_extract_signal = _signal(
                "Utility Bill Field Detection", 1.0, True,
                f"Located {uf['detected']} by sight; recovered: {recovered or 'none'}.")

    # ------ Udyam (MSME) QR authentication (URN cross-check; verify via gov-mock) ------
    # The Udyam cert's QR encodes the URN + verify URL. Decode it and cross-check
    # against the printed URN: a QR/printed mismatch is a tamper indicator. The URN
    # is recovered into entities so Cross-Source Verification checks it against the
    # (mock) Udyam registry. QR-absent is informational only (scans drop it).
    udyam_signal = None
    if classification["doc_type"] == "udyam_certificate" and forensic_bytes is not None:
        ud = extract_udyam_fields(forensic_bytes, forensic_type)
        printed = set(entities.get("udyam", []))
        if ud["qr_urn"]:
            if ud["qr_urn"] not in printed:  # recover URN for verification if OCR missed it
                entities["udyam"] = sorted(printed | {ud["qr_urn"]})
            consistent = (not printed) or (ud["qr_urn"] in printed)
            if consistent:
                udyam_signal = _signal("Udyam QR Authentication", 1.0, True,
                    f"QR decoded; URN {ud['qr_urn']} consistent with the certificate.")
            else:
                udyam_signal = _signal("Udyam QR Authentication", 0.5, False,
                    f"QR URN {ud['qr_urn']} does NOT match the printed URN "
                    f"{sorted(printed)} — possible tampering; verify manually.")
        elif ud["qr_present"]:
            udyam_signal = _signal("Udyam QR Authentication", 1.0, True,
                "QR present but no URN decoded (informational).")
        else:
            udyam_signal = _signal("Udyam QR Authentication", 1.0, True,
                "No QR detected (scans/prints often omit it); verification via printed URN.")

    # ------ Single-document photo-region tamper (edited/superimposed photo) ------
    # Catches a digitally edited / swapped photo on ONE ID card (where face-match,
    # which needs 2 docs, can't help): intersect the ManTraNet forgery heatmap with
    # the YOLO-located photo box. Genuine printed photos stay LOW in-box (unlike ELA);
    # a spliced photo spikes. A confident, localized hit is a critical (RED).
    photo_forensic = None
    photo_signal = None
    if forensic_bytes is not None and classification["doc_type"] in ("aadhaar", "pan"):
        photo_forensic = analyze_photo_region(forensic_bytes, forensic_type, classification["doc_type"])
        if photo_forensic.get("checked"):
            photo_signal = _signal(
                "Photo Region Forensics",
                0.0 if photo_forensic["verdict"] == "tampered" else 1.0,
                photo_forensic["verdict"] != "tampered", photo_forensic["detail"])

    # ------ Face embedding for cross-document photo-match (identity) ------
    # A swapped face photo (the #1 ID tamper) is invisible to ELA — a genuine face
    # is naturally high-ELA. So we embed the portrait here; the case-level cross-doc
    # check (cross_doc.py) compares it across the applicant's ID documents. This is
    # purely informational per-document (a single photo can't be matched against
    # anything yet); it never affects the single-doc trust score.
    face_info = None
    face_signal = None
    if forensic_bytes is not None and classification["doc_type"] in FACE_DOC_TYPES:
        fe = extract_face_embedding(forensic_bytes, forensic_type)
        face_info = {"quality": fe["quality"], "prob": fe["prob"]}
        if fe["embedding"] is not None:
            face_info["embedding"] = fe["embedding"]
        _q = {"ok": "captured", "low": "low-quality", "none": "not found",
              "unavailable": "skipped (model unavailable)"}.get(fe["quality"], fe["quality"])
        face_signal = _signal(
            "Face Detection", 1.0, True,
            f"Portrait {_q} (detector confidence {fe['prob']}); "
            f"used for cross-document photo match at case level.")

    # ------ Cross-Source Verification (mock DigiLocker/AA/GSTN/ITR, spec §6) ------
    cs_result = analyze_cross_source(entities, classification["doc_type"])
    cs_signal = _signal(
        "Cross-Source Verification", cs_result["score"], cs_result["passed"], cs_result["detail"]
    )

    # ------ Aadhaar field forensics (uses the trained YOLOv8 6-field detector) ------
    # Run on image uploads (how Aadhaar usually arrive) or anything the classifier
    # already calls an Aadhaar. Self-gates: returns a no-op unless it actually
    # locates a photo + number, so it stays quiet on non-Aadhaar documents.
    aadhaar_signal = None
    aadhaar_result: dict | None = None
    if forensic_bytes is not None and (
            forensic_type in IMAGE_TYPES or classification["doc_type"] == "aadhaar"):
        aadhaar_result = analyze_aadhaar_fields(forensic_bytes, forensic_type)
        if aadhaar_result.get("info"):  # info populated only when an Aadhaar was recognised
            aadhaar_signal = _signal(
                "Aadhaar Field Forensics", aadhaar_result["score"],
                aadhaar_result["passed"], aadhaar_result["detail"])

    # ------ PAN card rule validation (confidence boost; AI stays primary) ------
    # Deterministic structure checks (4th=holder type, 5th=surname letter) +
    # identity confirmation (header + a REAL PAN code, not just the words) +
    # label-anchored cross-check of the AI's name/father/DOB. Runs only when the
    # document is classified as a PAN card.
    pan_signal = None
    pan_result: dict | None = None
    if classification["doc_type"] == "pan":
        pan_result = analyze_pan_card(extracted_text, entities, text_source_bytes, text_source_type)
        pan_signal = _signal(
            "PAN Card Validation", pan_result["score"], pan_result["passed"], pan_result["detail"])

    # ------ Bank Statement Analyzer (only for bank statements) ------
    bank_signal = None
    bank_result: dict | None = None
    if classification["doc_type"] == "bank_statement":
        bank_result = analyze_bank_statement(
            extracted_text, classification["doc_type"], forensic_bytes, forensic_type)
        bank_signal = _signal(
            "Bank Statement Analysis", bank_result["score"], bank_result["passed"], bank_result["detail"]
        )

    # ------ Assemble signals (only those that apply) and score with normalised weights ------
    signals = []
    if docx_signal is not None:
        signals.append(docx_signal)
    signals.extend([pdf_signal, font_signal, sig_signal, stamp_signal])
    if bank_signal is not None:
        signals.append(bank_signal)
    if aadhaar_signal is not None:
        signals.append(aadhaar_signal)
    if pan_signal is not None:
        signals.append(pan_signal)
    if pan_extract_signal is not None:
        signals.append(pan_extract_signal)
    if utility_extract_signal is not None:
        signals.append(utility_extract_signal)
    if udyam_signal is not None:
        signals.append(udyam_signal)
    if photo_signal is not None:
        signals.append(photo_signal)
    if face_signal is not None:
        signals.append(face_signal)
    signals.extend([ela_signal, mt_signal, cs_signal])

    # A scanned/photographed PDF (no usable text layer → had to be OCR'd) — pixel
    # forensics are unreliable there (the scan's re-compression mimics splicing).
    is_scanned_pdf = (forensic_type == PDF_TYPE and text_method == "tesseract-pdf-ocr")

    # Pixel forensics (ELA, ManTraNet) are reliable on IMAGE uploads (photoshopped
    # IDs/payslips, CASIA splices) but NOISY on DOCUMENT PDFs — logos, stamps,
    # signatures and scans spike ELA on perfectly genuine docs. To stop that from
    # dragging genuine documents into YELLOW/RED (and defeating fast-track), the
    # TRUST SCORE neutralises ELA for any PDF input, and ManTraNet too for scanned
    # PDFs. The real signals are still shown and still drive the critical
    # indicators where they're reliable (ManTraNet stays a hard critical for
    # digital PDFs + images). Image uploads keep full-strength pixel forensics.
    neutralise: set[str] = set()
    if forensic_type == PDF_TYPE:
        neutralise.add("Error Level Analysis")
        if is_scanned_pdf:
            neutralise.add("Copy-Move Detection")
    scoring_signals = [({**s, "score": 1.0} if s["name"] in neutralise else s) for s in signals]

    # Trust Score: prefer the trained XGBoost risk scorer (spec §3.2); fall back
    # to normalised weighted scoring if the model isn't trained yet.
    xgb_out = score_from_signals(scoring_signals)
    if xgb_out is not None:
        trust_score = xgb_out["trust_score"]
        scorer_used = "xgboost"
        shap_contributions = xgb_out.get("contributions", {})
    else:
        present_weight = sum(WEIGHTS.get(s["name"], 0.0) for s in scoring_signals) or 1.0
        trust_score_float = sum(s["score"] * WEIGHTS.get(s["name"], 0.0) for s in scoring_signals) / present_weight
        trust_score = int(round(trust_score_float * 100))
        scorer_used = "weighted"
        shap_contributions = {}
    tier, routing = _tier_for_score(trust_score)

    criticals = _collect_critical_indicators(
        pdf_result, docx_result, ela_result, mt_result, font_result, sig_result, stamp_result,
        bank_result, cs_result, aadhaar_result, is_scanned_pdf,
        doc_type=classification["doc_type"],
    )
    # A confident, localized photo-region splice is photo substitution → RED (the
    # ManTraNet whole-image average can dilute a small photo edit below its own
    # threshold, so this localized check is what catches it).
    if photo_forensic and photo_forensic.get("verdict") == "tampered":
        criticals.append("Photo region manipulation — " + photo_forensic["detail"])
    if criticals and tier != "RED":
        tier, routing = "RED", "fraud_escalation"
    # Force the displayed Trust Score into a low RED band (graded by the model's read
    # and the number of forgery indicators) so the UI never shows "RED · 100".
    if criticals:
        graded = round(trust_score * CRITICAL_SCORE_BAND / 100) - 5 * (len(criticals) - 1)
        trust_score = max(1, min(trust_score, graded))

    # Review signals are INFORMATIONAL only — they surface benign-on-real-docs
    # artifacts (scan/logo/stamp/signature ELA spikes, PDF-generator font subsets)
    # in the evidence report, but they do NOT cap the tier. Per spec §7 a tier is
    # GREEN (trust ≥85, no critical), YELLOW (trust 50-84 or verification failure),
    # or RED (trust <50 or critical) — "has a stamp/logo/signature" is not a review
    # trigger. Downgrading every genuine scanned doc to YELLOW for these defeats
    # fast-track (the underwriter would re-read everything). So we keep the notes
    # but let the trust score + criticals decide the tier.
    review_indicators = _collect_review_indicators(
        sig_result, ela_result, font_result, mt_result, is_scanned_pdf)

    # A score-based RED (no critical) whose ONLY sub-threshold forensics are the
    # review-only signals is a genuine document with an unreliable flag, not fraud.
    # Downgrade to YELLOW review so a clean scanned deed / certified copy / portal-
    # generated form isn't auto-escalated. Review-only signals: ELA & signature-
    # region (unreliable on scans — ManTraNet is the authoritative splice critical)
    # and Font (subset duplication here is non-office-corroborated, i.e. a benign
    # PDF-generator artifact; the Word-edit case is a critical and never reaches
    # here). Any OTHER hard failure (PDF, stamp, bank, ManTraNet, cross-source)
    # keeps it RED.
    if tier == "RED" and not criticals and review_indicators:
        REVIEW_SIGNAL_NAMES = {"Error Level Analysis", "Signature Region (ELA)", "Font & Spacing"}
        # On a scanned PDF, ManTraNet (Copy-Move Detection) is unreliable too, so a
        # low score there is review, not a hard failure (consistent with the
        # ManTraNet critical being suppressed for scans above).
        if is_scanned_pdf:
            REVIEW_SIGNAL_NAMES = REVIEW_SIGNAL_NAMES | {"Copy-Move Detection"}
        hard_fail = [s for s in signals
                     if s["score"] < 0.7 and s["name"] not in REVIEW_SIGNAL_NAMES]
        if not hard_fail:
            tier, routing = "YELLOW", "underwriter_review"

    # Office-editor "edit fingerprint" on an everyday (non-system-generated) doc type
    # routes to human REVIEW (YELLOW), not auto-reject (RED): for documents people
    # legitimately author/edit in Word/LibreOffice it cannot tell a benign edit from a
    # fraudulent one. Strict system-generated types already became a RED critical.
    edit_fingerprint = (
        pdf_result is not None
        and any(f.startswith("office_editor") for f in pdf_result.get("flags", []))
        and font_result is not None
        and any(f.startswith(("subset_duplication", "excessive_subsets"))
                for f in font_result.get("flags", []))
    )
    if edit_fingerprint and classification["doc_type"] not in STRICT_EDIT_DOC_TYPES:
        review_indicators.append(
            "Document appears edited in office software (Word/LibreOffice) — verify it "
            "is the original, not a re-saved/edited copy (review)")
        if tier == "GREEN":
            tier, routing = "YELLOW", "underwriter_review"

    # Classifier disagreement (keyword vs a CONFIDENT LayoutLMv3) — surfaced as an
    # informational review note for the underwriter (doc-type ambiguity / possible
    # type-spoofing). Appended AFTER the tier is finalized so it is display-only and
    # never changes the tier (bank-safe; classifier_agreement is False only when
    # LayoutLMv3 is above its confidence floor and still disagrees).
    if classification.get("classifier_agreement") is False:
        review_indicators.append(
            f"Classifier disagreement: keyword type '{classification['doc_type']}' vs "
            f"visual model '{classification.get('ml_doc_type')}' "
            f"({classification.get('ml_confidence', 0.0):.0%} conf) — verify document type (review)"
        )

    summary_extras = ""
    if docx_signal is not None:
        if conversion_error:
            summary_extras = f" DOCX→PDF conversion failed: {conversion_error}"
        else:
            summary_extras = " DOCX converted to PDF via LibreOffice for pixel forensics."
    if criticals:
        summary_extras += (
            " RED override per spec §7 — critical forgery indicators: " + "; ".join(criticals)
        )

    result = {
        "document_id": document_id,
        "filename": filename,
        "trust_score": trust_score,
        "risk_tier": tier,
        "routing": routing,
        "signals": signals,
        "evidence_summary": (
            f"Analysis of {filename}. "
            "PDF metadata + Font/Spacing + Signature-region + Stamp-auth + Bank-analyzer + ELA + ManTraNet active."
            + summary_extras
        ),
        "heatmap_url": heatmap_url,
        "critical_indicators": criticals,
        "review_indicators": review_indicators,
        "extracted_text": truncate_for_response(extracted_text) if extracted_text else None,
        "text_extraction_method": text_method,
        "document_type": classification["doc_type"],
        "document_display_name": classification["display_name"],
        "document_category": classification["category"],
        "classification_confidence": classification["confidence"],
        "classification_matches": classification["matches"],
        "ml_doc_type": classification.get("ml_doc_type"),
        "ml_confidence": classification.get("ml_confidence", 0.0),
        "classifier_agreement": classification.get("classifier_agreement"),
        "ml_inconclusive": classification.get("ml_inconclusive", False),
        "entities": entities,
        "face": face_info,
        "scorer": scorer_used,
        "shap_contributions": shap_contributions,
    }

    # LLM evidence report (LangChain + Ollama, strict-grounded; template fallback).
    report_text, report_source = generate_evidence_report(result)
    result["llm_evidence_report"] = report_text
    result["llm_report_source"] = report_source
    return result
