"""一次性补丁脚本：应用代码审查发现的修复（保留原 CRLF 换行）。"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def save(path: Path, text: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(text)


def patch(path: Path, pairs: list[tuple[str, str]], must: int | None = None) -> None:
    text = load(path)
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"[FAIL] {path.name}: 未找到片段\n{old[:120]}")
        text = text.replace(old, new, 1)
    save(path, text)
    print(f"[OK] {path.name}")


# ------------------------------------------------------------------ canvas
patch(ROOT / "ui" / "canvas.py", [
    ("        self._pen_cache: dict[tuple[int, int, int], QPen] = {}",
     "        self._pen_cache: dict[tuple[int, int, int, float], QPen] = {}"),
    ("        key = (rgb[0], rgb[1], rgb[2])",
     "        key = (rgb[0], rgb[1], rgb[2], round(width, 3))"),
    ("""            if entity.is_point:
                dist = math.hypot(entity.points[0][0] - wx, entity.points[0][1] - wy)""",
     """            # 先用包围盒做一次廉价排除，避免在超大折线上逐段算距离
            bx0, by0, bx1, by1 = entity.bbox
            if wx < bx0 - tol or wx > bx1 + tol or wy < by0 - tol or wy > by1 + tol:
                continue
            if entity.is_point:
                dist = math.hypot(entity.points[0][0] - wx, entity.points[0][1] - wy)"""),
    ("""    def handles_in_rect(self, rect: QRect, crossing: bool = True) -> list[int]:""",
     """    def handles_in_rect(self, rect: QRect, window: bool = False) -> list[int]:
        \"\"\"框选命中的句柄。

        window=True 为窗口选择（实体整体落在框内才算命中，对应从左往右拖框）；
        window=False 为交叉选择（包围盒与框相交即命中，对应从右往左拖框）。
        \"\"\""""),
    ("""            x0, y0, x1, y1 = entity.bbox
            if crossing:
                if x0 >= wx0 and x1 <= wx1 and y0 >= wy0 and y1 <= wy1:
                    result.append(handle)
            else:
                result.append(handle)""",
     """            if window:
                x0, y0, x1, y1 = entity.bbox
                if x0 < wx0 or x1 > wx1 or y0 < wy0 or y1 > wy1:
                    continue
            result.append(handle)"""),
    ("            handles = self.handles_in_rect(rect, crossing=self._rubber_dir > 0)",
     "            handles = self.handles_in_rect(rect, window=self._rubber_dir > 0)"),
])

# ------------------------------------------------------------------ loader
patch(ROOT / "core" / "dwg_loader.py", [
    ("""            if bulges and uniform and scale[0] > 0 and scale[1] > 0 and not closed:
                pass
            elif bulges:
                # 非均匀缩放/镜像时圆弧不再是圆弧，退化为密折线
                from .geometry import polyline_render_points
                points = polyline_render_points(points, bulges, closed)
                bulges = []
            elif uniform and (scale[0] < 0 or scale[1] < 0):
                bulges = [b for b in bulges]""",
     """            if bulges and not (uniform and scale[0] > 0 and scale[1] > 0):
                # 非均匀缩放或镜像时圆弧不再是圆弧，退化为密折线
                from .geometry import polyline_render_points
                points = polyline_render_points(points, bulges, closed)
                bulges = []"""),
])

# ------------------------------------------------------------------ window
patch(ROOT / "ui" / "main_window.py", [
    ("from core.excel_export import ExportOptions, export_excel",
     "from core.excel_export import APP_VERSION, ExportOptions, export_excel"),
    ("        self._last_export: str | None = None",
     "        self._last_export: str | None = None\n        self._status_prefix = \"\""),
    ("""        name = os.path.basename(model.path)
        self.lbl_count.setText(f"{name} | 实体 {len(model.entities)} | 块展开 {model.insert_count}")""",
     """        name = os.path.basename(model.path)
        self._status_prefix = f"{name} | 实体 {len(model.entities)} | 块展开 {model.insert_count}"
        self.lbl_count.setText(self._status_prefix)"""),
    ("""        self.lbl_count.setText(
            f"实体 {len(self.model.entities)} | 已选 {len(self.selection)} | "
            f"图纸单位")""",
     """        prefix = self._status_prefix or f"实体 {len(self.model.entities)}"
        self.lbl_count.setText(f"{prefix} | 已选 {len(self.selection)}")"""),
    ("""            "DWG 坐标导出工具 1.0.0\\n\\n\"""",
     """            f"DWG 坐标导出工具 {APP_VERSION}\\n\\n\""""),
    ("""    def closeEvent(self, event) -> None:  # noqa: N802
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)""",
     """    def closeEvent(self, event) -> None:  # noqa: N802
        if self._thread is not None:
            self._thread.quit()
            if not self._thread.wait(3000):
                # 线程仍在解析时直接销毁会崩溃，提示用户等待
                QMessageBox.information(self, "正在读取图纸", "图纸仍在解析中，请等待加载完成后再关闭窗口。")
                event.ignore()
                return
            self._thread.deleteLater()
            self._thread = None
            self._worker = None
        super().closeEvent(event)"""),
])

# ------------------------------------------------------------------ geometry
text = load(ROOT / "core" / "geometry.py")
for block in (
    '''def sub(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def add(a: Point3, b: Point3) -> Point3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

def scale(a: Point3, k: float) -> Point3:
    return (a[0] * k, a[1] * k, a[2] * k)

''',
    '''def total_planar_length(points: list[Point3], bulges: list[float], closed: bool) -> float:
    length = 0.0
    for seg in build_segments(points, bulges, closed):
        length += seg.length
    return length

''',
    '''def format_azimuth(value: float) -> str:
    return format_decimal(normalize_angle(value), AZIMUTH_DECIMALS)

''',
    '''def significant_digits(value: float) -> int:
    text = format(abs(value), ".15g")
    digits = [c for c in text if c.isdigit()]
    return len(digits)
''',
):
    if block not in text:
        raise SystemExit(f"[FAIL] geometry.py 未找到片段:\n{block[:100]}")
    text = text.replace(block, "", 1)

# AZIMUTH_DECIMALS 已无调用点，但保留常量做口径说明；去掉尾部多余空行
text = text.rstrip("\n") + "\n"
save(ROOT / "core" / "geometry.py", text)
print("[OK] geometry.py")
