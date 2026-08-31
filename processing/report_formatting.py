"""Shared openpyxl post-processing pass for generated NOC Excel workbooks.

Extracted from enhanced_noc_analysis.py so historical_noc_analysis.py gets the
same look (frozen header, autofilter, bold white-on-blue header, auto column
width, P1/P2/P3 row coloring) without duplicating the styling code.
"""
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

PRIORITY_FILLS = {"P1": "C00000", "P2": "F4B183", "P3": "FFF2CC"}


def format_workbook(path: Path, priority_columns: dict | None = None):
    """priority_columns maps a sheet title to the 1-based column index that
    holds P1/P2/P3 values to color-code. Defaults to the original
    NOC Site Triage report's convention (column 1) for backward compat."""
    priority_columns = priority_columns if priority_columns is not None else {"NOC Site Triage": 1}
    workbook = load_workbook(path)
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
        priority_col = priority_columns.get(sheet.title)
        if priority_col:
            for row in range(2, sheet.max_row + 1):
                value = sheet.cell(row, priority_col).value
                if value in PRIORITY_FILLS:
                    sheet.cell(row, priority_col).fill = PatternFill("solid", fgColor=PRIORITY_FILLS[value])
                    sheet.cell(row, priority_col).font = Font(bold=True)
        for column in range(1, sheet.max_column + 1):
            values = [len(str(sheet.cell(row, column).value or "")) for row in range(1, min(sheet.max_row, 200) + 1)]
            sheet.column_dimensions[get_column_letter(column)].width = min(max(values, default=10) + 2, 55)
    workbook.save(path)
