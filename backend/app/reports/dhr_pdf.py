"""Render a Device History Record as an auditor-facing PDF (ReportLab).

Layout, top to bottom: a header block (serial, part, work order, build date),
the full as-built genealogy, incoming inspection results with signatures, then
nonconformances. Every page carries a generation timestamp and "Page X of Y".
"""

from __future__ import annotations

import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.dhr import DHRDocument
from app.services.genealogy import SerialNode

RED = colors.HexColor("#b3261e")
AMBER = colors.HexColor("#8a5a00")
GREY = colors.HexColor("#6b7280")
LINE = colors.HexColor("#c9ced6")
HEAD_BG = colors.HexColor("#eef1f4")
MARGIN = 0.75 * inch

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle("dhrTitle", parent=_styles["Title"], fontSize=17, spaceAfter=2)
SUBTITLE = ParagraphStyle("dhrSub", parent=_styles["Normal"], fontSize=9, textColor=GREY, spaceAfter=10)
SECTION = ParagraphStyle("dhrSection", parent=_styles["Heading2"], fontSize=11, spaceBefore=14, spaceAfter=5)
CELL = ParagraphStyle("dhrCell", parent=_styles["Normal"], fontSize=7.5, leading=9.5)
CELL_MONO = ParagraphStyle("dhrCellMono", parent=CELL, fontName="Courier")


def _fmt_dt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _fmt_date(value) -> str:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%Y-%m-%d")
    return "—"


class _NumberedCanvas(canvas.Canvas):
    """Two-pass canvas so the footer can print 'Page X of Y' plus a timestamp."""

    footer_left = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_states = []

    def showPage(self):
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total_pages: int) -> None:
        width, _ = self._pagesize
        self.setFont("Helvetica", 7)
        self.setFillColor(GREY)
        self.setStrokeColor(LINE)
        self.line(MARGIN, 0.55 * inch, width - MARGIN, 0.55 * inch)
        self.drawString(MARGIN, 0.4 * inch, self.footer_left)
        self.drawRightString(
            width - MARGIN, 0.4 * inch, f"Page {self._pageNumber} of {total_pages}"
        )


def _canvas_maker(footer_left: str):
    return type("_DHRCanvas", (_NumberedCanvas,), {"footer_left": footer_left})


def _p(text, style=CELL) -> Paragraph:
    return Paragraph(text if text not in (None, "") else "—", style)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def _header_block(doc: DHRDocument, story: list) -> None:
    story.append(Paragraph("Device History Record", TITLE))
    story.append(Paragraph("Full as-built genealogy and quality record for a single unit.", SUBTITLE))
    data = [
        [_p("<b>Serial number</b>"), _p(doc.serial_number, CELL_MONO),
         _p("<b>Work order</b>"), _p(doc.work_order_number, CELL_MONO)],
        [_p("<b>Part</b>"), _p(f"{doc.part_number or '—'} — {doc.part_name or ''}"),
         _p("<b>Build date</b>"), _p(_fmt_date(doc.built_at))],
    ]
    table = Table(data, colWidths=[1.1 * inch, 2.6 * inch, 1.0 * inch, 2.3 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HEAD_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)


def _flatten(node: SerialNode):
    """Yield (depth, position, kind, payload) rows for the whole tree."""
    rows: list[tuple] = []

    def walk(n: SerialNode, depth: int, position):
        rows.append((depth, position, "unit", n))
        for comp in n.components:
            if comp.kind == "serial" and comp.child:
                walk(comp.child, depth + 1, comp.position)
            else:
                rows.append((depth + 1, comp.position, comp.kind, comp))

    walk(node, 0, None)
    return rows


def _genealogy_section(doc: DHRDocument, story: list) -> None:
    story.append(Paragraph("1. As-Built Genealogy", SECTION))
    header = ["Position", "Part", "Serial / Lot", "Supplier", "CoC", "Status", "Qty"]
    data = [header]
    styles_extra = []

    for i, (depth, position, kind, payload) in enumerate(_flatten(doc.genealogy), start=1):
        indent = "&nbsp;" * (depth * 4)
        if kind == "unit":
            node: SerialNode = payload
            open_ncs = [nc for nc in node.nonconformances if nc.status == "open"]
            status = "OPEN NC" if open_ncs else ""
            part_cell = f"{indent}<b>{node.part_number or '—'}</b> {node.part_name or ''}"
            data.append([
                _p(position, CELL_MONO), _p(part_cell),
                _p(f"<b>{node.serial_number or '—'}</b>", CELL_MONO),
                _p("—"), _p("—"),
                _p(f'<font color="#b3261e"><b>{status}</b></font>' if status else "—"),
                _p("—"),
            ])
            if status:
                styles_extra.append(("TEXTCOLOR", (0, i), (0, i), RED))
        elif kind == "lot":
            lot = payload.lot
            failed = lot and lot.inspection_disposition == "rejected"
            open_nc = lot and any(nc.status == "open" for nc in lot.nonconformances)
            flags = []
            if failed:
                flags.append('<font color="#b3261e"><b>FAILED INSP</b></font>')
            if open_nc:
                flags.append('<font color="#b3261e"><b>OPEN NC</b></font>')
            if not flags and lot and lot.inspection_disposition:
                flags.append(f'<font color="#6b7280">{lot.inspection_disposition}</font>')
            coc = "present" if lot and lot.certificate_status == "present" else "ABSENT"
            data.append([
                _p(position, CELL_MONO),
                _p(f"{indent}{(lot.part_number if lot else '—') or '—'} {(lot.part_name if lot else '') or ''}"),
                _p(lot.lot_number if lot else "—", CELL_MONO),
                _p(lot.supplier_name if lot else "—"),
                _p(coc if coc == "present" else f'<font color="#8a5a00"><b>{coc}</b></font>'),
                _p(" ".join(flags) if flags else "—"),
                _p(str(payload.quantity) if payload.quantity is not None else "—"),
            ])
        else:  # orphan
            data.append([
                _p(position, CELL_MONO), _p(f"{indent}<i>missing reference</i>"),
                _p("—"), _p("—"), _p("—"),
                _p(f'<font color="#b3261e">{payload.note or "orphan"}</font>'), _p("—"),
            ])

    table = Table(
        data, repeatRows=1,
        colWidths=[0.9 * inch, 2.5 * inch, 1.15 * inch, 1.25 * inch, 0.55 * inch, 0.95 * inch, 0.35 * inch],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ] + styles_extra))
    story.append(table)


