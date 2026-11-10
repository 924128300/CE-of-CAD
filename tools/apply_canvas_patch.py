"""一次性补丁：画布高亮/顶点标记的性能优化。

用法：python tools/apply_canvas_patch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "ui" / "canvas.py"

OLD_CONST = """PICK_PIXELS = 7.0
COARSE_SWITCH_ELEMENTS = 140000
"""

NEW_CONST = """PICK_PIXELS = 7.0
COARSE_SWITCH_ELEMENTS = 140000
# 选中/悬停高亮逐点描边的点数上限；超过就沿用底图那套抽稀折线
HIGHLIGHT_POINT_LIMIT = 20000
# 完整折线缓存：条目数与总点数双重上限，避免选很多长线时反复重建
FULL_POLYGON_CACHE = 128
FULL_POLYGON_BUDGET = 300000
# 当前要素的顶点方块：最多画这么多个，超出按序号均匀抽样
VERTEX_MARKER_LIMIT = 2000
VERTEX_MARKER_SIZE = 5.0
"""

OLD_FULL = '''    def _full_polygon(self, entity: EntityRecord) -> QPolygonF | None:
        cached = self._full_polygons.get(entity.handle)
        if cached is not None:
            return cached
        ox, oy = self._origin
        polygon = QPolygonF()
        for p in entity.render_points:
            polygon.append(QPointF(p[0] - ox, p[1] - oy))
        if len(polygon) < 2:
            return None
        if len(self._full_polygons) > 64:
            self._full_polygons.clear()
        self._full_polygons[entity.handle] = polygon
        return polygon
'''

NEW_FULL = '''    def _full_polygon(self, entity: EntityRecord) -> QPolygonF | None:
        """完整折线（局部坐标），带 LRU + 总点数预算的缓存。"""
        cached = self._full_polygons.get(entity.handle)
        if cached is not None:
            return cached
        points = entity.render_points
        if len(points) < 2:
            return None
        ox, oy = self._origin
        polygon = QPolygonF()
        append = polygon.append
        for p in points:
            append(QPointF(p[0] - ox, p[1] - oy))
        # 淘汰最久未用的条目，直到同时满足条数与总点数预算（原来超限整表清空，
        # 选很多长线时每帧都要重建，反而更慢）
        while self._full_polygons and (len(self._full_polygons) >= FULL_POLYGON_CACHE
                                       or self._full_points + len(polygon) > FULL_POLYGON_BUDGET):
            old_handle, old_polygon = self._full_polygons.popitem()
            self._full_points -= len(old_polygon)
        self._full_polygons[entity.handle] = polygon
        self._full_points += len(polygon)
        return polygon

    def _highlight_polygon(self, entity: EntityRecord) -> QPolygonF | None:
        """选中/悬停高亮用的折线。

        超长要素逐点描边不划算：底图本身就是按 ``DISPLAY_POINT_LIMIT`` 抽稀显示的，
        这里直接沿用它，保证高亮与底图轮廓一致，又不会每帧回放十万级顶点。
        """
        if len(entity.render_points) > HIGHLIGHT_POINT_LIMIT:
            return self._polygons.get(entity.handle)
        return self._full_polygon(entity)
'''

OLD_VERTICES = '''    def _draw_vertices(self, painter: QPainter, entity: EntityRecord) -> None:
        painter.save()
        painter.resetTransform()
        painter.setPen(QPen(QColor(theme.SELECT), 1))
        painter.setBrush(QBrush(QColor(theme.BG)))
        for p in entity.points:
            pos = self.to_screen(p[0], p[1])
            painter.drawRect(QRectF(pos.x() - 2.5, pos.y() - 2.5, 5.0, 5.0))
        painter.setBrush(Qt.NoBrush)
        painter.restore()
'''

NEW_VERTICES = '''    def _draw_vertices(self, painter: QPainter, entity: EntityRecord,
                       viewport: tuple[float, float, float, float] | None = None) -> None:
        """在当前要素的每个顶点画小方块。

        先按视口裁掉屏幕外的点，再按 ``VERTEX_MARKER_LIMIT`` 抽样：十万点的多段线
        逐点算屏幕坐标 + 逐点 drawRect 要 300 ms 以上，且屏幕上一个像素里挤着几十个
        方块，看不出区别。
        """
        points = entity.points
        if not points:
            return
        if viewport is not None:
            wx0, wy0, wx1, wy1 = viewport
            points = [p for p in points if wx0 <= p[0] <= wx1 and wy0 <= p[1] <= wy1]
        total = len(points)
        if total == 0:
            return
        step = 1 if total <= VERTEX_MARKER_LIMIT else math.ceil(total / VERTEX_MARKER_LIMIT)
        ox, oy = self._origin
        scale = self.scale
        half = VERTEX_MARKER_SIZE / 2.0
        cx = self.width() / 2.0 + self.pan.x()
        cy = self.height() / 2.0 + self.pan.y()
        painter.save()
        painter.resetTransform()
        painter.setPen(QPen(QColor(theme.SELECT), 1))
        painter.setBrush(QBrush(QColor(theme.BG)))
        draw = painter.drawRect
        for index in range(0, total, step):
            p = points[index]
            sx = (p[0] - ox) * scale + cx
            sy = cy - (p[1] - oy) * scale
            draw(QRectF(sx - half, sy - half, VERTEX_MARKER_SIZE, VERTEX_MARKER_SIZE))
        if step > 1:
            p = points[-1]
            sx = (p[0] - ox) * scale + cx
            sy = cy - (p[1] - oy) * scale
            draw(QRectF(sx - half, sy - half, VERTEX_MARKER_SIZE, VERTEX_MARKER_SIZE))
        painter.setBrush(Qt.NoBrush)
        painter.restore()
'''

OLD_INIT = """        self._polygons: dict[int, QPolygonF] = {}
        self._full_polygons: dict[int, QPolygonF] = {}
