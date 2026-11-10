"""Excel 导出：按「采场矿房坐标计算表」形式输出。"""
from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass

from openpyxl import Workbook
from openpyxl.styles import Font

from .geometry import COORD_DECIMALS, LENGTH_DECIMALS, DMS_SECOND_DECIMALS, slope_ratio
from .model import DrawingModel, EntityRecord
from .section_sheet import block_points, prepare_sheet, write_block

APP_VERSION = "1.5.0"

UNIT_CHOICES = {
    "drawing": "图纸单位",
    "meter": "米",
    "millimeter": "毫米",
}

# 常用比例尺；平距按“图上 1 单位 = 分母/1000 米”换算
SCALE_CHOICES = (100, 200, 500, 1000, 2000, 5000)
DEFAULT_SCALE = 1000


@dataclass(slots=True)
class ExportOptions:
    path: str
    include_info: bool = True
    include_vertices: bool = True
    sample_step: float = 1.0
    unit: str = "drawing"
    scale_denominator: int = DEFAULT_SCALE
    fill_slope: bool = False
    reversed_count: int = 0
    # 点选模式：每轮点选各占一块，取点规则固定为「按点选顺序」
    pick_mode: bool = False


@dataclass(slots=True)
class ExportResult:
    path: str
    point_rows: int
    line_rows: int


# 绝对路径（含盘符、UNC、POSIX），写进信息表时按文本处理，避免 Excel 当超链接
_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def _save_atomic(wb: Workbook, path: str) -> None:
    """先写临时文件再替换目标文件，避免失败时留下打不开的半个 xlsx。"""
    temp_path = f"{path}.part"
    try:
        wb.save(temp_path)
        os.replace(temp_path, path)
    except OSError as exc:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise OSError(
            f"保存失败：{path}\n请确认该文件没有在 Excel 中打开，且目录有写入权限。") from exc
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise


def meters_per_unit(scale_denominator: int) -> float:
    """按比例尺换算：1:1000 时图上 1 单位 = 1000 mm = 1 m。"""
    return max(int(scale_denominator), 1) / 1000.0


def _factor(model: DrawingModel, unit: str) -> float:
    mpu = model.meters_per_unit or 1.0
    if unit == "meter":
        return mpu
    if unit == "millimeter":
        return mpu * 1000.0
    return 1.0


def _unit_symbol(model: DrawingModel, unit: str) -> str:
    if unit == "meter":
        return "m"
    if unit == "millimeter":
        return "mm"
    return "m"


def _write_info_sheet(wb: Workbook, model: DrawingModel, entities: list[EntityRecord],
                      options: ExportOptions, point_total: int) -> None:
    ws = wb.create_sheet("导出信息")
    info = [
        ("图纸文件", model.path),
        ("DWG 版本", model.version or "未知"),
        ("图纸标记单位", f"{model.unit_name}（{model.unit_symbol or '-'}）"),
        ("坐标单位", UNIT_CHOICES.get(options.unit, options.unit)),
        ("比例尺", f"1:{options.scale_denominator}"
         f"（图上 1 单位 = {meters_per_unit(options.scale_denominator):g} m）"),
        ("平距口径", "沿路径的平面长度，圆弧段取弧长（不是弦长）"),
        ("坐标顺序", "按图纸 CAD 坐标原样输出（X 东、Y 北）"),
        ("方位角口径", "测量方位角：正北起顺时针，0-360°，度分秒"),
        ("方位角格式", f"度分秒，秒取整数" if DMS_SECOND_DECIMALS == 0
         else f"度分秒，秒保留 {DMS_SECOND_DECIMALS} 位小数"),
        ("取点规则", "仅顶点" if options.include_vertices
         else f"按间距 {options.sample_step:g} 采样"),
        ("坐标小数位", COORD_DECIMALS),
        ("平距小数位", LENGTH_DECIMALS),
        ("排版说明", "每点占两列合并；平距/巷道长/方位位于相邻两点之间；巷道长留空待填"),
        ("坡度", "已反算：相邻两点高差 ÷ 水平距离（图纸原值），0.00%，负值下坡"
         if options.fill_slope else "未反算（留空待填）"),
        ("导出时间", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("软件版本", f"DWG 坐标导出工具 {APP_VERSION}"),
        ("选择方式", "点选（按端点顺序连线，每轮一块）" if options.pick_mode
         else "线选（整条线按取点规则取点）"),
        ("要素数量", len(entities)),
        ("点总数", point_total),
    ]
    if options.reversed_count:
        info.append(("点序方向", f"{options.reversed_count} 条已反向（点号、方位角、平距按新方向输出）"))
    else:
        info.append(("点序方向", "正向"))
    if model.warnings:
        info.append(("加载提示", "；".join(model.warnings)))
    ws.cell(row=1, column=1, value="项目").font = Font(bold=True)
    ws.cell(row=1, column=2, value="内容").font = Font(bold=True)
    for index, (key, value) in enumerate(info, start=2):
        ws.cell(row=index, column=1, value=key)
        cell = ws.cell(row=index, column=2, value=value)
        if isinstance(value, str) and _PATH_RE.match(value):
            cell.number_format = "@"
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 90


def export_excel(model: DrawingModel, entities: list[EntityRecord],
                 options: ExportOptions) -> ExportResult:
    if not entities:
        raise ValueError("没有可导出的要素")

    factor = _factor(model, options.unit)
    symbol = _unit_symbol(model, options.unit)
    multiple = len(entities) > 1

    wb = Workbook()
    ws = wb.active
    ws.title = "坐标计算表"

    # 点选块只导出被点中的那些点，不再按间距插值
    samples = [
        block_points(entity,
                     True if entity.dxftype == "PICK" else options.include_vertices,
                     options.sample_step)
        for entity in entities
    ]
    max_points = max((len(points) for points, _ in samples), default=1)
    prepare_sheet(ws, max(max_points, 1))

    length_factor = meters_per_unit(options.scale_denominator)
    row = 1
    point_total = 0
    for index, (points, cumulative) in enumerate(samples, start=1):
        entity = entities[index - 1]
        title = f"点选{index}" if entity.dxftype == "PICK" else f"线{index}"
        # 相邻两点的平距取累计平面长度之差：直线即水平距离，圆弧即弧长
        raw_spans = [max(cumulative[i + 1] - cumulative[i], 0.0)
                     for i in range(len(points) - 1)]
        spans = [length * length_factor for length in raw_spans]
        slopes = None
        if options.fill_slope:
            # 高差与水平距离同取图纸原值，结果与比例尺、坐标单位无关
            slopes = [slope_ratio(points[i][2], points[i + 1][2], raw_spans[i])
                      for i in range(len(points) - 1)]
        row = write_block(ws, row, points, spans, title, factor, symbol, slopes)
        point_total += len(points)

    if options.include_info:
        _write_info_sheet(wb, model, entities, options, point_total)

    directory = os.path.dirname(os.path.abspath(options.path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    _save_atomic(wb, options.path)
    return ExportResult(path=options.path, point_rows=point_total,
                        line_rows=len(entities))
