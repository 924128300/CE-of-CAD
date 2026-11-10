"""按「采场矿房坐标计算表」形式排版：点位、平距、方位、坐标阶梯式排列。

每一列对应一个点（占两列合并），相邻两点之间的平距/巷道长/方位写在两列中间，
坐标分 X/Y/Z 三行，坡度单独一行。巷道长留空由使用者填写；坡度默认留空，打开「反算坡度」开关后按相邻两点高差反算填入。
"""
from __future__ import annotations

from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.styles.cell_style import StyleArray
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange
from openpyxl.worksheet.merge import MergedCellRange
from openpyxl.worksheet.worksheet import Worksheet

from .geometry import (
    COORD_DECIMALS,
    LENGTH_DECIMALS,
    azimuth as azimuth_deg,
    excel_cell_value,
    format_dms,
    round_decimal,
    walk_path_points,
)

BLOCK_ROWS = 9          # 工程名称/点号/平距/巷道长/方位/X/Y/Z/坡度
BLOCK_GAP = 1           # 块之间空一行

FONT = Font(name="宋体", size=11)
ALIGN = Alignment(horizontal="center", vertical="center")
THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

COORD_FORMAT = "0." + "0" * COORD_DECIMALS
LENGTH_FORMAT = "0." + "0" * LENGTH_DECIMALS
TEXT_FORMAT = "@"
PERCENT_FORMAT = "0.00%"


def block_style(ws: Worksheet) -> StyleArray:
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

def block_points(entity, include_vertices: bool, sample_step: float):
    """返回 ``(点列表, 每点的累计平面长度列表)``（长度单位与图纸一致）。"""
    if entity.is_point:
        return [entity.points[0]], [0.0]
    walked = walk_path_points(entity.points, entity.bulges, entity.closed,
                              sample_step, include_vertices)
    return [item[0] for item in walked], [item[2] for item in walked]


def write_block(ws: Worksheet, start_row: int, points: list[tuple[float, float, float]],
                spans: list[float], title: str, coord_factor: float,
                coord_symbol: str, slopes: list[float | None] | None = None) -> int:
    """写入一个坐标计算块（固定 9 行），返回下一个可用行号。

    布局：每个点占两列合并；第 1 行工程名称、第 2 行点号、第 3-5 行平距/巷道长/方位、
    第 6-8 行 X/Y/Z 坐标、第 9 行坡度，平距与方位写在相邻两点之间。

    - ``points``：本块点序列（已按取点规则展开），至少 1 个点
    - ``spans``：相邻两点之间的平距（米，已按比例尺换算），长度 = ``len(points) - 1``
    - ``coord_factor``：图纸坐标到导出坐标单位的换算系数（1.0 表示按原值输出）
    - ``coord_symbol``：坐标表头单位符号，如 m / mm
    - 平距固定按米写，圆弧段取弧长；巷道长只留空单元格由使用者填写
    - ``slopes``：相邻两点坡度比值（0.01 = 1%），长度 = ``len(points) - 1``；
      传 ``None`` 表示不反算，坡度行留空由使用者填写
    """
    n = len(points)
    if n == 0:
        return start_row
    first_col = 3
    last_col = first_col + 2 * n - 1
    rows = range(start_row, start_row + BLOCK_ROWS)
    _style_range(ws, rows.start, 1, rows.stop - 1, last_col)

    # 工程名称
    _merge(ws, start_row, 1, start_row, 2)
    ws.cell(row=start_row, column=1, value="工程名称")
    _merge(ws, start_row, first_col, start_row, last_col)
    ws.cell(row=start_row, column=first_col, value=title)

    # 点号
    name_row = start_row + 1
    _merge(ws, name_row, 1, name_row, 2)
    ws.cell(row=name_row, column=1, value="点号")
    for index in range(n):
        col = first_col + 2 * index
        _merge(ws, name_row, col, name_row, col + 1)
        ws.cell(row=name_row, column=col, value=f"P{index + 1}")

    # 平距 / 巷道长 / 方位
    for offset, label in enumerate(("平距(m)", "巷道长(m)", "方位")):
        row = start_row + 2 + offset
        _merge(ws, row, 1, row, 2)
        ws.cell(row=row, column=1, value=label)
        for index in range(n - 1):
            col = 4 + 2 * index
            _merge(ws, row, col, row, col + 1)
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

    # 坐标 X/Y/Z
    coord_start = start_row + 5
    _merge(ws, coord_start, 1, coord_start + 2, 1)
    ws.cell(row=coord_start, column=1, value=f"坐标({coord_symbol})")
    for offset, axis in enumerate(("X", "Y", "Z")):
        row = coord_start + offset
        ws.cell(row=row, column=2, value=axis)
        for index in range(n):
            col = first_col + 2 * index
            _merge(ws, row, col, row, col + 1)
            cell = ws.cell(row=row, column=col)
            value = excel_cell_value(points[index][offset] * coord_factor, COORD_DECIMALS)
            cell.value = value
            # 超过 Excel 15 位有效数字时退化为文本，避免静默丢精度
            cell.number_format = COORD_FORMAT if isinstance(value, float) else TEXT_FORMAT

    # 坡度（默认留空；slopes 非空时写入反算值，格式 0.00%）
    slope_row = start_row + 8
    _merge(ws, slope_row, 1, slope_row, 2)
    ws.cell(row=slope_row, column=1, value="坡度")
    for index in range(n - 1):
        col = 4 + 2 * index
        _merge(ws, slope_row, col, slope_row, col + 1)
        cell = ws.cell(row=slope_row, column=col)
        cell.number_format = PERCENT_FORMAT
        if slopes and index < len(slopes) and slopes[index] is not None:
            # 百分比保留两位小数，等价于比值保留四位
            cell.value = round_decimal(slopes[index], 4)

    return start_row + BLOCK_ROWS + BLOCK_GAP


def prepare_sheet(ws: Worksheet, max_points: int) -> None:
    ws.column_dimensions["A"].width = 10.0
    ws.column_dimensions["B"].width = 5.5
    for index in range(max_points * 2):
        letter = get_column_letter(3 + index)
        ws.column_dimensions[letter].width = 12.0
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
