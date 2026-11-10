"""一次性补丁：把「反算坡度」开关从导出对话框移到主界面工具栏（多选按钮旁）。

版本：V1.3.3 -> V1.3.4
"""
from __future__ import annotations

import io
import os
import sys

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
        if old not in text:
            raise SystemExit(f"[失败] {os.path.basename(path)} 未找到锚点：\n{old[:120]}")
        if text.count(old) != 1:
            raise SystemExit(f"[失败] {os.path.basename(path)} 锚点不唯一：\n{old[:120]}")
        text = text.replace(old, new, 1)
    write(path, text)
    print(f"[完成] {os.path.basename(path)}")


main_window = os.path.join(ROOT, "ui", "main_window.py")
export_dialog = os.path.join(ROOT, "ui", "export_dialog.py")

patch(main_window, [
    (
        "        self._fill_slope = False  # 反算坡度：启动默认关闭，勾选后在本次运行内记住",
        "        self._fill_slope = False  # 反算坡度：工具栏开关状态，启动默认关闭",
    ),
    (
        '        self.act_multi.toggled.connect(self._on_multi_toggled)\n'
        '        self.act_multi.setEnabled(False)\n',
        '        self.act_multi.toggled.connect(self._on_multi_toggled)\n'
        '        self.act_multi.setEnabled(False)\n'
        '\n'
        '        self.act_slope = QAction("反算坡度", self)\n'
        '        self.act_slope.setCheckable(True)\n'
        '        self.act_slope.setShortcut("S")\n'
        '        self.act_slope.setToolTip(\n'
        '            "反算坡度（默认关闭）：打开后导出时按相邻两点高差 ÷ 水平距离计算坡度，\\n"\n'
        '            "以 0.00% 写入坡度行，上坡为正、下坡为负；关闭时坡度行留空由你填写。")\n'
        '        self.act_slope.toggled.connect(self._on_slope_toggled)\n',
    ),
    (
        "        toolbar.addAction(self.act_multi)\n"
        "        toolbar.addSeparator()\n"
        "        toolbar.addAction(self.act_export)",
        "        toolbar.addAction(self.act_multi)\n"
        "        toolbar.addAction(self.act_slope)\n"
        "        toolbar.addSeparator()\n"
        "        toolbar.addAction(self.act_export)",
    ),
    (
        '    def _on_multi_toggled(self, enabled: bool) -> None:\n'
        '        self.canvas.set_additive_mode(enabled)\n'
        '        if enabled:\n'
        '            self.statusBar().showMessage(\n'
        '                "多选模式：连续单击即可追加/取消选中；导出时每条线各占一块，块与块之间空一行", 6000)\n',
        '    def _on_multi_toggled(self, enabled: bool) -> None:\n'
        '        self.canvas.set_additive_mode(enabled)\n'
        '        if enabled:\n'
        '            self.statusBar().showMessage(\n'
        '                "多选模式：连续单击即可追加/取消选中；导出时每条线各占一块，块与块之间空一行", 6000)\n'
        '\n'
        '    def _on_slope_toggled(self, enabled: bool) -> None:\n'
        '        self._fill_slope = enabled\n'
        '        self.statusBar().showMessage(\n'
        '            "反算坡度：已开启，导出时按 0.00% 自动填写坡度行"\n'
        '            if enabled else "反算坡度：已关闭，导出时坡度行留空由你填写", 6000)\n',
    ),
    (
        "        options: ExportOptions = dialog.options()\n"
        "        self._fill_slope = options.fill_slope\n",
        "        options: ExportOptions = dialog.options()\n",
    ),
])

patch(export_dialog, [
    (
        "        self._model = model\n",
        "        self._model = model\n"
        "        self._fill_slope = bool(fill_slope)\n",
    ),
    (
        '        self.check_slope = QCheckBox("反算坡度（相邻两点高差 ÷ 水平距离，按 0.00% 写入）")\n'
        '        self.check_slope.setChecked(fill_slope)\n'
        '        self.check_slope.setToolTip(\n'
        '            "默认关闭，坡度行留空由你填写。打开后按图纸原值反算：\\n"\n'
        '            "上坡为正、下坡为负，保留两位小数（如 -1.00%）。\\n"\n'
        '            "高差与水平距离同取图纸原值，因此与比例尺、坐标单位无关。")\n'
        '        option_layout.addWidget(self.check_slope)\n',
        '        slope_hint = QLabel(\n'
        '            "坡度：已反算（主界面工具栏「反算坡度」已开启）——"\n'
        '            "相邻两点高差 ÷ 水平距离，按 0.00% 写入，上坡为正、下坡为负。"\n'
        '            if self._fill_slope else\n'
        '            "坡度：留空待填（主界面工具栏「反算坡度」未开启；需要自动反算时"\n'
        '            "关闭本对话框，在工具栏打开该开关）。")\n'
        '        slope_hint.setWordWrap(True)\n'
        '        slope_hint.setStyleSheet("color:#8a97a6;")\n'
        '        option_layout.addWidget(slope_hint)\n',
    ),
    (
        '            "坡度默认留空，勾选上方开关后自动反算。\\n"',
        '            "坡度默认留空，在主界面工具栏打开「反算坡度」后自动填入。\\n"',
    ),
    (
        "            fill_slope=self.check_slope.isChecked(),",
        "            fill_slope=self._fill_slope,",
    ),
])

version_file = os.path.join(ROOT, "core", "excel_export.py")
patch(version_file, [
    ('APP_VERSION = "1.3.3"', 'APP_VERSION = "1.3.4"'),
])

print("补丁全部完成")
sys.exit(0)
