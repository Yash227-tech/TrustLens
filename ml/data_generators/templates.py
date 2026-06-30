"""23 synthetic Indian document templates with authentic per-type layouts.

Each template returns (pdf_bytes, fields_dict). Layouts are drawn with absolute
positioning (ReportLab) to resemble the real document type — passports have a
photo-left / MRZ-bottom layout, ID cards are card-style, statements use
accounting columns, letters use letterheads, deeds use stamp-paper headers.

Kept as PDFs (not images) so PDF-metadata + font forensic features still apply.
KYC/ID docs carry a "SYNTHETIC SPECIMEN" watermark + grey silhouette (never a
real face/data). All keyword phrases the classifier needs are preserved.
"""

from __future__ import annotations

import random
import string

from reportlab.lib.units import mm

from . import indian_data as D
from .builder import PAGE_H, DocBuilder


# ----------------------------- shared helpers -----------------------------

def _letterhead(b: DocBuilder, org: str, sub: str = "", color=(0.12, 0.23, 0.54)) -> None:
    b.rect_at(0, 0, 210, 26, stroke=None, fill=color)
    b.text_at(15, 14, org, size=16, bold=True, color=(1, 1, 1))
    if sub:
        b.text_at(15, 21, sub, size=9, color=(0.9, 0.9, 0.95))


def _cursor(b: DocBuilder, top_mm: float) -> None:
    b.y = b._ay(top_mm)


def _stamp_seal(b: DocBuilder, x_mm: float, top_mm: float, text: str = "SEAL") -> None:
    cx, cy = x_mm * mm, b._ay(top_mm)
    b.c.setStrokeColorRGB(0.6, 0, 0)
    b.c.setLineWidth(1.2)
    b.c.circle(cx, cy, 13 * mm, stroke=1, fill=0)
    b.c.circle(cx, cy, 10 * mm, stroke=1, fill=0)
    b.c.setFillColorRGB(0.6, 0, 0)
    b.c.setFont("Helvetica-Bold", 6)
    b.c.drawCentredString(cx, cy - 2, text)
    b.c.setFillColorRGB(0, 0, 0)
    b.c.setStrokeColorRGB(0, 0, 0)
    b.c.setLineWidth(1)


def _stamp_paper_header(b: DocBuilder, value: str) -> None:
    b.rect_at(15, 10, 180, 16, stroke=(0.3, 0.3, 0.3))
    b.text_at(105, 16, "INDIA NON-JUDICIAL", size=11, bold=True, center=True, color=(0.25, 0.25, 0.3))
    b.text_at(105, 22, f"e-Stamp  ·  Stamp Duty Paid : {value}", size=8, center=True, color=(0.4, 0.4, 0.45))


def _signature_at(b: DocBuilder, x_mm: float, top_mm: float, name: str, role: str) -> None:
    b.hline(x_mm, top_mm, x_mm + 55, color=(0, 0, 0))
    b.text_at(x_mm, top_mm + 5, name, size=9, bold=True)
    b.text_at(x_mm, top_mm + 10, role, size=8, color=(0.4, 0.4, 0.45))


# ----------------------------- LEGAL (12) -----------------------------

def passport():
    name = D.person_name()
    surname = name.split()[-1].upper()
    given = " ".join(name.split()[:-1]).upper() or surname
    num = D.passport_number()
    city, state, pin = D.city_state_pin()
    sex = random.choice(["M", "F"])
    b = DocBuilder("Passport")
    b.rect_at(0, 0, 210, 14, stroke=None, fill=(0.20, 0.12, 0.38))
    b.text_at(105, 10, "REPUBLIC OF INDIA", size=14, bold=True, center=True, color=(1, 1, 1))
    b.text_at(105, 20, "PASSPORT", size=11, bold=True, center=True, color=(0.2, 0.12, 0.38))
    b.photo_box(18, 30, 32, 40)
    b.labeled(60, 30, "Type", "P")
    b.labeled(90, 30, "Country Code", "IND")
    b.labeled(135, 30, "Passport No.", num, vsize=13)
    b.labeled(60, 44, "Surname", surname)
    b.labeled(60, 56, "Given Name(s)", given)
    b.labeled(60, 70, "Nationality", "INDIAN")
    b.labeled(110, 70, "Sex", sex)
    b.labeled(135, 70, "Date of Birth", D.date_str())
    b.labeled(60, 84, "Place of Birth", f"{city}, {state}")
    b.labeled(60, 96, "Place of Issue", city)
    b.labeled(135, 96, "Date of Expiry", D.date_str())
    b.labeled(60, 108, "Date of Issue", D.date_str())
    _signature_at(b, 18, 78, name, "Signature of Holder")
    b.hline(15, 125, 195, color=(0.5, 0.5, 0.6))
    def pad(s): return (s + "<" * 44)[:44]
    l1 = pad(f"P<IND{surname}<<{given.replace(' ', '<')}")
    l2 = pad(f"{num}<8IND")
    b.mrz(132, l1, l2)
    b.watermark()
    return b.build(), {"name": name, "passport": num}


def aadhaar():
    name = D.person_name()
    num = D.aadhaar()
    city, state, pin = D.city_state_pin()
    b = DocBuilder("Aadhaar")
    b.rect_at(0, 0, 210, 16, stroke=None, fill=(0.85, 0.34, 0.13))
    b.text_at(15, 9, "Government of India", size=12, bold=True, color=(1, 1, 1))
    b.text_at(15, 14, "Unique Identification Authority of India (UIDAI)", size=8, color=(1, 1, 1))
    b.text_at(180, 11, "AADHAAR", size=14, bold=True, right=True, color=(0.2, 0.4, 0.2))
    b.rect_at(15, 26, 180, 56, stroke=(0.6, 0.6, 0.65))
    b.photo_box(20, 32, 28, 36)
    b.labeled(56, 34, "Name", name, vsize=13)
    b.labeled(56, 48, "Date of Birth", D.date_str())
    b.labeled(120, 48, "Gender", random.choice(["MALE", "FEMALE"]))
    b.labeled(56, 62, "Address", f"{city}, {state} - {pin}")
    b.text_at(105, 96, f"Your Aadhaar No.  :  {num}", size=18, bold=True, center=True)
    b.text_at(105, 116, "Aadhaar is proof of identity, not of citizenship.", size=9, center=True, color=(0.4, 0.4, 0.45))
    b.watermark()
    return b.build(), {"name": name, "aadhaar": num}


