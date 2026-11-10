"""界面回归：「清空图纸」按钮位置、状态与资源释放。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolBar  # noqa: E402

from core.model import DrawingModel, EntityRecord, LayerInfo  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _model() -> DrawingModel:
    entity = EntityRecord(
        handle=7,
        dxftype="LWPOLYLINE",
        layer="0",
        color=(255, 255, 255),
        points=[(0.0, 0.0, 0.0), (10.0, 0.0, 2.0), (10.0, 10.0, 3.0)],
        bbox=(0.0, 0.0, 10.0, 10.0),
    )
    return DrawingModel(
        path="D:/tmp/示例图纸.dwg",
        version="AC1015",
        entities=[entity],
        layers={"0": LayerInfo("0", entity_count=1)},
        bbox=(0.0, 0.0, 10.0, 10.0),
    )


def _toolbar(window: MainWindow) -> QToolBar:
    bars = window.findChildren(QToolBar)
    assert bars, "工具栏未创建"
    return bars[0]


def test_clear_button_sits_next_to_open_and_is_disabled_without_drawing() -> None:
    window = MainWindow()
    actions = _toolbar(window).actions()
    assert window.act_close in actions
    assert actions.index(window.act_close) == actions.index(window.act_open) + 1
    assert window.act_close.isEnabled() is False
    window.close()


def test_clear_drawing_releases_model_and_caches() -> None:
    window = MainWindow()
    model = _model()
    window.model = model
    window.canvas.set_model(model)
    window.layer_panel.bind_model(model)
    window._update_actions(True)  # noqa: SLF001
    window.selection.apply([7])
    assert window.act_close.isEnabled()
    assert window.canvas.index is not None
    assert window.canvas._polygons  # noqa: SLF001 - 确认缓存已建立

    window.clear_drawing()

    assert window.model is None
    assert window.canvas.model is None
    assert window.canvas.index is None
    assert window.canvas._polygons == {}  # noqa: SLF001
    assert window.canvas._paths == {}  # noqa: SLF001
    assert window.canvas._pen_cache == {}  # noqa: SLF001
    assert window.canvas.scale == 1.0
    assert window.layer_panel.tree.topLevelItemCount() == 0
    assert window.selection_panel.model.rowCount() == 0
    assert len(window.selection) == 0
    assert window.act_close.isEnabled() is False
    assert window.act_export.isEnabled() is False
    assert window.windowTitle() == "DWG 坐标导出工具"
    # 再点一次应安全无副作用
    window.clear_drawing()
    window.close()
