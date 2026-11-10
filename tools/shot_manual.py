"""生成说明书用的界面截图（真实窗口渲染，非合成图）。

用法：python tools/shot_manual.py [dwg路径]
输出：copyright/05_截图/*.png
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from core.excel_export import DEFAULT_SCALE  # noqa: E402
from ui.export_dialog import ExportDialog  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import STYLE_SHEET  # noqa: E402

OUT_DIR = os.path.join("copyright", "05_截图")
DEFAULT_FILE = "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
    os.makedirs(OUT_DIR, exist_ok=True)

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
    window.setWindowTitle(f"矿山测量图纸坐标提取与导出软件 V1.3.2 - {os.path.basename(model.path)}")
    window._update_actions(True)  # noqa: SLF001
    window.show()

    lines = [e for e in model.entities if e.dxftype in ("LINE", "LWPOLYLINE")]

    def save(name: str) -> None:
        full = os.path.join(OUT_DIR, name)
        window.grab().save(full)
        print("已保存", full)

    def step1() -> None:
        save("01_主界面.png")
        # 单条选中：属性面板出现起点/终点/长度/方位角
        window._on_entity_picked(lines[0].handle, False)  # noqa: SLF001
        window.canvas.set_current(lines[0].handle)
        QTimer.singleShot(300, step2)

    def step2() -> None:
        save("02_选中要素与属性.png")
        # 多选：连续追加三条
        window.act_multi.setChecked(True)
        for entity in lines[1:4]:
            window._on_entity_picked(entity.handle, True)  # noqa: SLF001
        QTimer.singleShot(300, step3)

    def step3() -> None:
        save("03_多选与待导出列表.png")
        window.canvas.zoom_by(12.0)
        QTimer.singleShot(300, step4)

    def step4() -> None:
        save("04_图纸缩放.png")
        dialog = ExportDialog(model, True, 1.0, DEFAULT_SCALE,
                             len(window.selection), window)
        dialog.show()
        QApplication.processEvents()
        dialog.grab().save(os.path.join(OUT_DIR, "05_导出对话框.png"))
        print("已保存", os.path.join(OUT_DIR, "05_导出对话框.png"))
        dialog.close()
        app.quit()

    QTimer.singleShot(600, step1)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
