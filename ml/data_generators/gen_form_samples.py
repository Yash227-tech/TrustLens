"""Generate ONE high-fidelity synthetic sample of each of the 4 form types
(Form 16, GSTR-3B, ITR-1, ITR-V) — for evaluating generation quality.

Realistic government-form structure (sections + tables), data obeys the real
rules (PAN holder/surname, GSTIN from company, assessment year, ack number).
Watermarked SYNTHETIC SPECIMEN — never a real document.

    docker exec trustlens-backend sh -c "cd /ml && python -m data_generators.gen_form_samples"
Outputs to /data/raw/external/Form/_synthetic_samples/
"""
from __future__ import annotations

import random
from pathlib import Path

from reportlab.lib.units import mm

from . import indian_data as D
from .builder import DocBuilder

OUT = Path("/data/raw/external/Form/_synthetic_samples")


def _section(b: DocBuilder, text: str):
    b.spacer(1 * mm)
    b.c.setFillColorRGB(0.12, 0.23, 0.54)
    b.c.setFont("Helvetica-Bold", 10)
    b.c.drawString(b.left, b.y, text)
    b.c.setStrokeColorRGB(0.12, 0.23, 0.54)
    b.c.line(b.left, b.y - 1.5 * mm, b.right, b.y - 1.5 * mm)
    b.c.setFillColorRGB(0, 0, 0)
    b.y -= 7 * mm


def _two_col(b: DocBuilder, left_label, left_val, right_label, right_val):
    """Two fields on one row — compact, form-like."""
    y = b.y
    b.c.setFont("Helvetica-Bold", 9); b.c.drawString(b.left, y, f"{left_label}:")
    b.c.setFont("Helvetica", 9); b.c.drawString(b.left + 38 * mm, y, str(left_val))
    b.c.setFont("Helvetica-Bold", 9); b.c.drawString(b.left + 105 * mm, y, f"{right_label}:")
    b.c.setFont("Helvetica", 9); b.c.drawString(b.left + 145 * mm, y, str(right_val))
    b.y -= 6 * mm


# ---------------------------------------------------------------- Form 16
def form_16():
    name, comp = D.person_name(), D.company_name()
    pan_e = D.pan(surname=name.split()[-1], holder="P")
    tan = "".join(random.choice("ABCDEFGHIJKLMNPQRSTUVWXYZ") for _ in range(4)) + \
        "".join(str(random.randint(0, 9)) for _ in range(5)) + random.choice("ABCDEFGHJKLMNP")
    pan_d = D.pan(holder="C")
    ay = D.assessment_year()
    gross = D.amount(600_000, 2_400_000)
    addr_c = D.address()
    b = DocBuilder("Form No. 16")
    b.header_bar("FORM NO. 16", "[See rule 31(1)(a)]  -  INCOME TAX DEPARTMENT, GOVT. OF INDIA")
    b.title("Certificate under Section 203 of the Income-tax Act, 1961", 11)
    b.subtitle("for tax deducted at source on salary paid to an employee", 9)
    _section(b, "PART A  -  Details of Deductor and Deductee")
    b.field("Name of Employer (Deductor)", comp, label_w=62 * mm)
    b.field("Address of Employer", addr_c, label_w=62 * mm)
    _two_col(b, "TAN of Deductor", tan, "PAN of Deductor", pan_d)
    b.field("Name of Employee (Deductee)", name, label_w=62 * mm)
    _two_col(b, "PAN of Employee", pan_e, "Assessment Year", ay)
    _two_col(b, "Period From", "01-Apr-" + ay.split("-")[0][:4],
             "Period To", "31-Mar-" + ay.split("-")[1])
    _section(b, "Summary of tax deducted at source")
    rows = []
    total_tds = 0
    for q in ("Q1", "Q2", "Q3", "Q4"):
        paid = D.amount(120_000, 600_000)
        tds = int(paid * random.uniform(0.05, 0.12))
        total_tds += tds
        rows.append([q, f"RCPT{random.randint(100000,999999)}", D.inr(paid), D.inr(tds), D.inr(tds)])
    b.table(["Quarter", "Receipt No.", "Amount Paid/Credited", "Tax Deducted (Rs.)", "Tax Deposited (Rs.)"],
            rows, col_w=[18 * mm, 32 * mm, 42 * mm, 38 * mm, 40 * mm])
    _section(b, "PART B (Annexure)  -  Details of Salary Paid and Tax Computation")
    ded_16 = 50000
    chap6a = D.amount(50_000, 150_000)
    ti = gross - ded_16 - chap6a
    tax = int(ti * 0.15)
    b.field("1. Gross Salary u/s 17(1)", D.inr(gross), label_w=78 * mm)
    b.field("2. Less: Standard Deduction u/s 16(ia)", D.inr(ded_16), label_w=78 * mm)
    b.field("3. Deductions under Chapter VI-A (80C/80D)", D.inr(chap6a), label_w=78 * mm)
    b.field("4. Total Income", D.inr(ti), label_w=78 * mm)
    b.field("5. Tax on Total Income", D.inr(tax), label_w=78 * mm)
    b.field("6. Health & Education Cess @ 4%", D.inr(int(tax * 0.04)), label_w=78 * mm)
    b.field("7. Total Tax Deducted at Source", D.inr(total_tds), label_w=78 * mm)
    b.paragraph("I hereby certify that the information given above is true, complete and correct and is "
                "based on the books of account, documents, TDS statements and other available records.")
    b.signature_block(D.person_name(), "Person responsible for deduction of tax")
    b.stamp_placeholder("TDS")
    b.footer("SYNTHETIC SPECIMEN - generated for model testing. Not a real Form 16.")
    return b.build()