def pan():
    name = D.person_name()
    surname = name.split()[-1] if name.split() else name
    num = D.pan(surname=surname, holder="P")
    b = DocBuilder("PAN Card")
    b.rect_at(0, 0, 210, 16, stroke=None, fill=(0.10, 0.30, 0.60))
    b.text_at(105, 8, "INCOME TAX DEPARTMENT", size=13, bold=True, center=True, color=(1, 1, 1))
    b.text_at(105, 13, "GOVT. OF INDIA", size=9, center=True, color=(1, 1, 1))
    b.text_at(15, 28, "Permanent Account Number Card", size=10, bold=True, color=(0.2, 0.2, 0.25))
    b.rect_at(15, 32, 130, 60, stroke=(0.6, 0.6, 0.65))
    b.labeled(20, 38, "Name", name, vsize=12)
    b.labeled(20, 52, "Father's Name", D.person_name())
    b.labeled(20, 66, "Date of Birth", D.date_str())
    b.text_at(20, 86, num, size=20, bold=True)
    b.photo_box(155, 32, 30, 38)
    _signature_at(b, 150, 78, name, "Signature")
    b.text_at(15, 105, "This PAN Card is issued under the Income Tax Act, 1961.", size=8, color=(0.4, 0.4, 0.45))
    b.watermark()
    return b.build(), {"name": name, "pan": num}


def _legal_letter(title, org, body, signer, role, fields, stamp=True, stamp_paper=None):
    b = DocBuilder(title)
    if stamp_paper:
        _stamp_paper_header(b, stamp_paper)
        b.text_at(105, 36, title.upper(), size=15, bold=True, center=True)
        top = 48
    else:
        _letterhead(b, org)
        b.text_at(105, 40, title.upper(), size=14, bold=True, center=True)
        top = 50
    b.text_at(170, top, "Date: " + D.date_str(), size=9, right=True)
    _cursor(b, top + 6)
    for para in body:
        b.paragraph(para)
        b.spacer(1.5 * mm)
    _signature_at(b, 25, 250, signer, role)
    if stamp:
        _stamp_seal(b, 165, 250, "SEAL")
    b.footer("Synthetic document for testing.")
    return b.build(), fields


def loan_agreement():
    name, bank = D.person_name(), D.bank()[0]
    amt = D.amount(100_000, 5_000_000)
    rate = round(random.uniform(7.5, 14.5), 2)
    tenure = random.choice([12, 24, 36, 60, 120, 180])
    body = [
        f"This Loan Agreement is made between {bank} (the Lender) and {name} (the Borrower).",
        f"The Lender agrees to advance the principal sum of {D.inr(amt)} to the Borrower against "
        f"the loan account specified below.",
        f"Loan Account: {D.account_number()}    Principal Sum: {D.inr(amt)}",
        f"Rate of Interest: {rate}% per annum    Tenure of the Loan: {tenure} months    "
        f"EMI: {D.inr(int(amt * 1.1 / tenure))}",
        "The Borrower agrees to repay the loan as per the schedule. This agreement is governed by "
        "the laws of India and subject to the jurisdiction of the local courts.",
    ]
    return _legal_letter("Loan Agreement", bank, body, name, "Borrower",
                         {"borrower": name, "lender": bank, "principal": amt})


def sanction_letter():
    name, bank = D.person_name(), D.bank()[0]
    amt = D.amount(200_000, 8_000_000)
    body = [
        f"To,  {name}",
        f"We are pleased to inform you that your loan application has been approved. This letter of "
        f"sanction confirms a sanctioned amount of {D.inr(amt)} under our loan sanction scheme.",
        f"Sanctioned Amount: {D.inr(amt)}    Validity: 30 days from date of issue",
        "Please visit the branch with original documents to complete disbursal formalities.",
    ]
    return _legal_letter("Letter of Sanction", bank, body, "For " + bank, "Branch Manager",
                         {"applicant": name, "bank": bank, "sanctioned": amt})


def noc():
    name, bank = D.person_name(), D.bank()[0]
    body = [
        f"Ref No: NOC/{random.randint(1000, 9999)}/{random.randint(2021, 2024)}",
        f"This is to certify that {name} has cleared all dues. We have no objection to the closure of "
        f"the loan account and issuance of this No Objection Certificate.",
        f"Account Holder: {name}    Loan Account: {D.account_number()}",
    ]
    return _legal_letter("No Objection Certificate", bank, body, "For " + bank, "Authorised Signatory",
                         {"holder": name, "issuer": bank})


def guarantee_letter():
    guarantor, bank = D.person_name(), D.bank()[0]
    amt = D.amount(100_000, 5_000_000)
    body = [
        f"We hereby guarantee, as guarantor, the due performance and payment obligations of the "
        f"applicant up to a maximum sum of {D.inr(amt)} under this letter of guarantee.",
        f"Guarantor: {guarantor}    Beneficiary: {bank}    Guaranteed Amount: {D.inr(amt)}",
        f"Valid Until: {D.date_str()}",
    ]
    return _legal_letter("Letter of Guarantee", bank, body, guarantor, "Guarantor",
                         {"guarantor": guarantor, "amount": amt})


def board_resolution():
    comp = D.company_name()
    directors = [D.person_name() for _ in range(3)]
    body = [
        f"Certified true copy of the resolution passed at the meeting of the Board of Directors of "
        f"{comp} held on {D.date_str()}.",
        "RESOLVED THAT the company be and is hereby authorised to avail credit facilities from the "
        "bank, and that the Directors be authorised to execute all necessary documents.",
        "Directors present: " + ", ".join(directors),
    ]
    return _legal_letter("Board Resolution", comp, body, directors[0], "Director",
                         {"company": comp, "directors": directors})


def partnership_deed():
    comp = D.company_name()
    partners = [D.person_name() for _ in range(random.choice([2, 3]))]
    ratio = " : ".join(["50", "50"] if len(partners) == 2 else ["33", "33", "34"])
    body = [
        f"This Partnership Deed is executed under the Indian Partnership Act, 1932 between the partners "
        f"to carry on business under the name {comp}.",
        "The partners: " + ", ".join(partners),
        f"Profit Sharing Ratio: {ratio}    Capital Contribution: {D.inr(D.amount(100000, 2000000))}",
        "The partners agree to share profits and losses as per the profit sharing ratio above.",
    ]
    return _legal_letter("Partnership Deed", comp, body, partners[0], "Partner",
                         {"firm": comp, "partners": partners}, stamp_paper=D.inr(1000))


