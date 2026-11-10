"""真实窗口截图：工具栏「清空图纸」按钮，以及清空后的空工作区。

用法：python tools/shot_clear_button.py [dwg路径]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import STYLE_SHEET  # noqa: E402

SHOTS = os.path.join("tools", "screenshots")
LOADED_SHOT = os.path.join(SHOTS, "_clear_button.png")
CLEARED_SHOT = os.path.join(SHOTS, "_cleared_workspace.png")


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

    lines = [e for e in model.entities if e.dxftype in ("LINE", "LWPOLYLINE")][2:6]
    for entity in lines:
        window._on_entity_picked(entity.handle, True)  # noqa: SLF001
    window.canvas.set_selection(set(window.selection.handles))
    window.show()

    def shoot_loaded() -> None:
        window.grab().save(LOADED_SHOT)
        print("已保存", LOADED_SHOT, "| 清空按钮可用", window.act_close.isEnabled())
        window.act_close.trigger()
        app.processEvents()
        QTimer.singleShot(900, shoot_cleared)

    def shoot_cleared() -> None:
        window.grab().save(CLEARED_SHOT)
        print("已保存", CLEARED_SHOT, "| 清空后模型", window.model,
              "| 清空按钮可用", window.act_close.isEnabled())
        app.quit()

    QTimer.singleShot(1200, shoot_loaded)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
