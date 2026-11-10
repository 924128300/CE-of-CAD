"""性能基准：解析、构建、绘制、拾取、导出、常驻内存。

用法：python tools/bench_perf.py [图纸路径...]
不传参数时使用内置的两张样图。
"""
from __future__ import annotations

import cProfile
import gc
import io
import os
import pstats
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from core.excel_export import ExportOptions, export_excel  # noqa: E402
from ui.canvas import CadCanvas  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402

DEFAULT_FILES = [
    "D:/6月探采对比汇报资料/剖面图/EW000线.dwg",
    "D:/D盘迁移文件/工作 Lonshi/Lonshi mining总图/龙溪矿总图9-11(1).dwg",
]


def rss_mb() -> float:
    """当前进程常驻内存（MB），失败返回 -1。"""
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
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

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters),
                                                        counters.cb):
            return -1.0
        return counters.WorkingSetSize / 1e6
    except Exception:  # noqa: BLE001
        return -1.0


def timed(func, repeat: int = 5) -> float:
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        func()
        best = min(best, time.perf_counter() - start)
    return best * 1000.0


def profile(func, label: str, top: int = 12) -> None:
    profiler = cProfile.Profile()
    profiler.enable()
    func()
    profiler.disable()
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).sort_stats("tottime").print_stats(top)
    print(f"---- profile: {label} ----")
    print("\n".join(stream.getvalue().splitlines()[4:4 + top]))


def bench_file(path: str) -> None:
    print(f"\n===== {os.path.basename(path)} =====")
    gc.collect()
    base_rss = rss_mb()
    t0 = time.perf_counter()
    model = load_dwg(path)
    load_ms = (time.perf_counter() - t0) * 1000
    print(f"解析: {load_ms:.0f} ms | 实体 {len(model.entities)} | 块展开 {model.insert_count} "
          f"| 常驻 {rss_mb() - base_rss:.0f} MB")

    t0 = time.perf_counter()
    prepared = build_geometry(model.entities, (model.origin[0], model.origin[1]), model.bbox)
    print(f"构建绘制缓存: {(time.perf_counter() - t0) * 1000:.0f} ms")

    canvas = CadCanvas()
    canvas.resize(1400, 880)
    canvas.set_model(model, prepared)
    image = QImage(1400, 880, QImage.Format_RGB32)
    image.fill(QColor("#000000"))

    canvas.fit_view()
    print(f"全图绘制: {timed(lambda: canvas.render(image)):.1f} ms")
    canvas.zoom_by(20.0)
    print(f"放大 20x: {timed(lambda: canvas.render(image)):.1f} ms")
    canvas.zoom_by(10.0)
    print(f"放大 200x: {timed(lambda: canvas.render(image)):.1f} ms")

    points = [QPoint(x, y) for x in range(100, 1300, 120) for y in range(100, 800, 120)]
    hover_ms = timed(lambda: [canvas.pick(pos) for pos in points], 3)
    print(f"拾取 {len(points)} 点: {hover_ms:.1f} ms（单次 {hover_ms / len(points):.2f} ms）")

    longest = max(model.entities, key=lambda e: len(e.render_points))
    canvas.fit_view()
    canvas.set_selection({longest.handle})
    canvas.set_current(longest.handle)
    print(f"选中最长实体({len(longest.render_points)} 点)后重绘: "
          f"{timed(lambda: canvas.render(image)):.1f} ms")

    canvas.set_selection(set())
    canvas.set_current(None)
    canvas.hover_handle = longest.handle
    print(f"悬停超长实体重绘: {timed(lambda: canvas.render(image)):.1f} ms")
    canvas.hover_handle = None

    for count in (1, 20, 100):
        subset = model.entities[:count]
        if not subset:
            continue
        out = os.path.join("tools", "screenshots", f"_bench_{count}.xlsx")
        t0 = time.perf_counter()
        export_excel(model, subset, ExportOptions(path=out, include_info=False))
        print(f"导出 {count} 条: {(time.perf_counter() - t0) * 1000:.0f} ms")
    return model


def main() -> int:
    app = QApplication.instance() or QApplication([])
    files = sys.argv[1:] or DEFAULT_FILES
    models = []
    for path in files:
        if os.path.isfile(path):
            models.append((path, bench_file(path)))

    if "--profile" in os.environ.get("BENCH_MODE", ""):
        path, model = models[0]
        canvas = CadCanvas()
        canvas.resize(1400, 880)
        canvas.set_model(model)
        image = QImage(1400, 880, QImage.Format_RGB32)
        profile(lambda: canvas.render(image), "全图绘制")
        profile(lambda: export_excel(model, model.entities[:100],
                                     ExportOptions(path="tools/screenshots/_bench_p.xlsx",
                                                   include_info=False)), "导出 100 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