def power_of_attorney():
    grantor, grantee = D.person_name(), D.person_name()
    body = [
        f"KNOW ALL MEN BY THESE PRESENTS that I, {grantor}, do hereby nominate, constitute and appoint "
        f"{grantee} as my lawful attorney (attorney in fact) to act on my behalf.",
        "This Power of Attorney authorises the attorney to manage all matters specified herein, "
        "including banking, property, and legal representation.",
        f"Grantor: {grantor}    Attorney: {grantee}",
    ]
    return _legal_letter("General Power of Attorney", "POWER OF ATTORNEY", body, grantor, "Grantor",
                         {"grantor": grantor, "attorney": grantee}, stamp_paper=D.inr(500))


def indemnity_bond():
    indemnifier, party = D.person_name(), D.bank()[0]
    amt = D.amount(50_000, 2_000_000)
    body = [
        f"This Indemnity Bond is executed by {indemnifier} (the Indemnifier) in favour of {party} "
        f"(the Indemnified Party).",
        f"The Indemnifier agrees to indemnify and hold harmless the Indemnified Party against all "
        f"losses up to {D.inr(amt)}.",
        f"Indemnifier: {indemnifier}    Indemnified Party: {party}    Bond Value: {D.inr(amt)}",
    ]
    return _legal_letter("Indemnity Bond", "INDEMNITY BOND", body, indemnifier, "Indemnifier",
                         {"indemnifier": indemnifier, "party": party}, stamp_paper=D.inr(100))


def moa_aoa():
    comp = D.company_name()
    b = DocBuilder("MOA / AOA")
    _letterhead(b, comp, "Registrar of Companies")
    b.text_at(105, 40, "MEMORANDUM OF ASSOCIATION", size=14, bold=True, center=True)
    b.text_at(105, 47, "AND ARTICLES OF ASSOCIATION", size=11, bold=True, center=True)
    _cursor(b, 56)
    b.paragraph(f"Memorandum of Association of {comp}, incorporated under the Companies Act, 2013. "
                "The object clauses for which the company is established are set out below.")
    b.field("Registered Office", D.address())
    b.field("Authorised Share Capital", D.inr(D.amount(1_000_000, 50_000_000)))
    b.paragraph("ARTICLES OF ASSOCIATION: The regulations in Table F shall apply except as modified "
                "herein. The object clauses define the scope of the company's business activities.")
    _stamp_seal(b, 165, 250, "ROC")
    b.footer("Synthetic document for testing.")
    return b.build(), {"company": comp}


# ----------------------------- RENTAL / LEASE AGREEMENT -----------------------------

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three_words(n: int) -> str:  # 0..999
    h, r = divmod(n, 100)
    out = _ONES[h] + " Hundred" if h else ""
    if r:
        out = (out + " " if out else "") + _two_words(r)
    return out


def _num_words(n: int) -> str:  # Indian numbering (crore/lakh/thousand)
    if n == 0:
        return "Zero"
    cr, n = divmod(n, 10_000_000)
    lk, n = divmod(n, 100_000)
    th, n = divmod(n, 1000)
    parts = []
    if cr:
        parts.append(_three_words(cr) + " Crore")
    if lk:
        parts.append(_three_words(lk) + " Lakh")
    if th:
        parts.append(_three_words(th) + " Thousand")
    if n:
        parts.append(_three_words(n))
    return " ".join(parts)


_PROP_CATEGORY = ["Independent House", "Apartment", "Farm House", "Residential Property",
                  "Builder Floor", "Villa", "Studio Apartment"]


def rental_agreement():
    """Residential rental / lease agreement — Indian LESSOR/LESSEE deed format.

    Prose legal document (like loan_agreement / partnership_deed). Used in
    underwriting as an address proof / tenancy + rental-income substantiation, so
    the distinctive vocabulary (LESSOR/LESSEE, said premises, monthly rent,
    security deposit, IN WITNESS WHEREOF) is what the classifier learns. Multi-page
    with a page guard (DocBuilder.paragraph has no auto page-break)."""
    landlord, tenant = D.person_name(), D.person_name()
    w1, w2 = D.person_name(), D.person_name()
    city, state, _pin = D.city_state_pin()
    prop_addr = D.address()
    category = random.choice(_PROP_CATEGORY)
    beds, baths, cars = random.randint(1, 4), random.randint(1, 3), random.randint(0, 2)
    sqft = random.choice([450, 600, 750, 900, 1100, 1250, 1500, 1800, 2200])
    term = f"{random.choice([11, 12, 24, 36])} months"
    start = D.date_str()
    rent = random.choice([8000, 12000, 15000, 18000, 22000, 25000, 30000, 35000, 45000, 60000])
    deposit = rent * random.choice([2, 3, 6, 10])
    notice = random.choice(["one month", "two months", "three months"])
    meter = random.randint(1000, 99999)
    rent_s = f"{D.inr(rent)} (Rupees {_num_words(rent)} only)"
    dep_s = f"{D.inr(deposit)} (Rupees {_num_words(deposit)} only)"

    b = DocBuilder("Residential Rental Agreement")
    b.text_at(105, 22, "RESIDENTIAL RENTAL AGREEMENT", size=15, bold=True, center=True)
    b.hline(60, 26, 150, color=(0.4, 0.4, 0.45))
    _cursor(b, 34)
    clauses = [
        f"This Rental Agreement is made at {city}, {state} on this {start} between {landlord}, "
        f"residing at {D.address()}, hereinafter referred to as the 'LESSOR' of the One Part AND "
        f"{tenant}, residing at {D.address()}, hereinafter referred to as the 'LESSEE' of the other Part.",
        f"WHEREAS the Lessor is the lawful owner of {prop_addr}, falling in the category {category}, "
        f"comprising of {beds} Bedrooms, {baths} Bathrooms and {cars} Carparks with an extent of {sqft} "
        f"Square Feet, hereinafter referred to as the 'said premises'.",
        f"AND WHEREAS at the request of the Lessee, the Lessor has agreed to let the said premises to the "
        f"Lessee for a term of {term} commencing from {start} in the manner hereinafter appearing.",
        "NOW THIS AGREEMENT WITNESSETH AND IT IS HEREBY AGREED BY AND BETWEEN THE PARTIES AS UNDER:",
        "1. That the Lessor hereby grants to the Lessee the right to enter into, use and remain in the "
        "said premises along with the existing fixtures and fittings listed in Annexure I to this Agreement.",
        f"2. That the lease hereby granted shall remain in force for a period of {term}, unless cancelled "
        "earlier under any provision of this Agreement.",
        f"3. That the Lessee will have the option to terminate this lease by giving {notice} notice in "
        "writing to the Lessor.",
        "4. That the Lessee shall have no right to create any sub-lease or to assign or transfer the lease "
        "or give possession of the said premises or any part thereof to anyone.",
        "5. That the Lessee shall use the said premises only for residential purposes.",
        f"6. That in consideration of the use of the said premises, the Lessee agrees to pay to the Lessor "
        f"a monthly rent of {rent_s}, payable in advance on or before the 1st day of every calendar month.",
        f"7. That the Lessee has paid to the Lessor a sum of {dep_s} as an interest-free security deposit, "
        "which the Lessor accepts and acknowledges, refundable to the Lessee on vacating the said premises.",
        f"8. That the Lessee shall pay the actual electricity, water and shared maintenance charges for the "
        f"period of the agreement directly to the authorities concerned. The start-date meter reading is "
        f"{meter} units.",
        "9. That the Lessor shall be responsible for the payment of all taxes and levies pertaining to the "
        "said premises including House Tax and Property Tax levied by the Government.",
        "IN WITNESS WHEREOF, the parties hereto have set their hands on the day and year first hereinabove "
        "mentioned.",
    ]
    for c in clauses:
        if b.y < 45 * mm:  # page guard — paragraph() does not auto page-break
            b.c.showPage()
            b.y = PAGE_H - 20 * mm
        b.paragraph(c)
        b.spacer(1.2 * mm)

    if b.y < 70 * mm:
        b.c.showPage()
        b.y = PAGE_H - 30 * mm
    b.spacer(8 * mm)
    top = (PAGE_H - b.y) / mm
    b.text_at(25, top, "LESSOR (Landlord)", size=9, bold=True)
    b.text_at(120, top, "LESSEE (Tenant)", size=9, bold=True)
    b.text_at(25, top + 12, landlord, size=9)
    b.text_at(120, top + 12, tenant, size=9)
    b.text_at(25, top + 22, "WITNESS ONE: " + w1, size=8)
    b.text_at(120, top + 22, "WITNESS TWO: " + w2, size=8)
    b.footer("Synthetic document for testing.")
    return b.build(), {"lessor": landlord, "lessee": tenant, "property_address": prop_addr,
                       "monthly_rent": rent, "deposit": deposit, "lease_term": term,
                       "person": [landlord, tenant]}


