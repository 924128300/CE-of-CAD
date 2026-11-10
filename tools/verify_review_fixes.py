"""复审修复的端到端验证：长实体在深缩放下的可见性与可拾取性。"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.dwg_loader import load_dwg  # noqa: E402
from ui.canvas import CadCanvas  # noqa: E402

SAMPLE = r"D:/6月探采对比汇报资料/剖面图/EW000线.dwg"


def main() -> int:
    app = QApplication.instance() or QApplication([])
    model = load_dwg(SAMPLE)
    print(f"实体 {len(model.entities)}，版本 {model.version}，块展开 {model.insert_count}")

    canvas = CadCanvas()
    canvas.resize(1000, 700)
    canvas.set_model(model)

    span = sorted(model.entities,
                  key=lambda e: (e.bbox[2] - e.bbox[0]) * (e.bbox[3] - e.bbox[1]),
                  reverse=True)
    entity = span[0]
    cx = (entity.bbox[0] + entity.bbox[2]) / 2.0
    cy = (entity.bbox[1] + entity.bbox[3]) / 2.0
    print(f"最大实体 handle={entity.handle} 类型={entity.dxftype} 跨度="
          f"{entity.bbox[2] - entity.bbox[0]:.1f} x {entity.bbox[3] - entity.bbox[1]:.1f}")

    # 选实体上离包围盒中心最近的一个顶点，把它对准屏幕中心
    vertex = min(entity.render_points,
                 key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    canvas.scale = 900.0
    cx_screen = canvas.width() / 2.0
    cy_screen = canvas.height() / 2.0
    canvas.pan.setX(cx_screen - (vertex[0] - canvas._origin[0]) * canvas.scale - cx_screen)
    canvas.pan.setY(cy_screen + (vertex[1] - canvas._origin[1]) * canvas.scale - cy_screen)
    wx0, wy0, wx1, wy1 = canvas.world_rect()
    print(f"视口世界范围 {wx1 - wx0:.3f} x {wy1 - wy0:.3f}")

    hits = canvas.index.query_rect(wx0, wy0, wx1, wy1)
    print(f"视口候选 {len(hits)}，长实体在其中: {entity.handle in hits}")

    image = QImage(1000, 700, QImage.Format_RGB32)
    image.fill(QColor("#000000"))
    canvas.render(image)
    drawn = 0
    for y in range(0, 700, 3):
        for x in range(0, 1000, 3):
            if image.pixelColor(x, y).lightness() > 40:
                drawn += 1
    print(f"绘制像素采样命中 {drawn}")

    px, py = int(canvas.to_screen(vertex[0], vertex[1]).x()), int(canvas.to_screen(vertex[0], vertex[1]).y())
    picked = canvas.pick(QPoint(px, py))
    print(f"中心点拾取: {picked}")

    assert entity.handle in hits, "长实体在深缩放下缺失（修复失败）"
    assert drawn > 5, "视口内容未绘制"
    around = max(image.pixelColor(px + dx, py + dy).lightness()
                 for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    assert around > 40, "实体顶点处未绘制"
    print("验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
