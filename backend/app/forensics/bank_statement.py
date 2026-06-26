"""Bank Statement Analyzer (spec §3.2 + §6).

"Pandas + custom rules — Parses bank statements; flags fabricated transactions,
round-number anomalies, mismatched running balances, and unusual salary credit
patterns within the statement itself."

Two parsers:
  * REAL statements (digital PDF) — a COORDINATE-AWARE table parser
    (`_parse_pdf_table`) reconstructs rows from word x/y positions, assigning
    each amount to the Debit / Credit / Balance column by its x-position. Handles
    DD-Mon-YYYY dates, bare (un-prefixed) amounts, wrapped particulars and
    multi-page tables — the common Indian bank-statement layout.
  * SYNTHETIC / text-only — the line-based `_parse_transactions` fallback.

Checks: running-balance integrity, round-number anomalies, duplicate rows,
irregular salary credits.

BANK-SAFE design: `balance_mismatch` is a RED-forcing critical, so it is raised
ONLY when the parse is COMPLETE (every transaction-date row parsed cleanly and
the opening balance was found). On an incomplete/ambiguous parse the analyzer
returns "inconclusive" (no flag) rather than risk a false fraud escalation on a
genuine statement.

Returns the standard forensic dict {score, passed, detail, flags, info}.
"""

from __future__ import annotations

import re

import pandas as pd

PDF_TYPE = "application/pdf"

# ---- text-mode (synthetic) patterns ----
AMOUNT_RE = re.compile(r"(?:Rs\.?|₹|INR)\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")
BALANCE_TOLERANCE = 1.0  # rupees

# ---- coordinate-mode (real PDF) patterns ----
_NUM_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
_MON_DATE_RE = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{2,4}$")


def _amt(s: str) -> float:
    return float(s.replace(",", ""))


# =================== coordinate-aware parser (real statements) ===================
def _parse_pdf_table(content: bytes) -> dict | None:
    """Reconstruct the transaction table from word positions. Returns
    {txns, opening, closing, date_starts, parse_complete} or None if the document
    has no recognisable Debit/Credit/Balance transaction table."""
    try:
        import fitz
    except Exception:
        return None
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception:
        return None

    # 1) column centres from the transaction-table header
    cols = None
    for page in doc:
        by_y: dict[float, list] = {}
        for w in page.get_text("words"):
            by_y.setdefault(round(w[1] / 3) * 3, []).append(w)
        for row in by_y.values():
            texts = {w[4]: (w[0] + w[2]) / 2 for w in row}
            if {"Debit", "Credit", "Balance", "Particulars"} <= set(texts):
                cols = {"debit": texts["Debit"], "credit": texts["Credit"],
                        "balance": texts["Balance"]}
                break
        if cols:
            break
    if not cols:
        return None

    # 2) opening / closing from the summary band (Opening ... Closing Balance)
    opening = closing = None
    for page in doc:
        by_y = {}
        for w in page.get_text("words"):
            by_y.setdefault(round(w[1] / 3) * 3, []).append(w)
        ys = sorted(by_y)
        for idx, y in enumerate(ys):
            line = " ".join(w[4] for w in sorted(by_y[y], key=lambda w: w[0]))
            if "Opening" in line and "Closing" in line and "Balance" in line:
                for y2 in ys[idx + 1: idx + 4]:
                    nums = [_amt(w[4]) for w in sorted(by_y[y2], key=lambda w: w[0])
                            if _NUM_RE.match(w[4])]
                    if len(nums) >= 4:
                        opening, closing = nums[0], nums[-1]
                        break
            if opening is not None:
                break
        if opening is not None:
            break

    # 3) transactions — a row begins at a Transaction-Date token at the far left
    raw: list[dict] = []
    date_starts = 0
    for page in doc:
        by_y = {}
        for w in page.get_text("words"):
            by_y.setdefault(round(w[1] / 2) * 2, []).append(w)
        cur = None
        for y in sorted(by_y):
            row = sorted(by_y[y], key=lambda w: w[0])
            if row and row[0][0] < 70 and _MON_DATE_RE.match(row[0][4]):
                date_starts += 1
                if cur:
                    raw.append(cur)
                cur = {"date": row[0][4], "amts": [], "particulars": []}
            if cur is None:
                continue
            for w in row:
                t = w[4]
                cx = (w[0] + w[2]) / 2
                if _NUM_RE.match(t):
                    col = min(cols, key=lambda c: abs(cx - cols[c]))
                    cur["amts"].append((col, _amt(t)))
                elif not _MON_DATE_RE.match(t) and 130 < w[0] < 360:
                    cur["particulars"].append(t)
        if cur:
            raw.append(cur)

    # 4) keep only cleanly-structured rows: exactly 1 balance + (debit XOR credit)
    txns = []
    for t in raw:
        bal = [v for c, v in t["amts"] if c == "balance"]
        deb = [v for c, v in t["amts"] if c == "debit"]
        cred = [v for c, v in t["amts"] if c == "credit"]
        if len(bal) == 1 and (len(deb) + len(cred)) == 1:
            txns.append({"date": t["date"], "particulars": " ".join(t["particulars"]),
                         "debit": (deb[0] if deb else 0.0),
                         "credit": (cred[0] if cred else 0.0), "balance": bal[0]})

    parse_complete = bool(txns) and len(txns) == date_starts and opening is not None
    return {"txns": txns, "opening": opening, "closing": closing,
            "date_starts": date_starts, "parse_complete": parse_complete}


