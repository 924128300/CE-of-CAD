"""给画布加入点选模式：模式切换、端点吸附、右键撤点、空格换轮、呼吸提示。

一次性补丁脚本，按锚点精确替换；锚点缺失直接报错，避免改错位置。
"""
from __future__ import annotations

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "ui", "canvas.py")


def apply(text: str, patches: list[tuple[str, str]]) -> str:
    for index, (old, new) in enumerate(patches, start=1):
        if old not in text:
            raise SystemExit(f"锚点 {index} 未找到：{old[:60]!r}")
        if text.count(old) != 1:
            raise SystemExit(f"锚点 {index} 不唯一：{old[:60]!r}")
        text = text.replace(old, new)
    return text


SIGNALS_OLD = '''class CadCanvas(QWidget):
    entityPicked = Signal(int, bool)          # handle, 是否累加
    boxSelected = Signal(list, bool)          # handles, 是否累加
    emptyClicked = Signal(bool)               # 点击空白处
    cursorMoved = Signal(float, float)        # 世界坐标
    viewChanged = Signal(float)               # 当前比例
    hint = Signal(str)
'''

SIGNALS_NEW = '''class CadCanvas(QWidget):
    entityPicked = Signal(int, bool)          # handle, 是否累加
    boxSelected = Signal(list, bool)          # handles, 是否累加
    emptyClicked = Signal(bool)               # 点击空白处
    cursorMoved = Signal(float, float)        # 世界坐标
    viewChanged = Signal(float)               # 当前比例
    hint = Signal(str)
    pointPicked = Signal(object, int, int)    # (x, y, z), 句柄, 顶点下标
    pickCancelled = Signal()                  # 右键：撤销当前轮最后一个点
    roundFinished = Signal()                  # 空格：结束本轮，开始下一轮
'''

INIT_OLD = '''        self.hover_handle: int | None = None
        self.current_handle: int | None = None
'''

INIT_NEW = '''        self.hover_handle: int | None = None
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
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(BREATH_INTERVAL_MS)
        self._breath_timer.timeout.connect(self._on_breath)
'''

MODE_METHODS = '''    # ------------------------------------------------------------ 选择模式
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

'''

SNAP_SECTION = '''    # ------------------------------------------------------------ 点选端点
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
            self.hint.emit(
                f"视口内端点过多：只载入前 {len(snap.points)} 个端点，请放大后再点选")

    def _build_snap_path(self, snap) -> QPainterPath:
        """端点小十字合并成一条路径，每帧一次 drawPath 画完。"""
        path = QPainterPath()
        points = snap.points
        if not points:
            return path
        step = 1 if len(points) <= SNAP_MARKER_LIMIT else \\
            (len(points) + SNAP_MARKER_LIMIT - 1) // SNAP_MARKER_LIMIT
        half = SNAP_MARKER_HALF_PX / self.scale if self.scale > 0 else SNAP_MARKER_HALF_PX
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
        if 0 <= self.pick_current < len(self.pick_rounds) \\
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
            if 0 <= self.pick_current < len(self.pick_rounds) \\
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

'''

MOUSE_OLD = '''    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.model is None:
            return
        if event.button() in (Qt.MiddleButton, Qt.RightButton) or \\
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
        wx, wy = self.to_world(pos)
        self.cursorMoved.emit(wx, wy)
        if self._panning:
            delta = pos - self._pan_last
            self._pan_last = pos
            self.pan += QPointF(delta.x(), delta.y())
            self.update()
            return
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
            self.setCursor(Qt.ArrowCursor)
            return
        if event.button() != Qt.LeftButton:
            return
'''

MOUSE_NEW = '''    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.model is None:
            return
        if self.mode == "point":
            if event.button() == Qt.RightButton:
                # 点选模式下右键不再平移，改为撤销刚才点下的那个点
                self.pickCancelled.emit()
                event.accept()
                return
            if event.button() == Qt.MiddleButton or \\
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
        if event.button() in (Qt.MiddleButton, Qt.RightButton) or \\
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
                if abs(pos.x() - self._press_pos.x()) > 3 or \\
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
'''

KEY_OLD = '''    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space:
            self._space_down = True
            self.setCursor(Qt.OpenHandCursor)
        elif event.key() == Qt.Key_F:
            self.fit_view()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space:
            self._space_down = False
            self.setCursor(Qt.ArrowCursor)
        super().keyReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.hover_handle is not None:
            self.hover_handle = None
            self.update()
        super().leaveEvent(event)
'''

KEY_NEW = '''    def keyPressEvent(self, event) -> None:  # noqa: N802
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
'''


