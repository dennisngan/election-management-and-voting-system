"""One bundled Chinese PDF font and serialized document subsetting."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from fastapi import HTTPException
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]

FONT_NAME = "ElectionReceiptSans"
FONT_FILE = Path(__file__).resolve().parents[3] / "assets/fonts/ElectionReportSansCJKTC-Regular.ttf"
_pdf_build_lock = Lock()
_font: TTFont | None = None


@contextmanager
def font_for_pdf(rendered_text: Iterable[str]) -> Iterator[str]:
    """Validate source glyphs and retain the font lock for the complete PDF build."""
    global _font
    # TTFont's document-specific subsetting is not safe for concurrent builds.
    with _pdf_build_lock:
        if _font is None:
            _font = TTFont(FONT_NAME, str(FONT_FILE))
            pdfmetrics.registerFont(_font)
        # ReportLab 5.1.0 emits invalid non-UTF-16 ToUnicode entries above the BMP.
        # Preserve source text in preview/CSV and reject a corrupt PDF explicitly.
        if any(
            not char.isspace() and (ord(char) > 0xFFFF or not _font.face.charToGlyph.get(ord(char)))
            for text in rendered_text
            for char in text
        ):
            raise HTTPException(422, detail={"code": "report_glyph_unavailable"})
        yield FONT_NAME
