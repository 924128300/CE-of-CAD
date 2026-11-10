"""验证多选模式与多线导出（同 sheet、块间空一行）。

用法：python tools/verify_multiselect.py [dwg路径]
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import load_workbook  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from core.excel_export import ExportOptions, export_excel  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

DEFAULT_FILE = "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
    app = QApplication.instance() or QApplication([])
    model = load_dwg(path)
    prepared = build_geometry(model.entities, model.origin, model.bbox)

    window = MainWindow()
    window.resize(1400, 880)
    window.model = model
    window.canvas.set_model(model, prepared)
    window.layer_panel.bind_model(model)
    window._update_actions(True)  # noqa: SLF001

    # 1) 多选模式开关
    window.act_multi.setChecked(True)
    print("多选模式已开启:", window.canvas._additive_mode)  # noqa: SLF001

    # 2) 连续三次单击（additive=True）模拟追加
    lines = [e for e in model.entities if e.dxftype in ("LINE", "LWPOLYLINE")][:3]
    for entity in lines:
        window._on_entity_picked(entity.handle, True)  # noqa: SLF001
    print("已选条数:", len(window.selection), "| 列表标题:", window.selection_panel.title.text())
    assert len(window.selection) == 3, "追加选中失败"

    # 3) 再次单击同一条 = 取消
    window._on_entity_picked(lines[0].handle, True)  # noqa: SLF001
    remaining = len(window.selection)
    window._on_entity_picked(lines[0].handle, True)  # noqa: SLF001
    print("再次单击可取消 / 恢复:", remaining, "->", len(window.selection))
    assert remaining == 2 and len(window.selection) == 3

    # 4) 导出到同一张 sheet
    out = os.path.join("tools", "screenshots", "_multiselect.xlsx")
    entities = [model.get(h) for h in window.selection.handles]
    result = export_excel(model, [e for e in entities if e], ExportOptions(path=out))
    print(f"导出: {result.line_rows} 条线 / {result.point_rows} 个点 -> {out}")

    ws = load_workbook(out)["坐标计算表"]
    starts = [1, 11, 21]
    titles = [ws.cell(row=row, column=3).value for row in starts]
    blanks = [row for row in (10, 20) if any(ws.cell(row=row, column=col).value
                                            for col in range(1, 13))]
    print("块标题:", titles, "| 块间空行被占用:", blanks)
    assert titles == ["线1", "线2", "线3"], titles
    assert not blanks, blanks

    window.canvas.set_selection(set(window.selection.handles))
    window.canvas.set_current(lines[1].handle)
    image = window.grab()
    image.save(os.path.join("tools", "screenshots", "_multiselect.png"))
    print("界面截图: tools/screenshots/_multiselect.png")
    window.close()
    app.processEvents()
    print("全部检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
