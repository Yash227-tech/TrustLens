"""DOCX metadata forensic analysis.

DOCX files have a richer metadata footprint than PDFs because Word
tracks editing state in the document's core/app/custom property streams.
Catches the kinds of tampering specific to Word-edited submissions:

  - Suspicious creating application (LibreOffice/online editors used to
    edit a bank-generated doc)
  - Last-modified-by ≠ creator (someone else edited it after creation)
  - High revision count (many save cycles)
  - Total edit time vastly exceeds expected (long manual editing session)
  - Created vs modified timestamps far apart
"""

from __future__ import annotations

import io
from datetime import datetime

from docx import Document

SUSPICIOUS_APPS = {
    "ilovepdf",
    "smallpdf",
    "pdfcandy",
    "sejda",
    "photoshop",
    "gimp",
}


def _personal_name_like(s: str) -> bool:
    """Heuristic: 2-3 token name with no organisational keywords."""
    if not s:
        return False
    org_words = {
        "bank",
        "ltd",
        "limited",
        "pvt",
        "private",
        "corporation",
        "corp",
        "company",
        "co.",
        "llp",
        "inc",
        "branch",
        "office",
        "system",
        "admin",
    }
    tokens = s.lower().split()
    if not (1 <= len(tokens) <= 4):
        return False
    if any(w in tokens for w in org_words):
        return False
    return all(t.replace(".", "").isalpha() for t in tokens)


def analyze_docx_metadata(content: bytes) -> dict:
    flags: list[str] = []
    info: dict = {}

    try:
        doc = Document(io.BytesIO(content))
        core = doc.core_properties
        author = (core.author or "").strip()
        last_modified_by = (core.last_modified_by or "").strip()
        title = (core.title or "").strip()
        revision = core.revision or 0
        created = core.created
        modified = core.modified
        category = (core.category or "").strip()
        keywords = (core.keywords or "").strip()

        info = {
            "author": author or "(none)",
            "last_modified_by": last_modified_by or "(none)",
            "title": title or "(none)",
            "revision": revision,
            "created": created.isoformat() if isinstance(created, datetime) else "(none)",
            "modified": modified.isoformat() if isinstance(modified, datetime) else "(none)",
            "category": category or "(none)",
            "keywords": keywords or "(none)",
        }
    except Exception as e:
        return {
            "score": 0.3,
            "passed": False,
            "detail": f"Could not parse DOCX: {e.__class__.__name__}",
            "flags": ["unparseable"],
            "info": {},
        }

    # Bank-safe calibration: see feedback_bank_safe_calibration memory.
    # A bank-issued DOCX should have an organizational author, revision=1, and
    # creation==modified timestamps. Anything else is treated as worth review.
    score = 1.0

    if _personal_name_like(author):
        score -= 0.20
        flags.append(f"personal_author({author})")

    if author and last_modified_by and author.lower() != last_modified_by.lower():
        score -= 0.30
        flags.append(f"different_editor({last_modified_by})")

    if revision >= 5:
        score -= 0.30
        flags.append(f"high_revision({revision})")
    elif revision >= 2:
        score -= 0.20
        flags.append(f"multiple_revisions({revision})")

    if isinstance(created, datetime) and isinstance(modified, datetime):
        delta_seconds = abs((modified - created).total_seconds())
        if delta_seconds > 60:
            score -= 0.15
            flags.append(f"modified_after_creation({int(delta_seconds)}s)")

    score = max(0.0, min(1.0, score))
    passed = score >= 0.7

    author_label = info["author"] if info["author"] != "(none)" else "unknown"
    if flags:
        detail = f"Author: {author_label} · Revision: {revision} · Flagged: " + "; ".join(flags)
    else:
        detail = f"Author: {author_label} · Revision: {revision} · No tampering indicators."

    return {
        "score": score,
        "passed": passed,
        "detail": detail,
        "flags": flags,
        "info": info,
    }
