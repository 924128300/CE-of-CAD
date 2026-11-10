"""主窗口：装配画布、面板、工具栏与导出流程。"""
from __future__ import annotations

import gc
import os

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QRadioButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.dwg_loader import DwgLoadError, load_dwg
from core.excel_export import (
    APP_VERSION,
    DEFAULT_SCALE,
    SCALE_CHOICES,
    ExportOptions,
    export_excel,
    meters_per_unit,
)
from core.model import DrawingModel, EntityRecord
from core.pick_model import PickModel
from core.undo import SelectionHistory, SelectionModel

from .canvas import CadCanvas
from .export_dialog import ExportDialog
from .geometry_cache import build_geometry
from .layer_panel import LayerPanel
from .property_panel import TYPE_LABELS, PropertyPanel, SelectionPanel


class LoadWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path

    @Slot()
    def run(self) -> None:
        try:
            model = load_dwg(self.path, lambda stage, pct: self.progress.emit(stage, pct))
        except DwgLoadError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"读取失败：{exc}")
            return
        # 折线转多边形与建索引是最重的纯计算，放这里做，主线程只接指针
        self.progress.emit("构建视图", -1)
        try:
            prepared = build_geometry(model.entities,
                                      (model.origin[0], model.origin[1]), model.bbox)
        except Exception:  # noqa: BLE001 - 构建失败退回主线程，不影响加载结果
            prepared = None
        self.finished.emit((model, prepared))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DWG 坐标导出工具")
        self.resize(1400, 880)
        self.setAcceptDrops(True)

        self.model: DrawingModel | None = None
        self.selection = SelectionModel(self)
        self.history = SelectionHistory(self.selection, self)
        # 点选模式：按轮次记录端点，独立于整条线的选择集
        self.picks = PickModel()
        self._mode = "line"
        self._thread: QThread | None = None
        self._worker: LoadWorker | None = None
        self._include_vertices = True
        self._sample_step = 1.0
        self._scale_denominator = DEFAULT_SCALE
        self._last_export: str | None = None
        self._status_prefix = ""

        self._build_actions()
        self._build_ui()
        self._build_status()
        self.selection.changed.connect(self._refresh_selection)
        self._refresh_selection()

    # ------------------------------------------------------------ 构建
    def _build_actions(self) -> None:
        self.act_open = QAction("打开图纸", self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self.choose_file)

        self.act_close = QAction("清空图纸", self)
        self.act_close.setShortcut("Ctrl+W")
        self.act_close.setToolTip(
            "清空图纸（Ctrl+W）：卸下当前图纸、释放实体与绘图缓存并复位视图，\n"
            "方便连续打开多张图纸；不会修改磁盘上的 DWG 文件。")
        self.act_close.triggered.connect(self.clear_drawing)
        self.act_close.setEnabled(False)

        self.act_export = QAction("导出 Excel", self)
        self.act_export.setShortcut("Ctrl+E")
        self.act_export.triggered.connect(self.export_excel)
        self.act_export.setEnabled(False)

        self.act_undo = QAction("撤销", self)
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_undo.triggered.connect(self._undo)
        self.act_undo.setEnabled(False)

        self.act_redo = QAction("重做", self)
        self.act_redo.setShortcut(QKeySequence.Redo)
        self.act_redo.triggered.connect(self._redo)
        self.act_redo.setEnabled(False)

        self.act_clear = QAction("清空选择", self)
        self.act_clear.triggered.connect(self._clear)
        self.act_clear.setEnabled(False)

        self.act_delete = QAction("删除选中", self)
        self.act_delete.setShortcut(QKeySequence.Delete)
        self.act_delete.triggered.connect(self._delete_current)
        self.act_delete.setEnabled(False)

        self.act_mode_line = QAction("线选", self)
        self.act_mode_line.setCheckable(True)
        self.act_mode_line.setChecked(True)
        self.act_mode_line.setShortcut("L")
        self.act_mode_line.setToolTip(
            "线选模式（L）：单击选中整条线，可框选/多选/反向，导出按整条线取点。")

        self.act_mode_point = QAction("点选", self)
        self.act_mode_point.setCheckable(True)
        self.act_mode_point.setShortcut("P")
        self.act_mode_point.setToolTip(
            "点选模式（P）：显示视口内各线条的端点，鼠标变为十字，靠近端点自动吸附。\n"
            "左键逐个加点、右键撤销上一个点、空格结束本轮并开始下一轮；\n"
            "Esc 取消本轮；点选序列与图纸中的多段线重合时用呼吸虚线提示。")

        self.act_mode_group = QActionGroup(self)
        self.act_mode_group.setExclusive(True)
        self.act_mode_group.addAction(self.act_mode_line)
        self.act_mode_group.addAction(self.act_mode_point)
        self.act_mode_group.triggered.connect(self._on_mode_action)

        self.act_multi = QAction("多选", self)
        self.act_multi.setCheckable(True)
        self.act_multi.setShortcut("M")
        self.act_multi.setToolTip(
            "多选模式：开启后连续单击即可追加/取消选中（任何时候也可 Ctrl/Shift+单击追加）")
        self.act_multi.toggled.connect(self._on_multi_toggled)
        self.act_multi.setEnabled(False)

        self.act_reverse = QAction("反向", self)
        self.act_reverse.setShortcut("R")
        self.act_reverse.setToolTip(
            "反向点序（R）：把选中线的输出方向倒过来——点号 1→n、各段方位角与平距\n"
            "按新方向重算；已反向的线用粉色高亮。再次按下恢复原方向，Ctrl+Z 也可撤销。")
        self.act_reverse.triggered.connect(self._reverse_order)
        self.act_reverse.setEnabled(False)

        self.act_slope = QAction("反算坡度", self)
        self.act_slope.setCheckable(True)
        self.act_slope.setShortcut("S")
        self.act_slope.setToolTip(
            "反算坡度（默认关闭）：打开后导出时按相邻两点高差 ÷ 水平距离计算坡度，\n"
            "以 0.00% 写入坡度行，上坡为正、下坡为负；关闭时坡度行留空由你填写。")
        self.act_slope.toggled.connect(self._on_slope_toggled)

        self.act_fit = QAction("适配视图", self)
        self.act_fit.setShortcut("F")
        self.act_fit.triggered.connect(lambda: self.canvas.fit_view())
        self.act_fit.setEnabled(False)

        self.act_zoom_in = QAction("放大", self)
        self.act_zoom_in.setShortcut("Ctrl+=")
        self.act_zoom_in.triggered.connect(lambda: self.canvas.zoom_by(1.3))
        self.act_zoom_in.setEnabled(False)

        self.act_zoom_out = QAction("缩小", self)
        self.act_zoom_out.setShortcut("Ctrl+-")
        self.act_zoom_out.triggered.connect(lambda: self.canvas.zoom_by(1 / 1.3))
        self.act_zoom_out.setEnabled(False)

        self.act_about = QAction("关于", self)
        self.act_about.triggered.connect(self._about)

    def _build_ui(self) -> None:
        self.canvas = CadCanvas(self)
        self.canvas.entityPicked.connect(self._on_entity_picked)
        self.canvas.emptyClicked.connect(self._on_empty_clicked)
        self.canvas.boxSelected.connect(self._on_box_selected)
        self.canvas.cursorMoved.connect(self._on_cursor)
        self.canvas.viewChanged.connect(self._on_scale)
        self.canvas.pointPicked.connect(self._on_point_picked)
        self.canvas.pickCancelled.connect(self._on_pick_cancelled)
        self.canvas.roundFinished.connect(self._on_round_finished)
        self.canvas.hint.connect(self._on_hint)

        self.layer_panel = LayerPanel(self)
        self.layer_panel.layersChanged.connect(self._on_layers_changed)

        self.property_panel = PropertyPanel(self)

        self.selection_panel = SelectionPanel(self)
        self.selection_panel.removeRequested.connect(self._remove_handles)
        self.selection_panel.clearRequested.connect(self._clear)
        self.selection_panel.locateRequested.connect(self._locate)
        self.selection_panel.highlightRequested.connect(self._highlight)
        self.selection_panel.exportRequested.connect(self.export_excel)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)
        right_layout.addWidget(self.property_panel, 3)
        right_layout.addWidget(self.selection_panel, 2)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.layer_panel)
        splitter.addWidget(self.canvas)
        splitter.addWidget(right)
        splitter.setSizes([240, 820, 380])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        self.setCentralWidget(splitter)

        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.addAction(self.act_open)
        toolbar.addAction(self.act_close)
        toolbar.addSeparator()
        toolbar.addAction(self.act_fit)
        toolbar.addAction(self.act_zoom_in)
        toolbar.addAction(self.act_zoom_out)
        toolbar.addSeparator()
        mode_label = QLabel("模式")
        mode_label.setStyleSheet("color:#8a97a6;padding:0 2px;")
        toolbar.addWidget(mode_label)
        toolbar.addAction(self.act_mode_line)
        toolbar.addAction(self.act_mode_point)
        toolbar.addSeparator()

        rule_widget = QWidget()
        rule_layout = QHBoxLayout(rule_widget)
        rule_layout.setContentsMargins(4, 0, 4, 0)
        rule_layout.setSpacing(6)
        rule_layout.addWidget(QLabel("取点"))
        self.radio_vertices = QRadioButton("仅顶点")
        self.radio_step = QRadioButton("按间距")
        self.radio_vertices.setChecked(True)
        self.radio_vertices.toggled.connect(self._on_rule_changed)
        self.radio_step.toggled.connect(self._on_rule_changed)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setDecimals(3)
        self.step_spin.setRange(0.001, 1e7)
        self.step_spin.setValue(1.0)
        self.step_spin.setFixedWidth(110)
        self.step_spin.valueChanged.connect(self._on_step_changed)
        rule_layout.addWidget(self.radio_vertices)
        rule_layout.addWidget(self.radio_step)
        rule_layout.addWidget(self.step_spin)
        rule_layout.addWidget(QLabel("比例尺"))
        self.scale_combo = QComboBox()
        for denominator in SCALE_CHOICES:
            self.scale_combo.addItem(f"1:{denominator}", denominator)
        self.scale_combo.setCurrentIndex(SCALE_CHOICES.index(DEFAULT_SCALE))
        self.scale_combo.setFixedWidth(96)
        self.scale_combo.setToolTip("仅影响导出的平距：1:1000 表示图上 1 个单位等于实际 1 米")
        self.scale_combo.currentIndexChanged.connect(self._on_scale_changed)
        rule_layout.addWidget(self.scale_combo)
        toolbar.addWidget(rule_widget)
        toolbar.addSeparator()
        toolbar.addAction(self.act_undo)
        toolbar.addAction(self.act_redo)
        toolbar.addAction(self.act_clear)
        toolbar.addAction(self.act_multi)
        toolbar.addAction(self.act_reverse)
        toolbar.addAction(self.act_slope)
        toolbar.addSeparator()
        toolbar.addAction(self.act_export)
        self.addToolBar(toolbar)

        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_close)
        file_menu.addAction(self.act_export)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)
        edit_menu = menu.addMenu("编辑")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_delete)
        edit_menu.addAction(self.act_clear)
        edit_menu.addAction(self.act_mode_line)
        edit_menu.addAction(self.act_mode_point)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_multi)
        edit_menu.addAction(self.act_reverse)
        view_menu = menu.addMenu("视图")
        view_menu.addAction(self.act_fit)
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        help_menu = menu.addMenu("帮助")
        help_menu.addAction(self.act_about)

    def _build_status(self) -> None:
        bar = self.statusBar()
        self.lbl_coord = QLabel("X: —   Y: —")
        self.lbl_count = QLabel("未打开图纸")
        self.lbl_scale = QLabel("比例: —")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(160)
        self.progress.setVisible(False)
        bar.addWidget(self.lbl_coord, 1)
        bar.addPermanentWidget(self.progress)
        bar.addPermanentWidget(self.lbl_count)
        bar.addPermanentWidget(self.lbl_scale)

    # ------------------------------------------------------------ 打开
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 DWG 图纸", "", "DWG 图纸 (*.dwg);;所有文件 (*.*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        if self._thread is not None:
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "打开失败", f"文件不存在：\n{path}")
            return
        self.lbl_count.setText("正在读取…")
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.act_open.setEnabled(False)
        self.act_close.setEnabled(False)  # 读图期间不允许清空，避免新旧模型交叉

        self._thread = QThread(self)
        self._worker = LoadWorker(path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_loaded)
        self._worker.failed.connect(self._on_load_failed)
        self._thread.start()

    @Slot(str, int)
    def _on_progress(self, stage: str, pct: int) -> None:
        self.lbl_count.setText(f"{stage}…")
        if pct < 0:
            # 负值表示“不确定进度”，用忙碌动画代替百分比
            self.progress.setRange(0, 0)
            return
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(pct)

    def _finish_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.progress.setVisible(False)
        self.act_open.setEnabled(True)
        self.act_close.setEnabled(self.model is not None)

    @Slot(object)
    def _on_loaded(self, payload) -> None:
        self._finish_thread()
        model, prepared = payload
        self.model = model
        self.selection.reset()
        self.picks.reset()
        self.history.stack.clear()
        self.canvas.allowed_types = self.layer_panel.allowed_types()
        self.canvas.set_model(model, prepared)
        self.layer_panel.bind_model(model)
        self._update_unit_hint()
        self.setWindowTitle(f"DWG 坐标导出工具 - {os.path.basename(model.path)}")
        self._update_actions(True)
        self._refresh_selection()
        name = os.path.basename(model.path)
        self._status_prefix = f"{name} | 实体 {len(model.entities)} | 块展开 {model.insert_count}"
        self.lbl_count.setText(self._status_prefix)
        if model.warnings:
            QMessageBox.information(self, "加载提示", "\n".join(model.warnings))

    @Slot()
    def clear_drawing(self) -> None:
        """卸下当前图纸并释放模型、空间索引、折线与画笔缓存。

        只动内存，不碰磁盘文件；清空后可立即打开下一张图纸。
        """
        if self.model is None or self._thread is not None:
            return
        name = os.path.basename(self.model.path) if self.model.path else "未命名图纸"
        count = len(self.model.entities)
        # 先断开所有面板/选择/画布对模型的引用，再释放模型本身
        self.selection.reset()
        self.picks.reset()
        self.history.stack.clear()
        self.canvas.set_model(None)
        self.canvas.set_pick_state([], -1, None)
        self.layer_panel.bind_model(None)
        self.property_panel.set_entities([])
        self.selection_panel.set_entities([])
        self.model = None
        self._last_export = None
        self._status_prefix = ""
        self.canvas.allowed_types = self.layer_panel.allowed_types()
        self.lbl_count.setText("未打开图纸")
        self.lbl_coord.setText("X: —   Y: —")
        self.lbl_scale.setText("比例: —")
        self.setWindowTitle("DWG 坐标导出工具")
        self._update_actions(False)
        self._refresh_selection()
        # 实体点数以万计时，引用释放后交给 GC 回收（CPython 的引用计数已在上面完成大半）
        gc.collect()
        self.statusBar().showMessage(f"已清空图纸 {name}：释放 {count} 条实体与绘图缓存，可继续打开下一张", 8000)

    @Slot(str)
    def _on_load_failed(self, message: str) -> None:
        self._finish_thread()
        self.lbl_count.setText("读取失败")
        QMessageBox.critical(self, "无法打开图纸", message)

    def _update_actions(self, enabled: bool) -> None:
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
        # 取点规则只对整条线有意义；点选块固定按单击顺序导出
        self.radio_vertices.setEnabled(not point_mode)
        self.radio_step.setEnabled(not point_mode)
        self.step_spin.setEnabled(not point_mode and not self.radio_vertices.isChecked())
        if point_mode:
            self.act_undo.setEnabled(enabled and self.picks.can_undo)
            self.act_redo.setEnabled(enabled and self.picks.can_redo)
        else:
            self.act_undo.setEnabled(enabled and self.history.can_undo)
            self.act_redo.setEnabled(enabled and self.history.can_redo)

    # ------------------------------------------------------------ 选择
    def _on_multi_toggled(self, enabled: bool) -> None:
        self.canvas.set_additive_mode(enabled)
        if enabled:
            self.statusBar().showMessage(
                "多选模式：连续单击即可追加/取消选中；导出时每条线各占一块，块与块之间空一行", 6000)

    def _on_mode_action(self, action: QAction) -> None:
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
        match = self._pick_match()
        matched = self.model.get(match) if match is not None else None
        if matched is not None:
            self.statusBar().showMessage(
                f"已加入{where}：与图纸中的 "
                f"{TYPE_LABELS.get(matched.dxftype, matched.dxftype)}"
                f"（句柄 {matched.source_handle}）"
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

    def _on_slope_toggled(self, enabled: bool) -> None:
        self.statusBar().showMessage(
            "反算坡度：已开启，导出时按 0.00% 自动填写坡度行"
            if enabled else "反算坡度：已关闭，导出时坡度行留空由你填写", 6000)

    def _on_entity_picked(self, handle: int, additive: bool) -> None:
        self.canvas.set_current(handle)
        if additive:
            if handle in self.selection:
                self.history.remove([handle])
            else:
                self.history.add([handle])
                self.selection_panel.focus_entity(handle)
        else:
            self.history.replace([handle], "选择要素")
        self._update_actions(True)

    def _on_empty_clicked(self, additive: bool) -> None:
        if not additive and len(self.selection):
            self._clear()

    def _on_box_selected(self, handles: list[int], additive: bool) -> None:
        if additive:
            self.history.add(handles)
        else:
            self.history.replace(handles, f"框选 {len(handles)} 条要素")
        self._update_actions(True)

    def _remove_handles(self, handles: list[int]) -> None:
        self.history.remove(handles)
        self._update_actions(True)

    def _delete_current(self) -> None:
        handles = self.selection.handles
        if handles:
            self.history.remove(handles)
            self._update_actions(True)

    def _clear(self) -> None:
        if self._mode == "point":
            if self.picks.clear():
                self._refresh_selection()
                self._update_actions(True)
                self.statusBar().showMessage("已清空全部点选（Ctrl+Z 可恢复）", 4000)
            return
        self.history.clear()
        self.canvas.set_current(None)
        self._update_actions(True)

    def _reverse_order(self) -> None:
        """翻转选中要素的输出方向，作为一条可撤销命令。"""
        if self.model is None:
            return
        handles = [
            handle for handle in self.selection.handles
            if (entity := self.model.get(handle)) is not None
            and not entity.is_point and len(entity.points) >= 2
        ]
        if not handles:
            return
        self.history.toggle_reversed(handles)
        self._update_actions(True)
        flipped = len(self.selection.reversed_handles & set(handles))
        if flipped == len(handles):
            note = "全部已反向"
        elif flipped:
            note = f"{flipped}/{len(handles)} 条已反向"
        else:
            note = "已恢复正向"
        self.statusBar().showMessage(
            f"点序方向：{note}（粉色高亮）。导出按新方向输出坐标、方位角与平距；"
            "再按 R 切换，Ctrl+Z 可撤销。", 9000)

    def _view_entities(self):
        """按选择顺序返回展示/导出用实体；已反向的返回反向副本。"""
        if self.model is None:
            return []
        flips = self.selection.reversed_handles
        result = []
        for handle in self.selection.handles:
            entity = self.model.get(handle)
            if entity is None:
                continue
            result.append(entity.reversed() if handle in flips else entity)
        return result

    def _undo(self) -> None:
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
        self._update_actions(True)

    def _locate(self, handle: int) -> None:
        if handle < 0:
            # 点选块没有真实句柄，用它的包围盒定位
            for entity in self.picks.entities():
                if entity.handle == handle:
                    self.canvas.center_on_bbox(entity.bbox)
                    self.canvas.zoom_by(1.6)
                    return
            return
        self.canvas.center_on(handle)
        self.canvas.zoom_by(1.6)
        self.canvas.set_current(handle)

    def _highlight(self, handle: int) -> None:
        self.canvas.set_current(handle)

    def _refresh_selection(self) -> None:
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
        self._update_status()

    def _update_status(self) -> None:
        if self.model is None:
            return
        prefix = self._status_prefix or f"实体 {len(self.model.entities)}"
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
        self.act_redo.setEnabled(self.history.can_redo)

    def _on_cursor(self, x: float, y: float) -> None:
        self.lbl_coord.setText(f"X: {x:.4f}   Y: {y:.4f}")

    def _on_scale(self, scale: float) -> None:
        if scale > 0:
            self.lbl_scale.setText(f"比例 1:{1 / scale:,.0f}")

    def _on_layers_changed(self) -> None:
        self.canvas.allowed_types = self.layer_panel.allowed_types()
        self.canvas.invalidate()
        if self._mode == "point":
            self._refresh_selection()

    def _on_scale_changed(self) -> None:
        self._scale_denominator = int(self.scale_combo.currentData() or DEFAULT_SCALE)
        self._update_unit_hint()

    def _update_unit_hint(self) -> None:
        if self.model is None:
            return
        meters = meters_per_unit(self._scale_denominator)
        self.property_panel.set_unit(
            f"{self.model.unit_name}，坐标按图纸原值输出；"
            f"比例 1:{self._scale_denominator}（图上 1 单位 = {meters:g} m，仅用于平距）")

    def _on_rule_changed(self) -> None:
        self._include_vertices = self.radio_vertices.isChecked()
        self.step_spin.setEnabled(not self._include_vertices and self._mode == "line")

    def _on_step_changed(self, value: float) -> None:
        self._sample_step = float(value)

    # ------------------------------------------------------------ 导出
    def export_excel(self) -> None:
        if self.model is None:
            return
        entities = self._export_entities()
        if not entities:
            QMessageBox.information(
                self, "导出",
                "请先在图纸中选择要导出的线或点。" if self._mode == "line"
                else "请先点选端点（至少一个点）再导出。")
            return
        dialog = ExportDialog(self.model, self._include_vertices, self._sample_step,
                              self._scale_denominator, len(entities),
                              self.act_slope.isChecked(), self,
                              pick_mode=self._mode == "point")
        if not dialog.exec():
            return
        options: ExportOptions = dialog.options()
        options.pick_mode = self._mode == "point"
        options.reversed_count = 0 if options.pick_mode else sum(
            1 for handle in self.selection.handles if self.selection.is_reversed(handle))
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            result = export_excel(self.model, entities, options)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._last_export = result.path
        box = QMessageBox(self)
        box.setWindowTitle("导出完成")
        unit = "轮点选" if self._mode == "point" else "条线"
        box.setText(f"已生成 {result.line_rows} {unit}的坐标计算表，"
                    f"共 {result.point_rows} 个点。")
        detail = result.path
        box.setInformativeText(detail)
        open_btn = box.addButton("打开文件", QMessageBox.ActionRole)
        folder_btn = box.addButton("打开所在目录", QMessageBox.ActionRole)
        box.addButton("关闭", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(result.path))
        elif box.clickedButton() is folder_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(result.path)))

    # ------------------------------------------------------------ 其它
    def _about(self) -> None:
        QMessageBox.about(
            self, "关于",
            f"DWG 坐标导出工具 {APP_VERSION}\n\n"
            "本地解析 DWG（ezdwg），无需安装 AutoCAD。\n"
            "方位角口径：正北起顺时针（测量方位角）。\n"
            "坐标保留 4 位小数，长度保留 3 位小数。\n\n"
            "线选：整条线导出；点选：按端点逐点选，空格分轮，每轮各占一块。")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".dwg"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".dwg"):
                self.open_file(path)
                return

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            if self._mode == "point":
                self._cancel_round()
            else:
                self._clear()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
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
        super().closeEvent(event)
