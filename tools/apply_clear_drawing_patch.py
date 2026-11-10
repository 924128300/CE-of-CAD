"""一次性补丁：工具栏「打开图纸」旁新增「清空图纸」，释放模型与绘图缓存（V1.3.5）。"""
from __future__ import annotations

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path: str) -> str:
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def write(path: str, text: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", "\r\n"))


def patch(path: str, pairs: list[tuple[str, str]]) -> None:
    text = read(path)
    for old, new in pairs:
        if text.count(old) != 1:
            raise SystemExit(f"[失败] {os.path.basename(path)} 锚点命中 {text.count(old)} 次：\n{old[:160]}")
        text = text.replace(old, new, 1)
    write(path, text)
    print(f"[完成] {os.path.basename(path)}")


main_window = os.path.join(ROOT, "ui", "main_window.py")
canvas = os.path.join(ROOT, "ui", "canvas.py")
excel_export = os.path.join(ROOT, "core", "excel_export.py")

patch(main_window, [
    (
        "import os\n\nfrom PySide6.QtCore import QObject",
        "import gc\nimport os\n\nfrom PySide6.QtCore import QObject",
    ),
    (
        '        self.act_export = QAction("导出 Excel", self)\n'
        '        self.act_export.setShortcut("Ctrl+E")',
        '        self.act_close = QAction("清空图纸", self)\n'
        '        self.act_close.setShortcut("Ctrl+W")\n'
        '        self.act_close.setToolTip(\n'
        '            "清空图纸（Ctrl+W）：卸下当前图纸、释放实体与绘图缓存并复位视图，\\n"\n'
        '            "方便连续打开多张图纸；不会修改磁盘上的 DWG 文件。")\n'
        '        self.act_close.triggered.connect(self.clear_drawing)\n'
        '        self.act_close.setEnabled(False)\n'
        '\n'
        '        self.act_export = QAction("导出 Excel", self)\n'
        '        self.act_export.setShortcut("Ctrl+E")',
    ),
    (
        "        toolbar.addAction(self.act_open)\n"
        "        toolbar.addSeparator()\n"
        "        toolbar.addAction(self.act_fit)",
        "        toolbar.addAction(self.act_open)\n"
        "        toolbar.addAction(self.act_close)\n"
        "        toolbar.addSeparator()\n"
        "        toolbar.addAction(self.act_fit)",
    ),
    (
        "        file_menu.addAction(self.act_open)\n"
        "        file_menu.addAction(self.act_export)",
        "        file_menu.addAction(self.act_open)\n"
        "        file_menu.addAction(self.act_close)\n"
        "        file_menu.addAction(self.act_export)",
    ),
    (
        "        self.act_open.setEnabled(False)\n\n        self._thread = QThread(self)",
        "        self.act_open.setEnabled(False)\n"
        "        self.act_close.setEnabled(False)  # 读图期间不允许清空，避免新旧模型交叉\n"
        "\n"
        "        self._thread = QThread(self)",
    ),
    (
        "        self._thread = None\n        self._worker = None\n        self.progress.setVisible(False)\n        self.act_open.setEnabled(True)",
        "        self._thread = None\n"
        "        self._worker = None\n"
        "        self.progress.setVisible(False)\n"
        "        self.act_open.setEnabled(True)\n"
        "        self.act_close.setEnabled(self.model is not None)",
    ),
    (
        "        for action in (self.act_export, self.act_fit, self.act_zoom_in, self.act_zoom_out,\n"
        "                       self.act_clear, self.act_delete, self.act_multi):",
        "        for action in (self.act_export, self.act_fit, self.act_zoom_in, self.act_zoom_out,\n"
        "                       self.act_clear, self.act_delete, self.act_multi, self.act_close):",
    ),
    (
        "    @Slot(str)\n    def _on_load_failed(self, message: str) -> None:",
        '    @Slot()\n'
        '    def clear_drawing(self) -> None:\n'
        '        """卸下当前图纸并释放模型、空间索引、折线与画笔缓存。\n'
        '\n'
        '        只动内存，不碰磁盘文件；清空后可立即打开下一张图纸。\n'
        '        """\n'
        '        if self.model is None or self._thread is not None:\n'
        '            return\n'
        '        name = os.path.basename(self.model.path) if self.model.path else "未命名图纸"\n'
        '        count = len(self.model.entities)\n'
        '        # 先断开所有面板/选择/画布对模型的引用，再释放模型本身\n'
        '        self.selection.apply([])\n'
        '        self.history.stack.clear()\n'
        '        self.canvas.set_model(None)\n'
        '        self.layer_panel.bind_model(None)\n'
        '        self.property_panel.set_entities([])\n'
        '        self.selection_panel.set_entities([])\n'
        '        self.model = None\n'
        '        self._last_export = None\n'
        '        self._status_prefix = ""\n'
        '        self.canvas.allowed_types = self.layer_panel.allowed_types()\n'
        '        self.lbl_count.setText("未打开图纸")\n'
        '        self.lbl_coord.setText("X: —   Y: —")\n'
        '        self.lbl_scale.setText("比例: —")\n'
        '        self.setWindowTitle("DWG 坐标导出工具")\n'
        '        self._update_actions(False)\n'
        '        self._refresh_selection()\n'
        '        # 实体点数以万计时，引用释放后交给 GC 回收（CPython 的引用计数已在上面完成大半）\n'
        '        gc.collect()\n'
        '        self.statusBar().showMessage(f"已清空图纸 {name}：释放 {count} 条实体与绘图缓存，可继续打开下一张", 8000)\n'
        '\n'
        '    @Slot(str)\n'
        '    def _on_load_failed(self, message: str) -> None:',
    ),
])

patch(canvas, [
    (
        "        self._coarse_active = False\n"
        "        if model is None or not model.entities:\n"
        "            self.index = None\n"
        "            self.update()\n"
        "            return",
        "        self._coarse_active = False\n"
        "        self._paths_dirty = True\n"
        "        if model is None or not model.entities:\n"
        "            # 清空图纸：空间索引、视图与画笔缓存一并复位，避免残留引用拖住内存\n"
        "            self.index = None\n"
        "            self._origin = (0.0, 0.0)\n"
        "            self.scale = 1.0\n"
        "            self.pan = QPointF(0.0, 0.0)\n"
        "            self._pen_cache.clear()\n"
        "            self._full_points = 0\n"
        "            self.update()\n"
        "            return",
    ),
])

patch(excel_export, [
    ('APP_VERSION = "1.3.4"', 'APP_VERSION = "1.3.5"'),
])

print("补丁完成")
