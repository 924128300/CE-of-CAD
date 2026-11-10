"""把实体折线预处理成 QPolygonF 与空间索引，供画布直接接管。

这部分是加载后最重的纯计算（大图可达上万条折线、百万级点），放在加载线程里完成，
主线程拿到结果后只做绘制，避免“图纸已加载完又卡一下”。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPolygonF

from core.model import EntityRecord
from core.spatial_index import GridIndex

# 细/粗两级显示的折线点数上限
DISPLAY_POINT_LIMIT = 600
COARSE_POINT_LIMIT = 80


@dataclass(slots=True)
class PreparedGeometry:
    """画布需要的全部派生数据，构建后即可直接绘制。"""

    origin: tuple[float, float]
    index: GridIndex
    polygons: dict[int, QPolygonF]
    coarse_polygons: dict[int, QPolygonF]


def _display_polygon(points, ox: float, oy: float) -> QPolygonF:
    polygon = QPolygonF()
    if len(points) <= DISPLAY_POINT_LIMIT:
        for p in points:
            polygon.append(QPointF(p[0] - ox, p[1] - oy))
    else:
        step = (len(points) + DISPLAY_POINT_LIMIT - 1) // DISPLAY_POINT_LIMIT
        for p in points[::step]:
            polygon.append(QPointF(p[0] - ox, p[1] - oy))
        last = points[-1]
        polygon.append(QPointF(last[0] - ox, last[1] - oy))
    return polygon


def _coarse_polygon(polygon: QPolygonF) -> QPolygonF:
    if polygon.size() <= COARSE_POINT_LIMIT:
        return polygon
    step = (polygon.size() + COARSE_POINT_LIMIT - 1) // COARSE_POINT_LIMIT
    coarse = QPolygonF()
    for index in range(0, polygon.size(), step):
        coarse.append(polygon.at(index))
    coarse.append(polygon.at(polygon.size() - 1))
    return coarse


def _bbox_of(entities: list[EntityRecord]) -> tuple[float, float, float, float]:
    if not entities:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(e.bbox[0] for e in entities),
        min(e.bbox[1] for e in entities),
        max(e.bbox[2] for e in entities),
        max(e.bbox[3] for e in entities),
    )


def build_geometry(entities: list[EntityRecord], origin: tuple[float, float],
                   bbox: tuple[float, float, float, float] | None = None) -> PreparedGeometry:
    """构建绘制多边形与空间索引。

    坐标以图形范围中心为原点做平移，避免超大坐标进入 32 位光栅化；点实体的坐标
    不进入多边形，由画布在屏幕坐标系里另画十字。
    """
    ox, oy = float(origin[0]), float(origin[1])
    index = GridIndex(bbox or _bbox_of(entities))
    polygons: dict[int, QPolygonF] = {}
    coarse: dict[int, QPolygonF] = {}
    for entity in entities:
        index.add(entity.handle, entity.bbox)
        if entity.is_point:
            continue
        polygon = _display_polygon(entity.render_points, ox, oy)
        if len(polygon) < 2:
            continue
        polygons[entity.handle] = polygon
        coarse[entity.handle] = _coarse_polygon(polygon)
    return PreparedGeometry(origin=(ox, oy), index=index,
                            polygons=polygons, coarse_polygons=coarse)
