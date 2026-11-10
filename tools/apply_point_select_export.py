"""导出与面板支持点选块：块标题、选择方式信息行、对话框文案、版本号。"""
from __future__ import annotations

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patch(rel: str, patches: list[tuple[str, str]]) -> None:
    path = os.path.join(ROOT, rel)
    with io.open(path, encoding="utf-8", newline="") as handle:
        raw = handle.read()
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n") if crlf else raw
    for index, (old, new) in enumerate(patches, start=1):
        if text.count(old) != 1:
            raise SystemExit(f"{rel} 锚点 {index} 匹配 {text.count(old)} 次：{old[:70]!r}")
        text = text.replace(old, new)
    if crlf:
        text = text.replace("\n", "\r\n")
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    print(f"{rel} 已更新")


patch("core/excel_export.py", [
    ('APP_VERSION = "1.4.0"', 'APP_VERSION = "1.5.0"'),
    ('''    fill_slope: bool = False
    reversed_count: int = 0''',
     '''    fill_slope: bool = False
    reversed_count: int = 0
    # 点选模式：每轮点选各占一块，取点规则固定为「按点选顺序」
    pick_mode: bool = False'''),
    ('''        ("要素数量", len(entities)),
        ("点总数", point_total),
    ]''',
     '''        ("选择方式", "点选（按端点顺序连线，每轮一块）" if options.pick_mode
         else "线选（整条线按取点规则取点）"),
        ("要素数量", len(entities)),
        ("点总数", point_total),
    ]'''),
    ('''    samples = [
        block_points(entity, options.include_vertices, options.sample_step)
        for entity in entities
    ]''',
     '''    # 点选块只导出被点中的那些点，不再按间距插值
    samples = [
        block_points(entity,
                     True if entity.dxftype == "PICK" else options.include_vertices,
                     options.sample_step)
        for entity in entities
    ]'''),
    ('''    for index, (points, cumulative) in enumerate(samples, start=1):''',
     '''    for index, (points, cumulative) in enumerate(samples, start=1):
        entity = entities[index - 1]
        title = f"点选{index}" if entity.dxftype == "PICK" else f"线{index}"'''),
    ('''        row = write_block(ws, row, points, spans, f"线{index}", factor, symbol, slopes)''',
     '''        row = write_block(ws, row, points, spans, title, factor, symbol, slopes)'''),
])

patch("ui/property_panel.py", [
    ('''    "POINT": "点",
}''',
     '''    "POINT": "点",
    "PICK": "点选路径",
}'''),
    ('''        parts = []
        if len(entities) > 1:
            parts.append(f"共选中 {len(entities)} 条，显示第 1 条")
        if flipped:
            parts.append("已反向")''',
     '''        parts = []
        if entity.dxftype == "PICK":
            parts.append(f"点选块 {entity.layer}（{len(entity.points)} 点）")
        if len(entities) > 1:
            parts.append(f"共选中 {len(entities)} 条，显示第 1 条")
        if flipped:
            parts.append("已反向")'''),
    ('''        self.title.setToolTip("导出时每条线各占一块（9 行），块与块之间空一行")''',
     '''        self.title.setToolTip(
            "线选：每条线一块；点选：每轮点选一块。各块 9 行，块间空一行")'''),
])

patch("ui/export_dialog.py", [
    ('''    def __init__(self, model: DrawingModel, include_vertices: bool = True,
                 sample_step: float = 1.0, scale_denominator: int = DEFAULT_SCALE,
                 entity_count: int = 0, fill_slope: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出坐标计算表")
        self.setMinimumWidth(560)
        self._model = model
        self._fill_slope = bool(fill_slope)''',
     '''    def __init__(self, model: DrawingModel, include_vertices: bool = True,
                 sample_step: float = 1.0, scale_denominator: int = DEFAULT_SCALE,
                 entity_count: int = 0, fill_slope: bool = False, parent=None,
                 pick_mode: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出坐标计算表")
        self.setMinimumWidth(560)
        self._model = model
        self._fill_slope = bool(fill_slope)
        self._pick_mode = bool(pick_mode)'''),
    ('''        if entity_count > 1:
            summary = QLabel(f"本次导出 {entity_count} 条线：每条线各占一块（9 行），"
                             f"块与块之间空一行，全部写在同一张 sheet 里。")
            summary.setWordWrap(True)
            summary.setStyleSheet("color:#8a97a6;")
            layout.addWidget(summary)
        elif entity_count == 1:
            layout.addWidget(QLabel("本次导出 1 条线。"))''',
     '''        unit = "轮点选" if self._pick_mode else "条线"
        if entity_count > 1:
            summary = QLabel(f"本次导出 {entity_count} {unit}：每{'轮' if self._pick_mode else '条'}"
                             f"各占一块（9 行），块与块之间空一行，全部写在同一张 sheet 里。")
            summary.setWordWrap(True)
            summary.setStyleSheet("color:#8a97a6;")
            layout.addWidget(summary)
        elif entity_count == 1:
            layout.addWidget(QLabel(f"本次导出 1 {unit}。"))'''),
    ('''        self.radio_vertices.toggled.connect(lambda checked: self.step_spin.setEnabled(not checked))
        self.step_spin.setEnabled(self.radio_step.isChecked())''',
     '''        self.radio_vertices.toggled.connect(lambda checked: self.step_spin.setEnabled(not checked))
        self.step_spin.setEnabled(self.radio_step.isChecked())
        if self._pick_mode:
            # 点选块只输出被点中的点，取点规则固定为「仅顶点」
            self.radio_vertices.setChecked(True)
            self.radio_step.setEnabled(False)
            self.step_spin.setEnabled(False)'''),
    ('''        tip = QLabel(
            "输出为「采场矿房坐标计算表」版本：每个点占两列合并，点号、X/Y/Z 坐标逐点排列；"''',
     '''        if self._pick_mode:
            pick_tip = QLabel(
                "点选模式：每一轮点选按单击顺序导出为一整块（左侧「工程名称」写作「点选N」），"
                "点号按点选顺序排列，平距与方位由相邻两点直接计算，坡度同样按相邻两点反算。")
            pick_tip.setWordWrap(True)
            pick_tip.setStyleSheet("color:#8a97a6;")
            layout.addWidget(pick_tip)

        tip = QLabel(
            "输出为「采场矿房坐标计算表」版本：每个点占两列合并，点号、X/Y/Z 坐标逐点排列；"'''),
])