# =================== text parser (synthetic / fallback) ===================
def _to_amount(line: str) -> float | None:
    s = line.strip()
    if s == "-" or s == "":
        return 0.0
    m = AMOUNT_RE.search(s)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _opening_balance(lines: list[str]) -> float | None:
    for i, ln in enumerate(lines):
        if "opening balance" in ln.lower():
            for nxt in lines[i + 1: i + 3]:
                v = _to_amount(nxt)
                if v not in (None, 0.0) or "Rs" in nxt:
                    a = _to_amount(nxt)
                    if a is not None:
                        return a
    return None


def _parse_transactions(text: str) -> pd.DataFrame:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rows = []
    i = 0
    while i < len(lines):
        if DATE_RE.match(lines[i]):
            date = lines[i]
            j = i + 1
            particulars = None
            money_tokens: list[float] = []
            while j < len(lines) and not DATE_RE.match(lines[j]):
                low = lines[j].lower()
                if "closing balance" in low:
                    break
                amt = _to_amount(lines[j])
                if amt is None:
                    if particulars is None:
                        particulars = lines[j]
                else:
                    money_tokens.append(amt)
                if len(money_tokens) >= 3 and particulars is not None:
                    break
                j += 1
            if len(money_tokens) >= 3:
                debit, credit, balance = money_tokens[0], money_tokens[1], money_tokens[2]
                rows.append({"date": date, "particulars": particulars or "",
                             "debit": debit, "credit": credit, "balance": balance})
            i = j
        else:
            i += 1
    return pd.DataFrame(rows)


# =================== shared anomaly checks ===================
def _anomaly_checks(df: pd.DataFrame) -> tuple[float, list[str]]:
    """Round-number / duplicate / irregular-salary checks (non-critical)."""
    score = 0.0
    flags: list[str] = []
    amts = pd.concat([df["debit"], df["credit"]])
    amts = amts[amts > 0]
    if len(amts) > 0:
        round_share = float((amts % 1000 == 0).mean())
        if round_share >= 0.6:
            score -= 0.20
            flags.append(f"round_number_anomaly({round_share:.0%} end in 000)")
    dup = int(df.duplicated(subset=["date", "particulars", "debit", "credit"]).sum())
    if dup:
        score -= min(0.30, 0.15 * dup)
        flags.append(f"duplicate_transactions({dup})")
    sal = df[df["particulars"].str.lower().str.contains("salary", na=False)]
    sal_credits = sal["credit"][sal["credit"] > 0]
    if len(sal_credits) >= 2:
        spread = (sal_credits.max() - sal_credits.min()) / max(1.0, sal_credits.mean())
        if spread > 0.5:
            score -= 0.15
            flags.append(f"irregular_salary(spread {spread:.0%})")
    return score, flags


