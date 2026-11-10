"""真实图纸验证：点选模式的吸附、轮次、重合呼吸提示与导出结果。

用法：python tools/verify_point_select.py [dwg路径]
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QTimer, Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from core.excel_export import ExportOptions, export_excel  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import STYLE_SHEET  # noqa: E402

SHOTS = os.path.join("tools", "screenshots")
SHOT_PICKING = os.path.join(SHOTS, "_point_picking.png")
SHOT_MATCHED = os.path.join(SHOTS, "_point_matched.png")
SHOT_ROUNDS = os.path.join(SHOTS, "_point_rounds.png")
XLSX = os.path.join(SHOTS, "_point_select.xlsx")


def pick_line(model):
    """挑一条 5~8 点、形状展开的开口多段线，便于看清点选顺序。"""
    fallback = None
    for entity in model.entities:
        if entity.dxftype not in ("LWPOLYLINE", "POLYLINE_2D", "POLYLINE_3D"):
            continue
        if not 5 <= len(entity.points) <= 8:
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
    canvas.scale = min(canvas.width() * 0.5 / span_x, canvas.height() * 0.5 / span_y)
    canvas.center_on(entity.handle)
    canvas.pick_hover = None


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)
    app.setFont(QFont("Microsoft YaHei UI", 9))

    model = load_dwg(path)
    prepared = build_geometry(model.entities, model.origin, model.bbox)
    entity = pick_line(model)
    points = list(entity.points)
    print(f"选用要素 handle={entity.handle} 点数={len(points)} 闭合={entity.closed}", flush=True)

    window = MainWindow()
    window.resize(1400, 880)
    window.model = model
    window.canvas.allowed_types = window.layer_panel.allowed_types()
    window.canvas.set_model(model, prepared)
    window.layer_panel.bind_model(model)
    window.setWindowTitle(f"DWG 坐标导出工具 - {os.path.basename(model.path)}")
    window._update_actions(True)  # noqa: SLF001
    window.show()
    app.processEvents()
    focus_entity(window.canvas, entity)
    app.processEvents()

    def run() -> None:
        try:
            _run()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            app.quit()

    def _run() -> None:
        canvas = window.canvas
        window.act_mode_point.trigger()
        app.processEvents()
        canvas.update()
        app.processEvents()

        canvas._ensure_snap()  # noqa: SLF001
        marker_count = (canvas._snap_path.elementCount()  # noqa: SLF001
                        if canvas._snap_path is not None else 0)
        print("载入端点数:", len(canvas._snap or ()), "| 标记路径元素:", marker_count, flush=True)

        positions = [canvas.to_screen(p[0], p[1]).toPoint() for p in points]
        print("各端点屏幕坐标:", [(p.x(), p.y()) for p in positions], flush=True)

        # 前三个点逐个单击
        for index in range(min(3, len(points))):
            QTest.mouseClick(canvas, Qt.LeftButton, pos=positions[index])
            app.processEvents()
        window.grab().save(SHOT_PICKING)
        print("已点选 3 点，吸附坐标:", [p[:3] for p in window.picks.block_points()[0]], flush=True)

        # 剩下的一次点完，与整条多段线重合
        for index in range(3, len(points)):
            QTest.mouseClick(canvas, Qt.LeftButton, pos=positions[index])
            app.processEvents()
        canvas._breath_phase = 0.0  # noqa: SLF001 - 截「暗」相位
        canvas.update()
        app.processEvents()
        window.grab().save(SHOT_MATCHED)
        print("重合句柄:", canvas._match_handle, "| 呼吸动画:",  # noqa: SLF001
              canvas._breath_timer.isActive(), flush=True)  # noqa: SLF001

        # 第二轮：只点一个点，验证分轮
        QTest.keyClick(canvas, Qt.Key_Space)
        app.processEvents()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=positions[0])
        app.processEvents()
        print("轮次:", window.picks.round_count, "| 当前轮点数:",
              window.picks.current_length, flush=True)
        window.grab().save(SHOT_ROUNDS)

        opts = ExportOptions(path=XLSX, include_info=True, pick_mode=True)
        result = export_excel(model, window.picks.entities(), opts)
        print("导出:", result.line_rows, "块", result.point_rows, "点", flush=True)

        ws = load_workbook(XLSX)["坐标计算表"]
        columns = [3 + 2 * i for i in range(len(points))]
        xs = [ws.cell(row=6, column=col).value for col in columns]
        ys = [ws.cell(row=7, column=col).value for col in columns]
        zs = [ws.cell(row=8, column=col).value for col in columns]
        spans = [ws.cell(row=3, column=4 + 2 * i).value for i in range(len(points) - 1)]
        az = [ws.cell(row=5, column=4 + 2 * i).value for i in range(len(points) - 1)]
        print("标题:", ws["C1"].value, "| 点号:",
              [ws.cell(row=2, column=col).value for col in columns], flush=True)
        print("导出 X:", xs, flush=True)
        print("图纸 X:", [round(p[0], 4) for p in points], flush=True)
        print("导出 Y:", ys, flush=True)
        print("导出 Z:", zs, flush=True)
        print("平距:", spans, flush=True)
        print("方位:", az, flush=True)
        same = all(abs((x or 0) - p[0]) < 1e-4 for x, p in zip(xs, points)) and \
            all(abs((y or 0) - p[1]) < 1e-4 for y, p in zip(ys, points)) and \
            all(abs((z or 0) - p[2]) < 1e-4 for z, p in zip(zs, points))
        print("坐标与图纸顶点一致:", same, flush=True)
        print("截图:", SHOT_PICKING, "|", SHOT_MATCHED, "|", SHOT_ROUNDS, flush=True)
        app.quit()

    QTimer.singleShot(1200, run)
    QTimer.singleShot(30000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
