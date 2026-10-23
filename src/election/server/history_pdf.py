"""Shared landscape layout for station history statements."""

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4, landscape  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from election.server.report_fonts import font_for_pdf


@dataclass(frozen=True)
class HistoryTable:
    title: str
    rows: list[list[str]]
    widths: tuple[float, ...]
    empty_message: str = ""
    split_in_row: bool = True


# ReportLab does not ship type information for its Flowable subclasses.
class WholeRowTable(Table):  # type: ignore[misc]
    """Keep fitting rows whole; continue oversized rows only from a fresh frame."""

    def split(self, availWidth: float, availHeight: float) -> list[Any]:
        parts: list[Any] = super().split(availWidth, availHeight)
        # ReportLab 5.1's Frame.split attaches this context for the duration of
        # splitting. Without it, preserve the ordinary whole-row policy. Public
        # PDF regressions cover this adapter against the locked library version.
        if parts or not getattr(getattr(self, "_frame", None), "_atTop", False):
            return parts
        self.splitInRow = 1
        try:
            parts = super().split(availWidth, availHeight)
        finally:
            self.splitInRow = 0
        # Table clones its own class while splitting. Later ordinary rows must
        # still move intact to the next page, including after an oversized row.
        for part in parts:
            part.splitInRow = 0
        return parts


def history_pdf(
    title: str,
    metadata: list[list[str]],
    sections: list[HistoryTable],
    footer: str,
    page_label: str,
) -> bytes:
    rendered = [title, footer, page_label, *[value for row in metadata for value in row]]
    for section in sections:
        rendered += [section.title, section.empty_message]
        rendered += [value for row in section.rows for value in row]
    with font_for_pdf(rendered) as font_name:
        output = BytesIO()
        pagesize = landscape(A4)
        document = SimpleDocTemplate(
            output,
            pagesize=pagesize,
            leftMargin=12 * mm,
            rightMargin=12 * mm,
            topMargin=12 * mm,
            bottomMargin=15 * mm,
            title=title,
        )
        body = ParagraphStyle(
            "HistoryBody", fontName=font_name, fontSize=8, leading=11, wordWrap="CJK"
        )
        latin = ParagraphStyle("HistoryLatin", parent=body, wordWrap=None)
        title_style = ParagraphStyle(
            "HistoryTitle", parent=body, fontSize=17, leading=23, spaceAfter=12
        )
        heading = ParagraphStyle(
            "HistoryHeading", parent=body, fontSize=11, leading=15, spaceAfter=8
        )

        def paragraph(
            value: str, style: Any = None, *, available_width: float | None = None
        ) -> Any:
            if style is None:
                cjk = re.search(r"[\u2e80-\u9fff\uf900-\ufaff\uac00-\ud7af]", value)
                style = body if cjk else latin
            timestamp = re.fullmatch(
                r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}(?:\.\d{1,6})? HKT)", value
            )
            if (
                timestamp
                and available_width is not None
                and pdfmetrics.stringWidth(value, font_name, body.fontSize) > available_width
            ):
                value = timestamp[1] + "\n" + timestamp[2]
            return Paragraph(escape(value).replace("\n", "<br/>"), style)

        paired = [
            metadata[index] + (metadata[index + 1] if index + 1 < len(metadata) else ["", ""])
            for index in range(0, len(metadata), 2)
        ]
        # SimpleDocTemplate's frame reserves six points of padding on each side.
        table_width = document.width - 12
        context_table = Table(
            [[paragraph(value) for value in row] for row in paired],
            colWidths=[table_width * fraction for fraction in (0.15, 0.35, 0.15, 0.35)],
            hAlign="LEFT",
            splitInRow=1,
        )
        context_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f5fa")),
                    ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f2f5fa")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce3ed")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story = [paragraph(title, title_style), context_table]
        for section in sections:
            table_class = Table if section.split_in_row else WholeRowTable
            table = table_class(
                [
                    [
                        paragraph(value, available_width=table_width * section.widths[index] - 12)
                        for index, value in enumerate(row)
                    ]
                    for row in section.rows
                ],
                colWidths=[table_width * fraction for fraction in section.widths],
                repeatRows=1,
                hAlign="LEFT",
                splitInRow=int(section.split_in_row),
            )
            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6eef9")),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f7f9fc")],
                        ),
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce3ed")),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            section_heading = paragraph(section.title, heading)
            # Untitled continuation tables retain their existing split placement.
            section_heading.keepWithNext = bool(section.title)
            story += [Spacer(1, 14), section_heading, table]
            if section.empty_message:
                story += [Spacer(1, 8), paragraph(section.empty_message)]

        def page_footer(canvas: Any, doc: Any) -> None:
            canvas.saveState()
            canvas.setFont(font_name, 8)
            canvas.setFillColor(colors.HexColor("#52637b"))
            canvas.drawString(document.leftMargin, 8 * mm, footer)
            canvas.drawRightString(
                pagesize[0] - document.rightMargin, 8 * mm, page_label + " " + str(doc.page)
            )
            canvas.restoreState()

        document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
        return output.getvalue()
