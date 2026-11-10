"""Exports Excel (openpyxl) et PDF (Qt), à partir d'une structure de tableau générique."""

import datetime as dt
import html
from dataclasses import dataclass, field

from .money import fmt_eur, fmt_pct

MONEY, PCT, TEXT, DATE, RATIO = "money", "pct", "text", "date", "ratio"


@dataclass
class TableRow:
    cells: list
    bold: bool = False
    indent: int = 0
    shade: bool = False


@dataclass
class TableData:
    title: str
    subtitle: str
    headers: list
    col_types: list            # MONEY / PCT / TEXT / DATE par colonne
    rows: list = field(default_factory=list)

    def add(self, cells, **kw):
        self.rows.append(TableRow(cells, **kw))


def report_to_rows(table, report, value_fn):
    """Remplit ``table`` à partir d'un analytics.Report. value_fn(node) -> liste de cellules."""
    for title, _kind, nodes in report.sections:
        table.add([title.upper()] + [None] * (len(table.headers) - 1), bold=True, shade=True)
        for n in nodes:
            table.add([n.label] + value_fn(n), bold=True, indent=1)
            for ch in n.children:
                table.add([ch.label] + value_fn(ch), indent=2)
    if report.totals:
        table.add([""] + [None] * (len(table.headers) - 1))
        for t in report.totals:
            table.add([t.label] + value_fn(t), bold=True, shade=True)


# ------------------------------------------------------------------ Excel
def export_excel(path, tables):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    used = set()
    for t in tables:
        name = "".join(ch for ch in t.title if ch not in "[]:*?/\\")[:31] or "Feuille"
        base, i = name, 2
        while name in used:
            name = f"{base[:28]} {i}"
            i += 1
        used.add(name)
        ws = wb.create_sheet(name)
        ws.append([t.title])
        ws["A1"].font = Font(bold=True, size=14)
        ws.append([t.subtitle])
        ws["A2"].font = Font(italic=True, color="666666")
        ws.append([])
        ws.append(t.headers)
        header_fill = PatternFill("solid", fgColor="1F4E79")
        for j in range(1, len(t.headers) + 1):
            c = ws.cell(row=4, column=j)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = header_fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        shade_fill = PatternFill("solid", fgColor="DDEBF7")
        for r in t.rows:
            values = []
            for j, v in enumerate(r.cells):
                typ = t.col_types[j] if j < len(t.col_types) else TEXT
                if v is None:
                    values.append(None)
                elif typ == MONEY:
                    values.append(v / 100)
                elif typ == DATE and isinstance(v, str) and len(v) == 10:
                    values.append(dt.date.fromisoformat(v))
                else:
                    values.append(v)
            ws.append(values)
            row_idx = ws.max_row
            for j, typ in enumerate(t.col_types, start=1):
                c = ws.cell(row=row_idx, column=j)
                if typ == MONEY:
                    c.number_format = '#,##0.00 "€";[Red]-#,##0.00 "€"'
                elif typ == PCT:
                    c.number_format = '+0.0%;[Red]-0.0%'
                elif typ == RATIO:
                    c.number_format = '0%'
                elif typ == DATE:
                    c.number_format = "DD/MM/YYYY"
                if r.bold:
                    c.font = Font(bold=True)
                if r.shade:
                    c.fill = shade_fill
            if r.indent:
                ws.cell(row=row_idx, column=1).alignment = Alignment(indent=r.indent * 2 - 2)
        for j, typ in enumerate(t.col_types, start=1):
            if j == 1 or typ == TEXT:
                width = max([len(str(x.cells[j - 1] or "")) for x in t.rows if j - 1 < len(x.cells)] + [12])
                ws.column_dimensions[get_column_letter(j)].width = min(width + 4, 60)
            else:
                ws.column_dimensions[get_column_letter(j)].width = 14
        ws.freeze_panes = "B5"
    wb.save(path)


# -------------------------------------------------------------------- PDF
def _fmt(v, typ):
    if v is None:
        return ""
    if typ == MONEY:
        return fmt_eur(v, blank_zero=True)
    if typ == PCT:
        return fmt_pct(v)
    if typ == RATIO:
        return f"{v * 100:.0f} %"
    if typ == DATE and isinstance(v, str) and len(v) == 10:
        return f"{v[8:10]}/{v[5:7]}/{v[:4]}"
    return str(v)


def table_html(t):
    font = 7 if len(t.headers) > 10 else 8.5
    out = [f"<h2>{html.escape(t.title)}</h2><p class='sub'>{html.escape(t.subtitle)}</p>",
           f"<table width='100%' cellspacing='0' cellpadding='3' style='font-size:{font}pt'>", "<tr>"]
    for h in t.headers:
        out.append(f"<th bgcolor='#1F4E79' style='color:white'>{html.escape(str(h))}</th>")
    out.append("</tr>")
    for i, r in enumerate(t.rows):
        bg = "#DDEBF7" if r.shade else ("#F5F5F5" if i % 2 else "#FFFFFF")
        out.append(f"<tr bgcolor='{bg}'>")
        for j, v in enumerate(r.cells):
            typ = t.col_types[j] if j < len(t.col_types) else TEXT
            text = html.escape(_fmt(v, typ))
            if r.bold:
                text = f"<b>{text}</b>"
            align = "right" if typ in (MONEY, PCT, RATIO) else "left"
            pad = "&nbsp;" * (4 * max(r.indent - 1, 0)) if j == 0 else ""
            color = ""
            if typ in (MONEY, PCT) and isinstance(v, (int, float)) and v < 0:
                color = " style='color:#C00000'"
            out.append(f"<td align='{align}'{color}>{pad}{text}</td>")
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def export_pdf(path, tables, images=(), landscape=None, title="Mes Comptes"):
    """images : liste de (titre, octets PNG). Nécessite une QApplication active."""
    from PySide6.QtCore import QMarginsF, QSizeF, QUrl
    from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

    if landscape is None:
        landscape = any(len(t.headers) > 7 for t in tables)
    writer = QPdfWriter(path)
    writer.setTitle(title)
    writer.setCreator("Mes Comptes")
    writer.setResolution(150)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4),
                                     QPageLayout.Landscape if landscape else QPageLayout.Portrait,
                                     QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter))
    doc = QTextDocument()
    doc.setDefaultStyleSheet("h1{color:#1F4E79} h2{color:#1F4E79; margin-top:14px} .sub{color:#666}"
                             " th{font-weight:bold}")
    parts = [f"<h1>{html.escape(title)}</h1>",
             f"<p class='sub'>Édité le {dt.date.today().strftime('%d/%m/%Y')}</p>"]
    page_w_px = writer.width()
    for i, (img_title, png) in enumerate(images):
        img = QImage.fromData(png)
        name = f"img{i}.png"
        doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
        w = min(page_w_px * 0.95, img.width())
        parts.append(f"<h2>{html.escape(img_title)}</h2><p align='center'><img src='{name}' width='{int(w)}'></p>")
    for t in tables:
        parts.append(table_html(t))
    doc.setHtml("".join(parts))
    doc.setPageSize(QSizeF(writer.width(), writer.height()))
    doc.print_(writer)