def main() -> None:
    with io.open(TARGET, encoding="utf-8", newline="") as handle:
        raw = handle.read()
    # 仓库里是 CRLF：先归一成 LF 再按锚点替换，写回时还原，避免半新半旧
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n") if crlf else raw

    patches = [
        ('    "POINT": "点",\n}\n\n\nclass CadCanvas(QWidget):',
         '    "POINT": "点",\n    "PICK": "点选路径",\n}\n\n\nclass CadCanvas(QWidget):'),
        (SIGNALS_OLD, SIGNALS_NEW),
        (INIT_OLD, INIT_NEW),
        # set_model：换图时清掉点选状态与呼吸动画
        ('''        self.model = model
        self.selected.clear()
        self.reversed.clear()
        self.hover_handle = None
        self.current_handle = None
''',
         '''        self.model = model
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
        self._update_breath()
'''),
        # 在 set_reversed 之后插入模式方法与绘制方法
        ('''    def _full_polygon(self, entity: EntityRecord) -> QPolygonF | None:''',
         MODE_METHODS + '''    def _full_polygon(self, entity: EntityRecord) -> QPolygonF | None:'''),
        # invalidate：图层/类型变化后重新收集端点
        ('''    def invalidate(self) -> None:
        self._paths_dirty = True
        self.update()
''',
         '''    def invalidate(self) -> None:
        self._paths_dirty = True
        self._snap = None
        self._snap_path = None
        self._snap_rect = None
        self.update()
'''),
        # fit_view / zoom_by 后旧吸附缓存失效
        ('''        self.pan = QPointF(0.0, 0.0)
        self.viewChanged.emit(self.scale)
        self.update()
''',
         '''        self.pan = QPointF(0.0, 0.0)
        self.pick_hover = None
        self.viewChanged.emit(self.scale)
        self.update()
'''),
        ('''        self.scale = new_scale
        self._anchor_to(before, anchor)
        self.viewChanged.emit(self.scale)
        self.update()
''',
         '''        self.scale = new_scale
        self._anchor_to(before, anchor)
        if self.mode == "point":
            self.pick_hover = None
        self.viewChanged.emit(self.scale)
        self.update()
'''),
        # 绘制：选中要素之后叠加点选层
        ('''        # 以下内容在屏幕坐标系绘制
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
''',
         '''        if self.mode == "point":
            self._draw_point_mode(painter)

        # 以下内容在屏幕坐标系绘制
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
'''),
        # HUD 增加点选提示
        ('''        text = (f"可见实体 {self._visible_count}   比例 1:{1 / self.scale:,.0f}   "
                f"绘制 {self._last_paint_ms:.1f} ms")
        painter.drawText(12, self.height() - 10, text)
''',
         '''        text = (f"可见实体 {self._visible_count}   比例 1:{1 / self.scale:,.0f}   "
                f"绘制 {self._last_paint_ms:.1f} ms")
        painter.drawText(12, self.height() - 10, text)
        if self.mode == "point":
            snaps = len(self._snap.points) if self._snap is not None else 0
            picked = sum(len(block) for block in self.pick_rounds)
            painter.setPen(QColor(theme.PICK_HOVER))
            painter.drawText(12, self.height() - 26,
                             f"点选模式：端点 {snaps}（已载入）  已选 {picked} 点   "
                             "左键加点 · 右键撤点 · 空格结束本轮 · Esc 取消本轮")
'''),
        # 在拾取之前插入端点捕捉与点选绘制
        ('''    # ------------------------------------------------------------ 拾取
    def pick(self, pos: QPoint) -> int | None:''',
         SNAP_SECTION + '''    # ------------------------------------------------------------ 拾取
    def pick(self, pos: QPoint) -> int | None:'''),
        (MOUSE_OLD, MOUSE_NEW),
        (KEY_OLD, KEY_NEW),
        # 点选模式下双击不缩放，避免把两次单击当双击
        ('''    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.model is None:
            return
''',
         '''    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.model is None or self.mode == "point":
            return
'''),
        # 合成实体（点选块）用包围盒定位
        ('''    def zoom_by(self, factor: float, anchor: QPoint | None = None) -> None:''',
         '''    def center_on_bbox(self, bbox: tuple[float, float, float, float]) -> None:
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

    def zoom_by(self, factor: float, anchor: QPoint | None = None) -> None:'''),
    ]

    text = apply(text, patches)
    if crlf:
        text = text.replace("\n", "\r\n")
    with io.open(TARGET, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    print("canvas.py 已更新")


if __name__ == "__main__":
    main()
