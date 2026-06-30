"""Train a spaCy NER model on SYNTHETIC Indian document text (Step: NER training).

Goal (per user): a spaCy NER that works correctly on SYNTHETIC data now; real
data will be added later. Generates ID-card / form / prose text with EXACT entity
spans (we control them), trains a blank English CNN NER on CPU, evaluates on a
held-out synthetic split, and saves to /data/models/spacy-ner-synthetic.

Run inside the NER container (has spaCy; CPU is fine for a CNN model):
    docker exec trustlens-ner python /data/train_spacy_ner.py
"""
from __future__ import annotations

import random
from pathlib import Path

import spacy
from spacy.training import Example
from spacy.util import minibatch, compounding

SEED = 13
random.seed(SEED)
OUT_DIR = Path("/data/models/spacy-ner-synthetic")
LABELS = ["PERSON", "ORG", "GPE", "DATE"]

# --- realistic Indian value pools (synthetic, no real-doc dependency) ---
FIRST = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Arjun", "Kavya",
         "Rohan", "Pooja", "Sanjay", "Deepa", "Karthik", "Meena", "Imran", "Fatima",
         "Gurpreet", "Simran", "Joseph", "Mary", "Santhoshi", "Maqdooma", "Aditya",
         "Nisha", "Suresh", "Lakshmi", "Faisal", "Aisha", "Harish", "Divya"]
LAST = ["Sharma", "Verma", "Patel", "Reddy", "Nair", "Iyer", "Singh", "Kaur",
        "Khan", "Sheikh", "Mondal", "Das", "Gupta", "Mehta", "Rao", "Pillai",
        "Maurya", "Kaluva", "Joshi", "Bose", "Chopra", "Bansal", "Naidu", "Menon"]
ORGS = ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Punjab National Bank",
        "Kotak Mahindra Bank", "Bharat Industries Private Limited", "Sunrise Textiles Ltd",
        "Apex Constructions LLP", "Reliance Traders Pvt Ltd", "Canara Bank", "Yes Bank",
        "Infotech Solutions Limited", "Greenfield Agro Industries"]
GPES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune",
        "Ahmedabad", "Jaipur", "Lucknow", "Maharashtra", "Tamil Nadu", "Telangana",
        "Karnataka", "Gujarat", "Kerala", "Punjab", "West Bengal"]
UTIL_PROVIDERS = ["Delhi Jal Board", "Indraprastha Gas Limited", "Gujarat Gas Limited",
                  "BSES Rajdhani Power Limited", "Tata Power Delhi Distribution Limited",
                  "Bangalore Water Supply & Sewerage Board", "Mahanagar Gas Limited",
                  "Maharashtra State Electricity Distribution Co. Ltd.", "Torrent Power Limited"]


def rand_name():
    return f"{random.choice(FIRST)} {random.choice(LAST)}"


def rand_date():
    return f"{random.randint(1,28):02d}/{random.randint(1,12):02d}/{random.randint(1980,2024)}"


def mrz_noise(name):
    s = "".join(name.upper().split())
    return f"P<IND{s}<<<<<<<<<<<<<<<<<<<<"


def build_parts(parts):
    """parts: list of (text, label|None) -> (text, {'entities':[(s,e,label)]})."""
    s, ents = "", []
    for txt, label in parts:
        start = len(s); s += txt; end = len(s)
        if label:
            ents.append((start, end, label))
    return s, ents


# Each template returns a list of (text, label|None) parts. Mix of ID cards
# (with MRZ/labels as NON-entity noise) and prose, so NER learns names in
# realistic document context, not just clean sentences.
def t_pan():
    p, f = rand_name(), rand_name()
    return [("INCOME TAX DEPARTMENT GOVT OF INDIA\nPermanent Account Number\n", None),
            ("ABCDE1234F\n", None), (p, "PERSON"), ("\n", None), (f, "PERSON"),
            ("\n", None), (rand_date(), "DATE")]

def t_aadhaar():
    n = rand_name()
    return [("Government of India\n", None), (n, "PERSON"), ("\nDOB: ", None),
            (rand_date(), "DATE"), ("\n", None), (random.choice(GPES), "GPE"),
            ("\n2345 6789 0123", None)]

def t_passport():
    n = rand_name()
    return [("Republic of India\nName ", None), (n, "PERSON"),
            ("\nPlace of Birth ", None), (random.choice(GPES), "GPE"),
            ("\nDate of Issue ", None), (rand_date(), "DATE"),
            ("\n" + mrz_noise(n), None)]

def t_bankstmt():
    return [(random.choice(ORGS), "ORG"), ("\nAccount Statement\nAccount Holder: ", None),
            (rand_name(), "PERSON"), ("\nBranch: ", None), (random.choice(GPES), "GPE"),
            ("\nStatement Period: ", None), (rand_date(), "DATE"), (" to ", None),
            (rand_date(), "DATE")]

