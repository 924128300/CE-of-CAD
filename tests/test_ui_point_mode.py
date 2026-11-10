"""界面回归：模式切换、端点吸附、右键撤点、空格换轮、重合呼吸与点选导出。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
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
        path="D:/tmp/点选界面.dwg",
        version="AC1015",
        entities=[entity],
        layers={"0": LayerInfo("0", entity_count=1)},
        bbox=(0.0, 0.0, 10.0, 10.0),
    )


def _window() -> MainWindow:
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    QApplication.processEvents()
    window.canvas.resize(520, 420)
    window.canvas.allowed_types = window.layer_panel.allowed_types()
    window.model = _model()
    window.canvas.set_model(window.model)
    window.canvas.scale = 20.0
    window.canvas.pan.setX(0.0)
    window.canvas.pan.setY(0.0)
    window._update_actions(True)  # noqa: SLF001
    window._refresh_selection()  # noqa: SLF001
    return window


def _pos(window: MainWindow, point) -> "object":
    return window.canvas.to_screen(point[0], point[1]).toPoint()


def _click(window: MainWindow, point, button=Qt.LeftButton) -> None:
    QTest.mouseClick(window.canvas, button, pos=_pos(window, point))


def test_mode_switch_and_actions() -> None:
    window = _window()
    assert window.act_mode_line.isChecked() and not window.act_mode_point.isChecked()
    assert window.canvas.mode == "line"
    assert window.canvas.cursor().shape() == Qt.ArrowCursor

    window.act_mode_point.trigger()
    assert window._mode == "point"  # noqa: SLF001
    assert window.canvas.mode == "point"
    assert window.canvas.cursor().shape() == Qt.CrossCursor
    assert window.act_mode_point.isChecked() and not window.act_mode_line.isChecked()
    assert not window.act_multi.isEnabled()
    assert not window.act_reverse.isEnabled()
    assert not window.act_delete.isEnabled()
    assert not window.radio_vertices.isEnabled(), "点选模式隐藏取点规则"
    assert not window.step_spin.isEnabled()

    window.act_mode_line.trigger()
    assert window.canvas.mode == "line"
    assert window.canvas.cursor().shape() == Qt.ArrowCursor
    assert window.act_multi.isEnabled()
    assert window.radio_vertices.isEnabled() and window.radio_step.isEnabled()
    window.close()


def test_snap_click_right_click_and_space() -> None:
    window = _window()
    window.act_mode_point.trigger()
    canvas = window.canvas

    # 视口内的端点都已收集，并生成了标记路径
    canvas._ensure_snap()  # noqa: SLF001
    assert canvas._snap is not None and len(canvas._snap) == 3  # noqa: SLF001
    assert not canvas._snap_path.isEmpty()  # noqa: SLF001
    assert canvas._snap_nearest(_pos(window, (0.0, 0.0))) is not None  # noqa: SLF001
    assert canvas._snap_nearest(_pos(window, (0.0, 9.0))) is None  # noqa: SLF001

    # 附近没有端点时只给提示，不产生点
    hints: list[str] = []
    canvas.hint.connect(hints.append)
    _click(window, (0.0, 9.0))
    assert window.picks.total_points == 0
    assert hints and "端点" in hints[-1]

    # 依次点选三个端点（吸附到精确坐标）
    _click(window, POINTS[0])
    _click(window, POINTS[1])
    assert window.picks.total_points == 2
    assert window.picks.block_points() == [[POINTS[0], POINTS[1]]]
    assert canvas._match_handle is None, "半条线不算重合"  # noqa: SLF001
    assert not canvas._breath_timer.isActive()  # noqa: SLF001

    _click(window, POINTS[2])
    assert window.picks.total_points == 3
    assert window.picks.block_points() == [list(POINTS)]
    assert canvas._match_handle == 7  # noqa: SLF001 - 整条线重合
    assert canvas._breath_timer.isActive()  # noqa: SLF001
    phase = canvas._breath_phase  # noqa: SLF001
    QTest.qWait(140)
    assert canvas._breath_phase > phase, "呼吸动画应在暗/明之间持续推进"  # noqa: SLF001

    # 右键撤销最后一个点，不再整条重合，呼吸动画停下
    _click(window, POINTS[2], Qt.RightButton)
    assert window.picks.total_points == 2
    assert canvas._match_handle is None  # noqa: SLF001
    assert not canvas._breath_timer.isActive()  # noqa: SLF001
    _click(window, POINTS[1], Qt.RightButton)
    assert window.picks.total_points == 1

    # 空格结束本轮
    _click(window, POINTS[1])
    QTest.keyClick(canvas, Qt.Key_Space)
    assert window.picks.round_count == 1
    assert window.picks.current_length == 0
    assert canvas.pick_rounds == [[POINTS[0], POINTS[1]]]
    assert canvas.pick_current == -1
    assert "点选 2 点" in window.lbl_count.text() and "1 轮" in window.lbl_count.text()

    # 第二轮
    _click(window, POINTS[2])
    assert window.picks.round_count == 2
    assert canvas.pick_current == 1
    assert window.selection_panel.title.text() == "待导出列表 (2)"
    window.close()


def test_undo_escape_and_panels() -> None:
    window = _window()
    window.act_mode_point.trigger()
    _click(window, POINTS[0])
    _click(window, POINTS[1])
    assert window.act_undo.isEnabled()

    window.act_undo.trigger()
    assert window.picks.total_points == 1
    window.act_redo.trigger()
    assert window.picks.total_points == 2

    model = window.selection_panel.model
    assert model.data(model.index(0, 1)) == "点选路径"
    assert model.data(model.index(0, 2)) == "点选1"
    assert "点选块" in window.property_panel.title.text()
    assert window.property_panel.values["sx"].text() == "0.0000"

    # Esc 取消本轮，但不影响已结束的轮次
    QTest.keyClick(window.canvas, Qt.Key_Space)
    _click(window, POINTS[2])
    assert window.picks.total_points == 3
    window._cancel_round()  # noqa: SLF001
    assert window.picks.total_points == 2 and window.picks.round_count == 1

    # 切回线选：点选结果保留在面板外，画布不再显示点选层
    window.act_mode_line.trigger()
    assert window.picks.total_points == 2
    assert window.canvas.pick_rounds == []
    window.act_mode_point.trigger()
    assert window.canvas.pick_rounds == [[POINTS[0], POINTS[1]]]
    window.close()


def test_export_point_rounds(monkeypatch, tmp_path) -> None:
    window = _window()
    window.act_mode_point.trigger()
    for point in POINTS:
        _click(window, point)
    assert window.act_export.isEnabled()
    target = tmp_path / "点选界面导出.xlsx"

    class _FakeDialog:
        def __init__(self, *args, **kwargs) -> None:
            assert kwargs.get("pick_mode") is True

        def exec(self) -> bool:
            return True

        def options(self) -> ExportOptions:
            return ExportOptions(path=str(target), pick_mode=True)

    monkeypatch.setattr("ui.main_window.ExportDialog", _FakeDialog)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    window.export_excel()

    assert target.exists()
    wb = load_workbook(target)
    ws = wb["坐标计算表"]
    assert ws["C1"].value == "点选1"
    assert ws["C6"].value == 0 and ws["E6"].value == 10 and ws["G6"].value == 10
    assert ws["C7"].value == 0 and ws["G7"].value == 10
    assert ws["C8"].value == 0 and ws["G8"].value == 2

    window.clear_drawing()
    assert window.picks.total_points == 0
    assert window.canvas.pick_rounds == []
    window.close()
