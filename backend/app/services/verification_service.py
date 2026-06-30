"""Cross-Source Verification client (spec §6 Verification Service).

Calls the mock DigiLocker / Account Aggregator / GSTN / IT e-Filing services
in parallel, then compares each authoritative record against the document's
extracted entities:

  - match     → that source verifies the document (raises trust)
  - mismatch  → authoritative name differs from the doc → CRITICAL fraud signal
  - not_found → no authoritative record for the ID → neutral (can't confirm)

Returns the standard forensic dict {score, passed, detail, flags, info}.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

import httpx
import jellyfish
from rapidfuzz import fuzz

from app.services.entity_extraction import aadhaar_checksum_valid

logger = logging.getLogger(__name__)


def _mask_aadhaar(a: str) -> str:
    """Never echo a full Aadhaar number — show first 4 + last 2 only."""
    return f"{a[:4]}XXXX{a[-2:]}" if len(a) == 12 else "XXXX"

GOV_MOCK_URL = os.environ.get("GOV_MOCK_URL", "http://gov-mock:8600")
TIMEOUT = 8.0
NAME_MATCH_THRESHOLD = 82


def _name_matches(a: str, b: str) -> bool:
    a1, b1 = (a or "").strip().lower(), (b or "").strip().lower()
    if not a1 or not b1:
        return False
    if fuzz.token_sort_ratio(a1, b1) >= NAME_MATCH_THRESHOLD:
        return True
    try:
        return bool(jellyfish.metaphone(a1)) and jellyfish.metaphone(a1) == jellyfish.metaphone(b1)
    except Exception:
        return False


def _post(path: str, payload: dict) -> dict | None:
    try:
        r = httpx.post(f"{GOV_MOCK_URL}{path}", json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("Verification call %s failed: %s", path, e.__class__.__name__)
        return None


def analyze_cross_source(entities: dict[str, list[str]], doc_type: str | None) -> dict:
    """entities: from entity_extraction. doc_type: keyword classifier doc_type."""
    if not entities:
        return {
            "score": 0.85, "passed": True,
            "detail": "No verifiable identifiers extracted — cross-source check inconclusive.",
            "flags": [], "info": {"checks": []},
        }

    doc_names = entities.get("person", [])
    org_names = entities.get("org", [])  # enterprise/legal names (for Udyam/GSTN)

    # Deterministic offline check: any extracted Aadhaar that matches the format
    # but fails the Verhoeff checksum is fabricated (no genuine UIDAI number can).
    invalid_aadhaars = [a for a in entities.get("aadhaar", [])
                        if not aadhaar_checksum_valid(a)]

    # Build the set of source calls applicable to this document.
    calls: list[tuple[str, str, dict]] = []
    for pan in entities.get("pan", [])[:1]:
        calls.append(("DigiLocker", "/digilocker/verify", {"pan": pan}))
    for aad in entities.get("aadhaar", [])[:1]:
        calls.append(("DigiLocker", "/digilocker/verify", {"aadhaar": aad}))
    for gstin in entities.get("gstin", [])[:1]:
        calls.append(("GSTN", "/gstn/verify", {"gstin": gstin}))
    for acct in entities.get("account_number", [])[:1]:
        calls.append(("Account Aggregator", "/aa/fetch", {"account_number": acct}))
    for ack in entities.get("itr_ack", [])[:1]:  # Income Tax e-Filing (spec §6)
        payload = {"ack_number": ack}
        if entities.get("pan"):
            payload["pan"] = entities["pan"][0]
        calls.append(("Income Tax e-Filing", "/itr/verify", payload))
    for urn in entities.get("udyam", [])[:1]:  # Udyam (MSME) registry
        calls.append(("Udyam", "/udyam/verify", {"urn": urn}))

    if not calls:
        return {
            "score": 0.85, "passed": True,
            "detail": "No PAN/Aadhaar/GSTIN/account number to cross-verify.",
            "flags": [], "info": {"checks": []},
        }

    with ThreadPoolExecutor(max_workers=4) as ex:
        responses = list(ex.map(lambda c: (c[0], _post(c[1], c[2])), calls))

    checks = []
    flags = []
    verified = 0
    mismatched = 0
    for source, resp in responses:
        if resp is None:
            checks.append({"source": source, "result": "unavailable"})
            continue
        if not resp.get("found"):
            checks.append({"source": source, "result": "not_found"})
            continue
        auth_name = resp.get("authoritative_name", "")
        # Udyam/GSTN are business records → compare against the ENTERPRISE name on
        # the doc (org), not the person; fall back to person if no org was found.
        compare_to = (org_names or doc_names) if source in ("Udyam", "GSTN") else doc_names
        # Compare authoritative name to the relevant name(s) on the document.
        if compare_to and not any(_name_matches(auth_name, dn) for dn in compare_to):
            mismatched += 1
            checks.append({"source": source, "result": "mismatch",
                           "authoritative_name": auth_name, "doc_names": compare_to})
            flags.append(f"{source}_name_mismatch(auth='{auth_name}')")
        else:
            verified += 1
            checks.append({"source": source, "result": "verified",
                           "authoritative_name": auth_name})

    # Invalid Aadhaar checksum is a strong, deterministic fabrication signal.
    for a in invalid_aadhaars:
        flags.append(f"invalid_aadhaar_checksum({_mask_aadhaar(a)})")
        checks.append({"source": "UIDAI (Verhoeff)", "result": "invalid_checksum",
                       "value_masked": _mask_aadhaar(a)})

    # Scoring: mismatch and fabricated Aadhaar are the strong signals.
    score = 1.0
    if mismatched:
        score -= min(0.6, 0.45 + 0.15 * (mismatched - 1))
    if invalid_aadhaars:
        score -= 0.5
    if verified == 0 and mismatched == 0 and not invalid_aadhaars:
        score = 0.85  # nothing found to confirm

    score = max(0.0, min(1.0, score))
    passed = score >= 0.7 and mismatched == 0 and not invalid_aadhaars

    bad_aadhaar = (f"{len(invalid_aadhaars)} Aadhaar number(s) FAIL the Verhoeff "
                   f"checksum (fabricated). " if invalid_aadhaars else "")
    if mismatched:
        detail = (bad_aadhaar + f"{mismatched} source(s) report a NAME MISMATCH vs "
                  f"authoritative records; {verified} verified. " + "; ".join(flags))
    elif invalid_aadhaars:
        detail = bad_aadhaar + f"{verified} source(s) verified."
    elif verified:
        srcs = ", ".join(sorted({c['source'] for c in checks if c['result'] == 'verified'}))
        detail = f"Verified against {verified} authoritative source(s): {srcs}."
    else:
        detail = "No authoritative records matched the document's identifiers."

    return {
        "score": score, "passed": passed, "detail": detail,
        "flags": flags, "info": {"checks": checks},
    }