def t_loan():
    return [("This Loan Agreement is made on ", None), (rand_date(), "DATE"),
            (" between ", None), (random.choice(ORGS), "ORG"),
            (", a banking company, and ", None), (rand_name(), "PERSON"),
            (", resident of ", None), (random.choice(GPES), "GPE"), (" (the Borrower).", None)]

def t_salary():
    return [(random.choice(ORGS), "ORG"), ("\nSalary Slip for ", None),
            (rand_date(), "DATE"), ("\nEmployee Name: ", None), (rand_name(), "PERSON"),
            ("\nLocation: ", None), (random.choice(GPES), "GPE")]

def t_board():
    return [("RESOLVED THAT ", None), (rand_name(), "PERSON"),
            (" be and is hereby authorised to act on behalf of ", None),
            (random.choice(ORGS), "ORG"), (" at ", None), (random.choice(GPES), "GPE"),
            (" on ", None), (rand_date(), "DATE"), (".", None)]

def t_partnership():
    return [("This Deed of Partnership made on ", None), (rand_date(), "DATE"),
            (" between ", None), (rand_name(), "PERSON"), (" and ", None),
            (rand_name(), "PERSON"), (", carrying on business as ", None),
            (random.choice(ORGS), "ORG"), (" at ", None), (random.choice(GPES), "GPE"), (".", None)]

def t_noc():
    return [("To Whom It May Concern\nThis is to certify that ", None),
            (rand_name(), "PERSON"), (" of ", None), (random.choice(GPES), "GPE"),
            (" has no objection from ", None), (random.choice(ORGS), "ORG"),
            (" as on ", None), (rand_date(), "DATE"), (".", None)]

def t_utility():
    # Utility bill (electricity/water/gas) — the common address proof. Teaches the
    # consumer NAME as PERSON in bill context + the billing-city GPE, matching the
    # whole-page-OCR fallback path in backend utility_fields.py.
    cno = "".join(random.choices("0123456789", k=random.choice([10, 11, 12])))
    return [(random.choice(UTIL_PROVIDERS), "ORG"), ("\n", None),
            (random.choice(["ELECTRICITY BILL", "WATER BILL", "PIPED NATURAL GAS BILL"]), None),
            ("\nConsumer Name: ", None), (rand_name(), "PERSON"),
            (f"\nBilling Address: Flat {random.randint(1, 499)}, ", None), (random.choice(GPES), "GPE"),
            (f"\nConsumer No: {cno}\nBill Date: ", None), (rand_date(), "DATE"),
            ("\nDue Date: ", None), (rand_date(), "DATE")]

TEMPLATES = [t_pan, t_aadhaar, t_passport, t_bankstmt, t_loan, t_salary, t_board,
             t_partnership, t_noc, t_utility]


def gen(n):
    out = []
    for _ in range(n):
        parts = random.choice(TEMPLATES)()
        out.append(build_parts(parts))
    return out


def to_example(nlp, text, ent_tuples):
    doc = nlp.make_doc(text)
    ents = []
    for s, e, l in ent_tuples:
        sp = doc.char_span(s, e, label=l, alignment_mode="contract")
        if sp is not None:
            ents.append((sp.start_char, sp.end_char, sp.label_))
    return Example.from_dict(doc, {"entities": ents})


def main():
    train_raw = gen(2000)
    dev_raw = gen(400)
    print(f"generated train={len(train_raw)} dev={len(dev_raw)}")

    nlp = spacy.blank("en")
    ner = nlp.add_pipe("ner")
    for l in LABELS:
        ner.add_label(l)

    train_ex = [to_example(nlp, t, e) for t, e in train_raw]
    dev_ex = [to_example(nlp, t, e) for t, e in dev_raw]

    optimizer = nlp.initialize(lambda: train_ex)
    for epoch in range(25):
        random.shuffle(train_ex)
        losses = {}
        for batch in minibatch(train_ex, size=compounding(4.0, 32.0, 1.001)):
            nlp.update(batch, sgd=optimizer, drop=0.2, losses=losses)
        if (epoch + 1) % 5 == 0:
            sc = nlp.evaluate(dev_ex)
            print(f"epoch {epoch+1:2d} loss={losses.get('ner', 0):.1f} "
                  f"P={sc['ents_p']:.3f} R={sc['ents_r']:.3f} F={sc['ents_f']:.3f}")

    sc = nlp.evaluate(dev_ex)
    print("\n==== FINAL (held-out synthetic) ====")
    print(f"Precision={sc['ents_p']:.3f}  Recall={sc['ents_r']:.3f}  F1={sc['ents_f']:.3f}")
    for lbl, m in sorted(sc["ents_per_type"].items()):
        print(f"  {lbl:8s} P={m['p']:.3f} R={m['r']:.3f} F={m['f']:.3f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nlp.to_disk(OUT_DIR)
    print(f"\nsaved model -> {OUT_DIR}")

    # qualitative sanity check
    print("\n==== sample predictions ====")
    for t, _ in dev_raw[:4]:
        d = nlp(t)
        print(repr(t[:70]), "->", [(e.text, e.label_) for e in d.ents])


if __name__ == "__main__":
    main()
