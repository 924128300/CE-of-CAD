"""点选模式的端点捕捉索引。

只收「当前显示范围（外扩半屏）」内的线条顶点，按捕捉容差分格。鼠标移动时只
比较光标所在格及相邻 8 格，因此几十万点的图纸上也能保持实时吸附。

点数按上限截断：视口内顶点过多时宁可提示用户放大，也不让一次点选卡住主线程。
"""
from __future__ import annotations

import math
from collections import defaultdict

from core.model import DrawingModel

# 一次最多收录的顶点数：约 12 万个点，构建耗时几十毫秒
SNAP_VERTEX_LIMIT = 120000


class SnapIndex:
    """屏幕容差 + 世界坐标分格的顶点索引。"""

    __slots__ = ("cells", "cell", "min_x", "min_y", "points", "truncated")

    def __init__(self, points: list[tuple[float, float, int, int]], cell: float,
                 min_x: float, min_y: float, truncated: bool = False) -> None:
        self.points = points
        self.cell = cell
        self.min_x = min_x
        self.min_y = min_y
        self.truncated = truncated
        cells: dict[tuple[int, int], list[tuple[float, float, int, int]]] = defaultdict(list)
        for item in points:
            key = (int((item[0] - min_x) // cell), int((item[1] - min_y) // cell))
            cells[key].append(item)
        self.cells = dict(cells)

    def __len__(self) -> int:
        return len(self.points)

    def nearest(self, x: float, y: float,
                radius: float) -> tuple[float, float, int, int] | None:
        """返回 ``radius`` 内最近的顶点 ``(x, y, handle, 顶点下标)``。"""
        cell = self.cell
        cx = int((x - self.min_x) // cell)
        cy = int((y - self.min_y) // cell)
        best = None
        best_dist = radius * radius
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                bucket = self.cells.get((gx, gy))
                if not bucket:
                    continue
                for item in bucket:
                    dx = item[0] - x
                    dy = item[1] - y
                    dist = dx * dx + dy * dy
                    if dist <= best_dist:
                        best_dist = dist
                        best = item
        return best


def build_snap_index(candidates: list[int], model: DrawingModel,
                     rect: tuple[float, float, float, float], radius: float,
                     allowed_types: set[str] | None = None,
                     limit: int = SNAP_VERTEX_LIMIT) -> SnapIndex:
    """收集 ``rect`` 内可见线条的顶点。

    - ``candidates``：由画布的空间索引按 ``rect`` 查出的候选句柄，避免全图遍历
    - ``radius``：捕捉半径（图纸单位，= 屏幕像素 / 当前比例），同时作为分格边长
    - 点实体只取一个点；线条取全部顶点（对应 CAD 的「端点」捕捉）
    - 达到 ``limit`` 时停止并置 ``truncated``，由调用方提示用户放大
    """
    x0, y0, x1, y1 = rect
    cell = max(float(radius), 1e-9)
    visible = model.visible_layers()
    points: list[tuple[float, float, int, int]] = []
    truncated = False
    scanned = 0
    # 顶点扫描量也设上限：全图视图下即使保留下来的端点不多，逐条点数也可能上百万
    scan_limit = max(limit * 2, 1000)
    for handle in candidates:
        entity = model.get(handle)
        if entity is None or entity.layer not in visible:
            continue
        if allowed_types is not None and entity.dxftype not in allowed_types:
            continue
        ex0, ey0, ex1, ey1 = entity.bbox
        if ex1 < x0 or ex0 > x1 or ey1 < y0 or ey0 > y1:
            continue
        for index, point in enumerate(entity.points):
            scanned += 1
            if not (x0 <= point[0] <= x1 and y0 <= point[1] <= y1):
                if scanned >= scan_limit:
                    truncated = True
                    break
                continue
            points.append((point[0], point[1], handle, index))
            if len(points) >= limit or scanned >= scan_limit:
                truncated = True
                break
        if truncated:
            break
    return SnapIndex(points, cell, x0, y0, truncated)


def snap_world_radius(pixels: float, scale: float) -> float:
    """屏幕像素换算成图纸单位；比例非法时退回一个极小值避免除零。"""
    if not math.isfinite(scale) or scale <= 0.0:
        return 1.0
    return float(pixels) / scale
