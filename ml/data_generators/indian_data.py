"""Indian synthetic data helpers built on Faker.

Generates realistic-looking (but entirely fake) Indian identifiers and
values for use in synthetic document generation. NONE of this is real PII.
"""

from __future__ import annotations

import random
import string

from faker import Faker

fake = Faker("en_IN")

BANKS = [
    ("State Bank of India", "SBIN"),
    ("HDFC Bank", "HDFC"),
    ("ICICI Bank", "ICIC"),
    ("Axis Bank", "UTIB"),
    ("Canara Bank", "CNRB"),
    ("Punjab National Bank", "PUNB"),
    ("Bank of Baroda", "BARB"),
    ("Kotak Mahindra Bank", "KKBK"),
]

CITIES = [
    ("Mumbai", "Maharashtra", "400001"),
    ("Delhi", "Delhi", "110001"),
    ("Bengaluru", "Karnataka", "560001"),
    ("Chennai", "Tamil Nadu", "600001"),
    ("Kolkata", "West Bengal", "700001"),
    ("Pune", "Maharashtra", "411001"),
    ("Hyderabad", "Telangana", "500001"),
    ("Ahmedabad", "Gujarat", "380001"),
]

COMPANY_SUFFIXES = ["Private Limited", "Limited", "LLP", "& Sons", "Enterprises", "Industries"]


def person_name() -> str:
    return fake.name()


def company_name() -> str:
    base = fake.last_name() + " " + random.choice(
        ["Traders", "Textiles", "Infotech", "Steel", "Motors", "Agro", "Pharma", "Constructions"]
    )
    return f"{base} {random.choice(COMPANY_SUFFIXES)}"


def address() -> str:
    city, state, pin = random.choice(CITIES)
    line = f"{random.randint(1, 999)}, {fake.street_name()}"
    return f"{line}, {city}, {state} - {pin}"


def city_state_pin() -> tuple[str, str, str]:
    return random.choice(CITIES)


def pan(surname: str | None = None, holder: str = "P") -> str:
    """Realistic PAN per Income-Tax rules so it survives structural validation:
      - chars 1-3: random letters
      - char 4   : holder type (P=Individual, C=Company, H=HUF, F=Firm, ...)
      - char 5   : first letter of the surname / entity name
      - chars 6-9: digits ; char 10: a letter
    If no surname is supplied the 5th letter is random (legacy behaviour)."""
    first3 = "".join(random.choices(string.ascii_uppercase, k=3))
    fourth = holder if holder in "PCHFATBLJG" else "P"
    fifth = surname[0].upper() if (surname and surname[:1].isalpha()) \
        else random.choice(string.ascii_uppercase)
    digits = "".join(random.choices(string.digits, k=4))
    last = random.choice(string.ascii_uppercase)
    return f"{first3}{fourth}{fifth}{digits}{last}"


# UIDAI Verhoeff tables (same as app/services/entity_extraction.py) so synthetic
# Aadhaar numbers carry a VALID check digit and aren't flagged "fabricated".
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6), (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4), (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2), (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def aadhaar() -> str:
    # Real format: 12 digits, first digit 2-9, last is a Verhoeff check digit.
    payload = [random.randint(2, 9)] + [random.randint(0, 9) for _ in range(10)]
    c = 0
    for i, d in enumerate(reversed(payload)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[(i + 1) % 8][d]]
    digits = payload + [_VERHOEFF_INV[c]]
    s = "".join(map(str, digits))
    return f"{s[0:4]} {s[4:8]} {s[8:12]}"


def gstin(company: str | None = None) -> str:
    # GSTIN embeds the entity's PAN (a business -> holder type C, 5th letter =
    # first letter of the company name) so it stays internally consistent.
    state_code = f"{random.randint(1, 37):02d}"
    p = pan(surname=company, holder="C")
    entity = random.choice(string.digits)
    return f"{state_code}{p}{entity}Z{random.choice(string.ascii_uppercase + string.digits)}"


def account_number() -> str:
    return "".join(random.choices(string.digits, k=random.choice([11, 12, 14])))


def ifsc(bank_code: str | None = None) -> str:
    code = bank_code or random.choice(BANKS)[1]
    return f"{code}0{''.join(random.choices(string.digits, k=6))}"


def passport_number() -> str:
    return random.choice(string.ascii_uppercase) + "".join(random.choices(string.digits, k=7))


def acknowledgement_number() -> str:
    return "".join(random.choices(string.digits, k=15))


def amount(lo: int = 10_000, hi: int = 5_000_000) -> int:
    return random.randint(lo, hi)


def inr(value: int | float) -> str:
    """Format a number in the Indian numbering system with a rupee sign."""
    s = f"{int(value):,}"  # fallback to western grouping if locale missing
    # Convert western grouping to Indian grouping.
    neg = s.startswith("-")
    digits = s.replace(",", "").lstrip("-")
    if len(digits) > 3:
        last3 = digits[-3:]
        rest = digits[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts) + "," + last3
    else:
        grouped = digits
    return ("-" if neg else "") + "Rs. " + grouped


def date_str() -> str:
    return fake.date_between(start_date="-2y", end_date="today").strftime("%d/%m/%Y")


def assessment_year() -> str:
    y = random.randint(2021, 2024)
    return f"{y}-{str(y + 1)[2:]}"


def bank() -> tuple[str, str]:
    return random.choice(BANKS)


def designation() -> str:
    return random.choice(
        ["Manager", "Senior Engineer", "Accountant", "Sales Executive",
         "Branch Manager", "Software Developer", "Operations Lead", "Analyst"]
    )


def seed(n: int) -> None:
    random.seed(n)
    Faker.seed(n)
