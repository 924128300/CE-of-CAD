"""实时属性面板与待导出列表。"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.geometry import format_coord, format_dms, format_length
from core.model import EntityRecord

TYPE_LABELS = {
    "LINE": "直线",
    "LWPOLYLINE": "轻量多段线",
    "POLYLINE_2D": "二维多段线",
    "POLYLINE_3D": "三维多段线",
    "ARC": "圆弧",
    "CIRCLE": "圆",
    "POINT": "点",
}


class PropertyPanel(QWidget):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 8, 4)
        layout.setSpacing(6)

        self.title = QLabel("当前要素")
        self.title.setStyleSheet("color:#8a97a6;font-weight:bold;")
        layout.addWidget(self.title)

        box = QGroupBox()
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self.values: dict[str, QLabel] = {}
        rows = [
            ("类型", "type"), ("图层", "layer"),
            ("句柄", "handle"), ("段数", "segments"),
            ("起点 X", "sx"), ("起点 Y", "sy"), ("起点 Z", "sz"),
            ("终点 X", "ex"), ("终点 Y", "ey"), ("终点 Z", "ez"),
            ("平面长度", "planar"), ("三维长度", "length"),
            ("起点→终点方位角", "azimuth"), ("输出方向", "direction"),
        ]
        for index, (label, key) in enumerate(rows):
            row = index // 2
            col = (index % 2) * 2
            name = QLabel(label)
            name.setStyleSheet("color:#8a97a6;")
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setFont(QFont("Consolas", 9))
            grid.addWidget(name, row, col)
            grid.addWidget(value, row, col + 1)
            self.values[key] = value
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addWidget(box)

        segment_title = QLabel("分段数据")
        segment_title.setStyleSheet("color:#8a97a6;font-weight:bold;")
        layout.addWidget(segment_title)
        self.segment_table = QTableWidget(0, 4)
        self.segment_table.setHorizontalHeaderLabels(["段", "方位角", "段长", "累计长"])
        self.segment_table.verticalHeader().setVisible(False)
        self.segment_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.segment_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.segment_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.segment_table.setMaximumHeight(160)
        layout.addWidget(self.segment_table)

        self.unit_label = QLabel("图纸单位：—")
        self.unit_label.setWordWrap(True)
        self.unit_label.setStyleSheet("color:#8a97a6;")
        layout.addWidget(self.unit_label)

    def set_unit(self, text: str) -> None:
        self.unit_label.setText(f"图纸单位：{text}")

    def set_entities(self, entities: list[EntityRecord],
                     reversed_handles: set[int] | None = None) -> None:
        if not entities:
            self.title.setText("当前要素")
            for label in self.values.values():
                label.setText("—")
            self.segment_table.setRowCount(0)
            return
        entity = entities[0]
        flips = reversed_handles or set()
        flipped = entity.handle in flips
        parts = []
        if len(entities) > 1:
            parts.append(f"共选中 {len(entities)} 条，显示第 1 条")
        if flipped:
            parts.append("已反向")
        suffix = f"（{'，'.join(parts)}）" if parts else ""
        self.title.setText(f"当前要素{suffix}")
        self.values["direction"].setText("已反向（按新方向输出）" if flipped else "正向")
        start = entity.first
        end = entity.last
        self.values["type"].setText(TYPE_LABELS.get(entity.dxftype, entity.dxftype))
        self.values["layer"].setText(entity.layer)
        self.values["handle"].setText(str(entity.source_handle))
        self.values["segments"].setText(str(len(entity.segments)))
        self.values["sx"].setText(format_coord(start[0]))
        self.values["sy"].setText(format_coord(start[1]))
        self.values["sz"].setText(format_coord(start[2]))
        self.values["ex"].setText(format_coord(end[0]))
        self.values["ey"].setText(format_coord(end[1]))
        self.values["ez"].setText(format_coord(end[2]))
        self.values["planar"].setText(format_length(entity.planar_length))
        self.values["length"].setText(format_length(entity.length))
        first = entity.segments[0] if entity.segments else None
        self.values["azimuth"].setText(format_dms(first.azimuth) if first else "—")

        segments = entity.segments[:200]
        self.segment_table.setRowCount(len(segments))
        cumulative = 0.0
        for row, seg in enumerate(segments):
            cumulative += seg.length
            values = [str(row + 1), format_dms(seg.azimuth),
                      format_length(seg.length), format_length(cumulative)]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.segment_table.setItem(row, col, item)


COLUMNS = ["编号", "类型", "图层", "起点 X", "总长", "方向"]


class SelectionTableModel(QAbstractTableModel):
    """待导出列表的数据模型。

    「总长」只在视图真正取到该单元格时才计算（并缓存），所以框选上万条时
    不会一次性把所有实体的分段都算一遍，滚动到哪里算到哪里。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entities: list[EntityRecord] = []
        self._lengths: dict[int, str] = {}
        self._reversed: set[int] = set()

    def set_entities(self, entities: list[EntityRecord],
                     reversed_handles: set[int] | None = None) -> None:
        self.beginResetModel()
        self._entities = list(entities)
        self._lengths.clear()
        self._reversed = set(reversed_handles or ())
        self.endResetModel()

    def entity_at(self, row: int) -> EntityRecord | None:
        if 0 <= row < len(self._entities):
            return self._entities[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._entities)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        if 0 <= section < len(COLUMNS):
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        entity = self._entities[index.row()]
        column = index.column()
        if role == Qt.TextAlignmentRole:
            aligned = column in (0, 3, 4, 5)
            return int((Qt.AlignRight if aligned else Qt.AlignLeft) | Qt.AlignVCenter)
        if role != Qt.DisplayRole:
            return None
        if column == 0:
            return str(index.row() + 1)
        if column == 1:
            return TYPE_LABELS.get(entity.dxftype, entity.dxftype)
        if column == 2:
            return entity.layer
        if column == 3:
            return format_coord(entity.first[0])
        if column == 5:
            return "已反向" if entity.handle in self._reversed else "正向"
        text = self._lengths.get(entity.handle)
        if text is None:
            text = format_length(entity.length)
            self._lengths[entity.handle] = text
        return text


