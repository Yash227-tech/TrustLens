"""Mock external verification APIs (spec §6 + §9).

Simulates the authoritative sources TrustLens cross-checks against:
  - DigiLocker     (Aadhaar / PAN authoritative copies)
  - Account Aggregator (Sahamati / Finvu-style bank statement fetch)
  - GSTN           (GSTIN validity + legal name)
  - Income Tax e-Filing (ITR acknowledgement verification)

Per spec §9 these are simulated with sample data (live integration requires
FIU/AUA licensing). Each endpoint looks up a small seeded "authoritative DB"
and returns the official record; the TrustLens backend compares it to the
document's extracted entities to decide verified vs mismatch.

The seed deliberately includes the demo identities (e.g. PAN ABCDE1234F ->
Rahul Verma) so verified/mismatch paths can both be shown.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="TrustLens Gov Mock APIs", version="1.0.0")

# --- Seeded authoritative records ---
DIGILOCKER_PAN = {
    "ABCDE1234F": {"name": "Rahul Verma", "dob": "1990-05-12", "status": "active"},
    "PQRS5678K": {"name": "Anita Desai", "dob": "1985-11-03", "status": "active"},
}
DIGILOCKER_AADHAAR = {
    "234512347890": {"name": "Rahul Verma", "status": "active"},
}
GSTN = {
    "27ABCDE1234F1Z5": {"legal_name": "Patel Traders Private Limited",
                         "status": "Active", "state": "Maharashtra"},
}
AA_ACCOUNTS = {
    "73452312854": {"account_holder": "Rahul Verma", "bank": "Canara Bank", "status": "verified"},
}
ITR = {
    "112233445566778": {"name": "Rahul Verma", "assessment_year": "2024-25", "status": "filed"},
}
# Udyam (MSME) registry — keyed by Udyam Registration Number (URN). The
# authoritative_name is the ENTERPRISE legal name (compared to the doc's org name).
UDYAM = {
    "UDYAM-MH-26-0123456": {"enterprise": "Patel Traders Private Limited",
                            "enterprise_type": "Small", "status": "active",
                            "major_activity": "TRADING"},
}


class DigiLockerReq(BaseModel):
    pan: str | None = None
    aadhaar: str | None = None


class AAReq(BaseModel):
    account_number: str | None = None


class GSTNReq(BaseModel):
    gstin: str | None = None


class ITRReq(BaseModel):
    ack_number: str | None = None
    pan: str | None = None


class UdyamReq(BaseModel):
    urn: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/digilocker/verify")
def digilocker(req: DigiLockerReq):
    if req.pan and req.pan in DIGILOCKER_PAN:
        rec = DIGILOCKER_PAN[req.pan]
        return {"source": "DigiLocker", "found": True, "id_type": "PAN",
                "id": req.pan, "authoritative_name": rec["name"], "status": rec["status"]}
    if req.aadhaar and req.aadhaar in DIGILOCKER_AADHAAR:
        rec = DIGILOCKER_AADHAAR[req.aadhaar]
        return {"source": "DigiLocker", "found": True, "id_type": "Aadhaar",
                "id": req.aadhaar, "authoritative_name": rec["name"], "status": rec["status"]}
    return {"source": "DigiLocker", "found": False}


@app.post("/aa/fetch")
def aa(req: AAReq):
    if req.account_number and req.account_number in AA_ACCOUNTS:
        rec = AA_ACCOUNTS[req.account_number]
        return {"source": "Account Aggregator", "found": True,
                "account_number": req.account_number,
                "authoritative_name": rec["account_holder"],
                "bank": rec["bank"], "status": rec["status"]}
    return {"source": "Account Aggregator", "found": False}


@app.post("/gstn/verify")
def gstn(req: GSTNReq):
    if req.gstin and req.gstin in GSTN:
        rec = GSTN[req.gstin]
        return {"source": "GSTN", "found": True, "gstin": req.gstin,
                "authoritative_name": rec["legal_name"], "status": rec["status"],
                "state": rec["state"]}
    return {"source": "GSTN", "found": False}


@app.post("/itr/verify")
def itr(req: ITRReq):
    if req.ack_number and req.ack_number in ITR:
        rec = ITR[req.ack_number]
        return {"source": "Income Tax e-Filing", "found": True,
                "ack_number": req.ack_number, "authoritative_name": rec["name"],
                "assessment_year": rec["assessment_year"], "status": rec["status"]}
    return {"source": "Income Tax e-Filing", "found": False}


@app.post("/udyam/verify")
def udyam(req: UdyamReq):
    urn = (req.urn or "").upper()
    if urn and urn in UDYAM:
        rec = UDYAM[urn]
        return {"source": "Udyam", "found": True, "urn": urn,
                "authoritative_name": rec["enterprise"],
                "enterprise_type": rec["enterprise_type"],
                "major_activity": rec["major_activity"], "status": rec["status"]}
    return {"source": "Udyam", "found": False}