"""
NEW_INIT = """        self._polygons: dict[int, QPolygonF] = {}
        self._full_polygons: dict[int, QPolygonF] = {}
        self._full_points = 0
"""

OLD_CLEAR = """        self._polygons.clear()
        self._polygons_coarse.clear()
"""
NEW_CLEAR = """        self._polygons.clear()
        self._polygons_coarse.clear()
        self._full_polygons.clear()
        self._full_points = 0
"""

OLD_HOVER = """                if entity.is_point:
                    self._draw_point(painter, entity, 6.0)
                else:
                    polygon = self._full_polygon(entity)
                    if polygon is not None:
                        painter.drawPolyline(polygon)
"""
NEW_HOVER = """                if entity.is_point:
                    self._draw_point(painter, entity, 6.0)
                else:
                    polygon = self._highlight_polygon(entity)
                    if polygon is not None:
                        painter.drawPolyline(polygon)
"""

OLD_SEL = """            if entity.is_point:
                self._draw_point(painter, entity, 8.0)
            else:
                polygon = self._full_polygon(entity)
                if polygon is not None:
                    painter.drawPolyline(polygon)
            if is_current and not entity.is_point:
                self._draw_vertices(painter, entity)
"""
NEW_SEL = """            if entity.is_point:
                self._draw_point(painter, entity, 8.0)
            else:
                polygon = self._highlight_polygon(entity)
                if polygon is not None:
                    painter.drawPolyline(polygon)
            if is_current and not entity.is_point:
                self._draw_vertices(painter, entity, viewport)
"""

EDITS = [
    (OLD_CONST, NEW_CONST, "常量"),
    (OLD_INIT, NEW_INIT, "初始化"),
    (OLD_CLEAR, NEW_CLEAR, "清空缓存"),
    (OLD_FULL, NEW_FULL, "完整折线缓存"),
    (OLD_HOVER, NEW_HOVER, "悬停高亮"),
    (OLD_SEL, NEW_SEL, "选中高亮"),
    (OLD_VERTICES, NEW_VERTICES, "顶点标记"),
]


def main() -> int:
    with open(TARGET, "r", encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    if "_highlight_polygon" in text:
        print("已是新实现，无需修改")
        return 0
    for old, new, label in EDITS:
        if old not in text:
            print(f"[失败] 未找到 {label} 段")
            return 1
        text = text.replace(old, new, 1)
    # paint 里先算出 viewport，供顶点标记裁剪使用
    marker = "        wx0, wy0, wx1, wy1 = self.world_rect()\n"
    if marker not in text:
        print("[失败] 未找到 world_rect 调用")
        return 1
    old_use = "            self._draw_vertices(painter, entity, viewport)"
    if old_use in text:
        text = text.replace(old_use, "            self._draw_vertices(painter, entity, "
                                     "(wx0, wy0, wx1, wy1))", 1)
    with open(TARGET, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", "\r\n"))
    print("已更新 ui/canvas.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
