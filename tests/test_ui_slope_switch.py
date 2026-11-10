"""界面回归：反算坡度开关在工具栏（多选按钮旁），默认关闭。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolBar  # noqa: E402

from ui.export_dialog import ExportDialog  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


class _StubModel:
    """ExportDialog 只用到 path。"""

    path = ""


_APP = QApplication.instance() or QApplication([])


def _toolbar(window: MainWindow) -> QToolBar:
    bars = window.findChildren(QToolBar)
    assert bars, "工具栏未创建"
    return bars[0]


def test_slope_toggle_sits_next_to_multi_and_defaults_off() -> None:
    window = MainWindow()
    assert window.act_slope.isCheckable()
    assert window.act_slope.isChecked() is False
    actions = _toolbar(window).actions()
    assert window.act_slope in actions
    assert actions.index(window.act_reverse) == actions.index(window.act_multi) + 1
    assert actions.index(window.act_slope) == actions.index(window.act_reverse) + 1
    window.close()


def test_dialog_only_reports_toolbar_state() -> None:
    off = ExportDialog(_StubModel(), fill_slope=False)
    assert off.options().fill_slope is False
    assert not [w for w in off.findChildren(object) if getattr(w, "text", None)
                and "反算坡度（" in str(w.text())]
    on = ExportDialog(_StubModel(), fill_slope=True)
    assert on.options().fill_slope is True
    off.close()
    on.close()
