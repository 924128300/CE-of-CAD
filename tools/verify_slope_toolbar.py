"""验证「反算坡度」开关已在工具栏（多选旁），并端到端检查导出结果。

用法：python tools/verify_slope_toolbar.py [dwg路径]
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


def _first_line(model):
    """挑一条高差最大的多段线，让坡度验证有非零数值。"""
    best, best_dz = None, -1.0
    for entity in model.entities:
        if entity.dxftype in ("LINE", "LWPOLYLINE", "POLYLINE_3D", "POLYLINE_2D"):
            if len(entity.points) >= 2:
                zs = [p[2] for p in entity.points]
                dz = max(zs) - min(zs)
                if dz > best_dz:
                    best, best_dz = entity, dz
    if best is None:
        raise SystemExit("没有找到可用的多段线")
    print(f"选用要素 handle={best.handle}，高差 {best_dz:.3f}")
    return best


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"
    app = QApplication.instance() or QApplication(sys.argv[:1])
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
    window._update_actions(True)  # noqa: SLF001
    window.act_multi.setChecked(True)
    window.act_slope.setChecked(True)
    window._on_entity_picked(_first_line(model).handle, True)  # noqa: SLF001
    window.show()
    app.processEvents()

    stamp = _dt.datetime.now().strftime("%H%M%S")
    toolbar_shot = os.path.join(SHOTS, "_slope_toolbar_on.png")
    os.makedirs(SHOTS, exist_ok=True)
    window.grab().save(toolbar_shot)

    dialog = ExportDialog(model, True, window._sample_step, window._scale_denominator,  # noqa: SLF001
                          1, window.act_slope.isChecked(), window)
    dialog.show()
    app.processEvents()
    dialog_shot = os.path.join(SHOTS, "_slope_dialog_state.png")
    dialog.grab().save(dialog_shot)

    results = {}
    for enabled in (True, False):
        window.act_slope.setChecked(enabled)
        app.processEvents()
        dialog2 = ExportDialog(model, True, 1.0, window._scale_denominator, 1,  # noqa: SLF001
                               window.act_slope.isChecked(), window)
        options = dialog2.options()
        out = os.path.join(SHOTS, f"_slope_toolbar_{'on' if enabled else 'off'}_{stamp}.xlsx")
        options.path = out
        export_excel(model, [window.model.get(h) for h in window.selection.handles], options)
        wb = load_workbook(out)
        ws = wb["坐标计算表"] if "坐标计算表" in wb.sheetnames else wb[wb.sheetnames[0]]
        cell = ws["D9"]
        results[enabled] = (cell.value, cell.number_format, out)
        dialog2.close()

    print("工具栏动作：", window.act_slope.text(), "| 可勾选", window.act_slope.isCheckable(),
          "| 快捷键", window.act_slope.shortcut().toString())
    for enabled, (value, fmt, out) in results.items():
        print(f"勾选={enabled}：D9 = {value!r}，格式 {fmt} -> {out}")
    print("截图：", toolbar_shot, "|", dialog_shot)
    assert results[True][0] is not None, "开启后坡度应由程序反算"
    assert results[False][0] is None, "关闭后坡度应留空"
    window.close()
    print("验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
