"""校验优化后的表形写入与原实现输出一致（样式、合并、数值）。

用法：python tools/verify_sheet_style.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, Side  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from core.section_sheet import BLOCK_ROWS, block_points, prepare_sheet, write_block  # noqa: E402

POINTS = [(606428.0946, 3831780.1304, 1250.0), (606427.6146, 3831780.1304, 1250.5),
          (606427.6146, 3831779.6504, 1251.0)]
SPANS = [0.48, 0.48]

FONT = Font(name="宋体", size=11)
ALIGN = Alignment(horizontal="center", vertical="center")
THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def legacy_write_block(ws, start_row, points, spans, title, coord_factor, coord_symbol):
    """优化前的写法：逐格赋样式 + 走 openpyxl 默认合并流程。"""
    n = len(points)
    first_col, last_col = 3, 3 + 2 * n - 1
    rows = range(start_row, start_row + BLOCK_ROWS)
    for row in rows:
        for col in range(1, last_col + 1):
            cell = ws.cell(row=row, column=col)
            cell.font = FONT
            cell.alignment = ALIGN
            cell.border = BORDER

    def merge(r1, c1, r2, c2):
        if (r1, c1) != (r2, c2):
            ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
        return None

    merge(start_row, 1, start_row, 2)
    ws.cell(row=start_row, column=1, value="工程名称")
    merge(start_row, first_col, start_row, last_col)
    ws.cell(row=start_row, column=first_col, value=title)

    name_row = start_row + 1
    merge(name_row, 1, name_row, 2)
    ws.cell(row=name_row, column=1, value="点号")
    for index in range(n):
        col = first_col + 2 * index
        merge(name_row, col, name_row, col + 1)
        ws.cell(row=name_row, column=col, value=f"P{index + 1}")

    from core.geometry import (
        LENGTH_DECIMALS, azimuth as azimuth_deg, format_dms, round_decimal,
    )
    from core.section_sheet import LENGTH_FORMAT, PERCENT_FORMAT, TEXT_FORMAT
    for offset, label in enumerate(("平距(m)", "巷道长(m)", "方位")):
        row = start_row + 2 + offset
        merge(row, 1, row, 2)
        ws.cell(row=row, column=1, value=label)
        for index in range(n - 1):
            col = 4 + 2 * index
            merge(row, col, row, col + 1)
            cell = ws.cell(row=row, column=col)
            p0, p1 = points[index], points[index + 1]
            if offset == 0:
                cell.value = round_decimal(spans[index], LENGTH_DECIMALS)
                cell.number_format = LENGTH_FORMAT
            elif offset == 2:
                cell.value = format_dms(azimuth_deg(p0, p1))
                cell.number_format = TEXT_FORMAT
            else:
                cell.number_format = LENGTH_FORMAT

    from core.geometry import COORD_DECIMALS, excel_cell_value
    from core.section_sheet import COORD_FORMAT
    coord_start = start_row + 5
    merge(coord_start, 1, coord_start + 2, 1)
    ws.cell(row=coord_start, column=1, value=f"坐标({coord_symbol})")
    for offset, axis in enumerate(("X", "Y", "Z")):
        row = coord_start + offset
        ws.cell(row=row, column=2, value=axis)
        for index in range(n):
            col = first_col + 2 * index
            merge(row, col, row, col + 1)
            cell = ws.cell(row=row, column=col)
            value = excel_cell_value(points[index][offset] * coord_factor, COORD_DECIMALS)
            cell.value = value
            cell.number_format = COORD_FORMAT if isinstance(value, float) else TEXT_FORMAT

    slope_row = start_row + 8
    merge(slope_row, 1, slope_row, 2)
    ws.cell(row=slope_row, column=1, value="坡度")
    for index in range(n - 1):
        col = 4 + 2 * index
        merge(slope_row, col, slope_row, col + 1)
        ws.cell(row=slope_row, column=col).number_format = PERCENT_FORMAT
    return start_row + BLOCK_ROWS + 1


def snapshot(ws, rows: int, cols: int):
    """取用户可见属性：值、数字格式、字体、居中、四边框。"""
    data = {}
    for row in range(1, rows + 1):
        for col in range(1, cols + 1):
            cell = ws.cell(row=row, column=col)
            border = cell.border
            data[(row, col)] = (
                cell.value,
                cell.number_format,
                tuple(side.style for side in (border.left, border.right, border.top, border.bottom)),
                cell.font.name,
                cell.font.size,
                cell.alignment.horizontal,
                cell.alignment.vertical,
            )
    return data


def content_map(snap):
    """只保留值 + 数字格式（跨实现必须完全一致的项）。"""
    return {key: value[:2] for key, value in snap.items()}


def style_ok(snap) -> list:
    """新版每格都应是宋体 11、居中、四边细线（旧版合并内部格本来会丢字体）。"""
    bad = []
    for key, value in snap.items():
        borders, font_name, font_size, align_h, align_v = value[2], value[3], value[4], value[5], value[6]
        if borders != ("thin",) * 4 or font_name != "宋体" or font_size != 11.0 \
                or align_h != "center" or align_v != "center":
            bad.append((key, value))
    return bad


def main() -> int:
    wb_new = Workbook()
    ws_new = wb_new.active
    wb_old = Workbook()
    ws_old = wb_old.active
    points = block_points(type("E", (), {
        "is_point": False, "points": POINTS, "bulges": [0.0, 0.0, 0.0], "closed": False,
    })(), True, 1.0)[0]
    prepare_sheet(ws_new, 3)
    prepare_sheet(ws_old, 3)
    write_block(ws_new, 1, points, SPANS, "线1", 1.0, "m")
    legacy_write_block(ws_old, 1, points, SPANS, "线1", 1.0, "m")

    new_ranges = sorted(r.coord for r in ws_new.merged_cells.ranges)
    old_ranges = sorted(r.coord for r in ws_old.merged_cells.ranges)
    print("合并区域一致:", new_ranges == old_ranges, f"({len(new_ranges)} 个)")

    cols = 3 + 2 * len(points) - 1
    snap_new = snapshot(ws_new, BLOCK_ROWS, cols)
    snap_old = snapshot(ws_old, BLOCK_ROWS, cols)
    content_diffs = [(key, content_map(snap_new)[key], content_map(snap_old)[key])
                     for key in snap_new
                     if content_map(snap_new)[key] != content_map(snap_old)[key]]
    print("值与数字格式一致:", not content_diffs)
    for item in content_diffs[:8]:
        print("  差异", item)

    bad = style_ok(snap_new)
    print("新版整块样式完整（宋体 11 / 居中 / 四边细线）:", not bad)
    for item in bad[:5]:
        print("  不达标", item)

    wb_new.save("tools/screenshots/_verify_new.xlsx")
    wb_old.save("tools/screenshots/_verify_old.xlsx")
    print("已输出 _verify_new.xlsx / _verify_old.xlsx 供人工比对")
    return 0 if new_ranges == old_ranges and not content_diffs and not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