# ---------------------------------------------------------------- GSTR-3B
def gstr_3b():
    comp = D.company_name()
    g = D.gstin(company=comp)
    month = random.choice(["April", "May", "June", "July", "August", "September"])
    b = DocBuilder("Form GSTR-3B")
    b.header_bar("FORM GSTR-3B", "[See rule 61(5)]  -  GOODS AND SERVICES TAX", color=(0.10, 0.40, 0.30))
    b.title("Monthly Summary Return", 12)
    _two_col(b, "GSTIN", g, "Return Period", f"{month} {D.assessment_year().split('-')[0][:4]}")
    b.field("Legal Name of Registered Person", comp, label_w=70 * mm)
    _section(b, "3.1  Details of Outward Supplies and inward supplies liable to reverse charge")
    def trip(v):  # split a taxable value into igst/cgst/sgst-ish
        return D.inr(int(v * 0.0)), D.inr(int(v * 0.09)), D.inr(int(v * 0.09))
    o1 = D.amount(500_000, 5_000_000)
    rc = D.amount(10_000, 100_000)
    rows = [
        ["(a) Outward taxable supplies (other than zero/nil/exempt)", D.inr(o1), *trip(o1)],
        ["(b) Outward taxable supplies (zero rated)", D.inr(0), D.inr(0), "-", "-"],
        ["(c) Other outward supplies (nil rated, exempted)", D.inr(D.amount(0, 50_000)), "-", "-", "-"],
        ["(d) Inward supplies (liable to reverse charge)", D.inr(rc), D.inr(int(rc * 0.18)), "-", "-"],
        ["(e) Non-GST outward supplies", D.inr(0), "-", "-", "-"],
    ]
    b.table(["Nature of Supplies", "Taxable Value", "Integrated Tax", "Central Tax", "State/UT Tax"],
            rows, col_w=[78 * mm, 28 * mm, 26 * mm, 19 * mm, 19 * mm])
    _section(b, "4.  Eligible Input Tax Credit (ITC)")
    itc = D.amount(50_000, 800_000)
    b.field("(A) ITC Available - Import / Inward supplies", D.inr(itc), label_w=80 * mm)
    b.field("(C) Net ITC Available", D.inr(int(itc * 0.95)), label_w=80 * mm)
    _section(b, "5.1  Interest and 6.1  Payment of Tax")
    b.field("Integrated Tax payable", D.inr(int(o1 * 0.0)), label_w=80 * mm)
    b.field("Central + State Tax payable (net of ITC)", D.inr(int(o1 * 0.18 - itc * 0.95)), label_w=80 * mm)
    b.field("Interest & Late Fee", D.inr(0), label_w=80 * mm)
    b.paragraph("Verified that the above details of inward and outward supplies liable to reverse charge "
                "and net tax payable are true and correct, filed as a summary return.")
    b.signature_block(D.person_name(), "Authorised Signatory")
    b.footer("SYNTHETIC SPECIMEN - generated for model testing. Not a real GSTR-3B.")
    return b.build()


