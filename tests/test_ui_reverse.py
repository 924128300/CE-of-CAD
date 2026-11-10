"""界面回归：反向按钮、粉色高亮、点序方向展示与撤销。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from core.excel_export import ExportOptions  # noqa: E402
from core.model import DrawingModel, EntityRecord, LayerInfo  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

_APP = QApplication.instance() or QApplication([])

POINTS = [(0.0, 0.0, 0.0), (10.0, 0.0, 1.0), (10.0, 10.0, 2.0)]


def _model() -> DrawingModel:
    entity = EntityRecord(
        handle=7,
        dxftype="LWPOLYLINE",
        layer="0",
        color=(255, 255, 255),
        points=list(POINTS),
        bbox=(0.0, 0.0, 10.0, 10.0),
    )
    return DrawingModel(
        path="D:/tmp/反向界面.dwg",
        version="AC1015",
        entities=[entity],
        layers={"0": LayerInfo("0", entity_count=1)},
        bbox=(0.0, 0.0, 10.0, 10.0),
    )


def _window_with_model() -> MainWindow:
    window = MainWindow()
    window.resize(1000, 700)
    window.canvas.resize(520, 420)
    model = _model()
    window.model = model
    window.canvas.set_model(model)
    window.layer_panel.bind_model(model)
    window._update_actions(True)  # noqa: SLF001
    window.selection.apply([7])
    window._refresh_selection()  # noqa: SLF001
    return window


def test_reverse_action_flips_order_colour_and_panels() -> None:
    window = _window_with_model()
    assert window.act_reverse.isEnabled()
    assert window.act_reverse.text() == "反向"
    assert window.act_reverse.shortcut().toString() == "R"
    assert window.canvas.reversed == set()
    assert window._view_entities()[0].first == POINTS[0]  # noqa: SLF001
    normal = window.canvas.grab().toImage()

    window.act_reverse.trigger()
    assert window.selection.is_reversed(7)
    assert window.canvas.reversed == {7}
    flipped = window._view_entities()[0]  # noqa: SLF001
    assert flipped.first == POINTS[-1]
    assert flipped.last == POINTS[0]
    assert "已反向" in window.property_panel.title.text()
    assert window.property_panel.values["direction"].text() == "已反向（按新方向输出）"
    assert window.selection_panel.model.data(
        window.selection_panel.model.index(0, 5)) == "已反向"
    assert "已反向 1" in window.lbl_count.text()
    reversed_image = window.canvas.grab().toImage()
    assert normal != reversed_image, "反向高亮应换成另一种颜色"

    window.history.undo()
    assert not window.selection.is_reversed(7)
    assert window.property_panel.values["direction"].text() == "正向"
    window.history.redo()
    assert window.selection.is_reversed(7)

    window.clear_drawing()
    assert window.selection.reversed_handles == set()
    window.close()


def test_reverse_without_selection_is_noop() -> None:
    window = MainWindow()
    assert window.act_reverse.isEnabled() is False
    window._reverse_order()  # noqa: SLF001 - 不应抛异常
    assert window.selection.reversed_handles == set()
    window.close()


def test_main_window_exports_reversed_order(monkeypatch, tmp_path) -> None:
    window = _window_with_model()
    window.act_reverse.trigger()
    target = tmp_path / "反向导出.xlsx"

    class _FakeDialog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def exec(self) -> bool:
            return True

        def options(self) -> ExportOptions:
            return ExportOptions(path=str(target))

    monkeypatch.setattr("ui.main_window.ExportDialog", _FakeDialog)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    window.export_excel()

    assert target.exists()
    wb = load_workbook(target)
    ws = wb["坐标计算表"]
    assert ws["C6"].value == 10
    assert ws["G6"].value == 0
    info = wb["导出信息"]
    values = [info.cell(row=row, column=1).value for row in range(2, info.max_row + 1)]
    key = values.index("点序方向") + 2
    assert "已反向" in info.cell(row=key, column=2).value
    window.close()
