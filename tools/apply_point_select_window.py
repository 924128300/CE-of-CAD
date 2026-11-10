"""主窗口接入点选模式：模式开关、点选交互、导出与撤销联动。

一次性补丁脚本，锚点缺失直接报错。
"""
from __future__ import annotations

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "ui", "main_window.py")


def apply(text: str, patches: list[tuple[str, str]]) -> str:
    for index, (old, new) in enumerate(patches, start=1):
        if text.count(old) != 1:
            raise SystemExit(f"锚点 {index} 匹配 {text.count(old)} 次：{old[:70]!r}")
        text = text.replace(old, new)
    return text


PATCHES = [
    # ---------------------------------------------------------------- 导入
    ('''from PySide6.QtGui import QAction, QDesktopServices, QKeySequence''',
     '''from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence'''),
    ('''from core.model import DrawingModel
from core.undo import SelectionHistory, SelectionModel''',
     '''from core.model import DrawingModel, EntityRecord
from core.pick_model import PickModel
from core.undo import SelectionHistory, SelectionModel'''),
    # ---------------------------------------------------------------- 状态
    ('''        self.model: DrawingModel | None = None
        self.selection = SelectionModel(self)
        self.history = SelectionHistory(self.selection, self)''',
     '''        self.model: DrawingModel | None = None
        self.selection = SelectionModel(self)
        self.history = SelectionHistory(self.selection, self)
        # 点选模式：按轮次记录端点，独立于整条线的选择集
        self.picks = PickModel()
        self._mode = "line"'''),
    # ---------------------------------------------------------------- 动作
    ('''        self.act_multi = QAction("多选", self)''',
     '''        self.act_mode_line = QAction("线选", self)
        self.act_mode_line.setCheckable(True)
        self.act_mode_line.setChecked(True)
        self.act_mode_line.setShortcut("L")
        self.act_mode_line.setToolTip(
            "线选模式（L）：单击选中整条线，可框选/多选/反向，导出按整条线取点。")

        self.act_mode_point = QAction("点选", self)
        self.act_mode_point.setCheckable(True)
        self.act_mode_point.setShortcut("P")
        self.act_mode_point.setToolTip(
            "点选模式（P）：显示视口内各线条的端点，鼠标变为十字，靠近端点自动吸附。\\n"
            "左键逐个加点、右键撤销上一个点、空格结束本轮并开始下一轮；\\n"
            "Esc 取消本轮；点选序列与图纸中的多段线重合时用呼吸虚线提示。")

        self.act_mode_group = QActionGroup(self)
        self.act_mode_group.setExclusive(True)
        self.act_mode_group.addAction(self.act_mode_line)
        self.act_mode_group.addAction(self.act_mode_point)
        self.act_mode_group.triggered.connect(self._on_mode_action)

        self.act_multi = QAction("多选", self)'''),
    # ---------------------------------------------------------------- 信号
    ('''        self.canvas.cursorMoved.connect(self._on_cursor)
        self.canvas.viewChanged.connect(self._on_scale)''',
     '''        self.canvas.cursorMoved.connect(self._on_cursor)
        self.canvas.viewChanged.connect(self._on_scale)
        self.canvas.pointPicked.connect(self._on_point_picked)
        self.canvas.pickCancelled.connect(self._on_pick_cancelled)
        self.canvas.roundFinished.connect(self._on_round_finished)
        self.canvas.hint.connect(self._on_hint)'''),
    # ---------------------------------------------------------------- 工具栏
    ('''        toolbar.addAction(self.act_zoom_out)
        toolbar.addSeparator()

        rule_widget = QWidget()''',
     '''        toolbar.addAction(self.act_zoom_out)
        toolbar.addSeparator()
        mode_label = QLabel("模式")
        mode_label.setStyleSheet("color:#8a97a6;padding:0 2px;")
        toolbar.addWidget(mode_label)
        toolbar.addAction(self.act_mode_line)
        toolbar.addAction(self.act_mode_point)
        toolbar.addSeparator()

        rule_widget = QWidget()'''),
    # ---------------------------------------------------------------- 菜单
    ('''        edit_menu.addAction(self.act_multi)
        edit_menu.addAction(self.act_reverse)''',
     '''        edit_menu.addAction(self.act_mode_line)
        edit_menu.addAction(self.act_mode_point)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_multi)
        edit_menu.addAction(self.act_reverse)'''),
    # ---------------------------------------------------------------- 换图
    ('''        model, prepared = payload
        self.model = model
        self.selection.reset()
        self.history.stack.clear()''',
     '''        model, prepared = payload
        self.model = model
        self.selection.reset()
        self.picks.reset()
        self.history.stack.clear()'''),
    # ---------------------------------------------------------------- 清空图纸
    ('''        self.selection.reset()
        self.history.stack.clear()
        self.canvas.set_model(None)''',
     '''        self.selection.reset()
        self.picks.reset()
        self.history.stack.clear()
        self.canvas.set_model(None)
        self.canvas.set_pick_state([], -1, None)'''),
    # ---------------------------------------------------------------- 动作可用性
    ('''    def _update_actions(self, enabled: bool) -> None:
        for action in (self.act_export, self.act_fit, self.act_zoom_in, self.act_zoom_out,
                       self.act_clear, self.act_delete, self.act_multi, self.act_reverse,
                       self.act_close):
            action.setEnabled(enabled)
        self.act_export.setEnabled(enabled and len(self.selection) > 0)
        self.act_undo.setEnabled(enabled and self.history.can_undo)
        self.act_redo.setEnabled(enabled and self.history.can_redo)''',
     '''    def _update_actions(self, enabled: bool) -> None:
        for action in (self.act_export, self.act_fit, self.act_zoom_in, self.act_zoom_out,
                       self.act_close):
            action.setEnabled(enabled)
        point_mode = self._mode == "point"
        # 多选/反向/删除只对「整条线」有意义，点选模式下收起
        for action in (self.act_multi, self.act_reverse, self.act_delete):
            action.setEnabled(enabled and not point_mode)
        self.act_clear.setEnabled(
            enabled and (self.picks.total_points > 0 if point_mode
                         else len(self.selection) > 0))
        self.act_export.setEnabled(enabled and bool(self._export_entities()))
        if point_mode:
            self.act_undo.setEnabled(enabled and self.picks.can_undo)
            self.act_redo.setEnabled(enabled and self.picks.can_redo)
        else:
            self.act_undo.setEnabled(enabled and self.history.can_undo)
            self.act_redo.setEnabled(enabled and self.history.can_redo)'''),
    # ---------------------------------------------------------------- 模式切换方法
    ('''    def _on_slope_toggled(self, enabled: bool) -> None:''',
     '''    def _on_mode_action(self, action: QAction) -> None:
        self._set_mode("point" if action is self.act_mode_point else "line")

    def _set_mode(self, mode: str) -> None:
        if mode not in ("line", "point") or mode == self._mode:
            return
        self._mode = mode
        self.canvas.set_mode(mode)
        if mode == "point":
            self.statusBar().showMessage(
                "点选模式：左键依次点选线条端点（靠近自动吸附），右键撤销上一个点，"
                "空格结束本轮并开始下一轮，Esc 取消本轮；中键或按住左键拖动可平移。",
                15000)
        else:
            self.statusBar().showMessage(
                "线选模式：单击选中整条线，可框选、多选、反向；导出按整条线取点。", 9000)
        self._refresh_selection()
        self._update_actions(self.model is not None)

    def _on_hint(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def _on_point_picked(self, point, handle: int, index: int) -> None:
        if self.model is None or self._mode != "point":
            return
        if not self.picks.add(point, handle, index):
            self.statusBar().showMessage("该点与上一个点重合，已忽略", 3000)
            return
        self._refresh_selection()
        self._update_actions(True)
        where = f"第 {self.picks.round_count} 轮第 {self.picks.current_length} 点"
        matched = self.model.get(self._pick_match() or 0)
        if matched is not None:
            self.statusBar().showMessage(
                f"已加入{where}：与图纸中的 {matched.dxftype}（句柄 {matched.source_handle}）"
                "完全重合，呼吸虚线提示中", 6000)
        else:
            self.statusBar().showMessage(
                f"已加入{where}；右键撤点，空格结束本轮，Esc 取消本轮", 4000)

    def _on_pick_cancelled(self) -> None:
        if self._mode != "point":
            return
        if self.picks.remove_last():
            self._refresh_selection()
            self._update_actions(True)
            self.statusBar().showMessage(
                f"已撤销上一个点：本轮剩 {self.picks.current_length} 点", 4000)
        else:
            self.statusBar().showMessage("当前轮没有可撤销的点", 3000)

    def _on_round_finished(self) -> None:
        if self._mode != "point":
            return
        if self.picks.finish_round():
            finished = self.picks.round_count
            self._refresh_selection()
            self._update_actions(True)
            self.statusBar().showMessage(
                f"第 {finished} 轮已结束（{len(self.picks.rounds[-1])} 点），"
                f"开始第 {finished + 1} 轮点选", 6000)
        else:
            self.statusBar().showMessage("当前轮还没有点：先在端点上单击，再按空格结束本轮", 4000)

    def _cancel_round(self) -> None:
        if self.picks.clear_current():
            self._refresh_selection()
            self._update_actions(True)
            self.statusBar().showMessage("已取消本轮点选（Ctrl+Z 可恢复）", 4000)
        else:
            self.statusBar().showMessage("本轮还没有点，无需取消", 3000)

    def _pick_match(self) -> int | None:
        if self.model is None or self._mode != "point":
            return None
        return self.picks.match_entity(self.model, self.model.visible_layers(),
                                       self.layer_panel.allowed_types())

    def _export_entities(self) -> list[EntityRecord]:
        """当前模式下待导出的要素：点选模式为各轮点选，线选模式为选中的线。"""
        if self._mode == "point":
            return self.picks.entities()
        return self._view_entities()

    def _on_slope_toggled(self, enabled: bool) -> None:'''),
    # ---------------------------------------------------------------- 撤销/清空
    ('''    def _clear(self) -> None:
        self.history.clear()
        self.canvas.set_current(None)
        self._update_actions(True)''',
     '''    def _clear(self) -> None:
        if self._mode == "point":
            if self.picks.clear():
                self._refresh_selection()
                self._update_actions(True)
                self.statusBar().showMessage("已清空全部点选（Ctrl+Z 可恢复）", 4000)
            return
        self.history.clear()
        self.canvas.set_current(None)
        self._update_actions(True)'''),
    ('''    def _undo(self) -> None:
        self.history.undo()
        self._update_actions(True)

    def _redo(self) -> None:
        self.history.redo()
        self._update_actions(True)''',
     '''    def _undo(self) -> None:
        if self._mode == "point":
            if self.picks.undo():
                self._refresh_selection()
                self._update_actions(True)
                self.statusBar().showMessage("已撤销一次点选操作", 3000)
            return
        self.history.undo()
        self._update_actions(True)

    def _redo(self) -> None:
        if self._mode == "point":
            if self.picks.redo():
                self._refresh_selection()
                self._update_actions(True)
                self.statusBar().showMessage("已重做一次点选操作", 3000)
            return
        self.history.redo()
        self._update_actions(True)'''),
    # ---------------------------------------------------------------- 定位点选块
    ('''    def _locate(self, handle: int) -> None:
        self.canvas.center_on(handle)''',
     '''    def _locate(self, handle: int) -> None:
        if handle < 0:
            # 点选块没有真实句柄，用它的包围盒定位
            for entity in self.picks.entities():
                if entity.handle == handle:
                    self.canvas.center_on_bbox(entity.bbox)
                    self.canvas.zoom_by(1.6)
                    return
            return
        self.canvas.center_on(handle)'''),
    # ---------------------------------------------------------------- 刷新面板
    ('''    def _refresh_selection(self) -> None:
        entities = self._view_entities()
        handles = {entity.handle for entity in entities}
        reversed_set = self.selection.reversed_handles
        self.canvas.set_reversed(reversed_set)
        self.canvas.set_selection(handles)
        self.property_panel.set_entities(entities, reversed_set)
        self.selection_panel.set_entities(entities, reversed_set)
        self.act_export.setEnabled(bool(entities))
        self.act_clear.setEnabled(bool(entities))
        self.act_delete.setEnabled(bool(entities))
        self.act_reverse.setEnabled(
            any(not entity.is_point and len(entity.points) >= 2 for entity in entities))
        self._update_status()''',
     '''    def _refresh_selection(self) -> None:
        if self._mode == "point":
            entities = self.picks.entities()
            reversed_set: set[int] = set()
            self.canvas.set_pick_state(self.picks.block_points(),
                                       self.picks.current_block_index,
                                       self._pick_match())
            self.canvas.set_reversed(reversed_set)
            self.canvas.set_selection(set())
        else:
            entities = self._view_entities()
            handles = {entity.handle for entity in entities}
            reversed_set = self.selection.reversed_handles
            self.canvas.set_pick_state([], -1, None)
            self.canvas.set_reversed(reversed_set)
            self.canvas.set_selection(handles)
        self.property_panel.set_entities(entities, reversed_set)
        self.selection_panel.set_entities(entities, reversed_set)
        line_mode = self._mode == "line"
        self.act_export.setEnabled(bool(entities))
        self.act_clear.setEnabled(bool(entities))
        self.act_delete.setEnabled(bool(entities) and line_mode)
        self.act_multi.setEnabled(line_mode and self.model is not None)
        self.act_reverse.setEnabled(
            line_mode and any(not entity.is_point and len(entity.points) >= 2
                              for entity in entities))
        self._update_status()'''),
    # ---------------------------------------------------------------- 状态栏
    ('''        prefix = self._status_prefix or f"实体 {len(self.model.entities)}"
        flipped = len(self.selection.reversed_handles & set(self.selection.handles))
        suffix = f" | 已反向 {flipped}" if flipped else ""
        self.lbl_count.setText(f"{prefix} | 已选 {len(self.selection)}{suffix}")
        self.act_undo.setEnabled(self.history.can_undo)
        self.act_redo.setEnabled(self.history.can_redo)''',
     '''        prefix = self._status_prefix or f"实体 {len(self.model.entities)}"
        if self._mode == "point":
            self.lbl_count.setText(
                f"{prefix} | 点选 {self.picks.total_points} 点 | "
                f"{self.picks.round_count} 轮")
            self.act_undo.setEnabled(self.picks.can_undo)
            self.act_redo.setEnabled(self.picks.can_redo)
            return
        flipped = len(self.selection.reversed_handles & set(self.selection.handles))
        suffix = f" | 已反向 {flipped}" if flipped else ""
        self.lbl_count.setText(f"{prefix} | 已选 {len(self.selection)}{suffix}")
        self.act_undo.setEnabled(self.history.can_undo)
        self.act_redo.setEnabled(self.history.can_redo)'''),
    # ---------------------------------------------------------------- 图层变化
    ('''    def _on_layers_changed(self) -> None:
        self.canvas.allowed_types = self.layer_panel.allowed_types()
        self.canvas.invalidate()''',
     '''    def _on_layers_changed(self) -> None:
        self.canvas.allowed_types = self.layer_panel.allowed_types()
        self.canvas.invalidate()
        if self._mode == "point":
            self._refresh_selection()'''),
    # ---------------------------------------------------------------- 导出
    ('''        entities = self._view_entities()
        if not entities:
            QMessageBox.information(self, "导出", "请先在图纸中选择要导出的线或点。")
            return
        dialog = ExportDialog(self.model, self._include_vertices, self._sample_step,
                              self._scale_denominator, len(entities),
                              self.act_slope.isChecked(), self)''',
     '''        entities = self._export_entities()
        if not entities:
            QMessageBox.information(
                self, "导出",
                "请先在图纸中选择要导出的线或点。" if self._mode == "line"
                else "请先点选端点（至少一个点）再导出。")
            return
        dialog = ExportDialog(self.model, self._include_vertices, self._sample_step,
                              self._scale_denominator, len(entities),
                              self.act_slope.isChecked(), self,
                              pick_mode=self._mode == "point")'''),
    ('''        options: ExportOptions = dialog.options()
        options.reversed_count = sum(1 for handle in self.selection.handles
                                     if self.selection.is_reversed(handle))''',
     '''        options: ExportOptions = dialog.options()
        options.pick_mode = self._mode == "point"
        options.reversed_count = 0 if options.pick_mode else sum(
            1 for handle in self.selection.handles if self.selection.is_reversed(handle))'''),
    ('''        box.setWindowTitle("导出完成")
        box.setText(f"已生成 {result.line_rows} 条线的坐标计算表，共 {result.point_rows} 个点。")''',
     '''        box.setWindowTitle("导出完成")
        unit = "轮点选" if self._mode == "point" else "条线"
        box.setText(f"已生成 {result.line_rows} {unit}的坐标计算表，"
                    f"共 {result.point_rows} 个点。")'''),
    # ---------------------------------------------------------------- Esc
    ('''        if event.key() == Qt.Key_Escape:
            self._clear()
            return''',
     '''        if event.key() == Qt.Key_Escape:
            if self._mode == "point":
                self._cancel_round()
            else:
                self._clear()
            return'''),
    # ---------------------------------------------------------------- 关于
    ('''            "方位角口径：正北起顺时针（测量方位角）。\\n"
            "坐标保留 4 位小数，长度保留 3 位小数。")''',
     '''            "方位角口径：正北起顺时针（测量方位角）。\\n"
            "坐标保留 4 位小数，长度保留 3 位小数。\\n\\n"
            "线选：整条线导出；点选：按端点逐点选，空格分轮，每轮各占一块。")'''),
]


def main() -> None:
    with io.open(TARGET, encoding="utf-8", newline="") as handle:
        raw = handle.read()
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n") if crlf else raw
    text = apply(text, PATCHES)
    if crlf:
        text = text.replace("\n", "\r\n")
    with io.open(TARGET, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    print("main_window.py 已更新")


if __name__ == "__main__":
    main()
