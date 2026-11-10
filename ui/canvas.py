"""自绘 CAD 画布：视口裁剪绘制、缩放平移、悬停与拾取、框选。

性能要点：实体折线在加载后缓存为局部坐标的 QPolygonF，绘制时只设置一次
QTransform，由 Qt 在 C++ 层完成坐标变换，避免逐点 Python 循环。
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QWidget

from core.geometry import point_segment_distance_2d
from core.model import DrawingModel, EntityRecord

from . import theme
from .geometry_cache import PreparedGeometry, build_geometry
from .snap_index import SnapIndex, build_snap_index, snap_world_radius

MIN_SCALE = 1e-9
MAX_SCALE = 1e7
PICK_PIXELS = 7.0
COARSE_SWITCH_ELEMENTS = 140000
# 选中/悬停高亮逐点描边的点数上限；超过就沿用底图那套抽稀折线
HIGHLIGHT_POINT_LIMIT = 20000
# 完整折线缓存：条目数与总点数双重上限，避免选很多长线时反复重建
FULL_POLYGON_CACHE = 128
FULL_POLYGON_BUDGET = 300000
# 选中要素的点序标注：序号 + 方向箭头，按屏幕像素间距抽稀
ORDER_LABEL_LIMIT = 60
ORDER_LABEL_MIN_PX = 26.0
ORDER_ARROW_LIMIT = 45
ORDER_ARROW_MIN_PX = 55.0
ORDER_SCAN_LIMIT = 20000
# 点选模式：吸附半径、端点标记大小与上限、呼吸动画节奏
SNAP_PIXELS = 12.0
SNAP_MARKER_HALF_PX = 3.6
SNAP_MARKER_LIMIT = 20000
SNAP_MARKER_DENSE = 4000
SNAP_MARGIN_RATIO = 0.5
PICK_LABEL_LIMIT = 60
PICK_LABEL_MIN_PX = 22.0
BREATH_INTERVAL_MS = 45
BREATH_STEP = 0.26

TYPE_LABELS = {
    "LINE": "直线",
    "LWPOLYLINE": "轻量多段线",
    "POLYLINE_2D": "二维多段线",
    "POLYLINE_3D": "三维多段线",
    "ARC": "圆弧",
    "CIRCLE": "圆",
    "POINT": "点",
    "PICK": "点选路径",
}


class CadCanvas(QWidget):
    entityPicked = Signal(int, bool)          # handle, 是否累加
    boxSelected = Signal(list, bool)          # handles, 是否累加
    emptyClicked = Signal(bool)               # 点击空白处
    cursorMoved = Signal(float, float)        # 世界坐标
    viewChanged = Signal(float)               # 当前比例
    hint = Signal(str)
    pointPicked = Signal(object, int, int)    # (x, y, z), 句柄, 顶点下标
    pickCancelled = Signal()                  # 右键：撤销当前轮最后一个点
    roundFinished = Signal()                  # 空格：结束本轮，开始下一轮

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 240)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        self.model: DrawingModel | None = None
        self.index: GridIndex | None = None
        self.selected: set[int] = set()
        self.reversed: set[int] = set()
        self.allowed_types: set[str] | None = None
        # 多选模式：开着时单击即追加/取消，不必按 Ctrl/Shift
        self._additive_mode = False
        self.hover_handle: int | None = None
        self.current_handle: int | None = None
        # 选择模式：line = 整条线，point = 端点逐点
        self.mode = "line"
        self.pick_rounds: list[list] = []
        self.pick_current = -1
        self.pick_hover: tuple[float, float, float, int, int] | None = None
        self._snap: SnapIndex | None = None
        self._snap_path: QPainterPath | None = None
        self._snap_rect: tuple[float, float, float, float] | None = None
        self._snap_scale = 0.0
        self._match_handle: int | None = None
        self._breath_phase = 0.0
        self._snap_warned = False
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(BREATH_INTERVAL_MS)
        self._breath_timer.timeout.connect(self._on_breath)

        self.scale = 1.0
        self.pan = QPointF(0.0, 0.0)
        self._origin = (0.0, 0.0)
        self._polygons: dict[int, QPolygonF] = {}
        self._full_polygons: dict[int, QPolygonF] = {}
        self._full_points = 0
        self._polygons_coarse: dict[int, QPolygonF] = {}
        self._paths: dict[tuple[int, int, int], QPainterPath] = {}
        self._paths_coarse: dict[tuple[int, int, int], QPainterPath] = {}
        self._coarse_active = False
        self._paths_dirty = True

        self._panning = False
        self._pan_last = QPoint()
        self._press_pos: QPoint | None = None
        self._dragging = False
        self._rubber: QRect | None = None
        self._rubber_dir = 1
        self._space_down = False
        self._last_paint_ms = 0.0
        self._visible_count = 0
        self._pen_cache: dict[tuple[int, int, int, float], QPen] = {}

    # ------------------------------------------------------------ 数据
    def set_additive_mode(self, enabled: bool) -> None:
        """多选模式开关：开启后单击图纸里的线/点即追加或取消选中。"""
        self._additive_mode = bool(enabled)

    def set_model(self, model: DrawingModel | None,
                  prepared: PreparedGeometry | None = None) -> None:
        """接管模型。

        ``prepared`` 由加载线程通过 :func:`build_geometry` 预先算好，传入时本方法只做
        指针替换；未传时在主线程现算（供脚本/测试直接调用）。
        """
        self.model = model
        self.selected.clear()
        self.reversed.clear()
        self.hover_handle = None
        self.current_handle = None
        self.pick_rounds = []
        self.pick_current = -1
        self.pick_hover = None
        self._match_handle = None
        self._snap = None
        self._snap_path = None
        self._snap_rect = None
        self._breath_phase = 0.0
        self._snap_warned = False
        self._update_breath()
        self._polygons.clear()
        self._polygons_coarse.clear()
        self._full_polygons.clear()
        self._full_points = 0
        self._paths.clear()
        self._paths_coarse.clear()
        self._coarse_active = False
        self._paths_dirty = True
        if model is None or not model.entities:
            # 清空图纸：空间索引、视图与画笔缓存一并复位，避免残留引用拖住内存
            self.index = None
            self._origin = (0.0, 0.0)
            self.scale = 1.0
            self.pan = QPointF(0.0, 0.0)
            self._pen_cache.clear()
            self._full_points = 0
            self.update()
            return
        if prepared is None:
            prepared = build_geometry(model.entities,
                                      (model.origin[0], model.origin[1]), model.bbox)
        self._origin = prepared.origin
        self.index = prepared.index
        self._polygons = prepared.polygons
        self._polygons_coarse = prepared.coarse_polygons
        self._paths_dirty = True
        self._rebuild_paths()
        self.fit_view()

    def _rebuild_paths(self, coarse: bool | None = None) -> None:
        """把可见实体按颜色合并成少量 QPainterPath，降低每帧绘制调用数。"""
        if coarse is not None:
            self._coarse_active = coarse
        self._paths_dirty = False
        self._paths.clear()
        self._paths_coarse.clear()
        if self.model is None:
            return
        visible = self.model.visible_layers()
        allowed = self.allowed_types
        for handle, polygon in self._polygons.items():
            entity = self.model.get(handle)
            if entity is None or entity.layer not in visible:
                continue
            if allowed is not None and entity.dxftype not in allowed:
                continue
            path = self._paths.get(entity.color)
            if path is None:
                path = QPainterPath()
                path.addPolygon(polygon)
                self._paths[entity.color] = path
            else:
                path.addPolygon(polygon)
            coarse_polygon = self._polygons_coarse.get(handle)
            if coarse_polygon is not None:
                cpath = self._paths_coarse.get(entity.color)
                if cpath is None:
                    cpath = QPainterPath()
                    cpath.addPolygon(coarse_polygon)
                    self._paths_coarse[entity.color] = cpath
                else:
                    cpath.addPolygon(coarse_polygon)

    def set_selection(self, handles: set[int]) -> None:
        if handles != self.selected:
            self.selected = set(handles)
            self.update()

    def set_current(self, handle: int | None) -> None:
        self.current_handle = handle
        self.update()

    def set_reversed(self, handles: set[int]) -> None:
        """已反向的要素集合：高亮换成反向色，点序按新方向编号。"""
        new = set(handles)
        if new != self.reversed:
            self.reversed = new
            self.update()

    # ------------------------------------------------------------ 选择模式
    def set_mode(self, mode: str) -> None:
        """切换选择模式：line = 整条线选中，point = 端点逐点。"""
        mode = "point" if mode == "point" else "line"
        if mode == self.mode:
            return
        self.mode = mode
        self.hover_handle = None
        self.pick_hover = None
        self.pick_rounds = []
        self.pick_current = -1
        self._match_handle = None
        self._snap = None
        self._snap_path = None
        self._snap_rect = None
        self._snap_warned = False
        self._press_pos = None
        self._dragging = False
        self._rubber = None
        self._space_down = False
        if mode == "point":
            self.setCursor(Qt.CrossCursor)
            self.setFocus()
        else:
            self.setCursor(Qt.ArrowCursor)
        self._update_breath()
        self.update()

    def set_pick_state(self, rounds: list[list], current_index: int,
                       match_handle: int | None) -> None:
        """接管点选结果：各轮的端点序列、当前轮下标、与已有线重合的句柄。"""
        self.pick_rounds = [list(block) for block in rounds]
        self.pick_current = current_index
        if match_handle != self._match_handle:
            self._match_handle = match_handle
            self._breath_phase = 0.0
        self._update_breath()
        self.update()

    def _update_breath(self) -> None:
        """只有「点选序列与图纸里的线重合」时才跑呼吸动画，避免常态耗电。"""
        active = self.mode == "point" and self._match_handle is not None
        if active:
            if not self._breath_timer.isActive():
                self._breath_timer.start()
        else:
            if self._breath_timer.isActive():
                self._breath_timer.stop()
            self._breath_phase = 0.0

    def _on_breath(self) -> None:
        self._breath_phase = (self._breath_phase + BREATH_STEP) % (math.pi * 2.0)
        self.update()

    def _breath_color(self) -> QColor:
        """由暗到明再到暗循环，给「与已有线重合」的虚线做呼吸提示。"""
        dark = QColor(theme.MATCH_DARK)
        bright = QColor(theme.MATCH_BRIGHT)
        ratio = 0.5 - 0.5 * math.cos(self._breath_phase)
        return QColor(
            int(dark.red() + (bright.red() - dark.red()) * ratio),
            int(dark.green() + (bright.green() - dark.green()) * ratio),
            int(dark.blue() + (bright.blue() - dark.blue()) * ratio),
        )

    def _full_polygon(self, entity: EntityRecord) -> QPolygonF | None:
        """完整折线（局部坐标），带 LRU + 总点数预算的缓存。"""
        # 命中时重新插入一次，把该条目挪到末尾（dict 保持插入序 = LRU 顺序）
        cached = self._full_polygons.pop(entity.handle, None)
        if cached is not None:
            self._full_polygons[entity.handle] = cached
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
            old_handle = next(iter(self._full_polygons))
            old_polygon = self._full_polygons.pop(old_handle)
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

    def invalidate(self) -> None:
        self._paths_dirty = True
        self._snap = None
        self._snap_path = None
        self._snap_rect = None
        self._snap_warned = False
        self.update()

    def fit_view(self) -> None:
        if self.model is None or not self.model.entities:
            self.update()
            return
        x0, y0, x1, y1 = self.model.bbox
        span_x = max(x1 - x0, 1e-6)
        span_y = max(y1 - y0, 1e-6)
        w = max(self.width(), 100)
        h = max(self.height(), 100)
        self.scale = min((w * 0.9) / span_x, (h * 0.9) / span_y)
        self.scale = max(MIN_SCALE, min(MAX_SCALE, self.scale))
        self.pan = QPointF(0.0, 0.0)
        self.pick_hover = None
        self.viewChanged.emit(self.scale)
        self.update()

    def center_on(self, handle: int) -> None:
        if self.model is None:
            return
        entity = self.model.get(handle)
        if entity is None:
            return
        x0, y0, x1, y1 = entity.bbox
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        sx = (cx - self._origin[0]) * self.scale
        sy = (cy - self._origin[1]) * self.scale
        self.pan = QPointF(-sx, sy)
        self.update()

    def center_on_bbox(self, bbox: tuple[float, float, float, float]) -> None:
        """把某个包围盒居中（点选块没有真实句柄，用包围盒定位）。"""
        if self.model is None:
            return
        x0, y0, x1, y1 = bbox
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        self.pan = QPointF(-(cx - self._origin[0]) * self.scale,
                           (cy - self._origin[1]) * self.scale)
        self.pick_hover = None
        self.update()

    def zoom_by(self, factor: float, anchor: QPoint | None = None) -> None:
        if self.model is None:
            return
        if anchor is None:
            anchor = QPoint(self.width() // 2, self.height() // 2)
        before = self.to_world(anchor)
        new_scale = max(MIN_SCALE, min(MAX_SCALE, self.scale * factor))
        if new_scale == self.scale:
            return
        self.scale = new_scale
        self._anchor_to(before, anchor)
        if self.mode == "point":
            self.pick_hover = None
        self.viewChanged.emit(self.scale)
        self.update()

    def _anchor_to(self, world: tuple[float, float], screen: QPoint) -> None:
        sx = (world[0] - self._origin[0]) * self.scale
        sy = (world[1] - self._origin[1]) * self.scale
        self.pan = QPointF(screen.x() - sx - self.width() / 2.0,
                           screen.y() - self.height() / 2.0 + sy)

    # ------------------------------------------------------------ 坐标变换
    def _transform(self) -> QTransform:
        t = QTransform()
        t.translate(self.width() / 2.0 + self.pan.x(),
                    self.height() / 2.0 + self.pan.y())
        t.scale(self.scale, -self.scale)
        return t

    def to_screen(self, x: float, y: float) -> QPointF:
        cx = self.width() / 2.0 + self.pan.x()
        cy = self.height() / 2.0 + self.pan.y()
        return QPointF((x - self._origin[0]) * self.scale + cx,
                       cy - (y - self._origin[1]) * self.scale)

    def to_world(self, pos: QPoint) -> tuple[float, float]:
        cx = self.width() / 2.0 + self.pan.x()
        cy = self.height() / 2.0 + self.pan.y()
        x = (pos.x() - cx) / self.scale + self._origin[0]
        y = (cy - pos.y()) / self.scale + self._origin[1]
        return (x, y)

    def world_rect(self) -> tuple[float, float, float, float]:
        p0 = self.to_world(QPoint(0, 0))
        p1 = self.to_world(QPoint(self.width(), self.height()))
        return (min(p0[0], p1[0]), min(p0[1], p1[1]),
                max(p0[0], p1[0]), max(p0[1], p1[1]))

    # ------------------------------------------------------------ 绘制
    def _pen(self, rgb: tuple[int, int, int], width: float = 1.0) -> QPen:
        key = (rgb[0], rgb[1], rgb[2], round(width, 3))
        pen = self._pen_cache.get(key)
        if pen is None:
            pen = QPen(QColor(*rgb))
            pen.setCosmetic(True)
            pen.setWidthF(width)
            pen.setCapStyle(Qt.FlatCap)
            pen.setJoinStyle(Qt.MiterJoin)
            self._pen_cache[key] = pen
        return pen

    def paintEvent(self, event) -> None:  # noqa: N802
        started = time.perf_counter()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG))
        if self.model is None:
            painter.setPen(QColor(theme.MUTED))
            painter.setFont(QFont("Microsoft YaHei UI", 11))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "打开 DWG 图纸开始\n也可以把 .dwg 文件拖到窗口")
            painter.end()
            return
        if self.index is None:
            painter.end()
            return

        wx0, wy0, wx1, wy1 = self.world_rect()
        candidates = self.index.query_rect(wx0, wy0, wx1, wy1)
        visible_layers = self.model.visible_layers()

        selected: list[EntityRecord] = []
        normal: list[EntityRecord] = []
        get = self.model.get
        for handle in candidates:
            entity = get(handle)
            if entity is None or entity.layer not in visible_layers:
                continue
            if self.allowed_types is not None and entity.dxftype not in self.allowed_types:
                continue
            if handle in self.selected:
                selected.append(entity)
            else:
                normal.append(entity)

        self._visible_count = len(normal) + len(selected)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setTransform(self._transform())

        estimate = 0
        for entity in normal:
            if not entity.is_point:
                polygon = self._polygons.get(entity.handle)
                if polygon is not None:
                    estimate += polygon.size()
        # 迟滞阈值，避免缩放时在两级细节之间反复重建
        threshold = COARSE_SWITCH_ELEMENTS * (0.7 if self._coarse_active else 1.0)
        want_coarse = estimate > threshold
        if self._paths_dirty or want_coarse != self._coarse_active:
            self._rebuild_paths(want_coarse)
        paths = self._paths_coarse if want_coarse else self._paths
        for color, path in paths.items():
            painter.setPen(self._pen(color, 0.0))
            painter.drawPath(path)

        if self.hover_handle is not None and self.hover_handle not in self.selected:
            entity = get(self.hover_handle)
            if entity is not None and entity.layer in visible_layers:
                hover_pen = QPen(QColor(theme.HOVER), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                hover_pen.setCosmetic(True)
                painter.setPen(hover_pen)
                if entity.is_point:
                    self._draw_point(painter, entity, 6.0)
                else:
                    polygon = self._highlight_polygon(entity)
                    if polygon is not None:
                        painter.drawPolyline(polygon)

        for entity in selected:
            is_current = entity.handle == self.current_handle
            reversed_order = entity.handle in self.reversed
            color = QColor(theme.REVERSE if reversed_order else theme.SELECT)
            pen = QPen(color, 3.0 if is_current else 2.0,
                       Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            pen.setCosmetic(True)
            painter.setPen(pen)
            if entity.is_point:
                self._draw_point(painter, entity, 8.0)
            else:
                polygon = self._highlight_polygon(entity)
                if polygon is not None:
                    painter.drawPolyline(polygon)
            if is_current and not entity.is_point:
                self._draw_order(painter, entity, reversed_order)

        if self.mode == "point":
            self._draw_point_mode(painter)

        # 以下内容在屏幕坐标系绘制
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._rubber is not None:
            color = QColor(theme.ACCENT if self._rubber_dir > 0 else "#ff9f43")
            painter.setPen(QPen(color, 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 40)))
            painter.drawRect(self._rubber)
            painter.setBrush(Qt.NoBrush)

        # 点实体在屏幕坐标系绘制，保证任何缩放下都可见
        painter.setRenderHint(QPainter.Antialiasing, False)
        for entity in normal:
            if entity.is_point:
                painter.setPen(self._pen(entity.color, 0.0))
                self._draw_point(painter, entity, 4.0)
        for entity in selected:
            if entity.is_point:
                painter.setPen(QPen(QColor(theme.SELECT), 2.0))
                self._draw_point(painter, entity, 7.0)

        self._draw_hud(painter)
        painter.end()
        self._last_paint_ms = (time.perf_counter() - started) * 1000.0

    def _draw_point(self, painter: QPainter, entity: EntityRecord, radius: float) -> None:
        p = entity.points[0]
        pos = self.to_screen(p[0], p[1])
        painter.drawLine(QPointF(pos.x() - radius, pos.y()),
                         QPointF(pos.x() + radius, pos.y()))
        painter.drawLine(QPointF(pos.x(), pos.y() - radius),
                         QPointF(pos.x(), pos.y() + radius))

    def _draw_order(self, painter: QPainter, entity: EntityRecord,
                    reversed_order: bool) -> None:
        """在当前要素上标出点序：顶点序号 + 沿线的方向箭头。

        序号超过 ``ORDER_LABEL_LIMIT`` 时按屏幕像素间距抽稀，只保留能看清的那些；
        箭头同理。反向时编号从 n 往 1 数，箭头指向另一端，与导出顺序一致。
        """
        points = entity.points
        total = len(points)
        if total < 2:
            return
        stride = 1 if total <= ORDER_SCAN_LIMIT else max(1, total // ORDER_SCAN_LIMIT)
        screen = self._screen_points(points, stride)
        if len(screen) < 2:
            return
        color = QColor(theme.REVERSE if reversed_order else theme.SELECT)

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        for _, sx, sy in (screen[0], screen[-1]):
            painter.drawEllipse(QPointF(sx, sy), 3.4, 3.4)

        # 方向箭头：闭合线补上最后一条闭合段
        loop = screen + [screen[0]] if entity.closed and len(screen) > 2 else screen
        last_arrow: tuple[float, float] | None = None
        arrows = 0
        for (_, ax, ay), (_, bx, by) in zip(loop, loop[1:]):
            dx, dy = bx - ax, by - ay
            if reversed_order:
                dx, dy = -dx, -dy
            if math.hypot(dx, dy) < 2.0:
                continue
            mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
            if last_arrow is not None and math.hypot(
                    mx - last_arrow[0], my - last_arrow[1]) < ORDER_ARROW_MIN_PX:
                continue
            last_arrow = (mx, my)
            self._draw_arrow(painter, mx, my, math.atan2(dy, dx))
            arrows += 1
            if arrows >= ORDER_ARROW_LIMIT:
                break

        font = QFont("Microsoft YaHei UI", 8)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        chosen: list[tuple[int, float, float]] = []
        last_label: tuple[float, float] | None = None
        for index, sx, sy in screen:
            if last_label is not None and math.hypot(
                    sx - last_label[0], sy - last_label[1]) < ORDER_LABEL_MIN_PX:
                continue
            chosen.append((index, sx, sy))
            last_label = (sx, sy)
            if len(chosen) >= ORDER_LABEL_LIMIT:
                break
        if chosen and chosen[-1][0] != total - 1 and len(chosen) < ORDER_LABEL_LIMIT:
            chosen.append(screen[-1])  # 末点无论多挤都要标出来
        for index, sx, sy in chosen:
            number = total - index if reversed_order else index + 1
            text = str(number)
            width = metrics.horizontalAdvance(text) + 8
            height = metrics.height()
            rect = QRectF(sx + 5.0, sy - height - 3.0, width, height)
            if rect.right() > self.width() - 2:
                rect.moveLeft(sx - width - 5.0)
            painter.setPen(QPen(color, 1))
            painter.setBrush(QBrush(QColor(15, 20, 25, 210)))
            painter.drawRoundedRect(rect, 2.5, 2.5)
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def _screen_points(self, points, stride: int) -> list[tuple[int, float, float]]:
        """把顶点换算成屏幕坐标；步长大于 1 时只取抽样点与末点。"""
        ox, oy = self._origin
        scale = self.scale
        cx = self.width() / 2.0 + self.pan.x()
        cy = self.height() / 2.0 + self.pan.y()
        result: list[tuple[int, float, float]] = []
        last = len(points) - 1
        for index in range(0, len(points), stride):
            p = points[index]
            result.append((index, (p[0] - ox) * scale + cx, cy - (p[1] - oy) * scale))
        if result and result[-1][0] != last:
            p = points[last]
            result.append((last, (p[0] - ox) * scale + cx, cy - (p[1] - oy) * scale))
        return result

    @staticmethod
    def _draw_arrow(painter: QPainter, x: float, y: float, angle: float) -> None:
        size = 6.5
        tip = QPointF(x + math.cos(angle) * size, y + math.sin(angle) * size)
        left = QPointF(x - math.cos(angle - 0.55) * size,
                       y - math.sin(angle - 0.55) * size)
        right = QPointF(x - math.cos(angle + 0.55) * size,
                        y - math.sin(angle + 0.55) * size)
        painter.drawPolygon(QPolygonF([tip, left, right]))

    def _draw_hud(self, painter: QPainter) -> None:
        painter.resetTransform()
        painter.setPen(QColor(theme.MUTED))
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        text = (f"可见实体 {self._visible_count}   比例 1:{1 / self.scale:,.0f}   "
                f"绘制 {self._last_paint_ms:.1f} ms")
        painter.drawText(12, self.height() - 10, text)
        if self.mode == "point":
            snaps = len(self._snap.points) if self._snap is not None else 0
            picked = sum(len(block) for block in self.pick_rounds)
            painter.setPen(QColor(theme.PICK_HOVER))
            painter.drawText(12, self.height() - 26,
                             f"点选模式：端点 {snaps}  已选 {picked} 点   "
                             "左键加点 · 右键撤点 · 空格结束本轮 · Esc 取消本轮")

    # ------------------------------------------------------------ 点选端点
    def _ensure_snap(self, force: bool = False) -> None:
        """按当前视口准备端点索引；视口仍在缓存范围内时直接复用。"""
        if self.mode != "point" or self.model is None or self.index is None:
            self._snap = None
            self._snap_path = None
            return
        view = self.world_rect()
        margin_x = max(view[2] - view[0], 1e-9) * SNAP_MARGIN_RATIO
        margin_y = max(view[3] - view[1], 1e-9) * SNAP_MARGIN_RATIO
        rect = (view[0] - margin_x, view[1] - margin_y,
                view[2] + margin_x, view[3] + margin_y)
        cached = self._snap_rect
        if (not force and self._snap is not None and self._snap_scale == self.scale
                and cached is not None
                and cached[0] <= view[0] and cached[1] <= view[1]
                and cached[2] >= view[2] and cached[3] >= view[3]):
            return
        radius = snap_world_radius(SNAP_PIXELS, self.scale)
        candidates = self.index.query_rect(*rect)
        snap = build_snap_index(candidates, self.model, rect, radius, self.allowed_types)
        self._snap = snap
        self._snap_rect = rect
        self._snap_scale = self.scale
        self._snap_path = self._build_snap_path(snap)
        if snap.truncated:
            # 平移/缩放会反复重建，提示只弹一次，避免刷屏
            if not self._snap_warned:
                self._snap_warned = True
                self.hint.emit(
                    f"视口内端点过多：只载入 {len(snap.points)} 个端点，请放大后再点选")
        else:
            self._snap_warned = False

    def _build_snap_path(self, snap) -> QPainterPath:
        """端点小十字合并成一条路径，每帧一次 drawPath 画完。"""
        path = QPainterPath()
        points = snap.points
        if not points:
            return path
        step = 1 if len(points) <= SNAP_MARKER_LIMIT else \
            (len(points) + SNAP_MARKER_LIMIT - 1) // SNAP_MARKER_LIMIT
        # 端点很密时缩小十字，避免整张图被标记糊住；放大后自动恢复
        half_px = SNAP_MARKER_HALF_PX if len(points) <= SNAP_MARKER_DENSE else 2.3
        half = half_px / self.scale if self.scale > 0 else half_px
        ox, oy = self._origin
        for item in points[::step]:
            x = item[0] - ox
            y = item[1] - oy
            path.moveTo(x - half, y)
            path.lineTo(x + half, y)
            path.moveTo(x, y - half)
            path.lineTo(x, y + half)
        return path

    def _snap_nearest(self, pos: QPoint):
        """光标附近最近的端点 ``(x, y, z, handle, 顶点下标)``。"""
        if self.mode != "point" or self.model is None:
            return None
        self._ensure_snap()
        if self._snap is None:
            return None
        wx, wy = self.to_world(pos)
        found = self._snap.nearest(wx, wy, snap_world_radius(SNAP_PIXELS, self.scale))
        if found is None:
            return None
        entity = self.model.get(found[2])
        if entity is None or found[3] >= len(entity.points):
            return None
        return (found[0], found[1], entity.points[found[3]][2], found[2], found[3])

    def _matched_block_index(self) -> int | None:
        """当前呼吸提示对应哪一轮点选（与 PickModel 的选取规则保持一致）。"""
        if self._match_handle is None:
            return None
        if 0 <= self.pick_current < len(self.pick_rounds) \
                and len(self.pick_rounds[self.pick_current]) >= 2:
            return self.pick_current
        for index in range(len(self.pick_rounds) - 1, -1, -1):
            if len(self.pick_rounds[index]) >= 2:
                return index
        return None

    def _draw_point_mode(self, painter: QPainter) -> None:
        """点选模式的叠加层：端点标记、点选连线与编号、重合呼吸虚线。"""
        self._ensure_snap()
        painter.setRenderHint(QPainter.Antialiasing, False)
        if self._snap_path is not None and not self._snap_path.isEmpty():
            painter.setPen(QPen(QColor(theme.SNAP), 0))
            painter.drawPath(self._snap_path)
        if self._match_handle is not None and self.model is not None:
            matched = self.model.get(self._match_handle)
            if matched is not None and not matched.is_point:
                polygon = self._highlight_polygon(matched)
                if polygon is not None:
                    pen = QPen(self._breath_color(), 3.0, Qt.DashLine,
                               Qt.RoundCap, Qt.RoundJoin)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.drawPolyline(polygon)

        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        matched_block = self._matched_block_index()
        for index, block in enumerate(self.pick_rounds):
            if not block:
                continue
            is_current = index == self.pick_current
            if index == matched_block:
                color = self._breath_color()
            elif is_current:
                color = QColor(theme.SELECT)
            else:
                color = QColor(theme.PICK_DONE)
            screen = [self.to_screen(point[0], point[1]) for point in block]
            if len(screen) >= 2:
                pen = QPen(color, 2.4 if is_current else 1.6, Qt.DashLine,
                           Qt.RoundCap, Qt.RoundJoin)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPolyline(QPolygonF(screen))
            painter.setBrush(QBrush(QColor(theme.BG)))
            painter.setPen(QPen(color, 1.6))
            for item in screen:
                painter.drawEllipse(item, 3.4, 3.4)
            if is_current:
                self._draw_pick_labels(painter, screen, color)
        painter.setBrush(Qt.NoBrush)

        hover = self.pick_hover
        if hover is not None:
            pos = self.to_screen(hover[0], hover[1])
            if 0 <= self.pick_current < len(self.pick_rounds) \
                    and self.pick_rounds[self.pick_current]:
                last = self.pick_rounds[self.pick_current][-1]
                start = self.to_screen(last[0], last[1])
                pen = QPen(QColor(theme.PICK_HOVER), 1.2, Qt.DotLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawLine(start, pos)
            painter.setPen(QPen(QColor(theme.PICK_HOVER), 2.0))
            painter.drawEllipse(pos, 6.5, 6.5)
            painter.drawLine(QPointF(pos.x() - 9, pos.y()), QPointF(pos.x() + 9, pos.y()))
            painter.drawLine(QPointF(pos.x(), pos.y() - 9), QPointF(pos.x(), pos.y() + 9))
        painter.setBrush(Qt.NoBrush)

    def _draw_pick_labels(self, painter: QPainter, screen, color: QColor) -> None:
        """给当前轮的点标序号；挤在一起时按屏幕间距抽稀。"""
        font = QFont("Microsoft YaHei UI", 8)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        last: tuple[float, float] | None = None
        drawn = 0
        for index, pos in enumerate(screen):
            if last is not None and math.hypot(pos.x() - last[0],
                                               pos.y() - last[1]) < PICK_LABEL_MIN_PX:
                continue
            text = str(index + 1)
            rect = QRectF(pos.x() + 6.0, pos.y() - metrics.height() - 2.0,
                          metrics.horizontalAdvance(text) + 8, metrics.height())
            if rect.right() > self.width() - 2:
                rect.moveLeft(pos.x() - rect.width() - 6.0)
            painter.setPen(QPen(color, 1))
            painter.setBrush(QBrush(QColor(15, 20, 25, 210)))
            painter.drawRoundedRect(rect, 2.5, 2.5)
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignCenter, text)
            last = (pos.x(), pos.y())
            drawn += 1
            if drawn >= PICK_LABEL_LIMIT:
                break
        painter.setBrush(Qt.NoBrush)

    # ------------------------------------------------------------ 拾取
    def pick(self, pos: QPoint) -> int | None:
        if self.model is None or self.index is None:
            return None
        wx, wy = self.to_world(pos)
        tol = PICK_PIXELS / self.scale
        candidates = self.index.query_point(wx, wy, tol)
        visible = self.model.visible_layers()
        best_handle = None
        best_dist = tol
        for handle in candidates:
            entity = self.model.get(handle)
            if entity is None or entity.layer not in visible:
                continue
            if self.allowed_types is not None and entity.dxftype not in self.allowed_types:
                continue
            # 先用包围盒做一次廉价排除，避免在超大折线上逐段算距离
            bx0, by0, bx1, by1 = entity.bbox
            if wx < bx0 - tol or wx > bx1 + tol or wy < by0 - tol or wy > by1 + tol:
                continue
            if entity.is_point:
                dist = math.hypot(entity.points[0][0] - wx, entity.points[0][1] - wy)
            else:
                points = entity.render_points
                dist = best_dist
                for a, b in zip(points, points[1:]):
                    d = point_segment_distance_2d((wx, wy, 0.0), a, b)
                    if d < dist:
                        dist = d
                if len(points) == 1:
                    dist = math.hypot(points[0][0] - wx, points[0][1] - wy)
            if dist < best_dist:
                best_dist = dist
                best_handle = handle
        return best_handle

    def handles_in_rect(self, rect: QRect, window: bool = False) -> list[int]:
        """框选命中的句柄。

        window=True 为窗口选择（实体整体落在框内才算命中，对应从左往右拖框）；
        window=False 为交叉选择（包围盒与框相交即命中，对应从右往左拖框）。
        """
        if self.model is None or self.index is None:
            return []
        p0 = self.to_world(rect.topLeft())
        p1 = self.to_world(rect.bottomRight())
        wx0, wx1 = min(p0[0], p1[0]), max(p0[0], p1[0])
        wy0, wy1 = min(p0[1], p1[1]), max(p0[1], p1[1])
        candidates = self.index.query_rect(wx0, wy0, wx1, wy1)
        visible = self.model.visible_layers()
        result: list[int] = []
        for handle in candidates:
            entity = self.model.get(handle)
            if entity is None or entity.layer not in visible:
                continue
            if self.allowed_types is not None and entity.dxftype not in self.allowed_types:
                continue
            if window:
                x0, y0, x1, y1 = entity.bbox
                if x0 < wx0 or x1 > wx1 or y0 < wy0 or y1 > wy1:
                    continue
            result.append(handle)
        return result

    # ------------------------------------------------------------ 事件
    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.model is None:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.18 if delta > 0 else 1 / 1.18
        self.zoom_by(factor, event.position().toPoint())
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.model is None:
            return
        if self.mode == "point":
            if event.button() == Qt.RightButton:
                # 点选模式下右键不再平移，改为撤销刚才点下的那个点
                self.pickCancelled.emit()
                event.accept()
                return
            if event.button() == Qt.MiddleButton or \
                    (event.button() == Qt.LeftButton and self._space_down):
                self._panning = True
                self._pan_last = event.position().toPoint()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
            if event.button() == Qt.LeftButton:
                self._press_pos = event.position().toPoint()
                self._dragging = False
                event.accept()
            return
        if event.button() in (Qt.MiddleButton, Qt.RightButton) or \
                (event.button() == Qt.LeftButton and self._space_down):
            self._panning = True
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._panning:
            delta = pos - self._pan_last
            self._pan_last = pos
            self.pan += QPointF(delta.x(), delta.y())
            self.update()
            return
        if self.mode == "point":
            if self._press_pos is not None and event.buttons() & Qt.LeftButton:
                if abs(pos.x() - self._press_pos.x()) > 3 or \
                        abs(pos.y() - self._press_pos.y()) > 3:
                    # 左键拖动用于平移，避免手抖时误加点
                    self._panning = True
                    self._pan_last = pos
                    self._press_pos = None
                    self.setCursor(Qt.ClosedHandCursor)
                    return
            hover = self._snap_nearest(pos)
            if hover is None:
                wx, wy = self.to_world(pos)
                self.cursorMoved.emit(wx, wy)
            else:
                self.cursorMoved.emit(hover[0], hover[1])
            if hover != self.pick_hover:
                self.pick_hover = hover
                self.update()
            return
        wx, wy = self.to_world(pos)
        self.cursorMoved.emit(wx, wy)
        if self._press_pos is not None and event.buttons() & Qt.LeftButton:
            if abs(pos.x() - self._press_pos.x()) > 3 or abs(pos.y() - self._press_pos.y()) > 3:
                self._dragging = True
                self._rubber_dir = 1 if pos.x() >= self._press_pos.x() else -1
                self._rubber = QRect(self._press_pos, pos).normalized()
                self.update()
            return
        handle = self.pick(pos)
        if handle != self.hover_handle:
            self.hover_handle = handle
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CrossCursor if self.mode == "point" else Qt.ArrowCursor)
            return
        if self.mode == "point":
            if event.button() != Qt.LeftButton:
                return
            pos = event.position().toPoint()
            self._press_pos = None
            hover = self._snap_nearest(pos)
            if hover is None:
                self.hint.emit("附近没有端点：把鼠标移到线条的转折点上再单击")
            else:
                self.pointPicked.emit((hover[0], hover[1], hover[2]), hover[3], hover[4])
            self.update()
            return
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        additive = self._additive_mode or bool(
            event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        if self._dragging and self._rubber is not None:
            rect = self._rubber
            handles = self.handles_in_rect(rect, window=self._rubber_dir > 0)
            self._rubber = None
            self._dragging = False
            self._press_pos = None
            if handles:
                self.boxSelected.emit(handles, additive)
            elif not additive:
                self.emptyClicked.emit(False)
            self.update()
            return
        self._press_pos = None
        self._rubber = None
        handle = self.pick(pos)
        if handle is not None:
            self.entityPicked.emit(handle, additive)
        else:
            self.emptyClicked.emit(additive)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.model is None or self.mode == "point":
            return
        if event.button() == Qt.LeftButton:
            handle = self.pick(event.position().toPoint())
            if handle is not None:
                self.center_on(handle)
                self.zoom_by(2.0, event.position().toPoint())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.mode == "point":
            if event.key() == Qt.Key_Space:
                # 空格：结束当前轮，开始下一轮点选
                self.roundFinished.emit()
                event.accept()
                return
            if event.key() == Qt.Key_F:
                self.fit_view()
                event.accept()
                return
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Space:
            self._space_down = True
            self.setCursor(Qt.OpenHandCursor)
        elif event.key() == Qt.Key_F:
            self.fit_view()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if self.mode == "point":
            super().keyReleaseEvent(event)
            return
        if event.key() == Qt.Key_Space:
            self._space_down = False
            self.setCursor(Qt.ArrowCursor)
        super().keyReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        changed = self.hover_handle is not None or self.pick_hover is not None
        if self.hover_handle is not None:
            self.hover_handle = None
        self.pick_hover = None
        if changed:
            self.update()
        super().leaveEvent(event)
