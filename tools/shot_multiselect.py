"""真实窗口截图：多选模式 + 3 条线进入待导出列表。

用法：python tools/shot_multiselect.py [dwg路径]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import STYLE_SHEET  # noqa: E402

OUT = os.path.join("tools", "screenshots", "_multiselect_ui.png")


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)
    app.setFont(QFont("Microsoft YaHei UI", 9))

    model = load_dwg(path)
    prepared = build_geometry(model.entities, model.origin, model.bbox)
    window = MainWindow()
    window.resize(1400, 880)
    window.model = model
    window.canvas.set_model(model, prepared)
    window.layer_panel.bind_model(model)
    window.setWindowTitle(f"DWG 坐标导出工具 - {os.path.basename(model.path)}")
    window._update_actions(True)  # noqa: SLF001
    window.act_multi.setChecked(True)

    lines = [e for e in model.entities if e.dxftype in ("LINE", "LWPOLYLINE")][2:5]
    for entity in lines:
        window._on_entity_picked(entity.handle, True)  # noqa: SLF001
    window.canvas.set_selection(set(window.selection.handles))
    window.canvas.set_current(lines[1].handle)
    window.show()

    def capture() -> None:
        image = window.grab()
        image.save(OUT)
        print("已保存", OUT, "| 选中", len(window.selection), "条")
        app.quit()

    QTimer.singleShot(900, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