class SelectionPanel(QWidget):
    removeRequested = Signal(list)
    clearRequested = Signal()
    locateRequested = Signal(int)
    highlightRequested = Signal(int)
    exportRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.title = QLabel("待导出列表 (0)")
        self.title.setStyleSheet("color:#8a97a6;font-weight:bold;")
        header.addWidget(self.title)
        header.addStretch(1)
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setObjectName("primary")
        self.btn_export.setEnabled(False)
        header.addWidget(self.btn_export)
        layout.addLayout(header)

        self.model = SelectionTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.selectionModel().selectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.btn_remove = QPushButton("删除所选")
        self.btn_clear = QPushButton("清空")
        buttons.addWidget(self.btn_remove)
        buttons.addWidget(self.btn_clear)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(lambda: self.clearRequested.emit())
        self.btn_export.clicked.connect(lambda: self.exportRequested.emit())

    def set_entities(self, entities: list[EntityRecord],
                     reversed_handles: set[int] | None = None) -> None:
        self.model.set_entities(entities, reversed_handles)
        self.title.setText(f"待导出列表 ({len(entities)})")
        self.title.setToolTip("导出时每条线各占一块（9 行），块与块之间空一行")
        self.btn_export.setEnabled(bool(entities))
        self.btn_remove.setEnabled(bool(entities))
        self.btn_clear.setEnabled(bool(entities))

    def focus_entity(self, handle: int) -> None:
        """把某条要素滚到可见位置并选中该行（多选时给即时反馈）。"""
        for row, entity in enumerate(self.model._entities):  # noqa: SLF001
            if entity.handle == handle:
                index = self.model.index(row, 0)
                self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
                self.table.selectRow(row)
                return

    def _selected_rows(self) -> list[int]:
        selection = self.table.selectionModel()
        if selection is None:
            return []
        return sorted({index.row() for index in selection.selectedRows()})

    def _remove_selected(self) -> None:
        handles = []
        for row in self._selected_rows():
            entity = self.model.entity_at(row)
            if entity is not None:
                handles.append(entity.handle)
        if handles:
            self.removeRequested.emit(handles)

    def _on_double_click(self, index) -> None:
        entity = self.model.entity_at(index.row())
        if entity is not None:
            self.locateRequested.emit(entity.handle)

    def _on_row_selected(self, *_args) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        entity = self.model.entity_at(rows[0])
        if entity is not None:
            self.highlightRequested.emit(entity.handle)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._remove_selected()
            return
        super().keyPressEvent(event)
