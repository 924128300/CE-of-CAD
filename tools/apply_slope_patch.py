"""一次性补丁：新增「反算坡度」功能与导出开关（V1.3.3）。

用法：python tools/apply_slope_patch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GEOMETRY = ROOT / "core" / "geometry.py"
SHEET = ROOT / "core" / "section_sheet.py"
EXPORT = ROOT / "core" / "excel_export.py"
DIALOG = ROOT / "ui" / "export_dialog.py"
WINDOW = ROOT / "ui" / "main_window.py"

GEOMETRY_ADD = '''

def slope_ratio(z0: float, z1: float, horizontal: float) -> float | None:
    """相邻两点坡度：高差 ÷ 水平距离，返回比值（0.01 即 1%）。

    - 高差与水平距离都取**图纸原值**（同一单位），因此与比例尺、坐标单位无关
    - 上坡为正、下坡为负，与现场计算表一致（-0.01 表示 -1%）
    - 水平距离为 0（两点重合）时返回 ``None``，由调用方留空
    """
    if horizontal <= 0:
        return None
    return (z1 - z0) / horizontal
'''

SHEET_EDITS = [
    ("坐标分 X/Y/Z 三行，坡度单独一行。巷道长与坡度留空，由使用者填写。",
     "坐标分 X/Y/Z 三行，坡度单独一行。巷道长留空由使用者填写；"
     "坡度默认留空，打开「反算坡度」开关后按相邻两点高差反算填入。"),
    ('''def write_block(ws: Worksheet, start_row: int, points: list[tuple[float, float, float]],
                spans: list[float], title: str, coord_factor: float,
                coord_symbol: str) -> int:''',
     '''def write_block(ws: Worksheet, start_row: int, points: list[tuple[float, float, float]],
                spans: list[float], title: str, coord_factor: float,
                coord_symbol: str, slopes: list[float | None] | None = None) -> int:'''),
    ('''    - 平距固定按米写，圆弧段取弧长；巷道长、坡度只留空单元格由使用者填写
    """''',
     '''    - 平距固定按米写，圆弧段取弧长；巷道长只留空单元格由使用者填写
    - ``slopes``：相邻两点坡度比值（0.01 = 1%），长度 = ``len(points) - 1``；
      传 ``None`` 表示不反算，坡度行留空由使用者填写
    """'''),
    ('''    # 坡度（留空，由使用者填写）
    slope_row = start_row + 8
    _merge(ws, slope_row, 1, slope_row, 2)
    ws.cell(row=slope_row, column=1, value="坡度")
    for index in range(n - 1):
        col = 4 + 2 * index
        _merge(ws, slope_row, col, slope_row, col + 1)
        ws.cell(row=slope_row, column=col).number_format = PERCENT_FORMAT
''',
     '''    # 坡度（默认留空；slopes 非空时写入反算值，格式 0.00%）
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
'''),
]

EXPORT_EDITS = [
    ('APP_VERSION = "1.3.2"', 'APP_VERSION = "1.3.3"'),
    ('''    unit: str = "drawing"
    scale_denominator: int = DEFAULT_SCALE''',
     '''    unit: str = "drawing"
    scale_denominator: int = DEFAULT_SCALE
    fill_slope: bool = False'''),
    ('''from .geometry import COORD_DECIMALS, LENGTH_DECIMALS, DMS_SECOND_DECIMALS''',
     '''from .geometry import COORD_DECIMALS, LENGTH_DECIMALS, DMS_SECOND_DECIMALS, slope_ratio'''),
    ('''        ("排版说明", "每点占两列合并；平距/巷道长/方位位于相邻两点之间；巷道长与坡度留空待填"),''',
     '''        ("排版说明", "每点占两列合并；平距/巷道长/方位位于相邻两点之间；巷道长留空待填"),
        ("坡度", "已反算：相邻两点高差 ÷ 水平距离（图纸原值），0.00%，负值下坡"
         if options.fill_slope else "未反算（留空待填）"),'''),
    ('''        spans = [max(cumulative[i + 1] - cumulative[i], 0.0) * length_factor
                 for i in range(len(points) - 1)]
        row = write_block(ws, row, points, spans, f"线{index}", factor, symbol)''',
     '''        raw_spans = [max(cumulative[i + 1] - cumulative[i], 0.0)
                     for i in range(len(points) - 1)]
        spans = [length * length_factor for length in raw_spans]
        slopes = None
        if options.fill_slope:
            # 高差与水平距离同取图纸原值，结果与比例尺、坐标单位无关
            slopes = [slope_ratio(points[i][2], points[i + 1][2], raw_spans[i])
                      for i in range(len(points) - 1)]
        row = write_block(ws, row, points, spans, f"线{index}", factor, symbol, slopes)'''),
]

DIALOG_EDITS = [
    ('''                 entity_count: int = 0, parent=None) -> None:''',
     '''                 entity_count: int = 0, fill_slope: bool = False, parent=None) -> None:'''),
    ('''        self.check_info = QCheckBox("附加「导出信息」工作表")
        self.check_info.setChecked(True)
        option_layout.addWidget(self.check_info)''',
     '''        self.check_slope = QCheckBox("反算坡度（相邻两点高差 ÷ 水平距离，按 0.00% 写入）")
        self.check_slope.setChecked(fill_slope)
        self.check_slope.setToolTip(
            "默认关闭，坡度行留空由你填写。打开后按图纸原值反算：\\n"
            "上坡为正、下坡为负，保留两位小数（如 -1.00%）。\\n"
            "高差与水平距离同取图纸原值，因此与比例尺、坐标单位无关。")
        option_layout.addWidget(self.check_slope)

        self.check_info = QCheckBox("附加「导出信息」工作表")
        self.check_info.setChecked(True)
        option_layout.addWidget(self.check_info)'''),
    ('''            "相邻两点之间的平距、方位写在中间，巷道长与坡度留空由你填写。\\n"''',
     '''            "相邻两点之间的平距、方位写在中间，巷道长留空由你填写；"
            "坡度默认留空，勾选上方开关后自动反算。\\n"'''),
    ('''            scale_denominator=int(self.scale_combo.currentData() or DEFAULT_SCALE),
        )''',
     '''            scale_denominator=int(self.scale_combo.currentData() or DEFAULT_SCALE),
            fill_slope=self.check_slope.isChecked(),
        )'''),
]

WINDOW_EDITS = [
    ('''        self._scale_denominator = DEFAULT_SCALE''',
     '''        self._scale_denominator = DEFAULT_SCALE
        self._fill_slope = False  # 反算坡度：启动默认关闭，勾选后在本次运行内记住'''),
    ('''        dialog = ExportDialog(self.model, self._include_vertices, self._sample_step,
                              self._scale_denominator, len(entities), self)''',
     '''        dialog = ExportDialog(self.model, self._include_vertices, self._sample_step,
                              self._scale_denominator, len(entities),
                              self._fill_slope, self)'''),
    ('''        options: ExportOptions = dialog.options()''',
     '''        options: ExportOptions = dialog.options()
        self._fill_slope = options.fill_slope'''),
]


def apply(path: Path, edits: list[tuple[str, str]], add: str = "") -> int:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    if add and add.strip() in text:
        print(f"  {path.name}: 新增函数已存在，跳过")
        add = ""
    for old, new in edits:
        if new in text and old not in text:
            print(f"  {path.name}: 已是最新，跳过一处")
            continue
        if old not in text:
            print(f"  [失败] {path.name}: 未找到锚点\n    {old[:60]!r}")
            return 1
        text = text.replace(old, new, 1)
        print(f"  {path.name}: 已改")
    if add:
        text = text.rstrip("\n") + "\n" + add
        print(f"  {path.name}: 已追加 slope_ratio()")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", "\r\n"))
    return 0


def main() -> int:
    if apply(GEOMETRY, [], add=GEOMETRY_ADD):
        return 1
    for path, edits in ((SHEET, SHEET_EDITS), (EXPORT, EXPORT_EDITS),
                        (DIALOG, DIALOG_EDITS), (WINDOW, WINDOW_EDITS)):
        if apply(path, edits):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
