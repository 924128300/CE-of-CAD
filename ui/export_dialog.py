"""导出选项对话框。"""
from __future__ import annotations

import datetime as _dt
import os

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from core.excel_export import (
    DEFAULT_SCALE,
    SCALE_CHOICES,
    UNIT_CHOICES,
    ExportOptions,
    meters_per_unit,
)
from core.model import DrawingModel


class ExportDialog(QDialog):
    def __init__(self, model: DrawingModel, include_vertices: bool = True,
                 sample_step: float = 1.0, scale_denominator: int = DEFAULT_SCALE,
                 entity_count: int = 0, fill_slope: bool = False, parent=None,
                 pick_mode: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出坐标计算表")
        self.setMinimumWidth(560)
        self._model = model
        self._fill_slope = bool(fill_slope)
        self._pick_mode = bool(pick_mode)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        unit = "轮点选" if self._pick_mode else "条线"
        if entity_count > 1:
            summary = QLabel(f"本次导出 {entity_count} {unit}：每{'轮' if self._pick_mode else '条'}"
                             f"各占一块（9 行），块与块之间空一行，全部写在同一张 sheet 里。")
            summary.setWordWrap(True)
            summary.setStyleSheet("color:#8a97a6;")
            layout.addWidget(summary)
        elif entity_count == 1:
            layout.addWidget(QLabel(f"本次导出 1 {unit}。"))

        path_box = QGroupBox("保存位置")
        path_layout = QHBoxLayout(path_box)
        self.path_edit = QLineEdit(self._default_path())
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        path_layout.addWidget(self.path_edit, 1)
        path_layout.addWidget(browse)
        layout.addWidget(path_box)

        rule_box = QGroupBox("取点规则")
        rule_layout = QVBoxLayout(rule_box)
        row = QHBoxLayout()
        self.radio_vertices = QRadioButton("仅顶点")
        self.radio_step = QRadioButton("按间距采样")
        (self.radio_vertices if include_vertices else self.radio_step).setChecked(True)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setDecimals(3)
        self.step_spin.setRange(0.001, 1e7)
        self.step_spin.setValue(max(0.001, sample_step))
        self.step_spin.setSuffix(" 图纸单位")
        row.addWidget(self.radio_vertices)
        row.addWidget(self.radio_step)
        row.addWidget(self.step_spin)
        row.addStretch(1)
        rule_layout.addLayout(row)
        self.radio_vertices.toggled.connect(lambda checked: self.step_spin.setEnabled(not checked))
        self.step_spin.setEnabled(self.radio_step.isChecked())
        if self._pick_mode:
            # 点选块只输出被点中的点，取点规则固定为「仅顶点」
            self.radio_vertices.setChecked(True)
            self.radio_step.setEnabled(False)
            self.step_spin.setEnabled(False)
        layout.addWidget(rule_box)

        option_box = QGroupBox("其它选项")
        option_layout = QVBoxLayout(option_box)
        unit_row = QHBoxLayout()
        unit_row.addWidget(QLabel("坐标单位"))
        self.unit_combo = QComboBox()
        for key, label in UNIT_CHOICES.items():
            self.unit_combo.addItem(label, key)
        unit_row.addWidget(self.unit_combo)
        unit_row.addSpacing(16)
        unit_row.addWidget(QLabel("比例尺"))
        self.scale_combo = QComboBox()
        for denominator in SCALE_CHOICES:
            self.scale_combo.addItem(f"1:{denominator}", denominator)
        if scale_denominator in SCALE_CHOICES:
            self.scale_combo.setCurrentIndex(SCALE_CHOICES.index(scale_denominator))
        else:
            self.scale_combo.setCurrentIndex(SCALE_CHOICES.index(DEFAULT_SCALE))
        self.scale_combo.currentIndexChanged.connect(self._refresh_scale_hint)
        unit_row.addWidget(self.scale_combo)
        unit_row.addStretch(1)
        option_layout.addLayout(unit_row)

        self.scale_hint = QLabel()
        self.scale_hint.setStyleSheet("color:#8a97a6;")
        option_layout.addWidget(self.scale_hint)
        self._refresh_scale_hint()
        slope_hint = QLabel(
            "坡度：已反算（主界面工具栏「反算坡度」已开启）——"
            "相邻两点高差 ÷ 水平距离，按 0.00% 写入，上坡为正、下坡为负。"
            if self._fill_slope else
            "坡度：留空待填（主界面工具栏「反算坡度」未开启；需要自动反算时"
            "关闭本对话框，在工具栏打开该开关）。")
        slope_hint.setWordWrap(True)
        slope_hint.setStyleSheet("color:#8a97a6;")
        option_layout.addWidget(slope_hint)

        self.check_info = QCheckBox("附加「导出信息」工作表")
        self.check_info.setChecked(True)
        option_layout.addWidget(self.check_info)
        layout.addWidget(option_box)

        if self._pick_mode:
            pick_tip = QLabel(
                "点选模式：每一轮点选按单击顺序导出为一整块（左侧「工程名称」写作「点选N」），"
                "点号按点选顺序排列，平距与方位由相邻两点直接计算，坡度同样按相邻两点反算。")
            pick_tip.setWordWrap(True)
            pick_tip.setStyleSheet("color:#8a97a6;")
            layout.addWidget(pick_tip)

        tip = QLabel(
            "输出为「采场矿房坐标计算表」版本：每个点占两列合并，点号、X/Y/Z 坐标逐点排列；"
            "相邻两点之间的平距、方位写在中间，巷道长留空由你填写；"
            "坡度默认留空，在主界面工具栏打开「反算坡度」后自动填入。\n"
            "平距按比例尺换算成米（圆弧段取弧长），坐标保留 4 位小数，"
            "平距保留 3 位，方位为度分秒（秒取整数）。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8a97a6;")
        layout.addWidget(tip)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("导出")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_scale_hint(self) -> None:
        denominator = int(self.scale_combo.currentData() or DEFAULT_SCALE)
        self.scale_hint.setText(
            f"1:{denominator} —— 图上 1 个单位 = 实际 {meters_per_unit(denominator):g} m，"
            f"只用于换算平距，坐标按原值输出。")

    def _default_path(self) -> str:
        stem = os.path.splitext(os.path.basename(self._model.path or "图纸"))[0]
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.dirname(os.path.abspath(self._model.path)) if self._model.path else os.getcwd()
        return os.path.join(folder, f"{stem}_坐标计算表_{stamp}.xlsx")

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存 Excel", self.path_edit.text(),
                                              "Excel 工作簿 (*.xlsx)")
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.path_edit.setText(path)

    def _validate(self) -> None:
        if not self.path_edit.text().strip():
            self.path_edit.setFocus()
            return
        self.accept()

    def options(self) -> ExportOptions:
        path = self.path_edit.text().strip()
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        return ExportOptions(
            path=path,
            include_info=self.check_info.isChecked(),
            include_vertices=self.radio_vertices.isChecked(),
            sample_step=self.step_spin.value(),
            unit=self.unit_combo.currentData() or "drawing",
            scale_denominator=int(self.scale_combo.currentData() or DEFAULT_SCALE),
            fill_slope=self._fill_slope,
        )
