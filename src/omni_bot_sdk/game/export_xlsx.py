"""带样式的中文 Excel 导出。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def export_styled_table(
    path: str | Path,
    headers: Sequence[str],
    rows: List[Sequence[Any]],
    title: str = "",
    col_widths: Optional[Dict[str, float]] = None,
) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "台账"

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF", size=12, name="微软雅黑")
    white_fill = PatternFill("solid", fgColor="FFFFFF")
    blue_fill = PatternFill("solid", fgColor="DDEBF7")
    title_font = Font(bold=True, size=14, name="微软雅黑", color="1F4E79")
    cell_font = Font(size=11, name="微软雅黑")
    thin = Border(
        left=Side(style="thin", color="B4B4B4"),
        right=Side(style="thin", color="B4B4B4"),
        top=Side(style="thin", color="B4B4B4"),
        bottom=Side(style="thin", color="B4B4B4"),
    )
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    start_row = 1
    if title:
        ws.merge_cells(
            start_row=1, start_column=1, end_row=1, end_column=max(len(headers), 1)
        )
        ws["A1"] = title
        ws["A1"].font = title_font
        ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 28
        start_row = 3

    for col, name in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col, value=name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center
        cell.border = thin
    ws.row_dimensions[start_row].height = 24

    for i, row in enumerate(rows):
        excel_row = start_row + 1 + i
        fill = white_fill if i % 2 == 0 else blue_fill
        for col, value in enumerate(row, start=1):
            cell = ws.cell(row=excel_row, column=col, value=value)
            cell.fill = fill
            cell.font = cell_font
            cell.alignment = center
            cell.border = thin
        ws.row_dimensions[excel_row].height = 22

    widths = col_widths or {}
    for col, name in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(col)].width = float(
            widths.get(name, max(12, min(28, len(str(name)) * 2.2)))
        )

    ws.freeze_panes = f"A{start_row + 1}"
    wb.save(path)
    return path
