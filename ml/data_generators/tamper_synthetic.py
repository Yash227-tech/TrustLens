"""Create tampered copies of synthetic clean PDFs (Step 19 training data).

Applies realistic, detectable tampering so the metadata/font forensic features
show a genuine clean-vs-tampered separation for XGBoost:

  - Rewrites /Producer + /Creator to a suspicious tool (Photoshop/iLovePDF/...)
  - Sets ModDate well after CreationDate
  - Appends an incremental-update marker (extra %%EOF)

Outputs to /data/synthetic_tampered/<doc_type>/<NNN>.pdf
"""

from __future__ import annotations

import io
import random
from pathlib import Path

import pikepdf

SRC_ROOT = Path("/data/synthetic")
OUT_ROOT = Path("/data/synthetic_tampered")

SUSPICIOUS = [
    ("Adobe Photoshop CS6 (Windows)", "Adobe Photoshop"),
    ("iLovePDF", "iLovePDF"),
    ("GIMP 2.10", "GIMP"),
    ("Smallpdf", "Smallpdf"),
    ("Microsoft® Word 2021", "Microsoft® Word"),
]


def tamper_pdf(content: bytes) -> bytes:
    with pikepdf.open(io.BytesIO(content)) as pdf:
        producer, creator = random.choice(SUSPICIOUS)
        with pdf.open_metadata() as meta:
            pass  # touch XMP
        di = pdf.docinfo
        di["/Producer"] = producer
        di["/Creator"] = creator
        di["/CreationDate"] = "D:20240101100000+05'30'"
        di["/ModDate"] = "D:20260528154500+05'30'"
        buf = io.BytesIO()
        pdf.save(buf)
    data = buf.getvalue()
    # Append an incremental-update marker (extra %%EOF) to trip that heuristic.
    data += b"\n%%EOF\n"
    return data


def main(per_type: int = 30) -> None:
    random.seed(99)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    total = 0
    for d in sorted(SRC_ROOT.iterdir()):
        if not d.is_dir():
            continue
        out_dir = OUT_ROOT / d.name
        out_dir.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(d.glob("*.pdf"))[:per_type]
        for p in pdfs:
            try:
                tampered = tamper_pdf(p.read_bytes())
                (out_dir / p.name).write_bytes(tampered)
                total += 1
            except Exception as e:
                print(f"  ! {p.name}: {e.__class__.__name__}: {e}")
    print(f"Tampered {total} synthetic docs -> {OUT_ROOT}")


if __name__ == "__main__":
    main()
