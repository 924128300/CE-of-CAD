"""一次性补丁：多选模式 + 多线导出的可见性提示。

用法：python tools/apply_multiselect_patch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CANVAS = ROOT / "ui" / "canvas.py"
WINDOW = ROOT / "ui" / "main_window.py"
PANEL = ROOT / "ui" / "property_panel.py"
DIALOG = ROOT / "ui" / "export_dialog.py"

CANVAS_EDITS = [
    ("        self.allowed_types: set[str] | None = None\n",
     "        self.allowed_types: set[str] | None = None\n"
     "        # 多选模式：开着时单击即追加/取消，不必按 Ctrl/Shift\n"
     "        self._additive_mode = False\n",
     "画布成员"),
    ("    def set_model(self, model",
     '    def set_additive_mode(self, enabled: bool) -> None:\n'
     '        """多选模式开关：开启后单击图纸里的线/点即追加或取消选中。"""\n'
     '        self._additive_mode = bool(enabled)\n\n'
     "    def set_model(self, model",
     "画布方法"),
    ("        additive = bool(event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))\n",
     "        additive = self._additive_mode or bool(\n"
     "            event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))\n",
     "鼠标追加判定"),
]

WINDOW_EDITS = [
    ('''        self.act_delete = QAction("删除选中", self)
        self.act_delete.setShortcut(QKeySequence.Delete)
        self.act_delete.triggered.connect(self._delete_current)
        self.act_delete.setEnabled(False)
''',
     '''        self.act_delete = QAction("删除选中", self)
        self.act_delete.setShortcut(QKeySequence.Delete)
        self.act_delete.triggered.connect(self._delete_current)
        self.act_delete.setEnabled(False)

        self.act_multi = QAction("多选", self)
        self.act_multi.setCheckable(True)
        self.act_multi.setShortcut("M")
        self.act_multi.setToolTip(
            "多选模式：开启后连续单击即可追加/取消选中（任何时候也可 Ctrl/Shift+单击追加）")
        self.act_multi.toggled.connect(self._on_multi_toggled)
        self.act_multi.setEnabled(False)
''',
     "多选动作"),
    ("        toolbar.addAction(self.act_clear)\n",
     "        toolbar.addAction(self.act_clear)\n        toolbar.addAction(self.act_multi)\n",
     "工具栏加入多选"),
    ("        edit_menu.addAction(self.act_clear)\n",
     "        edit_menu.addAction(self.act_clear)\n        edit_menu.addAction(self.act_multi)\n",
     "编辑菜单加入多选"),
    ('''    def _on_entity_picked(self, handle: int, additive: bool) -> None:
        self.canvas.set_current(handle)
        if additive:
            if handle in self.selection:
                self.history.remove([handle])
            else:
                self.history.add([handle])
        else:
            self.history.replace([handle], "选择要素")
        self._update_actions(True)
''',
     '''    def _on_multi_toggled(self, enabled: bool) -> None:
        self.canvas.set_additive_mode(enabled)
        if enabled:
            self.statusBar().showMessage(
                "多选模式：连续单击即可追加/取消选中；导出时每条线各占一块，块与块之间空一行", 6000)

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
''',
     "选中回调"),
    ('''        dialog = ExportDialog(self.model, self._include_vertices, self._sample_step,
                              self._scale_denominator, self)''',
     '''        dialog = ExportDialog(self.model, self._include_vertices, self._sample_step,
                              self._scale_denominator, len(entities), self)''',
     "导出对话框入参"),
    ("                       self.act_clear, self.act_delete):\n",
     "                       self.act_clear, self.act_delete, self.act_multi):\n",
     "动作可用性"),
]

PANEL_EDITS = [
    ('''    def set_entities(self, entities: list[EntityRecord]) -> None:
        self.model.set_entities(entities)
        self.title.setText(f"待导出列表 ({len(entities)})")
''',
     '''    def set_entities(self, entities: list[EntityRecord]) -> None:
        self.model.set_entities(entities)
        self.title.setText(f"待导出列表 ({len(entities)})")
        self.title.setToolTip("导出时每条线各占一块（9 行），块与块之间空一行")
''',
     "列表标题"),
    ('''    def _selected_rows(self) -> list[int]:''',
     '''    def focus_entity(self, handle: int) -> None:
        """把某条要素滚到可见位置并选中该行（多选时给即时反馈）。"""
        for row, entity in enumerate(self.model._entities):  # noqa: SLF001
            if entity.handle == handle:
                index = self.model.index(row, 0)
                self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
                self.table.selectRow(row)
                return

    def _selected_rows(self) -> list[int]:''',
     "定位行方法"),
]

DIALOG_EDITS = [
    ('''                 sample_step: float = 1.0, scale_denominator: int = DEFAULT_SCALE,
                 parent=None) -> None:''',
     '''                 sample_step: float = 1.0, scale_denominator: int = DEFAULT_SCALE,
                 entity_count: int = 0, parent=None) -> None:''',
     "对话框签名"),
    ('''        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        path_box = QGroupBox("保存位置")''',
     '''        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        if entity_count > 1:
            summary = QLabel(f"本次导出 {entity_count} 条线：每条线各占一块（9 行），"
                             f"块与块之间空一行，全部写在同一张 sheet 里。")
            summary.setWordWrap(True)
            summary.setStyleSheet("color:#8a97a6;")
            layout.addWidget(summary)
        elif entity_count == 1:
            layout.addWidget(QLabel("本次导出 1 条线。"))

        path_box = QGroupBox("保存位置")''',
     "对话框摘要"),
]


def apply(path: Path, edits: list[tuple[str, str, str]]) -> int:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    changed = 0
    for old, new, label in edits:
        if new.strip() and new in text:
            print(f"  {path.name} / {label}: 已存在，跳过")
            continue
        if old not in text:
            print(f"  [失败] {path.name} / {label}: 未找到锚点")
            return 1
        text = text.replace(old, new, 1)
        changed += 1
        print(f"  {path.name} / {label}: 已改")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", "\r\n"))
    return 0


def main() -> int:
    for path, edits in ((CANVAS, CANVAS_EDITS), (WINDOW, WINDOW_EDITS),
                        (PANEL, PANEL_EDITS), (DIALOG, DIALOG_EDITS)):
        if apply(path, edits):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
