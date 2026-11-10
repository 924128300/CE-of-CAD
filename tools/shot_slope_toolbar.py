"""真实窗口截图：「反算坡度」开关位于工具栏多选旁。

用法：python tools/shot_slope_toolbar.py [dwg路径]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolBar  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from ui.export_dialog import ExportDialog  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import STYLE_SHEET  # noqa: E402

SHOTS = os.path.join("tools", "screenshots")
WINDOW_SHOT = os.path.join(SHOTS, "_slope_toolbar_on.png")
DIALOG_SHOT = os.path.join(SHOTS, "_slope_dialog_state.png")


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
    window.canvas.fit_view()
    window.act_multi.setChecked(True)
    window.act_slope.setChecked(True)

    lines = [e for e in model.entities if e.dxftype in ("LINE", "LWPOLYLINE")][2:5]
    for entity in lines:
        window._on_entity_picked(entity.handle, True)  # noqa: SLF001
    window.canvas.set_selection(set(window.selection.handles))
    window.show()

    dialog = ExportDialog(model, True, window._sample_step, window._scale_denominator,  # noqa: SLF001
                          len(window.selection), window.act_slope.isChecked(), window)
    dialog.setModal(False)

    def capture() -> None:
        window.grab().save(WINDOW_SHOT)
        dialog.show()
        dialog.adjustSize()

        def shot_dialog() -> None:
            dialog.grab().save(DIALOG_SHOT)
            print("已保存", WINDOW_SHOT, "|", DIALOG_SHOT)
            bar = window.findChildren(QToolBar)[0]
            print("工具栏按钮：", [a.text() for a in bar.actions() if a.text()])
            print("反算坡度已勾选：", window.act_slope.isChecked())
            app.quit()

        QTimer.singleShot(500, shot_dialog)

    QTimer.singleShot(1200, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
