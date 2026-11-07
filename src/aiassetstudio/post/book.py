"""Lay a finished picture book out as a PDF: picture above, set text below (real text, not part of the image)."""

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont
from reportlab.pdfgen.canvas import Canvas

PAGE_WIDTH = 595.0  # points; the page height follows the book's picture shape
TEXT_BAND = 170.0
MARGIN = 58.0
FOOTER_Y = 26.0
BODY_SIZES = (15, 14, 13, 12, 11)  # the largest at which a page's text fits its band
FOOTER_SIZE = 9
TITLE_SIZE = 40
LINE_GAP = 1.7
PAPER = HexColor("#F7F2E8")
INK = HexColor("#2D2C2A")
MUTED = HexColor("#78705F")
FONT_NAME = "StudioBook"


class BookLayoutError(Exception):
    """The book cannot be laid out, for a reason the person can fix."""


@dataclass(frozen=True)
class BookPage:
    number: int
    image: Path
    text: str
    label: str = ""


def register_font(path: str) -> None:
    try:
        pdfmetrics.registerFont(TTFont(FONT_NAME, path, subfontIndex=0))
    except (TTFError, OSError) as e:
        raise BookLayoutError(f"cannot use the book font {path}: {e}; set AIAS_BOOK_FONT") from e


def wrap(text: str, size: float, width: float) -> list[str]:
    """Break between words; a word wider than the line breaks between letters."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if pdfmetrics.stringWidth(trial, FONT_NAME, size) <= width:
                line = trial
                continue
            if line:
                lines.append(line)
            line = word
            while pdfmetrics.stringWidth(line, FONT_NAME, size) > width:
                cut = len(line) - 1
                while cut > 1 and pdfmetrics.stringWidth(line[:cut], FONT_NAME, size) > width:
                    cut -= 1
                lines.append(line[:cut])
                line = line[cut:]
        lines.append(line)
    return lines


def _fit(text: str, width: float, height: float) -> tuple[int, list[str]]:
    for size in BODY_SIZES:
        lines = wrap(text, size, width)
        if len(lines) * size * LINE_GAP <= height:
            return size, lines
    return size, lines  # the smallest; render_pdf reports what still does not fit


def _sheet(canvas: Canvas, page_height: float) -> None:
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, PAGE_WIDTH, page_height, stroke=0, fill=1)


def _footer(canvas: Canvas, left: str, right: str) -> None:
    canvas.setFont(FONT_NAME, FOOTER_SIZE)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, FOOTER_Y, left)
    canvas.drawRightString(PAGE_WIDTH - MARGIN, FOOTER_Y, right)


def render_pdf(
    out: Path,
    title: str,
    cover: Path,
    pages: list[BookPage],
    colophon: list[str],
    font: str,
    picture_ratio: float,
) -> list[str]:
    """Write the PDF: cover, one page per BookPage, colophon. `picture_ratio` is height / width of the pictures.
    Returns warnings for pages whose text does not fit at the smallest size."""
    register_font(font)
    picture_height = PAGE_WIDTH * picture_ratio
    page_height = picture_height + TEXT_BAND
    width = PAGE_WIDTH - 2 * MARGIN
    band = TEXT_BAND - 2 * FOOTER_Y - 10
    canvas = Canvas(str(out), pagesize=(PAGE_WIDTH, page_height), pageCompression=1)
    canvas.setTitle(title)
    warnings = []

    _sheet(canvas, page_height)
    canvas.drawImage(str(cover), 0, TEXT_BAND, PAGE_WIDTH, picture_height)
    canvas.setFillColor(INK)
    canvas.setFont(FONT_NAME, TITLE_SIZE)
    canvas.drawCentredString(PAGE_WIDTH / 2, TEXT_BAND / 2 - TITLE_SIZE / 3, title)
    canvas.showPage()

    for page in pages:
        _sheet(canvas, page_height)
        canvas.drawImage(str(page.image), 0, TEXT_BAND, PAGE_WIDTH, picture_height)
        size, lines = _fit(page.text, width, band)
        leading = size * LINE_GAP
        if len(lines) * leading > band:
            warnings.append(f"page {page.number}: the text is too long for the page")
        canvas.setFillColor(INK)
        canvas.setFont(FONT_NAME, size)
        y = TEXT_BAND - 22 - size
        for line in lines:
            canvas.drawString(MARGIN, y, line)
            y -= leading
        _footer(canvas, page.label, str(page.number))
        canvas.showPage()

    _sheet(canvas, page_height)
    canvas.setFillColor(INK)
    canvas.setFont(FONT_NAME, 11)
    y = page_height / 2 + 60
    for text in colophon:
        for line in wrap(text, 11, width):
            canvas.drawString(MARGIN, y, line)
            y -= 11 * LINE_GAP
        y -= 8
    canvas.showPage()
    canvas.save()
    return warnings
