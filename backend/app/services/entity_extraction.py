"""Entity extraction for cross-document consistency (spec §6).

Two sources, combined:
  1. REGEX (local, deterministic, 100% accurate) for structured Indian IDs —
     these are the fraud-catching fields: PAN, GSTIN, Aadhaar, IFSC, account
     numbers, amounts, dates.
  2. NER MICROSERVICE (en_core_web_trf, isolated) for contextual entities —
     person names, organisations, locations. Called over HTTP; degrades
     gracefully to empty lists if the service is unavailable.

Returns a dict of entity_type -> sorted unique list of string values.
"""

from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

NER_URL = os.environ.get("NER_URL", "http://ner:8500/ner")
NER_TIMEOUT = 20.0

# --- Regex patterns for Indian structured identifiers ---
PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
GSTIN_RE = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")
AADHAAR_RE = re.compile(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b")
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
# Udyam Registration Number: UDYAM-<2-letter state>-<2 digit>-<7 digit>.
UDYAM_RE = re.compile(r"\bUDYAM-[A-Z]{2}-\d{2}-\d{7}\b", re.IGNORECASE)
ACCOUNT_RE = re.compile(r"\b\d{11,18}\b")
# Amounts like Rs. 1,50,000 or ₹50,000.00 or INR 12345
AMOUNT_RE = re.compile(r"(?:Rs\.?|₹|INR)\s?[\d,]+(?:\.\d{1,2})?", re.IGNORECASE)
# Dates dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd
DATE_RE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
# ITR / ITR-V acknowledgement number (a 12–16 digit number after the label) —
# verified against the Income Tax e-Filing portal (spec §6).
ACK_RE = re.compile(
    r"acknowledge(?:ment)?\s*(?:number|no\.?)?\s*[:\-]*\s*(\d{12,16})", re.IGNORECASE)
# Indian passport number: one letter + 7 digits (e.g. H9137927). Anchored on the
# "passport" label — the bare 1-letter+7-digit pattern is too generic to extract
# context-free without false positives. Used for cross-document consistency
# (spec §6): matching the applicant's passport across their submitted documents.
PASSPORT_RE = re.compile(
    r"passport\s*(?:file\s*)?(?:no\.?|number)?\s*[:\-]*\s*[\"']?\s*([A-Za-z][0-9]{7})\b",
    re.IGNORECASE)


# --- Aadhaar Verhoeff checksum (UIDAI uses the Verhoeff algorithm) ---
# Every genuine 12-digit Aadhaar number's last digit is a Verhoeff check digit.
# A number that matches the format but fails this checksum is fabricated — a
# deterministic, offline fraud signal (no model, no network).
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def aadhaar_checksum_valid(number: str) -> bool:
    """True if a 12-digit Aadhaar number passes the UIDAI Verhoeff checksum."""
    digits = re.sub(r"\D", "", number or "")
    if len(digits) != 12:
        return False
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def _norm_amount(s: str) -> str:
    digits = re.sub(r"[^\d.]", "", s)
    return digits


def _parse_mrz(text: str) -> tuple[set[str], set[str]]:
    """Parse an ICAO 9303 TD3 passport MRZ — the machine-readable zone a real
    passport reader uses. Deterministic and far more reliable than NER on a noisy
    ID scan. Returns (doc_numbers, names):

      * Line 2 starts with the DOCUMENT NUMBER (Indian: one letter + 7 digits)
        terminated by a '<' filler, e.g. `J7335300<6IND...`.
      * Line 1 carries the NAME as `P<ISS<SURNAME<<GIVEN<NAMES<<<` — surname and
        given names split by '<<', spaces are '<'.

    Both feed cross-document consistency (spec §6); the visual "Passport No."
    label regex remains a fallback for the number.
    """
    numbers: set[str] = set()
    names: set[str] = set()
    for raw in text.splitlines():
        s = re.sub(r"\s", "", raw)
        if len(s) < 20 or s.count("<") < 2:
            continue
        if sum(c.isalnum() or c == "<" for c in s) / len(s) < 0.6:
            continue  # not an MRZ-like line
        # Line 2: document number = first field before the filler.
        head = re.sub(r"[^A-Z0-9]", "", s.split("<", 1)[0].upper())
        if re.fullmatch(r"[A-Z][0-9]{7}", head):
            numbers.add(head)
        # Line 1: the name line begins with the passport type 'P'.
        if s[:1] == "P":
            m = re.match(r"P[A-Z<]?([A-Z]{3})(.+)", s)
            if m:
                surname, _, given = m.group(2).partition("<<")
                raw_name = surname.replace("<", " ") + " " + given.replace("<", " ")
                toks: list[str] = []
                for w in raw_name.split():
                    w = re.sub(r"[^A-Z]", "", w)
                    # The MRZ name is '<'-padded to a fixed width; OCR often reads
                    # that filler as a run of one repeated letter (e.g. KKKK). Such
                    # a token marks the end of the real name — stop there.
                    if len(w) >= 2 and len(set(w)) == 1:
                        break
                    if w:
                        toks.append(w)
                full = " ".join(toks).title()
                if len(full) >= 4 and re.search(r"[A-Za-z]{2,}", full):
                    names.add(full)
    return numbers, names


def _regex_entities(text: str, doc_type: str | None = None) -> dict[str, list[str]]:
    pans = sorted(set(PAN_RE.findall(text)))
    gstins = sorted(set(GSTIN_RE.findall(text)))
    # Aadhaar: a 12-digit number is only an Aadhaar when an Aadhaar/UIDAI label is
    # near it, OR the document itself is an Aadhaar card (doc_type=="aadhaar").
    # GROUPING ALONE (a space, "XXXX XXXX XXXX") is NOT sufficient: financial
    # statements / annual reports are full of tabular numbers like "2024 1234 5678"
    # (a year + two 4-digit cells) that match the spaced-Aadhaar regex, fail the
    # Verhoeff checksum and were FALSELY flagged "fabricated Aadhaar" -> RED on
    # genuine docs (benchmark: AR_ETERNAL annual report, real bank stmt). Real
    # Aadhaar cards classify as doc_type=="aadhaar" and/or print the UIDAI/आधार
    # label, so genuinely fabricated Aadhaar numbers are still caught.
    _AADHAAR_CTX = ("aadhaar", "aadhar", "uidai", "आधार", "uid no", "uid:")
    aadhaars_set = set()
    for m in AADHAAR_RE.finditer(text):
        raw = m.group(0)
        ctx = text[max(0, m.start() - 45):m.start()].lower()
        if doc_type == "aadhaar" or any(k in ctx for k in _AADHAAR_CTX):
            aadhaars_set.add(re.sub(r"\s", "", raw))
    aadhaars = sorted(aadhaars_set)
    ifscs = sorted(set(IFSC_RE.findall(text)))
    udyam = sorted({u.upper() for u in UDYAM_RE.findall(text)})
    amounts = sorted({_norm_amount(a) for a in AMOUNT_RE.findall(text)})
    dates = sorted(set(DATE_RE.findall(text)))
    itr_acks = sorted({m.group(1) for m in ACK_RE.finditer(text)})
    passports = sorted({m.group(1).upper() for m in PASSPORT_RE.finditer(text)})

    # Account numbers: long digit runs that are NOT already an Aadhaar or ITR ack.
    reserved = set(aadhaars) | set(itr_acks)
    accounts = sorted(
        {a for a in ACCOUNT_RE.findall(text) if a not in reserved and len(a) <= 18}
    )

    return {
        "pan": pans,
        "gstin": gstins,
        "aadhaar": aadhaars,
        "ifsc": ifscs,
        "udyam": udyam,
        "account_number": accounts,
        "amount": amounts,
        "date": dates,
        "itr_ack": itr_acks,
        "passport": passports,
    }


def _ner_entities(text: str) -> dict[str, list[str]]:
    try:
        resp = httpx.post(NER_URL, json={"text": text}, timeout=NER_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return {
            "person": data.get("persons", []),
            "org": data.get("orgs", []),
            "location": data.get("locations", []),
        }
    except Exception as e:
        logger.warning("NER service unavailable (%s) — names/orgs skipped.", e.__class__.__name__)
        return {"person": [], "org": [], "location": []}


# Identity documents that never carry a bank account number. For these we drop
# the generic 11-18 digit account match, because the long digit runs on them are
# MRZ codes (passport) or the Aadhaar number itself — NOT a bank account. The
# account regex is length-based with no context, so without this it mislabels
# them (e.g. a passport's MRZ personal number read as an account number).
NO_ACCOUNT_DOC_TYPES = {"passport", "pan", "aadhaar"}


def extract_entities(text: str, doc_type: str | None = None) -> dict[str, list[str]]:
    """Combine regex IDs (local) + NER names/orgs (microservice).

    doc_type, when known, suppresses fields that cannot exist on that document —
    currently the account number on a passport / PAN / Aadhaar.
    """
    if not text or not text.strip():
        return {}
    entities = _regex_entities(text, doc_type)
    entities.update(_ner_entities(text))

    # MRZ (passport machine-readable zone): authoritative, deterministic source
    # for the passport number AND the holder's name — more reliable than NER on a
    # noisy ID scan (NER tends to grab the signature). Self-gating: only fires
    # when an actual MRZ is present, so it never affects non-passport documents.
    mrz_numbers, mrz_names = _parse_mrz(text)
    if mrz_numbers:
        entities["passport"] = sorted(set(entities.get("passport", [])) | mrz_numbers)
    if mrz_names:
        persons = list(entities.get("person", []))
        for nm in sorted(mrz_names):
            if not any(nm.lower() == p.lower() for p in persons):
                persons.append(nm)
        entities["person"] = persons

    if doc_type in NO_ACCOUNT_DOC_TYPES:
        entities["account_number"] = []
    # Drop empty buckets to keep payloads tidy.
    return {k: v for k, v in entities.items() if v}