def _result(score, passed, detail, flags, info):
    return {"score": max(0.0, min(1.0, score)), "passed": passed,
            "detail": detail, "flags": flags, "info": info}


def analyze_bank_statement(text: str, doc_type: str | None,
                           content: bytes | None = None,
                           content_type: str | None = None) -> dict:
    if doc_type != "bank_statement":
        return _result(1.0, True, "Not a bank statement — analyzer skipped.", [], {})

    # ---- Prefer the coordinate parser on a real PDF statement ----
    pdf = _parse_pdf_table(content) if (content and content_type == PDF_TYPE) else None

    if pdf and len(pdf["txns"]) >= 2:
        txns = pdf["txns"]
        df = pd.DataFrame(txns)
        opening = pdf["opening"]
        closing = pdf["closing"]
        n = len(txns)

        if not pdf["parse_complete"]:
            # Some date-rows didn't parse cleanly → a running-balance check could
            # produce FALSE breaks. Stay inconclusive (bank-safe).
            return _result(1.0, True,
                           f"Bank statement: {n}/{pdf['date_starts']} rows parsed cleanly — "
                           "transaction table only partially structured, balance check inconclusive.",
                           [], {"transactions": n, "parse_complete": False})

        # running-balance integrity over a COMPLETE parse
        prev = opening
        broken = 0
        for t in txns:
            expected = prev + t["credit"] - t["debit"]
            if abs(expected - t["balance"]) > BALANCE_TOLERANCE:
                broken += 1
            prev = t["balance"]
        reconciles = (closing is None) or abs(txns[-1]["balance"] - closing) <= BALANCE_TOLERANCE

        score = 1.0
        flags: list[str] = []
        if broken == 0 and reconciles:
            detail = (f"{n} transactions parsed; running balance is internally consistent and "
                      f"reconciles opening→closing — verified.")
        elif broken > 0:
            score -= min(0.55, 0.25 + 0.1 * broken)
            flags.append(f"balance_mismatch({broken} row(s))")
            detail = f"{n} transactions parsed. Flagged: balance_mismatch({broken} row(s))."
        else:
            # complete parse, steps consistent, but final != closing → don't escalate
            return _result(1.0, True,
                           f"{n} transactions parsed; steps consistent but did not reconcile to "
                           "closing balance — inconclusive.", [],
                           {"transactions": n, "parse_complete": True})

        ds, df_flags = _anomaly_checks(df)
        score += ds
        flags += df_flags
        if df_flags and broken == 0:
            detail = f"{n} transactions parsed. Flagged: " + "; ".join(flags)
        return _result(score, score >= 0.7, detail, flags,
                       {"transactions": n, "opening_balance": opening,
                        "closing_balance": closing, "balance_breaks": broken,
                        "parse_complete": True})

    # ---- Fallback: text parser (synthetic / non-coordinate statements) ----
    df = _parse_transactions(text)
    if len(df) < 2:
        return _result(1.0, True,
                       f"Bank statement detected but only {len(df)} transactions parsed — inconclusive.",
                       [], {"transactions": int(len(df))})

    opening = _opening_balance(text.splitlines())
    flags = []
    score = 1.0
    broken = 0
    prev = opening
    for _, r in df.iterrows():
        if prev is not None:
            expected = prev + r["credit"] - r["debit"]
            if abs(expected - r["balance"]) > BALANCE_TOLERANCE:
                broken += 1
        prev = r["balance"]
    if broken:
        score -= min(0.55, 0.25 + 0.1 * broken)
        flags.append(f"balance_mismatch({broken} row(s))")
    ds, df_flags = _anomaly_checks(df)
    score += ds
    flags += df_flags

    score = max(0.0, min(1.0, score))
    if flags:
        detail = f"{len(df)} transactions parsed. Flagged: " + "; ".join(flags)
    else:
        detail = f"{len(df)} transactions parsed — running balance consistent, no anomalies."
    return _result(score, score >= 0.7, detail, flags,
                   {"transactions": int(len(df)), "opening_balance": opening,
                    "balance_breaks": broken})
