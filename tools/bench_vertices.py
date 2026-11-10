"""顶点标记绘制基准：超长多段线选中时（当前要素逐点画方块）的耗时。

用法：python tools/bench_vertices.py [点数...]
"""
from __future__ import annotations

import math
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.model import DrawingModel, EntityRecord, LayerInfo  # noqa: E402
from ui.canvas import CadCanvas  # noqa: E402
from ui.geometry_cache import build_geometry  # noqa: E402


def make_model(count: int) -> DrawingModel:
    """一条来回折返的长多段线，点数 count。"""
    points = []
    for index in range(count):
        x = float(index) * 0.5
        y = math.sin(index / 40.0) * 20.0
        points.append((x, y, 0.0))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    entity = EntityRecord(handle=1, dxftype="LWPOLYLINE", layer="线", color=(255, 255, 255),
                          points=points,
                          bbox=(min(xs), min(ys), max(xs), max(ys)))
    model = DrawingModel(path="synthetic", version="AC1032", insunits=6,
                         entities=[entity], layers={"线": LayerInfo(name="线")},
                         origin=(0.0, 0.0, 0.0),
                         bbox=(min(xs), min(ys), max(xs), max(ys)))
    model._by_handle = {1: entity}
    return model


def timed(func, repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        func()
        best = min(best, time.perf_counter() - start)
    return best * 1000.0


def main() -> int:
    QApplication.instance() or QApplication([])
    counts = [int(arg) for arg in sys.argv[1:]] or [2000, 20000, 100000]
    image = QImage(1400, 880, QImage.Format_RGB32)
    image.fill(QColor("#000000"))
    for count in counts:
        model = make_model(count)
        prepared = build_geometry(model.entities, model.origin, model.bbox)
        canvas = CadCanvas()
        canvas.resize(1400, 880)
        canvas.set_model(model, prepared)
        canvas.fit_view()
        canvas.set_selection({1})
        plain = timed(lambda: canvas.render(image))
        canvas.set_current(1)
        with_vertices = timed(lambda: canvas.render(image))
        canvas.zoom_by(200.0)
        zoomed = timed(lambda: canvas.render(image))
        print(f"点数 {count:>7}: 选中 {plain:6.1f} ms | 当前要素(画顶点) {with_vertices:6.1f} ms "
              f"| 放大200x 后 {zoomed:6.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
