"""真实窗口截图 + 导出核对：点序编号、方向箭头、反向粉色高亮。

用法：python tools/shot_reverse_order.py [dwg路径]
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from core.excel_export import ExportOptions, export_excel  # noqa: E402
from ui.export_dialog import ExportDialog  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import STYLE_SHEET  # noqa: E402

SHOTS = os.path.join("tools", "screenshots")
BEFORE_SHOT = os.path.join(SHOTS, "_reverse_before.png")
AFTER_SHOT = os.path.join(SHOTS, "_reverse_after.png")


def pick_line(model):
    """优先选一条首尾不重合、形状展开的 4~8 点多段线，便于看清方向。"""
    fallback = None
    for entity in model.entities:
        if entity.dxftype not in ("LWPOLYLINE", "POLYLINE_2D", "POLYLINE_3D"):
            continue
        if not 4 <= len(entity.points) <= 8:
            continue
        x0, y0, x1, y1 = entity.bbox
        if x1 - x0 <= 0.5 or y1 - y0 <= 0.5:
            continue
        if entity.closed or entity.points[0] == entity.points[-1]:
            fallback = fallback or entity
            continue
        return entity
    if fallback is not None:
        return fallback
    raise SystemExit("没有找到合适的多段线")


def focus_entity(canvas, entity) -> None:
    x0, y0, x1, y1 = entity.bbox
    span_x = max(x1 - x0, 1e-6)
    span_y = max(y1 - y0, 1e-6)
    canvas.scale = min(canvas.width() * 0.55 / span_x, canvas.height() * 0.55 / span_y)
    canvas.center_on(entity.handle)


def read_sheet(path: str):
    ws = load_workbook(path)["坐标计算表"]
    xs = [ws.cell(row=6, column=3 + 2 * i).value for i in range(6)]
    az = [ws.cell(row=5, column=4 + 2 * i).value for i in range(6)]
    spans = [ws.cell(row=3, column=4 + 2 * i).value for i in range(6)]
    return xs, az, spans


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)
    app.setFont(QFont("Microsoft YaHei UI", 9))

    model = load_dwg(path)
    prepared = build_geometry(model.entities, model.origin, model.bbox)
    entity = pick_line(model)
    print(f"选用要素 handle={entity.handle}，点数 {len(entity.points)}")

    window = MainWindow()
    window.resize(1400, 880)
    window.model = model
    window.canvas.set_model(model, prepared)
    window.layer_panel.bind_model(model)
    window.setWindowTitle(f"DWG 坐标导出工具 - {os.path.basename(model.path)}")
    window._update_actions(True)  # noqa: SLF001
    window.selection.apply([entity.handle])
    window.selection_panel.focus_entity(entity.handle)
    window.show()
    app.processEvents()
    focus_entity(window.canvas, entity)

    dialog = ExportDialog(model, True, window._sample_step, window._scale_denominator,  # noqa: SLF001
                          1, window.act_slope.isChecked(), window)
    dialog.setModal(False)

    def run() -> None:
        try:
            _run()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            app.quit()

    def _run() -> None:
        print("开始截图", flush=True)
        canvas = window.canvas
        canvas.update()
        app.processEvents()
        window.grab().save(BEFORE_SHOT)
        before_xlsx = os.path.join(SHOTS, "_reverse_before.xlsx")
        opts = dialog.options()
        opts.path = before_xlsx
        opts.include_info = False
        export_excel(model, window._view_entities(), opts)  # noqa: SLF001

        window.act_reverse.trigger()
        app.processEvents()
        canvas.update()
        app.processEvents()
        window.grab().save(AFTER_SHOT)
        after_xlsx = os.path.join(SHOTS, "_reverse_after.xlsx")
        opts2 = dialog.options()
        opts2.path = after_xlsx
        opts2.include_info = False
        export_excel(model, window._view_entities(), opts2)  # noqa: SLF001

        n = len(entity.points)
        xs0, az0, sp0 = read_sheet(before_xlsx)
        xs1, az1, sp1 = read_sheet(after_xlsx)
        print("原方向 X:", xs0[:n])
        print("反向后 X:", xs1[:n])
        print("原方向方位:", az0[:n - 1])
        print("反向后方位:", az1[:n - 1])
        print("原方向平距:", sp0[:n - 1])
        print("反向后平距:", sp1[:n - 1])
        print("反向标志:", window.selection.is_reversed(entity.handle),
              "| 画布反向集合:", window.canvas.reversed)
        print("截图：", BEFORE_SHOT, "|", AFTER_SHOT)
        ok = (xs1[:n] == list(reversed(xs0[:n]))
              and sp1[:n - 1] == list(reversed(sp0[:n - 1])))
        print("点数/坐标/平距倒序一致：", ok)
        app.quit()

    QTimer.singleShot(1200, run)
    QTimer.singleShot(25000, app.quit)  # 兜底，避免异常时窗口一直挂着
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
