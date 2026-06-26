"""DOCX → PDF conversion via LibreOffice headless.

Used so the pixel-based forensic modules (ELA, ManTraNet) can run on the
rendered pages of a Word document. LibreOffice is installed in the
container's Dockerfile.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

LIBREOFFICE_BIN = shutil.which("libreoffice") or shutil.which("soffice") or "libreoffice"
CONVERT_TIMEOUT_SEC = 60


class DocxConversionError(RuntimeError):
    pass


def docx_to_pdf_bytes(docx_bytes: bytes) -> bytes:
    """Convert a DOCX byte stream into a PDF byte stream.

    Raises DocxConversionError on failure (LibreOffice missing, timeout,
    or empty output).
    """
    with tempfile.TemporaryDirectory(prefix="trustlens_docx_") as td:
        td_path = Path(td)
        input_path = td_path / "input.docx"
        input_path.write_bytes(docx_bytes)

        try:
            proc = subprocess.run(
                [
                    LIBREOFFICE_BIN,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(td_path),
                    str(input_path),
                ],
                capture_output=True,
                timeout=CONVERT_TIMEOUT_SEC,
                check=False,
            )
        except FileNotFoundError as e:
            raise DocxConversionError(f"LibreOffice not found: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise DocxConversionError(
                f"LibreOffice conversion timed out after {CONVERT_TIMEOUT_SEC}s"
            ) from e

        pdf_path = td_path / "input.pdf"
        if proc.returncode != 0 or not pdf_path.exists():
            stderr = proc.stderr.decode("utf-8", errors="ignore")[:500]
            raise DocxConversionError(
                f"LibreOffice failed (exit {proc.returncode}): {stderr}"
            )

        return pdf_path.read_bytes()