def _inspections_section(doc: DHRDocument, story: list) -> None:
    story.append(Paragraph("2. Incoming Inspection Results &amp; Signatures", SECTION))
    if not doc.inspections:
        story.append(Paragraph("No incoming inspections on record for consumed lots.", CELL))
        return
    header = ["Lot", "Part", "Supplier", "Disposition", "Inspected", "Electronic signature"]
    data = [header]
    for e in doc.inspections:
        disp = e.disposition or "—"
        disp_cell = (
            f'<font color="#b3261e"><b>{disp.upper()}</b></font>'
            if disp == "rejected" else disp
        )
        if e.signatures:
            sig_bits = []
            for s in e.signatures:
                mark = ('<font color="#2f7d32">VERIFIED</font>' if s.verified
                        else '<font color="#b3261e">HASH MISMATCH</font>')
                sig_bits.append(
                    f"<b>{s.signer_name}</b> — “{s.meaning}”<br/>"
                    f"{_fmt_dt(s.signed_at)} · {mark}<br/>"
                    f'<font color="#6b7280" size="6">sha256 {s.record_hash[:24]}…</font>'
                )
            sig_cell = "<br/><br/>".join(sig_bits)
        else:
            sig_cell = '<font color="#6b7280"><i>— unsigned —</i></font>'
        data.append([
            _p(e.lot_number, CELL_MONO),
            _p(f"{e.part_number or '—'} {e.part_name or ''}"),
            _p(e.supplier_name),
            _p(disp_cell),
            _p(_fmt_date(e.inspected_at)),
            _p(sig_cell),
        ])
    table = Table(
        data, repeatRows=1,
        colWidths=[1.15 * inch, 1.7 * inch, 1.25 * inch, 0.85 * inch, 0.8 * inch, 2.05 * inch],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)


def _nonconformances_section(doc: DHRDocument, story: list) -> None:
    story.append(Paragraph("3. Nonconformances", SECTION))
    if not doc.nonconformances:
        story.append(Paragraph("No nonconformances associated with this build.", CELL))
        return
    header = ["NC", "Status", "Subject", "Description"]
    data = [header]
    for nc in doc.nonconformances:
        status_cell = (
            f'<font color="#b3261e"><b>{nc.status.upper()}</b></font>'
            if nc.status == "open" else nc.status
        )
        data.append([
            _p(nc.nc_number, CELL_MONO), _p(status_cell),
            _p(nc.subject, CELL_MONO), _p(nc.description),
        ])
    table = Table(data, repeatRows=1, colWidths=[0.9 * inch, 0.8 * inch, 1.3 * inch, 4.8 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)


def render_dhr_pdf(doc: DHRDocument) -> bytes:
    """Render a :class:`DHRDocument` to PDF bytes."""
    buffer = BytesIO()
    generated = _fmt_dt(doc.generated_at)
    pdf = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=0.8 * inch,
        title=f"Device History Record — {doc.serial_number}",
        author="qmstrace",
    )
    story: list = []
    _header_block(doc, story)
    _genealogy_section(doc, story)
    _inspections_section(doc, story)
    _nonconformances_section(doc, story)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f'<font color="#6b7280" size="7">Generated {generated} by qmstrace. '
        f"This document is uncontrolled when printed.</font>",
        CELL,
    ))

    pdf.build(story, canvasmaker=_canvas_maker(f"qmstrace · Device History Record · generated {generated}"))
    return buffer.getvalue()
