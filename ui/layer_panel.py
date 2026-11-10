"""图层与实体类型过滤面板。"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.model import DrawingModel

TYPE_LABELS = {
    "LINE": "直线",
    "LWPOLYLINE": "轻量多段线",
    "POLYLINE_2D": "二维多段线",
    "POLYLINE_3D": "三维多段线",
    "ARC": "圆弧",
    "CIRCLE": "圆",
    "POINT": "点",
}


class LayerPanel(QWidget):
    layersChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 4, 8)
        layout.setSpacing(6)

        title = QLabel("图层")
        title.setStyleSheet("color:#8a97a6;font-weight:bold;")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["图层", "数量"])
        self.tree.setColumnWidth(0, 150)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.btn_all = QPushButton("全显")
        self.btn_none = QPushButton("全隐")
        self.btn_invert = QPushButton("反选")
        for btn in (self.btn_all, self.btn_none, self.btn_invert):
            btn.setFixedHeight(24)
            buttons.addWidget(btn)
        layout.addLayout(buttons)

        self.type_group = QWidget()
        type_layout = QVBoxLayout(self.type_group)
        type_layout.setContentsMargins(0, 6, 0, 0)
        type_layout.setSpacing(3)
        label = QLabel("可选类型")
        label.setStyleSheet("color:#8a97a6;font-weight:bold;")
        type_layout.addWidget(label)
        self.type_checks: dict[str, QCheckBox] = {}
        for key in ("LINE", "LWPOLYLINE", "POLYLINE_2D", "POLYLINE_3D", "ARC", "CIRCLE", "POINT"):
            check = QCheckBox(TYPE_LABELS.get(key, key))
            check.setChecked(True)
            check.stateChanged.connect(self._on_type_changed)
            self.type_checks[key] = check
            type_layout.addWidget(check)
        # 全不勾选会让画布一片空白且没有任何提示，这里兜底并给出原因
        self.type_hint = QLabel("至少保留一类可选类型")
        self.type_hint.setStyleSheet("color:#ff9f43;")
        self.type_hint.setVisible(False)
        type_layout.addWidget(self.type_hint)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(lambda: self.type_hint.setVisible(False))
        self._fixing_type = False
        layout.addWidget(self.type_group)

        self._updating = False
        self._bound: DrawingModel | None = None
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_invert.clicked.connect(self._invert)

    def set_model(self, model: DrawingModel | None) -> None:
        self._updating = True
        self.tree.clear()
        if model is not None:
            for name, info in sorted(model.layers.items(), key=lambda kv: kv[0]):
                if info.entity_count == 0:
                    continue
                item = QTreeWidgetItem([name, str(info.entity_count)])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if info.visible else Qt.Unchecked)
                item.setData(0, Qt.UserRole, name)
                pix = QPixmap(10, 10)
                pix.fill(QColor(*info.color))
                item.setIcon(0, QIcon(pix))
                self.tree.addTopLevelItem(item)
        self._updating = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating:
            return
        name = item.data(0, Qt.UserRole)
        model = self._bound
        if model is not None and name in model.layers:
            model.layers[name].visible = item.checkState(0) == Qt.Checked
            self.layersChanged.emit()

    def bind_model(self, model: DrawingModel | None) -> None:
        self._bound = model
        self.set_model(model)

    def _iter_items(self):
        for i in range(self.tree.topLevelItemCount()):
            yield self.tree.topLevelItem(i)

    def _set_all(self, visible: bool) -> None:
        model = self._bound
        self._updating = True
        for item in self._iter_items():
            item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
            name = item.data(0, Qt.UserRole)
            if model is not None and name in model.layers:
                model.layers[name].visible = visible
        self._updating = False
        self.layersChanged.emit()

    def _invert(self) -> None:
        model = self._bound
        self._updating = True
        for item in self._iter_items():
            checked = item.checkState(0) == Qt.Checked
            item.setCheckState(0, Qt.Unchecked if checked else Qt.Checked)
            name = item.data(0, Qt.UserRole)
            if model is not None and name in model.layers:
                model.layers[name].visible = not checked
        self._updating = False
        self.layersChanged.emit()

    def _on_type_changed(self) -> None:
        if self._fixing_type:
            return
        if not self.allowed_types():
            # 取消最后一个勾选时自动恢复，避免画布变成空白
            check = self.sender()
            if isinstance(check, QCheckBox):
                self._fixing_type = True
                check.setChecked(True)
                self._fixing_type = False
            self.type_hint.setVisible(True)
            self._hint_timer.start(2500)
        self.layersChanged.emit()

    def allowed_types(self) -> set[str]:
        return {key for key, check in self.type_checks.items() if check.isChecked()}
