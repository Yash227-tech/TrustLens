"""PDF metadata forensic analysis.

Extracts the document's producer/creator software, timestamps, author,
and incremental update markers, then scores the document against a set
of tampering heuristics. Higher score = more trustworthy.
"""

from __future__ import annotations

import io
from datetime import datetime

import pikepdf

# Image editors. Their fingerprint on a *document* is a strong forgery signal —
# a genuine financial/legal PDF is not produced by Photoshop/GIMP. These remain a
# critical, RED-forcing indicator (flag prefix "suspicious_tool", see analysis.py).
IMAGE_FORGERY_TOOLS = {
    "photoshop",
    "gimp",
    "imagemagick",
    "inkscape",
}

# Ubiquitous, legitimate PDF utilities used constantly to merge / compress /
# convert / scan genuine documents (Ghostscript powers many scanners & Linux
# print-to-PDF; iLovePDF/Smallpdf/Sejda are everyday consumer tools). Their
# presence is NOT fraud — flagging them as critical false-RED'd real certified
# MOA/AOA bundles. Treated as a moderate, NON-critical flag instead (still lowers
# the score and surfaces for review; real tampering is caught by ELA/ManTraNet/
# font + the trained scorer). Bank-safe: review, not auto-escalate.
PDF_UTILITIES = {
    "ghostscript",
    "pdfescape",
    "ilovepdf",
    "smallpdf",
    "pdfcandy",
    "sejda",
    "wkhtmltopdf",
    "pdftk",
}

# Office editors are LEGITIMATE for many docs (letters, contracts) but rarely
# the original producer for system-generated financial docs (bank statements,
# payslips, ITRs, GSTRs). Their presence on a financial-looking doc is a
# moderate flag — someone may have opened a system-generated PDF in Word,
# edited it, and re-exported.
OFFICE_EDITORS = {
    "microsoft word",
    "microsoft® word",
    "ms word",
    "libreoffice",
    "openoffice",
    "wps office",
    "pages",
    "google docs",
}


def _parse_pdf_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    if s.startswith("D:"):
        s = s[2:]
    try:
        return datetime.strptime(s[:14], "%Y%m%d%H%M%S")
    except (ValueError, IndexError):
        return None


def _docinfo_str(docinfo, key: str) -> str:
    value = docinfo.get(key)
    return str(value) if value is not None else ""


def analyze_pdf_metadata(content: bytes) -> dict:
    flags: list[str] = []
    info: dict = {}

    try:
        with pikepdf.open(io.BytesIO(content)) as pdf:
            docinfo = pdf.docinfo or {}
            producer = _docinfo_str(docinfo, "/Producer").lower()
            creator = _docinfo_str(docinfo, "/Creator").lower()
            author = _docinfo_str(docinfo, "/Author")
            title = _docinfo_str(docinfo, "/Title")
            created_raw = _docinfo_str(docinfo, "/CreationDate")
            modified_raw = _docinfo_str(docinfo, "/ModDate")
            page_count = len(pdf.pages)

        info = {
            "producer": producer or "(none)",
            "creator": creator or "(none)",
            "author": author or "(none)",
            "title": title or "(none)",
            "created": created_raw or "(none)",
            "modified": modified_raw or "(none)",
            "pages": page_count,
        }

        incremental_updates = max(0, content.count(b"%%EOF") - 1)

    except Exception as e:
        return {
            "score": 0.3,
            "passed": False,
            "detail": f"Could not parse PDF: {e.__class__.__name__}",
            "flags": ["unparseable"],
            "info": {},
        }

    score = 1.0

    combined_tools = f"{producer} {creator}"
    matched_forgery = [t for t in IMAGE_FORGERY_TOOLS if t in combined_tools]
    if matched_forgery:
        score -= 0.40
        flags.append(f"suspicious_tool({','.join(matched_forgery)})")

    matched_utility = [t for t in PDF_UTILITIES if t in combined_tools]
    if matched_utility:
        score -= 0.15
        flags.append(f"pdf_utility({','.join(matched_utility)})")

    matched_editors = [e for e in OFFICE_EDITORS if e in combined_tools]
    if matched_editors:
        score -= 0.30
        flags.append(f"office_editor({matched_editors[0]})")

    if not producer and not creator:
        score -= 0.20
        flags.append("metadata_stripped")

    # modified-after-creation is WEAK evidence by itself — every reviewed, signed
    # or re-exported genuine PDF is modified after it was created. Small nudge, not
    # a sinker (a real edited 'draft' must not read as fraud).
    created = _parse_pdf_date(created_raw)
    modified = _parse_pdf_date(modified_raw)
    if created and modified:
        delta_seconds = abs((modified - created).total_seconds())
        if delta_seconds > 60:
            score -= 0.05
            flags.append(f"modified_after_creation({int(delta_seconds)}s)")

    # A couple of incremental updates are NORMAL (each save / e-signature appends
    # one). Only an EXCESSIVE count suggests heavy editing: the first two are free,
    # the penalty grows only beyond that. The flag is still recorded for
    # transparency but the first two do not lower the score.
    if incremental_updates >= 1:
        if incremental_updates >= 3:
            score -= 0.10 * min(incremental_updates - 2, 3)
        flags.append(f"incremental_updates({incremental_updates})")

    score = max(0.0, min(1.0, score))
    passed = score >= 0.7

    producer_label = info["producer"] if info["producer"] != "(none)" else "unknown"
    if flags:
        detail = f"Producer: {producer_label} · Flagged: " + "; ".join(flags)
    else:
        detail = (
            f"Producer: {producer_label} · "
            f"Pages: {info['pages']} · No tampering indicators."
        )

    return {
        "score": score,
        "passed": passed,
        "detail": detail,
        "flags": flags,
        "info": info,
    }
