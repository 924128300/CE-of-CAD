"""验证「清空图纸」：模型/缓存释放、内存变化、清空后继续读第二张图。

用法：python tools/verify_clear_drawing.py [dwg1] [dwg2]
"""
from __future__ import annotations

import ctypes
import os
import sys
import tracemalloc
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_PSAPI = ctypes.WinDLL("psapi")
_K32 = ctypes.WinDLL("kernel32")
_K32.GetCurrentProcess.restype = wintypes.HANDLE
_PSAPI.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
_PSAPI.GetProcessMemoryInfo.restype = wintypes.BOOL


def rss_mb() -> float:
    counters = _PMC()
    counters.cb = ctypes.sizeof(_PMC)
    _PSAPI.GetProcessMemoryInfo(_K32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.WorkingSetSize / (1024 * 1024)


def py_mb() -> float:
    return tracemalloc.get_traced_memory()[0] / (1024 * 1024)


def load_into(window: MainWindow, path: str) -> None:
    model = load_dwg(path)
    prepared = build_geometry(model.entities, model.origin, model.bbox)
    window.model = model
    window.canvas.set_model(model, prepared)
    window.layer_panel.bind_model(model)
    window._update_actions(True)  # noqa: SLF001
    window.setWindowTitle(f"DWG 坐标导出工具 - {os.path.basename(model.path)}")
    window.lbl_count.setText(f"{os.path.basename(model.path)} | 实体 {len(model.entities)}")


def main() -> int:
    first = sys.argv[1] if len(sys.argv) > 1 else \
        "D:/D盘迁移文件/工作 Lonshi/Lonshi mining总图/龙溪矿总图9-11(1).dwg"
    second = sys.argv[2] if len(sys.argv) > 2 else "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow()
    window.resize(1400, 880)

    tracemalloc.start()
    base_rss, base_py = rss_mb(), py_mb()
    print(f"基线：工作集 {base_rss:.1f} MB，Python 跟踪 {base_py:.1f} MB")

    load_into(window, first)
    loaded_rss, loaded_py = rss_mb(), py_mb()
    entities = len(window.model.entities)
    cells = len(window.canvas.index._cells)  # noqa: SLF001 - 仅用于打印规模
    print(f"读入 {os.path.basename(first)}：实体 {entities} 条，网格 {cells} 个，"
          f"工作集 {loaded_rss:.1f} MB，Python 跟踪 {loaded_py:.1f} MB")

    window.act_close.trigger()
    app.processEvents()
    cleared_rss, cleared_py = rss_mb(), py_mb()
    print(f"清空后：模型 {window.model!r}，画布模型 {window.canvas.model!r}，"
          f"折线缓存 {len(window.canvas._polygons)}，路径缓存 {len(window.canvas._paths)}，"
          f"空间索引 {window.canvas.index!r}")
    print(f"  工作集 {loaded_rss:.1f} -> {cleared_rss:.1f} MB（-{loaded_rss - cleared_rss:.1f} MB，"
          f"较基线 +{cleared_rss - base_rss:.1f} MB）")
    print(f"  Python 跟踪 {loaded_py:.1f} -> {cleared_py:.1f} MB"
          f"（-{loaded_py - cleared_py:.1f} MB）")
    print(f"  标题 {window.windowTitle()!r}，清空按钮可用 {window.act_close.isEnabled()}，"
          f"导出按钮可用 {window.act_export.isEnabled()}")

    load_into(window, second)
    app.processEvents()
    second_ok = window.model is not None and len(window.model.entities) > 0
    print(f"清空后读第二张 {os.path.basename(second)}：实体 {len(window.model.entities)} 条，"
          f"可用 {second_ok}")

    # 再清一次，确认第二轮同样干净（避免连续读图累积内存）
    window.clear_drawing()
    app.processEvents()
    print(f"第二次清空：工作集 {rss_mb():.1f} MB，Python 跟踪 {py_mb():.1f} MB")
    tracemalloc.stop()

    assert second_ok, "清空后无法继续读图"
    assert window.model is None and window.canvas.model is None
    assert window.canvas._polygons == {} and window.canvas._paths == {}  # noqa: SLF001
    assert window.canvas.index is None and window.act_close.isEnabled() is False
    window.close()
    print("验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