# ----------------------------- UDYAM / MSME CERTIFICATE -----------------------------

_UDYAM_STATES = ["MH", "DL", "KA", "GJ", "TN", "UP", "WB", "RJ", "TS", "KL", "PB",
                 "HR", "MP", "BR", "OD", "AP", "JH", "CG", "UK", "AS"]
# (nic2, nic4, nic5, short description, major activity)
_NIC_CODES = [
    ("62", "6209", "62091", "Computer programming, consultancy and related activities", "SERVICES"),
    ("47", "4711", "47110", "Retail sale in non-specialised stores", "TRADING"),
    ("10", "1071", "10712", "Manufacture of bakery products", "MANUFACTURING"),
    ("46", "4690", "46900", "Non-specialised wholesale trade", "TRADING"),
    ("56", "5610", "56101", "Restaurants and mobile food service activities", "SERVICES"),
    ("14", "1410", "14101", "Manufacture of wearing apparel", "MANUFACTURING"),
    ("43", "4321", "43211", "Electrical installation", "SERVICES"),
    ("25", "2599", "25999", "Manufacture of other fabricated metal products", "MANUFACTURING"),
    ("49", "4923", "49230", "Freight transport by road", "SERVICES"),
]
_ENTERPRISE_TYPES = ["Micro", "Micro", "Small", "Medium"]  # Micro most common
_SOCIAL_CATS = ["GENERAL", "OBC", "SC", "ST"]


def _udyam_urn() -> str:
    """URN: UDYAM-<state>-<2 digit>-<7 digit> (16 alphanumerics / 19 with hyphens)."""
    return (f"UDYAM-{random.choice(_UDYAM_STATES)}-{random.randint(0, 99):02d}-"
            f"{random.randint(0, 9_999_999):07d}")


def _draw_qr(b: DocBuilder, x_mm: float, top_mm: float, size_mm: float, data: str) -> None:
    """Draw a REAL scannable QR (ReportLab) at a top-origin mm box; cv2 can decode it."""
    try:
        from reportlab.graphics import renderPDF
        from reportlab.graphics.barcode import qr
        from reportlab.graphics.shapes import Drawing
        w = qr.QrCodeWidget(data)
        bb = w.getBounds()
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        s = size_mm * mm
        d = Drawing(s, s, transform=[s / bw, 0, 0, s / bh, 0, 0])
        d.add(w)
        renderPDF.draw(d, b.c, x_mm * mm, b._ay(top_mm) - s)
    except Exception:  # never fail generation over the QR
        b.rect_at(x_mm, top_mm, size_mm, size_mm, stroke=(0, 0, 0))
        b.text_at(x_mm + size_mm / 2, top_mm + size_mm / 2, "QR", size=8, center=True)


