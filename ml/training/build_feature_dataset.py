"""Build the XGBoost training CSV by running the forensic pipeline (Step 19).

Sources (label 0 = clean, 1 = tampered):
  - synthetic clean PDFs            (label 0) — realistic metadata/font/bank features
  - synthetic tampered PDFs         (label 1) — realistic metadata tampering
  - CASIA 2.0 Au (authentic) images (label 0) — realistic ELA/ManTraNet (clean)
  - CASIA 2.0 Tp (tampered)  images (label 1) — realistic ELA/ManTraNet (forgery)

Mixing both domains gives every feature a realistic clean-vs-tampered
distribution, so the learned scorer generalises to real documents.

Run inside the backend container:
    docker exec trustlens-backend sh -c "cd /ml && python -m training.build_feature_dataset"
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, "/app")  # make app.* importable

from app.forensics.bank_statement import analyze_bank_statement  # noqa: E402
from app.forensics.ela import analyze_ela  # noqa: E402
from app.forensics.font_spacing import analyze_font_spacing  # noqa: E402
from app.forensics.mantranet.wrapper import analyze_mantranet  # noqa: E402
from app.forensics.pdf_metadata import analyze_pdf_metadata  # noqa: E402
from app.forensics.signature_region import analyze_signature_regions  # noqa: E402
from app.forensics.stamp_auth import analyze_stamp_auth  # noqa: E402
from app.services.document_classifier import keyword_classify  # noqa: E402
from app.services.risk_features import FEATURE_NAMES, build_feature_vector  # noqa: E402
from app.services.text_extraction import extract_text  # noqa: E402

PDF_TYPE = "application/pdf"
OUT_CSV = Path("/data/models/xgb_features.csv")

SYN_CLEAN = Path("/data/synthetic")
SYN_TAMP = Path("/data/synthetic_tampered")
CASIA_AU = Path("/data/raw/external/casia2/CASIA2/Au")
CASIA_TP = Path("/data/raw/external/casia2/CASIA2/Tp")
PAYSLIP_ROOT = Path("/data/raw/external/payslip_forgery/sample_dataset")

# --- REAL clean documents (label 0). The single most important addition: every
# other clean PDF here is pristine *synthetic* (pdf_metadata == 1.0), so the
# scorer wrongly learned "any pdf_metadata imperfection => tampered". Real
# documents are produced by Office/Distiller/Ghostscript, are scanned, merged,
# certified — so they legitimately score <1.0 on metadata/font. Feeding them as
# CLEAN teaches the scorer that an imperfect-but-benign forensic profile is not
# fraud, while the tampered sources keep ela/mantranet/font discrimination. ---
REAL_PDF_DIRS = [
    ("real_financials", Path("/data/raw/external/real_docs")),     # audited/bal-sheet/p&l/cashflow
    ("real_annual_report", Path("/data/raw/external/annual_report")),
    ("real_moa", Path("/data/raw/external/MOA")),                   # 17 real MOA/AOA bundles
    ("real_partnership", Path("/data/raw/external/Partnership")),    # real partnership deeds (scanned)
]
MOA_TEXT_CACHE = Path("/data/raw/external/_moa_text")              # avoids re-OCR of scanned MOA
REAL_IMG_DIRS = [
    ("real_pancard", Path("/data/raw/external/pancard")),
    ("real_aadhaar", Path("/data/raw/external/roboflow_aadhaar")),
]

PER_TYPE_CLEAN = 18      # synthetic clean per doc type (23 types -> ~414)
CASIA_SAMPLE = 500       # per class
REAL_IMG_SAMPLE = 120    # per real-image source (genuine card photos -> clean)
SEED = 42


def features_for_pdf(content: bytes, text: str | None = None,
                     skip_text: bool = False) -> list[float]:
    scores = {
        "pdf_metadata": analyze_pdf_metadata(content)["score"],
        "font_spacing": analyze_font_spacing(content, PDF_TYPE)["score"],
        "signature_region": analyze_signature_regions(content, PDF_TYPE)["score"],
        "stamp_auth": analyze_stamp_auth(content, PDF_TYPE)["score"],
        "ela": analyze_ela(content, PDF_TYPE)["score"],
        "mantranet": analyze_mantranet(content, PDF_TYPE)["score"],
    }
    if skip_text:
        # Caller guarantees this is NOT a bank statement (real financials / legal /
        # annual reports). analyze_bank_statement returns 1.0 for any non-bank doc,
        # so we skip the (very slow, page-by-page) OCR of huge scanned PDFs and set
        # it directly. Train/serve-consistent: at serve time these classify as
        # non-bank too, so bank_statement == 1.0 there as well.
        scores["bank_statement"] = 1.0
    else:
        if text is None:  # caller may pass cached OCR text to skip re-OCR
            text, _ = extract_text(content, PDF_TYPE)
        dt = keyword_classify(text)["doc_type"]
        scores["bank_statement"] = analyze_bank_statement(text, dt)["score"]
    return build_feature_vector(scores)


def features_for_image(content: bytes, content_type: str) -> list[float]:
    # Downscale large photos so ManTraNet / stamp / signature passes stay fast
    # (ELA already downscales to 1600 internally). Keeps the full rebuild tractable;
    # no meaningful train/serve skew — these image features have ~0 model weight.
    import io as _io
    from PIL import Image as _Image
    try:
        im = _Image.open(_io.BytesIO(content))
        if max(im.size) > 1600:
            im = im.convert("RGB")
            im.thumbnail((1600, 1600))
            buf = _io.BytesIO()
            im.save(buf, format="JPEG", quality=92)
            content, content_type = buf.getvalue(), "image/jpeg"
    except Exception:
        pass
    scores = {
        "signature_region": analyze_signature_regions(content, content_type)["score"],
        "stamp_auth": analyze_stamp_auth(content, content_type)["score"],
        "ela": analyze_ela(content, content_type)["score"],
        "mantranet": analyze_mantranet(content, content_type)["score"],
        # pdf_metadata / font_spacing / bank_statement not applicable to raw images -> default 1.0
    }
    return build_feature_vector(scores)


def _ctype(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".png":
        return "image/png"
    return "image/jpeg"  # treat jpg/tif/bmp as jpeg-decodable via PIL


def main():
    random.seed(SEED)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[list[float], int, str]] = []

    # --- synthetic clean (label 0) ---
    n = 0
    for d in sorted(SYN_CLEAN.iterdir()):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.pdf"))[:PER_TYPE_CLEAN]:
            try:
                rows.append((features_for_pdf(p.read_bytes()), 0, "syn_clean"))
                n += 1
            except Exception as e:
                print(f"  ! {p}: {e.__class__.__name__}")
    print(f"synthetic clean: {n}")

    # --- REAL clean PDFs (label 0) — the fix for the pdf_metadata overfit ---
    for tag, d in REAL_PDF_DIRS:
        if not d.exists():
            print(f"{tag}: (missing {d})")
            continue
        n = 0
        for p in sorted(d.rglob("*.pdf")):
            try:
                # These real sources are financials / annual reports / MOA-AOA —
                # none are bank statements, so skip OCR entirely (huge scanned
                # annual reports were OCR-hanging the build for hours).
                rows.append((features_for_pdf(p.read_bytes(), skip_text=True), 0, tag))
                n += 1
                if n % 25 == 0:
                    print(f"  {tag}: {n}", flush=True)
            except Exception as e:
                print(f"  ! {p.name}: {e.__class__.__name__}", flush=True)
        print(f"{tag}: {n}", flush=True)

    # --- REAL clean images (label 0) — genuine Aadhaar/PAN card photos ---
    for tag, d in REAL_IMG_DIRS:
        if not d.exists():
            print(f"{tag}: (missing {d})")
            continue
        imgs = [f for f in d.rglob("*.jpg")] + [f for f in d.rglob("*.png")]
        imgs = [f for f in imgs if "__MACOSX" not in str(f)]
        random.shuffle(imgs)
        imgs = imgs[:REAL_IMG_SAMPLE]
        n = 0
        for p in imgs:
            ctype = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            try:
                rows.append((features_for_image(p.read_bytes(), ctype), 0, tag))
                n += 1
            except Exception as e:
                print(f"  ! {p.name}: {e.__class__.__name__}")
            if n % 100 == 0 and n:
                print(f"  {tag}: {n}/{len(imgs)}")
        print(f"{tag}: {n}")

    # --- synthetic tampered (label 1) ---
    n = 0
    if SYN_TAMP.exists():
        for d in sorted(SYN_TAMP.iterdir()):
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.pdf")):
                try:
                    rows.append((features_for_pdf(p.read_bytes()), 1, "syn_tamp"))
                    n += 1
                except Exception as e:
                    print(f"  ! {p}: {e.__class__.__name__}")
    print(f"synthetic tampered: {n}")

    # --- Payslip Forgery (real, in-domain): Genuine=0, forged=1 ---
    if PAYSLIP_ROOT.exists():
        genuine = [p for p in (PAYSLIP_ROOT / "Genuine").rglob("*.tif")
                   if "__MACOSX" not in str(p)]
        forged = [p for p in PAYSLIP_ROOT.rglob("*.tif")
                  if "__MACOSX" not in str(p)
                  and ("CopyPaste" in str(p) or "Imitation" in str(p))]
        for p in genuine:
            try:
                rows.append((features_for_image(p.read_bytes(), "image/jpeg"), 0, "payslip_genuine"))
            except Exception as e:
                print(f"  ! {p.name}: {e.__class__.__name__}")
        for p in forged:
            try:
                rows.append((features_for_image(p.read_bytes(), "image/jpeg"), 1, "payslip_forged"))
            except Exception as e:
                print(f"  ! {p.name}: {e.__class__.__name__}")
        print(f"payslip: {len(genuine)} genuine, {len(forged)} forged")

    # --- CASIA Au (label 0) + Tp (label 1) ---
    for folder, label, tag in [(CASIA_AU, 0, "casia_au"), (CASIA_TP, 1, "casia_tp")]:
        files = [f for f in folder.iterdir() if f.suffix.lower() in (".jpg", ".png", ".tif", ".bmp")]
        random.shuffle(files)
        files = files[:CASIA_SAMPLE]
        n = 0
        for p in files:
            try:
                rows.append((features_for_image(p.read_bytes(), _ctype(p)), label, tag))
                n += 1
            except Exception as e:
                print(f"  ! {p.name}: {e.__class__.__name__}")
            if n % 100 == 0 and n:
                print(f"  {tag}: {n}/{len(files)}")
        print(f"{tag}: {n}")

    random.shuffle(rows)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FEATURE_NAMES + ["label", "source"])
        for feats, label, tag in rows:
            w.writerow([f"{x:.5f}" for x in feats] + [label, tag])

    n_clean = sum(1 for _, l, _ in rows if l == 0)
    n_tamp = sum(1 for _, l, _ in rows if l == 1)
    print(f"\nWrote {len(rows)} rows ({n_clean} clean / {n_tamp} tampered) -> {OUT_CSV}")


if __name__ == "__main__":
    main()