# ---------------------------------------------------------------- ITR-1 Sahaj
def itr_full():
    name = D.person_name()
    pan = D.pan(surname=name.split()[-1], holder="P")
    ay = D.assessment_year()
    ifsc = D.ifsc()
    acct = D.account_number()
    sal = D.amount(500_000, 3_000_000)
    hp = D.amount(0, 200_000)
    oth = D.amount(5_000, 120_000)
    gti = sal + hp + oth
    ded = min(150_000, D.amount(50_000, 150_000))
    ti = gti - ded
    tax = int(max(0, ti - 250_000) * 0.12)
    b = DocBuilder("Indian Income Tax Return ITR-1")
    b.header_bar("INDIAN INCOME TAX RETURN  -  ITR-1 (SAHAJ)",
                 "For individuals being a resident with income up to Rs. 50 lakh")
    b.title(f"Assessment Year  {ay}", 12)
    _section(b, "Part A  -  General Information")
    b.field("Name", name, label_w=42 * mm)
    _two_col(b, "PAN", pan, "Aadhaar No.", D.aadhaar())
    _two_col(b, "Date of Birth", D.date_str(), "Status", "Individual")
    b.field("Address", D.address(), label_w=42 * mm)
    _two_col(b, "Filing Status", "Filed u/s 139(1) - On or before due date",
             "Return Type", "Original")
    _section(b, "Part B  -  Gross Total Income")
    b.field("B1  Income from Salary / Pension", D.inr(sal), label_w=78 * mm)
    b.field("B2  Income from House Property", D.inr(hp), label_w=78 * mm)
    b.field("B3  Income from Other Sources", D.inr(oth), label_w=78 * mm)
    b.field("B4  Gross Total Income (B1+B2+B3)", D.inr(gti), label_w=78 * mm)
    _section(b, "Part C  -  Deductions and Taxable Total Income")
    b.field("C1  Deduction u/s 80C", D.inr(min(ded, 150_000)), label_w=78 * mm)
    b.field("C2  Deduction u/s 80D / 80TTA", D.inr(D.amount(0, 25_000)), label_w=78 * mm)
    b.field("Total Income (Taxable)", D.inr(ti), label_w=78 * mm)
    _section(b, "Part D  -  Computation of Tax Payable")
    b.field("D1  Tax Payable on Total Income", D.inr(tax), label_w=78 * mm)
    b.field("D2  Rebate u/s 87A", D.inr(0 if ti > 700_000 else tax), label_w=78 * mm)
    b.field("D3  Health & Education Cess @ 4%", D.inr(int(tax * 0.04)), label_w=78 * mm)
    b.field("D4  Total Tax & Cess", D.inr(int(tax * 1.04)), label_w=78 * mm)
    b.field("D5  Total Taxes Paid (TDS + Advance Tax)", D.inr(int(tax * 1.04)), label_w=78 * mm)
    _section(b, "Bank Account for Refund")
    _two_col(b, "IFSC Code", ifsc, "Account Number", acct)
    b.paragraph("This income tax return is filed for the assessment year shown above under the "
                "provisions of the Income-tax Act, 1961.")
    b.footer("SYNTHETIC SPECIMEN - generated for model testing. Not a real ITR.")
    return b.build()


# ---------------------------------------------------------------- ITR-V
def itr_v():
    name = D.person_name()
    pan = D.pan(surname=name.split()[-1], holder="P")
    ack = D.acknowledgement_number()
    ay = D.assessment_year()
    gti = D.amount(400_000, 4_000_000)
    ded = D.amount(50_000, 150_000)
    ti = gti - ded
    tax = int(max(0, ti - 250_000) * 0.12 * 1.04)
    b = DocBuilder("ITR-V Acknowledgement")
    b.header_bar("INDIAN INCOME TAX RETURN VERIFICATION FORM  -  ITR-V",
                 "Where the return has been filed electronically without digital signature")
    b.title(f"Assessment Year  {ay}", 12)
    _section(b, "Acknowledgement of Receipt")
    b.field("Name of Assessee", name, label_w=52 * mm)
    _two_col(b, "PAN", pan, "Form Number", "ITR-1")
    _two_col(b, "e-Filing Acknowledgement Number", ack, "Date of Filing", D.date_str())
    _section(b, "Computation Summary")
    b.field("1  Gross Total Income", D.inr(gti), label_w=72 * mm)
    b.field("2  Total Deductions under Chapter VI-A", D.inr(ded), label_w=72 * mm)
    b.field("3  Total Income", D.inr(ti), label_w=72 * mm)
    b.field("4  Total Tax, Interest and Fee payable", D.inr(tax), label_w=72 * mm)
    b.field("5  Total Taxes Paid", D.inr(tax), label_w=72 * mm)
    b.field("6  Tax Payable / (Refund)", D.inr(0), label_w=72 * mm)
    _section(b, "Verification")
    b.paragraph(f"I, {name}, solemnly declare that to the best of my knowledge and belief, the "
                f"information given in the return is correct and complete and is in accordance with the "
                f"provisions of the Income-tax Act, 1961, holding PAN {pan} for the assessment year {ay}.")
    b.spacer(2 * mm)
    # barcode-ish acknowledgement strip (a real ITR-V has a code128 of the ack no.)
    b.c.setFont("Courier-Bold", 12)
    b.c.drawCentredString(105 * mm, b._ay(0) - b.y, "")  # noop safe
    b.text_at(105, 235, " ".join(ack), size=11, bold=True, center=True, font="Courier-Bold")
    b.text_at(105, 240, f"Acknowledgement Number : {ack}", size=9, center=True)
    b.signature_block(name, "Signature of the Assessee")
    b.footer("SYNTHETIC SPECIMEN - generated for model testing. Not a real ITR-V.")
    return b.build()


def main():
    D.seed(7)
    random.seed(7)
    OUT.mkdir(parents=True, exist_ok=True)
    for fn, label in [(form_16, "form16"), (gstr_3b, "gstr3b"),
                      (itr_full, "itr1"), (itr_v, "itrv")]:
        path = OUT / f"synthetic_{label}.pdf"
        path.write_bytes(fn())
        print(f"  wrote {path} ({path.stat().st_size} bytes)")
    print(f"\nDone -> {OUT}")


if __name__ == "__main__":
    main()