def udyam_certificate():
    """Udyam (MSME) Registration Certificate — Govt of India, M/o MSME.

    Born-digital portal print: distinctive header + URN + enterprise classification
    + NIC codes + a QR that encodes the URN and the verification URL (real,
    cv2-decodable). No PAN / turnover / signature on the basic print (those live in
    the 'Print with Annexure' version) — Udyam registration is lifetime (no expiry).
    Used in underwriting to establish MSME status (scheme/priority-sector eligibility)."""
    urn = _udyam_urn()
    name = D.company_name()
    etype = random.choice(_ENTERPRISE_TYPES)
    nic2, nic4, nic5, nic_desc, major = random.choice(_NIC_CODES)
    social = random.choice(_SOCIAL_CATS)
    cyear = random.choice(["2022-23", "2023-24", "2024-25"])
    city, state, pin = D.city_state_pin()
    addr_lines = [f"{random.choice(['Flat', 'Unit', 'Shop', 'Plot'])} {random.randint(1, 299)}, "
                  f"{D.fake.street_name()}", f"{city}, {state} - {pin}"]
    inc_date, comm_date, class_date, reg_date = (D.date_str() for _ in range(4))
    qr_data = f"{urn} https://udyamregistration.gov.in/Udyam_Verify.aspx"

    b = DocBuilder("Udyam Registration Certificate")
    b.rect_at(0, 0, 210, 26, stroke=None, fill=(0.27, 0.24, 0.43))
    b.text_at(105, 10, "Government of India", size=12, bold=True, center=True, color=(1, 1, 1))
    b.text_at(105, 16, "Ministry of Micro, Small and Medium Enterprises", size=8.5,
              center=True, color=(0.9, 0.9, 0.95))
    b.text_at(16, 12, "MSME", size=13, bold=True, color=(1, 1, 1))
    b.text_at(105, 34, "UDYAM REGISTRATION CERTIFICATE", size=15, bold=True, center=True)
    _draw_qr(b, 170, 40, 28, qr_data)

    y = 50

    def row(label, value, vbold=True, color=(0, 0, 0), lsize=8.0, dy=8.6):
        nonlocal y
        b.text_at(14, y, label, size=lsize, bold=True, color=(0.3, 0.3, 0.35))
        b.text_at(82, y, str(value), size=9.2, bold=vbold, color=color)
        y += dy

    row("UDYAM REGISTRATION NUMBER", urn, color=(0.1, 0.1, 0.5))
    row("NAME OF ENTERPRISE", name)
    row("TYPE OF ENTERPRISE", f"{etype}    (Classification Year {cyear}, Date {class_date})")
    row("MAJOR ACTIVITY", major, color=(0.1, 0.45, 0.15))
    row("SOCIAL CATEGORY OF ENTREPRENEUR", social)
    row("NAME OF UNIT(S)", name + " - Unit I")
    b.text_at(14, y, "OFFICIAL ADDRESS OF ENTERPRISE", size=8.0, bold=True, color=(0.3, 0.3, 0.35))
    for i, ln in enumerate(addr_lines):
        b.text_at(82, y + i * 5, ln, size=9)
    y += len(addr_lines) * 5 + 4
    row("DATE OF INCORPORATION / REGISTRATION", inc_date)
    row("DATE OF COMMENCEMENT OF BUSINESS", comm_date)
    row("NATIONAL INDUSTRY CLASSIFICATION CODE(S)",
        f"{nic2} / {nic4} / {nic5} - {nic_desc}", vbold=False, lsize=7.6)
    row("DATE OF UDYAM REGISTRATION", reg_date, color=(0.1, 0.1, 0.5))
    y += 3
    b.hline(14, y, 196, color=(0.7, 0.7, 0.75))
    y += 5
    b.text_at(14, y, "Disclaimer: This is a computer generated statement, no signature required. "
                     "Printed from https://udyamregistration.gov.in", size=7.3, color=(0.4, 0.4, 0.45))
    b.footer("Synthetic document for testing.")
    return b.build(), {"urn": urn, "enterprise": name, "enterprise_type": etype,
                       "major_activity": major, "social_category": social,
                       "address": ", ".join(addr_lines), "nic_code": nic5,
                       "registration_date": reg_date, "org": [name]}


# ----------------------------- FINANCIAL (11) -----------------------------

def bank_statement():
    name, (bank, code) = D.person_name(), D.bank()
    acc = D.account_number()
    opening = D.amount(20_000, 500_000)
    b = DocBuilder("Bank Statement")
    _letterhead(b, bank, "Statement of Account")
    b.rect_at(15, 32, 180, 26, stroke=(0.7, 0.7, 0.75), fill=(0.96, 0.97, 0.99))
    b.labeled(20, 35, "Account Holder", name)
    b.labeled(110, 35, "Account Number", acc)
    b.labeled(20, 47, "IFSC Code", D.ifsc(code))
    b.labeled(110, 47, "MICR Code", "".join(random.choices("0123456789", k=9)))
    b.text_at(20, 66, f"Opening Balance: {D.inr(opening)}", size=10, bold=True)
    _cursor(b, 72)
    rows, bal = [], opening
    for _ in range(random.randint(8, 13)):
        debit = random.choice([0, D.amount(500, 50_000)])
        credit = 0 if debit else D.amount(1_000, 80_000)
        bal = bal - debit + credit
        rows.append([D.date_str(), random.choice(["UPI", "NEFT", "Salary", "ATM WDL", "IMPS", "Cheque"]),
                     D.inr(debit) if debit else "-", D.inr(credit) if credit else "-", D.inr(bal)])
    b.table(["Transaction Date", "Particulars", "Debit", "Credit", "Running Balance"], rows,
            col_w=[28 * mm, 35 * mm, 28 * mm, 28 * mm, 35 * mm])
    b.field("Closing Balance", D.inr(bal))
    b.footer("Synthetic document for testing.")
    return b.build(), {"holder": name, "bank": bank, "account": acc, "closing": bal}


