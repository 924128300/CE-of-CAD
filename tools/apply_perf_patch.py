"""一次性补丁：Excel 写入批量化（样式模板 + 快速合并）。

用法：python tools/apply_perf_patch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "core" / "section_sheet.py"

NEW_IMPORT = """from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.styles.cell_style import StyleArray
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange
from openpyxl.worksheet.merge import MergedCellRange
from openpyxl.worksheet.worksheet import Worksheet
"""

NEW_STYLE = '''def block_style(ws: Worksheet) -> StyleArray:
    """整块共用的样式索引数组（宋体 11、居中、细黑边框）。

    openpyxl 给单元格赋 ``cell.font = FONT`` 时，每次都要把样式对象拿去集合里做
    hash/eq 去重，一格 3 次赋值意味着上千次递归比较。这里只算一次，之后把算好的
    ``StyleArray`` 直接拷进每个单元格，省掉全部去重开销。
    """
    wb = ws.parent
    cached = getattr(wb, "_dwg_block_style", None)
    if cached is not None:
        return cached
    cell = ws.cell(row=1, column=1)
    cell.font = FONT
    cell.alignment = ALIGN
    cell.border = BORDER
    cached = StyleArray(cell._style)  # noqa: SLF001 - 借用临时单元格求样式索引
    wb._dwg_block_style = cached  # noqa: SLF001 - 随工作簿缓存的样式模板
    return cached

def _style_range(ws: Worksheet, r1: int, c1: int, r2: int, c2: int) -> StyleArray:
    """给整块区域套统一样式，返回所用的样式数组。"""
    style = block_style(ws)
    cells = ws._cells  # noqa: SLF001 - 跳过 ws.cell() 的重复边界检查
    for row in range(r1, r2 + 1):
        for col in range(c1, c2 + 1):
            cell = cells.get((row, col))
            if cell is None:
                cell = ws.cell(row=row, column=col)
            if isinstance(cell, MergedCell):
                continue
            # 每格一份独立数组：number_format 是就地改数组的，不能共享
            cell._style = StyleArray(style)  # noqa: SLF001
    return style

def _merge(ws: Worksheet, r1: int, c1: int, r2: int, c2: int,
           style: StyleArray | None = None) -> None:
    """合并单元格（快速路径）。

    默认的 ``Worksheet.merge_cells`` 每次都要拿新区域跟已有区域逐个做包含判断，
    块数一多就退化成 O(n²)；``_clean_merge_range`` 还会给合并区域边缘逐格做
    ``cell.border += Border(...)``，每次都触发 Border 的递归 hash/eq —— 2000 次
    合并能花掉 2 s 以上。本表整块共用同一套细边框，给边缘格再叠一层边框是空操作，
    因此这里只登记区域，直接把非锚点格换成同一样式的 ``MergedCell``，显示效果一致。
    """
    if (r1, c1) == (r2, c2):
        return
    coord = f"{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}"
    if style is None:
        style = block_style(ws)
    try:
        merged = MergedCellRange.__new__(MergedCellRange)
        merged.ws = ws
        CellRange.__init__(merged, range_string=coord)
        merged.start_cell = None
        ws.merged_cells.ranges.add(merged)
        cells = ws._cells  # noqa: SLF001
        for row in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                if row == r1 and col == c1:
                    continue
                if isinstance(cells.get((row, col)), MergedCell):
                    continue  # 已被更小的合并区占用（本表布局不重叠，仅作保护）
                cell = MergedCell(ws, row=row, column=col)
                cell._style = StyleArray(style)  # noqa: SLF001
                cells[(row, col)] = cell
    except Exception:  # noqa: BLE001 - 版本变化时退回公开接口
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
'''

START_MARK = "def _style_range(ws: Worksheet"
END_MARK = "\ndef block_points("


def main() -> int:
    with open(TARGET, "r", encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    if "def block_style(" in text:
        print("已是新实现，无需修改")
        return 0

    old_import = ("from openpyxl.styles import Alignment, Border, Font, Side\n"
                  "from openpyxl.utils import get_column_letter\n"
                  "from openpyxl.worksheet.merge import MergedCellRange\n"
                  "from openpyxl.worksheet.worksheet import Worksheet\n")
    if old_import not in text:
        print("[失败] 未找到 import 段")
        return 1
    text = text.replace(old_import, NEW_IMPORT, 1)

    start = text.find(START_MARK)
    end = text.find(END_MARK)
    if start < 0 or end < 0 or end <= start:
        print("[失败] 未找到样式/合并函数段边界")
        return 1
    text = text[:start] + NEW_STYLE + text[end:]

    with open(TARGET, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", "\r\n"))
    print("已更新 core/section_sheet.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
