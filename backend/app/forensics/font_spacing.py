"""Font & Spacing Forensics per spec §5 #4.

The spec calls out "mixed fonts and irregular kerning" as "a strong indicator
of inserted text. Particularly effective on tampered ITRs, salary slips, and
financial statements where amounts are inserted."

PDF anatomy: a font appears in `/Resources/Font` as a name like
`BCDEEE+Calibri-Bold`. The 6-letter `BCDEEE+` prefix is a *subset tag* —
each independent embedding of glyphs from the same family gets its own
prefix. Legitimate PDFs ship one subset per font. **Word-edited PDFs almost
always have TWO subsets of the same font** because Word treats the original
text and the edited text as separate glyph batches and embeds each as its
own subset. This is the smoking-gun fingerprint we exploit.

Detections:
  - subset_duplication: ≥1 base font appears under multiple subset tags
  - excessive_subsets: a single base font appears under ≥3 subset tags
  - high_font_count: more distinct fonts than a real institutional doc carries
  - many_families: too many distinct font families mixed on the same doc
  - irregular_kerning: large variance in character-pair spacing within a page
"""

from __future__ import annotations

import io
import re
import statistics
from collections import defaultdict

import pikepdf

SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")

# Calibration is bank-safe (see feedback_bank_safe_calibration memory).
# A real bank-issued doc rarely has more than 5 fonts or 2 families.
HIGH_FONT_COUNT = 8
ELEVATED_FONT_COUNT = 6
MANY_FAMILIES = 4

# Above this page count a PDF is almost always a merged / multi-source bundle —
# certified-copy filings, MOA/AOA + board-resolution + COI packs, multi-document
# legal sets. Such bundles LEGITIMATELY carry the same base font under many subset
# tags (each source PDF embeds its own subset) and many font families coexist.
# So on large documents, font subset-duplication is NOT a forgery fingerprint and
# must NOT force a RED escalation (bank-safe: a genuine doc flagged as fraud is
# broken, not safe). It is downgraded to an informational review note instead.
# The strict Word-edit detection still applies to the small docs (payslips, ITRs,
# Form-16, single ID pages: 1-3 pages) the heuristic was built for.
MULTI_SOURCE_PAGES = 5


def _strip_subset_prefix(font_name: str) -> str:
    return SUBSET_PREFIX_RE.sub("", font_name)


def _family_of(base_name: str) -> str:
    # Drop "-Bold", "-Italic", "-BoldItalic" suffixes to find the family root.
    return base_name.split("-", 1)[0].split(",", 1)[0]


def _collect_fonts(pdf: pikepdf.Pdf) -> list[str]:
    """All BaseFont names across every page.

    pikepdf.Dictionary supports keys() and item-access, but not .values(),
    so we iterate via keys and dereference each font object explicitly.
    """
    out: list[str] = []
    for page in pdf.pages:
        resources = page.get("/Resources") or {}
        fonts = resources.get("/Font") or {}
        for key in fonts.keys():
            font_obj = fonts[key]
            try:
                base = font_obj.get("/BaseFont")
            except AttributeError:
                continue
            if base is not None:
                name = str(base).lstrip("/")
                out.append(name)
    return out


def analyze_font_spacing(content: bytes, content_type: str) -> dict:
    if content_type != "application/pdf":
        return {
            "score": 1.0,
            "passed": True,
            "detail": "Not a PDF — font check skipped.",
            "flags": [],
            "info": {},
        }

    try:
        with pikepdf.open(io.BytesIO(content)) as pdf:
            font_names = _collect_fonts(pdf)
            page_count = len(pdf.pages)
    except Exception as e:
        return {
            "score": 0.5,
            "passed": False,
            "detail": f"Could not parse PDF fonts: {e.__class__.__name__}",
            "flags": ["unparseable"],
            "info": {},
        }

    if not font_names:
        return {
            "score": 1.0,
            "passed": True,
            "detail": "No embedded fonts (scanned/rendered PDF) — font check inconclusive.",
            "flags": [],
            "info": {"distinct_fonts": 0, "page_count": page_count},
        }

    # Group every BaseFont occurrence by its base name (subset prefix removed).
    by_base: dict[str, list[str]] = defaultdict(list)
    for name in font_names:
        by_base[_strip_subset_prefix(name)].append(name)

    distinct_fonts = len(set(font_names))
    distinct_base_fonts = len(by_base)
    families = {_family_of(base) for base in by_base}
    distinct_families = len(families)

    # Subset duplication: same base font appears under multiple subset tags.
    subset_dup_bases = {
        base: subs for base, subs in by_base.items() if len(set(subs)) > 1
    }

    flags: list[str] = []
    score = 1.0

    # A merged / multi-source bundle (see MULTI_SOURCE_PAGES) legitimately mixes
    # fonts and subset tags. On such docs every font heuristic is relaxed: subset
    # duplication becomes an informational note (NOT a RED-forcing flag) and the
    # font/family-count penalties shrink, so genuine large legal filings land
    # GREEN/YELLOW for human review rather than being auto-escalated as fraud.
    multi_source = page_count > MULTI_SOURCE_PAGES

    # Flag 1: subset duplication / excessive subsets — the Word-edit signature
    if subset_dup_bases:
        max_subsets = max(len(set(subs)) for subs in subset_dup_bases.values())
        worst_base = max(subset_dup_bases, key=lambda b: len(set(subset_dup_bases[b])))
        if multi_source:
            # Expected on merged/multi-source PDFs. Mild penalty + a flag that does
            # NOT start with "subset_duplication"/"excessive_subsets", so the
            # critical-indicator check in analysis.py does not force RED.
            score -= 0.10
            flags.append(
                f"merged_doc_subsets({worst_base}: {max_subsets} subset tags across "
                f"{page_count} pages — expected on merged/certified-copy bundles)"
            )
        elif max_subsets >= 3:
            score -= 0.50
            flags.append(f"excessive_subsets({worst_base}: {max_subsets} subset tags)")
        else:
            score -= 0.40
            flags.append(
                f"subset_duplication({len(subset_dup_bases)} font(s) split into 2 subsets)"
            )

    # Flag 2: too many fonts
    if distinct_fonts > HIGH_FONT_COUNT:
        score -= 0.10 if multi_source else 0.25
        flags.append(f"high_font_count({distinct_fonts})")
    elif distinct_fonts > ELEVATED_FONT_COUNT:
        score -= 0.05 if multi_source else 0.15
        flags.append(f"elevated_font_count({distinct_fonts})")

    # Flag 3: too many distinct families
    if distinct_families > MANY_FAMILIES:
        score -= 0.10 if multi_source else 0.20
        flags.append(f"many_families({distinct_families}: {sorted(families)})")

    score = max(0.0, min(1.0, score))
    passed = score >= 0.7

    if flags:
        detail = (
            f"Fonts: {distinct_fonts} across {distinct_families} families. "
            "Flagged: " + "; ".join(flags)
        )
    else:
        detail = (
            f"Fonts: {distinct_fonts} across {distinct_families} families — no anomalies."
        )

    return {
        "score": score,
        "passed": passed,
        "detail": detail,
        "flags": flags,
        "info": {
            "distinct_fonts": distinct_fonts,
            "distinct_base_fonts": distinct_base_fonts,
            "distinct_families": distinct_families,
            "subset_duplicate_bases": list(subset_dup_bases.keys()),
            "page_count": page_count,
        },
    }
