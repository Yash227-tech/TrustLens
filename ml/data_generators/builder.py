"""ReportLab helpers for building synthetic document PDFs.

A thin DocBuilder wrapper over reportlab.canvas that gives templates a small
vocabulary: header bar, title, labelled fields, paragraphs, tables, signature
blocks, and a stamp placeholder. Returns PDF bytes.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = A4


class DocBuilder:
    def __init__(self, title_meta: str = "TrustLens Synthetic Document"):
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.c.setTitle(title_meta)
        self.y = PAGE_H - 20 * mm
        self.left = 20 * mm
        self.right = PAGE_W - 20 * mm

    # --- layout primitives ---
    def header_bar(self, text: str, sub: str = "", color=(0.12, 0.23, 0.54)):
        self.c.setFillColorRGB(*color)
        self.c.rect(0, PAGE_H - 28 * mm, PAGE_W, 28 * mm, fill=1, stroke=0)
        self.c.setFillColorRGB(1, 1, 1)
        self.c.setFont("Helvetica-Bold", 16)
        self.c.drawString(self.left, PAGE_H - 16 * mm, text)
        if sub:
            self.c.setFont("Helvetica", 9)
            self.c.drawString(self.left, PAGE_H - 22 * mm, sub)
        self.c.setFillColorRGB(0, 0, 0)
        self.y = PAGE_H - 38 * mm

    def title(self, text: str, size: int = 14):
        self.c.setFont("Helvetica-Bold", size)
        self.c.drawCentredString(PAGE_W / 2, self.y, text)
        self.y -= 9 * mm

    def subtitle(self, text: str, size: int = 10):
        self.c.setFont("Helvetica-Oblique", size)
        self.c.drawCentredString(PAGE_W / 2, self.y, text)
        self.y -= 7 * mm

    def field(self, label: str, value: str, label_w: float = 55 * mm):
        self.c.setFont("Helvetica-Bold", 10)
        self.c.drawString(self.left, self.y, f"{label}:")
        self.c.setFont("Helvetica", 10)
        self.c.drawString(self.left + label_w, self.y, str(value))
        self.y -= 6.5 * mm

    def paragraph(self, text: str, size: int = 10, leading: float = 5.5 * mm):
        self.c.setFont("Helvetica", size)
        words = text.split()
        line = ""
        max_w = self.right - self.left
        for w in words:
            trial = (line + " " + w).strip()
            if self.c.stringWidth(trial, "Helvetica", size) > max_w:
                self.c.drawString(self.left, self.y, line)
                self.y -= leading
                line = w
            else:
                line = trial
        if line:
            self.c.drawString(self.left, self.y, line)
            self.y -= leading
        self.y -= 2 * mm

    def spacer(self, h: float = 5 * mm):
        self.y -= h

    def table(self, headers: list[str], rows: list[list[str]], col_w: list[float] | None = None):
        n = len(headers)
        if col_w is None:
            col_w = [(self.right - self.left) / n] * n
        x0 = self.left
        # header
        self.c.setFont("Helvetica-Bold", 9)
        self.c.setFillColorRGB(0.9, 0.9, 0.95)
        self.c.rect(x0, self.y - 2 * mm, self.right - self.left, 7 * mm, fill=1, stroke=0)
        self.c.setFillColorRGB(0, 0, 0)
        x = x0
        for h, w in zip(headers, col_w):
            self.c.drawString(x + 1.5 * mm, self.y, h)
            x += w
        self.y -= 7 * mm
        # rows
        self.c.setFont("Helvetica", 9)
        for row in rows:
            if self.y < 30 * mm:
                self.c.showPage()
                self.y = PAGE_H - 20 * mm
                self.c.setFont("Helvetica", 9)
            x = x0
            for cell, w in zip(row, col_w):
                self.c.drawString(x + 1.5 * mm, self.y, str(cell))
                x += w
            self.c.setStrokeColorRGB(0.85, 0.85, 0.85)
            self.c.line(x0, self.y - 1.5 * mm, self.right, self.y - 1.5 * mm)
            self.y -= 6 * mm
        self.y -= 3 * mm

    def signature_block(self, name: str, role: str = "Authorised Signatory"):
        if self.y < 45 * mm:
            self.c.showPage()
            self.y = PAGE_H - 30 * mm
        self.y -= 12 * mm
        self.c.setStrokeColorRGB(0, 0, 0)
        self.c.line(self.left, self.y, self.left + 55 * mm, self.y)
        self.y -= 5 * mm
        self.c.setFont("Helvetica", 9)
        self.c.drawString(self.left, self.y, name)
        self.y -= 5 * mm
        self.c.drawString(self.left, self.y, role)
        self.y -= 6 * mm

    def stamp_placeholder(self, text: str = "SEAL"):
        cx, cy, r = self.right - 25 * mm, self.y + 5 * mm, 14 * mm
        self.c.setStrokeColorRGB(0.6, 0.0, 0.0)
        self.c.setLineWidth(1.2)
        self.c.circle(cx, cy, r, stroke=1, fill=0)
        self.c.circle(cx, cy, r - 3, stroke=1, fill=0)
        self.c.setFillColorRGB(0.6, 0.0, 0.0)
        self.c.setFont("Helvetica-Bold", 6)
        self.c.drawCentredString(cx, cy, text)
        self.c.setFillColorRGB(0, 0, 0)
        self.c.setLineWidth(1)

    def footer(self, text: str):
        self.c.setFont("Helvetica-Oblique", 7)
        self.c.setFillColorRGB(0.4, 0.4, 0.4)
        self.c.drawCentredString(PAGE_W / 2, 12 * mm, text)
        self.c.setFillColorRGB(0, 0, 0)

    # ----------------- absolute-positioning primitives (top-left origin, mm) -----------------
    def _ay(self, top_mm: float) -> float:
        """Convert a top-origin mm coordinate to ReportLab's bottom-origin points."""
        return PAGE_H - top_mm * mm

    def text_at(self, x_mm, top_mm, s, size=10, bold=False, color=(0, 0, 0),
                center=False, right=False, font=None, italic=False):
        fname = font or ("Helvetica-Bold" if bold else ("Helvetica-Oblique" if italic else "Helvetica"))
        self.c.setFont(fname, size)
        self.c.setFillColorRGB(*color)
        x = x_mm * mm
        y = self._ay(top_mm)
        if center:
            self.c.drawCentredString(x, y, s)
        elif right:
            self.c.drawRightString(x, y, s)
        else:
            self.c.drawString(x, y, s)
        self.c.setFillColorRGB(0, 0, 0)

    def rect_at(self, x_mm, top_mm, w_mm, h_mm, stroke=(0, 0, 0), fill=None, line=1.0):
        self.c.setLineWidth(line)
        if stroke:
            self.c.setStrokeColorRGB(*stroke)
        if fill:
            self.c.setFillColorRGB(*fill)
        self.c.rect(x_mm * mm, self._ay(top_mm) - h_mm * mm, w_mm * mm, h_mm * mm,
                    stroke=1 if stroke else 0, fill=1 if fill else 0)
        self.c.setFillColorRGB(0, 0, 0)
        self.c.setStrokeColorRGB(0, 0, 0)
        self.c.setLineWidth(1)

    def hline(self, x1_mm, top_mm, x2_mm, color=(0, 0, 0), line=1.0):
        self.c.setStrokeColorRGB(*color)
        self.c.setLineWidth(line)
        self.c.line(x1_mm * mm, self._ay(top_mm), x2_mm * mm, self._ay(top_mm))
        self.c.setStrokeColorRGB(0, 0, 0)
        self.c.setLineWidth(1)

    def labeled(self, x_mm, top_mm, label, value, vsize=11, vbold=True):
        """Small grey label with a bold value beneath — passport/ID style."""
        self.text_at(x_mm, top_mm, label, size=7.5, color=(0.45, 0.45, 0.5))
        self.text_at(x_mm, top_mm + 4.5, value, size=vsize, bold=vbold)

    def photo_box(self, x_mm, top_mm, w_mm=30, h_mm=38):
        """A grey placeholder portrait — never a real face."""
        self.rect_at(x_mm, top_mm, w_mm, h_mm, stroke=(0.4, 0.4, 0.4), fill=(0.88, 0.88, 0.9), line=1.2)
        cx = x_mm + w_mm / 2
        self.c.setFillColorRGB(0.62, 0.62, 0.66)
        # head
        r = w_mm * 0.18
        self.c.circle(cx * mm, self._ay(top_mm + h_mm * 0.32), r * mm, stroke=0, fill=1)
        # shoulders
        self.c.rect((cx - w_mm * 0.30) * mm, self._ay(top_mm + h_mm) , (w_mm * 0.60) * mm,
                    (h_mm * 0.38) * mm, stroke=0, fill=1)
        self.c.setFillColorRGB(0, 0, 0)

    def mrz(self, top_mm, line1, line2):
        self.text_at(self.left / mm, top_mm, line1, size=12, font="Courier-Bold")
        self.text_at(self.left / mm, top_mm + 6, line2, size=12, font="Courier-Bold")

    def watermark(self, text="SYNTHETIC SPECIMEN — NOT A REAL DOCUMENT"):
        self.c.saveState()
        self.c.setFont("Helvetica-Bold", 26)
        self.c.setFillColorRGB(0.85, 0.4, 0.4)
        try:
            self.c.setFillAlpha(0.18)
        except Exception:
            pass
        self.c.translate(PAGE_W / 2, PAGE_H / 2)
        self.c.rotate(35)
        self.c.drawCentredString(0, 0, text)
        self.c.restoreState()

    def build(self) -> bytes:
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()
