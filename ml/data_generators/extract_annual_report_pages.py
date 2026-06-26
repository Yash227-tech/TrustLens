"""Extract real financial-statement pages from annual-report PDFs.

An annual report is one large PDF containing the balance sheet, P&L, cash-flow
statement and auditor's report as SECTIONS. This script scans each report,
finds the pages that actually contain each statement (strong keyword combos,
to skip the contents page and the notes), and saves them as labelled
single-page PDFs for LayoutLMv3 training.

Outputs:
  /data/raw/external/real_docs/<doc_type>/<company>_<n>.pdf
  /data/raw/external/real_docs/labels.jsonl   (training manifest, source="real")
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz  # PyMuPDF

SRC = Path("/data/raw/external/annual_report")
OUT = Path("/data/raw/external/real_docs")
MAX_PER_TYPE_PER_REPORT = 3  # cap so notes pages don't flood one type


def has_numbers(t: str) -> bool:
    return len(re.findall(r"\d[\d,]{2,}", t)) >= 5


HEADING_LINES = 15  # title sits within the first lines, after page no./company banner

# Heading phrases that mark a page we must NOT collect, even if a title also
# appears: notes pages and the Statement of Changes in Equity narrate other
# statements and carry line items ("Cash Flow Hedge Reserve") that trip keywords.
_EXCLUDE_HEADING = (
    "notes to",
    "notes forming part",
    "significant accounting policies",
    "statement of changes in equity",
    "changes in equity",
)

# Canonical statement TITLES, in priority order. We assign a page to the first
# of these whose title phrase appears as (a substring of) one of the heading
# lines — respecting the page's own title order. Auditor's report is first
# because its narrative names every other statement.
_TITLE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("audited_financials", ("independent auditor", "auditor's report",
                            "auditors' report", "report on the audit of")),
    ("cash_flow_statement", ("cash flow statement", "statement of cash flow",
                             "statement of cash flows", "cash flows", "cash flow")),
    ("profit_and_loss", ("statement of profit and loss", "profit and loss account",
                         "statement of profit or loss", "profit and loss", "profit or loss")),
    ("balance_sheet", ("balance sheet",)),
]


def _confirm(doc_type: str, full: str) -> bool:
    """Strict STRUCTURAL confirmation — kills prose mentions (CFO certifications,
    governance annexures, OCI notes) that merely name a statement."""
    if doc_type == "audited_financials":
        return "in our opinion" in full
    if doc_type == "cash_flow_statement":
        # A real cash-flow statement always has all three activity sections.
        return ("operating activities" in full and "investing activities" in full
                and "financing activities" in full)
    if doc_type == "profit_and_loss":
        # Real P&L: a revenue line AND a profit line (corporate or banking form).
        has_rev = ("revenue from operations" in full or "interest earned" in full
                   or "interest income" in full)
        has_profit = ("profit before tax" in full or "profit for the" in full
                      or "profit before exceptional" in full)
        return has_rev and has_profit
    if doc_type == "balance_sheet":
        # Real balance sheet: both sides total out.
        return "total assets" in full and (
            "total equity and liabilities" in full or "total liabilities" in full
            or "capital and liabilities" in full)
    return False


def classify_page(t: str) -> str | None:
    """Return a doc_type only when the page HEADING titles it AND the body has the
    statement's structure. Precision over recall — ambiguous pages are skipped."""
    if not has_numbers(t):
        return None

    lines = [ln.strip().lower() for ln in t.splitlines() if ln.strip()][:HEADING_LINES]
    head = "\n".join(lines)
    full = t.lower()

    if any(x in head for x in _EXCLUDE_HEADING):
        # ...unless it's an auditor's report (those never are notes pages but may
        # mention "changes in equity" in the list of audited statements).
        if not (("independent auditor" in head or "report on the audit of" in head)
                and "in our opinion" in full):
            return None

    # First heading line that carries a known title decides the type.
    for line in lines:
        for doc_type, phrases in _TITLE_RULES:
            if any(p in line for p in phrases):
                return doc_type if _confirm(doc_type, full) else None
    return None


def company_of(name: str) -> str:
    m = re.search(r"AR_\d+_([A-Z]+)_", name)
    return m.group(1) if m else name[:8]


def main():
    if not SRC.exists():
        raise SystemExit(f"Not found: {SRC}")
    for t in ["balance_sheet", "profit_and_loss", "cash_flow_statement", "audited_financials"]:
        (OUT / t).mkdir(parents=True, exist_ok=True)

    manifest = OUT / "labels.jsonl"
    counts: dict[str, int] = {}
    total = 0
    with manifest.open("w", encoding="utf-8") as mf:
        for pdf_path in sorted(SRC.glob("*.pdf")):
            comp = company_of(pdf_path.name)
            per_report: dict[str, int] = {}
            try:
                doc = fitz.open(pdf_path)
            except Exception as e:
                print(f"  ! {pdf_path.name}: {e.__class__.__name__}")
                continue
            for pno in range(len(doc)):
                try:
                    t = doc[pno].get_text().lower()
                except Exception:
                    continue
                dt = classify_page(t)
                if dt is None:
                    continue
                if per_report.get(dt, 0) >= MAX_PER_TYPE_PER_REPORT:
                    continue
                per_report[dt] = per_report.get(dt, 0) + 1
                idx = counts.get(dt, 0)
                counts[dt] = idx + 1
                out_pdf = OUT / dt / f"{comp}_{idx:03d}.pdf"
                single = fitz.open()
                single.insert_pdf(doc, from_page=pno, to_page=pno)
                single.save(str(out_pdf))
                single.close()
                mf.write(json.dumps({
                    "path": f"raw/external/real_docs/{dt}/{out_pdf.name}",
                    "doc_type": dt, "category": "financial",
                    "label": "clean", "source": "real",
                }) + "\n")
                total += 1
            doc.close()
            print(f"  {pdf_path.name[:40]:40s} -> {per_report}")

    print(f"\nExtracted {total} real statement pages.")
    for k, v in sorted(counts.items()):
        print(f"  {k:22s} {v}")
    print(f"Manifest: {manifest}")


if __name__ == "__main__":
    main()
