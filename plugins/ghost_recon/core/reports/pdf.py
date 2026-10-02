"""Markdown -> PDF with ReportLab (cover with KPI tiles, header/footer with signature and 'Página N de M').

Fonts: bundled DejaVu (plugins/ghost-recon/assets/fonts) so accents, '−', '→', '·' render; Helvetica fallback.
Metadata: Title/Author/Subject/Creator/Producer set to Ghost Recon; generator comment lines are blanked
in place (same byte length, so xref offsets stay valid).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import ENGINE, SIGNATURE, SIGNATURE_SHORT
from .md import parse_blocks

NAVY = (0.09, 0.16, 0.30)
AMBER = (0.85, 0.55, 0.10)
GREY = (0.45, 0.45, 0.45)
LIGHT = (0.93, 0.94, 0.96)

FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"


def _register_fonts() -> Dict[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    names = {"regular": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique"}
    try:
        if (FONTS_DIR / "DejaVuSans.ttf").exists():
            pdfmetrics.registerFont(TTFont("GR-Sans", str(FONTS_DIR / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("GR-Sans-Bold", str(FONTS_DIR / "DejaVuSans-Bold.ttf")))
            pdfmetrics.registerFont(TTFont("GR-Sans-Italic", str(FONTS_DIR / "DejaVuSans-Oblique.ttf")))
            from reportlab.pdfbase.pdfmetrics import registerFontFamily
            registerFontFamily("GR-Sans", normal="GR-Sans", bold="GR-Sans-Bold", italic="GR-Sans-Italic", boldItalic="GR-Sans-Bold")
            names = {"regular": "GR-Sans", "bold": "GR-Sans-Bold", "italic": "GR-Sans-Italic"}
    except Exception:
        pass
    return names


def _inline(text: str) -> str:
    """Markdown inline -> ReportLab mini-markup (escape first)."""
    t = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r"<font face='Courier' size='8'>\1</font>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (<i>\2</i>)", t)
    return t


def build_pdf(md_text: str, dest: Path, *, title: str, subtitle: str = "", meta_lines: Optional[List[str]] = None,
              kpis: Optional[Dict[str, Any]] = None, companion: str = "", confidential: str = "CONFIDENCIAL · USO INTERNO",
              subject: str = "Auditoría financiera forense", keywords: str = "Ghost Recon, forensic audit") -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer,
                                    Table, TableStyle, Preformatted)

    fonts = _register_fonts()
    W, H = A4
    M = 18 * mm
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    styles = {
        "body": ParagraphStyle("body", fontName=fonts["regular"], fontSize=9.5, leading=13, alignment=TA_LEFT, spaceAfter=5),
        "h1": ParagraphStyle("h1", fontName=fonts["bold"], fontSize=16, leading=20, textColor=colors.Color(*NAVY), spaceBefore=10, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName=fonts["bold"], fontSize=12.5, leading=16, textColor=colors.Color(*NAVY), spaceBefore=9, spaceAfter=4),
        "h3": ParagraphStyle("h3", fontName=fonts["bold"], fontSize=10.5, leading=14, textColor=colors.Color(*NAVY), spaceBefore=7, spaceAfter=3),
        "cell": ParagraphStyle("cell", fontName=fonts["regular"], fontSize=7.6, leading=9.6),
        "cellb": ParagraphStyle("cellb", fontName=fonts["bold"], fontSize=7.6, leading=9.6, textColor=colors.white),
        "quote": ParagraphStyle("quote", fontName=fonts["italic"], fontSize=9.5, leading=13, leftIndent=12, textColor=colors.Color(*GREY), spaceAfter=5),
        "bullet": ParagraphStyle("bullet", fontName=fonts["regular"], fontSize=9.5, leading=13, leftIndent=12, bulletIndent=2, spaceAfter=2),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=7.5, leading=9.5, backColor=colors.Color(*LIGHT), spaceAfter=5),
    }

    from reportlab.pdfgen import canvas as rl_canvas

    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                if self._pageNumber > 1:  # cover has no page number
                    self.setFont(fonts["regular"], 7.5)
                    self.setFillColorRGB(*GREY)
                    self.drawRightString(W - M, 10 * mm, f"Página {self._pageNumber} de {total}")
                super().showPage()
            super().save()

    def on_cover(c, doc):
        c.saveState()
        c.setFillColorRGB(*NAVY); c.rect(0, H - 70 * mm, W, 70 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(fonts["regular"], 9); c.drawString(M, H - 18 * mm, "GHOST RECON · AUDITORÍA FINANCIERA FORENSE ASISTIDA POR IA")
        from reportlab.lib.utils import simpleSplit
        size = 22
        lines = simpleSplit(title, fonts["bold"], size, W - 2 * M)
        while len(lines) > 3 and size > 14:
            size -= 2; lines = simpleSplit(title, fonts["bold"], size, W - 2 * M)
        y = H - 32 * mm
        c.setFont(fonts["bold"], size)
        for ln in lines[:3]:
            c.drawString(M, y, ln); y -= size + 4
        if subtitle:
            c.setFont(fonts["regular"], 11)
            for ln in simpleSplit(subtitle, fonts["regular"], 11, W - 2 * M)[:2]:
                c.drawString(M, y, ln); y -= 14
        c.setFillColorRGB(*NAVY)
        y = H - 85 * mm
        c.setFont(fonts["regular"], 10)
        for ln in (meta_lines or []):
            for sub in simpleSplit(ln, fonts["regular"], 10, W - 2 * M):
                c.drawString(M, y, sub); y -= 14
        # KPI tiles
        items = list((kpis or {}).items())[:4]
        if items:
            tile_w = (W - 2 * M - (len(items) - 1) * 6 * mm) / len(items)
            ty = 40 * mm
            for i, (label, value) in enumerate(items):
                x = M + i * (tile_w + 6 * mm)
                c.setFillColorRGB(*LIGHT); c.roundRect(x, ty, tile_w, 30 * mm, 3 * mm, fill=1, stroke=0)
                c.setFillColorRGB(*GREY); c.setFont(fonts["regular"], 7.5)
                for j, sub in enumerate(simpleSplit(str(label), fonts["regular"], 7.5, tile_w - 8)[:2]):
                    c.drawString(x + 4, ty + 30 * mm - 10 - j * 9, sub)
                vs = str(value); vsize = 14
                from reportlab.pdfbase.pdfmetrics import stringWidth
                while stringWidth(vs, fonts["bold"], vsize) > tile_w - 8 and vsize > 8:
                    vsize -= 1
                c.setFillColorRGB(*NAVY); c.setFont(fonts["bold"], vsize); c.drawString(x + 4, ty + 7 * mm, vs)
        c.setFillColorRGB(*GREY); c.setFont(fonts["regular"], 7.5)
        c.drawString(M, 14 * mm, confidential)
        c.drawRightString(W - M, 14 * mm, SIGNATURE_SHORT)
        c.restoreState()

    def on_page(c, doc):
        c.saveState()
        c.setFillColorRGB(*NAVY); c.rect(0, H - 12 * mm, W, 12 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1); c.setFont(fonts["regular"], 8)
        from reportlab.lib.utils import simpleSplit
        head = simpleSplit(f"{title} · {confidential}", fonts["regular"], 8, W - 2 * M)[0]
        c.drawString(M, H - 7.5 * mm, head)
        c.setStrokeColorRGB(*GREY); c.setLineWidth(0.4); c.line(M, 15 * mm, W - M, 15 * mm)
        c.setFillColorRGB(*GREY); c.setFont(fonts["regular"], 7.5)
        if companion:
            c.drawString(M, 10 * mm, simpleSplit(f"Documento complementario: {companion}", fonts["regular"], 7.5, W - 2 * M - 40 * mm)[0])
        c.drawString(M, 6 * mm, SIGNATURE)
        c.restoreState()

    doc = BaseDocTemplate(str(dest), pagesize=A4, leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=20 * mm,
                          title=title, author="Ghost Recon (www.ghostrecon.ai)", subject=subject,
                          creator="Ghost Recon — Sistema de auditoría asistida por IA · https://www.ghostrecon.ai/",
                          keywords=keywords, producer=ENGINE)
    cover_frame = Frame(M, 20 * mm, W - 2 * M, H - 40 * mm, id="cover")
    body_frame = Frame(M, 20 * mm, W - 2 * M, H - 20 * mm - 16 * mm, id="body")
    doc.addPageTemplates([PageTemplate(id="cover", frames=[cover_frame], onPage=on_cover),
                          PageTemplate(id="normal", frames=[body_frame], onPage=on_page)])

    story: List[Any] = [Spacer(1, 1), PageBreak()]
    from reportlab.platypus import NextPageTemplate
    story.insert(1, NextPageTemplate("normal"))
    avail = W - 2 * M
    for b in parse_blocks(md_text):
        t = b["type"]
        if t == "heading":
            lvl = min(b["level"], 3)
            story.append(Paragraph(_inline(b["text"]), styles[f"h{lvl}"]))
        elif t == "paragraph":
            story.append(Paragraph(_inline(b["text"]), styles["body"]))
        elif t == "bullets":
            for it in b["items"]:
                story.append(Paragraph(_inline(it), styles["bullet"], bulletText="•"))
        elif t == "numbered":
            for k, it in enumerate(b["items"], 1):
                story.append(Paragraph(_inline(it), styles["bullet"], bulletText=f"{k}."))
        elif t == "quote":
            story.append(Paragraph(_inline(b["text"]), styles["quote"]))
        elif t == "rule":
            story.append(Spacer(1, 6))
        elif t == "code":
            story.append(Preformatted(b["text"][:4000], styles["code"]))
        elif t == "table":
            ncol = max(1, len(b["header"]))
            data = [[Paragraph(_inline(h), styles["cellb"]) for h in b["header"]]]
            for r in b["rows"]:
                r = (r + [""] * ncol)[:ncol]
                data.append([Paragraph(_inline(c), styles["cell"]) for c in r])
            widths = _col_widths(b["header"], b["rows"], avail)
            tbl = Table(data, colWidths=widths, repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(*NAVY)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(*LIGHT)]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.Color(0.8, 0.8, 0.8)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(tbl); story.append(Spacer(1, 6))
    doc.build(story, canvasmaker=NumberedCanvas)
    _scrub(dest)
    return dest


def _col_widths(header: List[str], rows: List[List[str]], avail: float) -> List[float]:
    n = max(1, len(header))
    weights = []
    for i in range(n):
        lens = [len(str(header[i])) if i < len(header) else 0] + [len(str(r[i])) if i < len(r) else 0 for r in rows[:60]]
        weights.append(min(max(max(lens), 4), 40))
    total = sum(weights) or n
    return [avail * w / total for w in weights]


_COMMENT_RE = re.compile(rb"%[^\n\r]*(ReportLab|reportlab)[^\n\r]*")


def _scrub(path: Path) -> None:
    """Blank generator comment lines in place (same length) and set Producer; keeps xref offsets valid."""
    data = path.read_bytes()

    def _blank(m: re.Match) -> bytes:
        s = m.group(0)
        return b"%" + b" " * (len(s) - 1)
    data2 = _COMMENT_RE.sub(_blank, data)
    # /Producer written by the library — replace with same-length padded engine name
    m = re.search(rb"/Producer \(([^)]*)\)", data2)
    if m:
        old = m.group(1)
        new = ENGINE.encode("latin-1")
        if len(new) <= len(old):
            new = new + b" " * (len(old) - len(new))
            data2 = data2[:m.start(1)] + new + data2[m.end(1):]
    path.write_bytes(data2)
