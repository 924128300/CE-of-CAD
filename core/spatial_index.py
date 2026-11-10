"""均匀网格空间索引：视口裁剪与拾取加速。

只保存句柄和包围盒，几何数据仍由 DrawingModel 持有。
"""
from __future__ import annotations

import math
from collections import defaultdict

# 单个实体最多写入的网格数量；超过后转入“长实体”候选列表，避免索引爆炸
MAX_CELLS_PER_ENTITY = 4096


class GridIndex:
    def __init__(self, bbox: tuple[float, float, float, float], cell_size: float | None = None) -> None:
        x0, y0, x1, y1 = bbox
        self.min_x = min(x0, x1)
        self.min_y = min(y0, y1)
        self.max_x = max(x0, x1)
        self.max_y = max(y0, y1)
        width = max(self.max_x - self.min_x, 1e-9)
        height = max(self.max_y - self.min_y, 1e-9)
        if cell_size is None or not math.isfinite(cell_size) or cell_size <= 0:
            cell_size = max(width, height) / 128.0
        self.cell_size = max(cell_size, 1e-9)
        self._cells: dict[tuple[int, int], list[int]] = defaultdict(list)
        self._bboxes: dict[int, tuple[float, float, float, float]] = {}
        self._all: list[int] = []
        # 跨格过多的长实体不写入网格，查询时始终作为候选返回。
        # （早期版本按步长抽样写入格子，放大后长实体落在未写入的格子就会“消失”）
        self._large: list[int] = []

    def _range(self, x0: float, y0: float, x1: float, y1: float):
        cs = self.cell_size
        ix0 = int(math.floor((x0 - self.min_x) / cs))
        iy0 = int(math.floor((y0 - self.min_y) / cs))
        ix1 = int(math.floor((x1 - self.min_x) / cs))
        iy1 = int(math.floor((y1 - self.min_y) / cs))
        return ix0, iy0, ix1, iy1

    def add(self, handle: int, bbox: tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = bbox
        norm = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        if handle in self._bboxes:
            return
        self._all.append(handle)
        self._bboxes[handle] = norm
        ix0, iy0, ix1, iy1 = self._range(*norm)
        if (ix1 - ix0 + 1) * (iy1 - iy0 + 1) > MAX_CELLS_PER_ENTITY:
            self._large.append(handle)
            return
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                self._cells[(ix, iy)].append(handle)

    def query_rect(self, x0: float, y0: float, x1: float, y1: float) -> list[int]:
        """返回与矩形相交的候选句柄（可能包含包围盒命中但几何未命中的项）。"""
        qx0, qy0 = min(x0, x1), min(y0, y1)
        qx1, qy1 = max(x0, x1), max(y0, y1)
        # 全图视图直接返回全部句柄，避免遍历大量空网格
        if not self._cells or (qx0 <= self.min_x and qy0 <= self.min_y
                               and qx1 >= self.max_x and qy1 >= self.max_y):
            return list(self._all)
        ix0, iy0, ix1, iy1 = self._range(qx0, qy0, qx1, qy1)
        found: set[int] = set(self._large)
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                bucket = self._cells.get((ix, iy))
                if bucket:
                    found.update(bucket)
        result: list[int] = []
        for handle in found:
            bx0, by0, bx1, by1 = self._bboxes[handle]
            if bx1 < qx0 or bx0 > qx1 or by1 < qy0 or by0 > qy1:
                continue
            result.append(handle)
        return result

    def query_point(self, x: float, y: float, radius: float) -> list[int]:
        return self.query_rect(x - radius, y - radius, x + radius, y + radius)

    def bbox_of(self, handle: int) -> tuple[float, float, float, float] | None:
        return self._bboxes.get(handle)
