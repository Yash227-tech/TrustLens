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
}