def salary_slip():
    name, comp = D.person_name(), D.company_name()
    basic = D.amount(20_000, 120_000)
    hra, allow, pf, tax = int(basic * .4), int(basic * .2), int(basic * .12), int(basic * .1)
    net = basic + hra + allow - pf - tax
    b = DocBuilder("Salary Slip")
    _letterhead(b, comp, "Salary Slip / Payslip")
    b.rect_at(15, 32, 180, 22, stroke=(0.7, 0.7, 0.75), fill=(0.96, 0.97, 0.99))
    b.labeled(20, 35, "Employee Name", name)
    b.labeled(110, 35, "Employee ID", str(random.randint(1000, 9999)))
    b.labeled(20, 45, "Designation", D.designation())
    b.labeled(110, 45, "Month / LOP Days", f"{D.date_str()} / {random.choice([0,0,1,2])}")
    _cursor(b, 62)
    b.table(["Earnings", "Amount", "Deductions", "Amount"], [
        ["Basic Salary", D.inr(basic), "Provident Fund", D.inr(pf)],
        ["HRA", D.inr(hra), "Income Tax", D.inr(tax)],
        ["Allowances", D.inr(allow), "", ""],
    ], col_w=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
    b.text_at(20, 120, f"Net Payable: {D.inr(net)}", size=12, bold=True)
    _signature_at(b, 140, 135, "For " + comp, "Authorised Signatory")
    b.footer("Synthetic document for testing.")
    return b.build(), {"employee": name, "employer": comp, "net": net, "basic": basic}


def _gov_form(title, sub, rows_fields, extra_lines, fields, body=None):
    b = DocBuilder(title)
    _letterhead(b, "INCOME TAX DEPARTMENT" if "TAX" in sub or "ITR" in title or "16" in title
                else "GOODS AND SERVICES TAX", sub)
    b.text_at(105, 40, title.upper(), size=14, bold=True, center=True)
    _cursor(b, 50)
    for label, value in rows_fields:
        b.field(label, value)
    if body:
        b.spacer(2 * mm)
        for para in body:
            b.paragraph(para)
    b.footer("Synthetic document for testing.")
    return b.build(), fields


def form_16():
    name, comp = D.person_name(), D.company_name()
    return _gov_form(
        "Form No. 16", "Certificate under Section 203 of the Income-tax Act, 1961",
        [("Deductor", comp), ("Employee", name),
         ("Employee PAN", D.pan(surname=name.split()[-1], holder="P")),
         ("Assessment Year", D.assessment_year()),
         ("Tax Deducted at Source", D.inr(D.amount(10_000, 300_000)))],
        None, {"employee": name, "deductor": comp},
        body=["This is to certify that tax has been deducted at source and deposited as per Section "
              "203 of the Income-tax Act. This TDS certificate is issued by the deductor."])


def itr_v():
    name, ack = D.person_name(), D.acknowledgement_number()
    return _gov_form(
        "ITR-V", "Indian Income Tax Return Acknowledgement / Verification Form",
        [("Name", name), ("PAN", D.pan(surname=name.split()[-1], holder="P")),
         ("Acknowledgement Number", ack),
         ("Assessment Year", D.assessment_year()),
         ("Total Income", D.inr(D.amount(300_000, 3_000_000)))],
        None, {"name": name, "ack": ack},
        body=["This is the verification form acknowledging the filed income tax return."])


def itr_full():
    name = D.person_name()
    gti = D.amount(400_000, 5_000_000)
    return _gov_form(
        "Income Tax Return", "ITR-1 Sahaj",
        [("Name", name), ("PAN", D.pan(surname=name.split()[-1], holder="P")),
         ("Assessment Year", D.assessment_year()),
         ("Gross Total Income", D.inr(gti)), ("Total Taxable Income", D.inr(int(gti * .85))),
         ("Tax Payable", D.inr(int(gti * .12)))],
        None, {"name": name, "gti": gti},
        body=["This income tax return is filed for the assessment year shown above."])


def gstr_1():
    comp = D.company_name()
    g = D.gstin(company=comp)
    b = DocBuilder("GSTR-1")
    _letterhead(b, "GOODS AND SERVICES TAX", "GSTR-1 Outward Supplies", color=(0.1, 0.4, 0.3))
    b.text_at(105, 40, "GSTR-1", size=15, bold=True, center=True)
    _cursor(b, 50)
    b.field("Legal Name", comp)
    b.field("GSTIN", g)
    b.field("Return Period", D.date_str())
    b.paragraph("Details of outward supplies of goods or services. B2B invoices and tax invoice "
                "summary with HSN code below.")
    rows = [[f"INV-{random.randint(100,999)}", D.inr(D.amount(10_000, 500_000)),
             str(random.randint(1000, 9999)), f"{random.choice([5,12,18,28])}%"] for _ in range(5)]
    b.table(["Tax Invoice", "Taxable Value", "HSN Code", "Rate"], rows)
    b.footer("Synthetic document for testing.")
    return b.build(), {"company": comp, "gstin": g}


def gstr_3b():
    comp = D.company_name()
    g = D.gstin(company=comp)
    b = DocBuilder("GSTR-3B")
    _letterhead(b, "GOODS AND SERVICES TAX", "GSTR-3B Summary Return", color=(0.1, 0.4, 0.3))
    b.text_at(105, 40, "GSTR-3B", size=15, bold=True, center=True)
    _cursor(b, 50)
    b.field("Legal Name", comp)
    b.field("GSTIN", g)
    b.field("Return Period", D.date_str())
    b.field("Outward Taxable Supplies", D.inr(D.amount(100_000, 5_000_000)))
    b.field("Input Tax Credit", D.inr(D.amount(10_000, 500_000)))
    b.paragraph("Inward supplies liable to reverse charge and net tax payable summarised in this "
                "summary return.")
    b.footer("Synthetic document for testing.")
    return b.build(), {"company": comp, "gstin": g}


def _fin_statement(title, sub, builder_fn, fields):
    b = DocBuilder(title)
    comp = fields.get("company", D.company_name())
    _letterhead(b, comp, sub, color=(0.2, 0.2, 0.28))
    b.text_at(105, 40, title.upper(), size=14, bold=True, center=True)
    _cursor(b, 52)
    builder_fn(b)
    b.footer("Synthetic document for testing.")
    return b.build(), fields


def balance_sheet():
    comp = D.company_name()
    def body(b):
        b.text_at(105, 50, "as at 31st March " + str(random.randint(2021, 2024)), size=10,
                  center=True, italic=True)
        _cursor(b, 60)
        b.table(["Equity and Liabilities", "Amount", "Assets", "Amount"], [
            ["Share Capital", D.inr(D.amount(1_000_000, 50_000_000)),
             "Non-Current Assets", D.inr(D.amount(2_000_000, 80_000_000))],
            ["Reserves & Surplus", D.inr(D.amount(500_000, 20_000_000)),
             "Current Assets", D.inr(D.amount(1_000_000, 30_000_000))],
            ["Current Liabilities", D.inr(D.amount(200_000, 10_000_000)), "", ""],
        ])
    return _fin_statement("Balance Sheet", "Financial Statements", body, {"company": comp})


def profit_and_loss():
    comp = D.company_name()
    rev = D.amount(5_000_000, 200_000_000)
    def body(b):
        b.field("Revenue from Operations", D.inr(rev))
        b.field("Total Expenses", D.inr(int(rev * .8)))
        b.field("Profit Before Tax", D.inr(int(rev * .2)))
        b.field("Tax Expense", D.inr(int(rev * .05)))
        b.field("Profit After Tax", D.inr(int(rev * .15)))
        b.field("Earnings Per Share", f"Rs. {round(random.uniform(2, 80), 2)}")
    return _fin_statement("Statement of Profit and Loss", "Financial Statements", body,
                          {"company": comp, "revenue": rev})


def audited_financials():
    comp = D.company_name()
    def body(b):
        b.paragraph(f"We have audited the accompanying financial statements of {comp}. In our opinion, "
                    "the audited financial statements give a true and fair view in conformity with the "
                    "accounting principles generally accepted in India. This audit report is issued by "
                    "the independent auditor.")
        b.field("Auditor", D.person_name() + " & Associates")
        b.field("Membership No", str(random.randint(100000, 999999)))
        b.field("Date", D.date_str())
        _signature_at(b, 25, 250, D.person_name(), "Chartered Accountant")
        _stamp_seal(b, 165, 250, "CA")
    return _fin_statement("Independent Auditor's Report", "Audited Financial Statements", body,
                          {"company": comp})


def cash_flow_statement():
    comp = D.company_name()
    def body(b):
        b.field("Cash Flow from Operating", D.inr(D.amount(500_000, 20_000_000)))
        b.field("Cash Flow from Investing", D.inr(-D.amount(200_000, 10_000_000)))
        b.field("Cash Flow from Financing", D.inr(D.amount(-5_000_000, 5_000_000)))
        b.field("Net Increase in Cash", D.inr(D.amount(100_000, 5_000_000)))
        b.paragraph("Cash flow statement prepared under the indirect method as per AS-3 / Ind AS-7.")
    return _fin_statement("Cash Flow Statement", "Financial Statements", body, {"company": comp})


# ----------------------------- UTILITY BILL (address proof) -----------------------------

_UTILITY_PROVIDERS = {
    "electricity": [
        ("BSES Rajdhani Power Limited", "ELECTRICITY BILL", (0.10, 0.32, 0.55)),
        ("Tata Power Delhi Distribution Limited", "ELECTRICITY BILL", (0.00, 0.30, 0.55)),
        ("Maharashtra State Electricity Distribution Co. Ltd.", "ENERGY BILL", (0.45, 0.12, 0.12)),
        ("Bangalore Electricity Supply Company (BESCOM)", "ELECTRICITY BILL", (0.12, 0.40, 0.22)),
        ("Torrent Power Limited", "ELECTRICITY BILL", (0.55, 0.20, 0.10)),
    ],
    "water": [
        ("Delhi Jal Board", "WATER BILL", (0.10, 0.35, 0.55)),
        ("Bangalore Water Supply & Sewerage Board", "WATER SUPPLY BILL", (0.10, 0.40, 0.45)),
        ("Municipal Corporation : Water Supply Department", "WATER CHARGES BILL", (0.20, 0.30, 0.50)),
    ],
    "gas": [
        ("Gujarat Gas Limited", "GAS BILL (DOMESTIC)", (0.55, 0.15, 0.15)),
        ("Indraprastha Gas Limited", "PIPED NATURAL GAS BILL", (0.10, 0.35, 0.55)),
        ("Mahanagar Gas Limited", "GAS BILL", (0.55, 0.25, 0.10)),
    ],
}

_SOC = ["Shanti", "Krishna", "Ganga", "Green Park", "Vrindavan", "Sai", "Gokul",
        "Lake View", "Sunrise", "Shree", "Ashiana", "Riddhi Siddhi"]
_SOC_KIND = ["Society", "Apartments", "Nagar", "Residency", "Enclave", "Colony", "Towers"]


def _res_address() -> list[str]:
    """A multi-line Indian residential address (for the address-proof use case)."""
    city, state, pin = D.city_state_pin()
    house = (f"{random.choice(['H.No.', 'Flat', 'Plot', 'Door No.'])} {random.randint(1, 499)}"
             f"{random.choice(['', '-A', '/2', '', 'B'])}")
    soc = f"{random.choice(_SOC)} {random.choice(_SOC_KIND)}"
    area = random.choice([f"Sector {random.randint(1, 45)}", f"Ward No. {random.randint(1, 30)}",
                          D.fake.street_name(), "Near " + D.fake.street_name()])
    return [f"{house}, {soc}", area, f"{city} - {pin}, {state}"]


_PT_MM = 25.4 / 72.0  # points -> millimetres


def _ybox(b, cls, x_mm, base_top_mm, text, size, bold=True, pad=1.3):
    """Normalised YOLO box around a single drawn text value (A4 = 210x297 mm)."""
    font = "Helvetica-Bold" if bold else "Helvetica"
    w = b.c.stringWidth(str(text), font, size) * _PT_MM
    asc, desc = 0.74 * size * _PT_MM, 0.22 * size * _PT_MM
    x0, y0 = x_mm - pad, base_top_mm - asc - pad
    bw, bh = w + 2 * pad, asc + desc + 2 * pad
    return [cls, (x0 + bw / 2) / 210.0, (y0 + bh / 2) / 297.0, bw / 210.0, bh / 297.0]


def _ybox_block(b, cls, x_mm, base_tops, texts, size, pad=1.6):
    """Normalised YOLO box spanning a multi-line block (e.g. the address)."""
    w = max(b.c.stringWidth(str(t), "Helvetica", size) for t in texts) * _PT_MM
    asc, desc = 0.74 * size * _PT_MM, 0.22 * size * _PT_MM
    top, bot = min(base_tops) - asc, max(base_tops) + desc
    x0, y0 = x_mm - pad, top - pad
    bw, bh = w + 2 * pad, (bot - top) + 2 * pad
    return [cls, (x0 + bw / 2) / 210.0, (y0 + bh / 2) / 297.0, bw / 210.0, bh / 297.0]


def utility_bill(sub: str | None = None):
    """Electricity / water / gas bill — the common 'utility bill' address proof.

    One broad class covering all three (layouts differ wildly by provider); the
    sub-type is recorded in the fields. Mirrors the field set of the real GGL gas
    bill and DJB water bill samples (consumer name, address, consumer no., meter
    readings, charges, due date).

    `sub` forces a sub-type (electricity/water/gas) — used by the detector-set
    builder to balance the three layouts; default None keeps the random mix used
    by the classifier generator."""
    # Electricity weighted highest (most common address proof), then water, gas.
    if sub is None:
        sub = random.choice(["electricity", "electricity", "electricity", "water", "water", "gas"])
    provider, billtype, color = random.choice(_UTILITY_PROVIDERS[sub])
    name = D.person_name()
    addr = _res_address()
    consumer_no = "".join(random.choices(string.digits, k=random.choice([9, 10, 11, 12])))
    bill_no = "".join(random.choices(string.digits, k=random.choice([10, 12])))
    units = random.randint(20, 600)
    prev = random.randint(1000, 9000)
    curr = prev + units
    rate = round(random.uniform(3.5, 9.5) if sub == "electricity" else random.uniform(8, 55), 2)
    energy = int(units * rate)
    fixed = random.choice([50, 75, 100, 120, 150, 200])
    tax = int(energy * 0.09)
    total = energy + fixed + tax
    late = max(20, int(total * 0.05))
    unit_label = {"electricity": "kWh", "water": "KL", "gas": "SCM"}[sub]
    id_label = {"electricity": "CA / Consumer No.", "water": "K No. (Consumer No.)",
                "gas": "Customer No. (BP No.)"}[sub]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    mi = random.randint(0, 10)
    period = f"{months[mi]} - {months[mi + 1]} {random.randint(2022, 2024)}"

    b = DocBuilder(billtype.title())
    b.rect_at(0, 0, 210, 22, stroke=None, fill=color)
    b.text_at(15, 10, provider, size=13, bold=True, color=(1, 1, 1))
    b.text_at(15, 17, billtype, size=10, color=(0.92, 0.92, 0.96))
    b.text_at(196, 13, "GSTIN " + D.gstin(company=provider)[:15], size=7.5, right=True, color=(1, 1, 1))

    # consumer block (left)
    b.rect_at(12, 28, 116, 48, stroke=(0.7, 0.7, 0.75))
    b.labeled(16, 32, "Consumer Name", name, vsize=11)
    b.text_at(16, 45, "Billing Address", size=7.5, color=(0.45, 0.45, 0.5))
    for i, ln in enumerate(addr):
        b.text_at(16, 50 + i * 4.6, ln, size=9)
    b.labeled(16, 68, id_label, consumer_no, vsize=10)

    # summary box (right)
    bill_date = D.date_str()
    b.rect_at(132, 28, 66, 48, stroke=(0.7, 0.7, 0.75), fill=(0.96, 0.97, 0.99))
    b.labeled(136, 32, "Bill Number", bill_no, vsize=9)
    b.labeled(136, 42, "Bill Date", bill_date, vsize=9)
    b.labeled(136, 52, "Billing Period", period, vsize=9)
    b.labeled(136, 62, "Due Date", D.date_str(), vsize=9)
    b.text_at(136, 73, "Bill Amount  " + D.inr(total), size=10, bold=True)

    # meter reading
    _cursor(b, 84)
    b.table(["Meter No.", "Previous Reading", "Current Reading", f"Units Consumed ({unit_label})"],
            [[str(random.randint(10 ** 6, 10 ** 7)), str(prev), str(curr), str(units)]],
            col_w=[34 * mm, 45 * mm, 45 * mm, 46 * mm])

    # charges
    if sub == "electricity":
        rows = [["Energy Charges (%d kWh @ Rs.%.2f)" % (units, rate), D.inr(energy)],
                ["Fixed / Demand Charges", D.inr(fixed)],
                ["Electricity Duty & Taxes", D.inr(tax)]]
    elif sub == "water":
        rows = [["Water Consumption Charges", D.inr(energy)],
                ["Sewerage / Maintenance Charges", D.inr(fixed)],
                ["Service Charge", D.inr(tax)]]
    else:
        rows = [["Gas Consumption Charges", D.inr(energy)],
                ["Minimum / Fixed Charges", D.inr(fixed)],
                ["VAT / GST", D.inr(tax)]]
    rows.append(["Current Bill Amount", D.inr(total)])
    b.table(["Charge Description", "Amount"], rows, col_w=[120 * mm, 50 * mm])

    b.spacer(2 * mm)
    b.field("Total Amount Payable", D.inr(total))
    b.field("Amount Payable After Due Date", D.inr(total + late))
    b.spacer(2 * mm)
    b.paragraph("This is a computer-generated utility bill. Please pay before the due date to avoid "
                "disconnection of supply. Retain this bill as proof of address and payment.")
    b.footer("Synthetic document for testing.")
    # YOLO field boxes (class order matches the real DJB detector: 0=Date,1=KNO,2=Name,3=address).
    # Geometry derived from the exact draw coords above (labeled() puts the value baseline at top_mm+4.5).
    boxes = [
        _ybox(b, 2, 16, 36.5, name, 11),          # Consumer Name
        _ybox(b, 1, 16, 72.5, consumer_no, 10),   # Consumer / K No.
        _ybox(b, 0, 136, 46.5, bill_date, 9),     # Bill Date
        _ybox_block(b, 3, 16, [50, 54.6, 59.2], addr, 9),  # Billing Address (3 lines)
    ]
    return b.build(), {"name": name, "address": ", ".join(addr), "consumer_no": consumer_no,
                       "sub_type": sub, "provider": provider, "amount": total, "_boxes": boxes}


# ----------------------------- REGISTRY -----------------------------

TEMPLATES = {
    "loan_agreement": (loan_agreement, "legal"),
    "sanction_letter": (sanction_letter, "legal"),
    "noc": (noc, "legal"),
    "board_resolution": (board_resolution, "legal"),
    "partnership_deed": (partnership_deed, "legal"),
    "moa_aoa": (moa_aoa, "legal"),
    "power_of_attorney": (power_of_attorney, "legal"),
    "indemnity_bond": (indemnity_bond, "legal"),
    "guarantee_letter": (guarantee_letter, "legal"),
    "rental_agreement": (rental_agreement, "legal"),
    "udyam_certificate": (udyam_certificate, "kyc"),
    "aadhaar": (aadhaar, "legal"),
    "pan": (pan, "legal"),
    "passport": (passport, "legal"),
    "bank_statement": (bank_statement, "financial"),
    "salary_slip": (salary_slip, "financial"),
    "form_16": (form_16, "financial"),
    "itr_v": (itr_v, "financial"),
    "itr_full": (itr_full, "financial"),
    "gstr_1": (gstr_1, "financial"),
    "gstr_3b": (gstr_3b, "financial"),
    "balance_sheet": (balance_sheet, "financial"),
    "profit_and_loss": (profit_and_loss, "financial"),
    "audited_financials": (audited_financials, "financial"),
    "cash_flow_statement": (cash_flow_statement, "financial"),
    "utility_bill": (utility_bill, "kyc"),
}
