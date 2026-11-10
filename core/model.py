"""图纸数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import (
    PathSegment,
    Point3,
    build_segments,
    planar_total,
    polyline_render_points,
    reverse_path,
    total_length,
)

# $INSUNITS 代码到名称/符号/米换算系数
INSUNITS: dict[int, tuple[str, str, float]] = {
    0: ("无单位", "", 1.0),
    1: ("英寸", "in", 0.0254),
    2: ("英尺", "ft", 0.3048),
    3: ("英里", "mi", 1609.344),
    4: ("毫米", "mm", 0.001),
    5: ("厘米", "cm", 0.01),
    6: ("米", "m", 1.0),
    7: ("千米", "km", 1000.0),
    8: ("微英寸", "uin", 2.54e-8),
    9: ("密耳", "mil", 2.54e-5),
    10: ("码", "yd", 0.9144),
    11: ("埃", "A", 1e-10),
    12: ("纳米", "nm", 1e-9),
    13: ("微米", "um", 1e-6),
    14: ("分米", "dm", 0.1),
    15: ("十米", "dam", 10.0),
    16: ("百米", "hm", 100.0),
    17: ("吉米", "Gm", 1e9),
    18: ("天文单位", "AU", 1.495978707e11),
    19: ("光年", "ly", 9.4607304725808e15),
    20: ("秒差距", "pc", 3.0856775814913673e16),
}


@dataclass(slots=True)
class LayerInfo:
    name: str
    color: tuple[int, int, int] = (200, 200, 200)
    visible: bool = True
    entity_count: int = 0


@dataclass(slots=True)
class EntityRecord:
    """一条可选要素。points 为 WCS 真实坐标（float64），bulges 与段对应。"""

    handle: int
    dxftype: str
    layer: str
    color: tuple[int, int, int]
    points: list[Point3]
    source_handle: int = 0
    bulges: list[float] = field(default_factory=list)
    closed: bool = False
    kind: str = "path"  # path | point
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    _segments: list[PathSegment] | None = field(default=None, repr=False)
    _render_points: list[Point3] | None = field(default=None, repr=False)

    @property
    def is_point(self) -> bool:
        return self.kind == "point"

    @property
    def segments(self) -> list[PathSegment]:
        if self._segments is None:
            self._segments = build_segments(self.points, self.bulges, self.closed)
        return self._segments

    @property
    def length(self) -> float:
        return total_length(self.segments)

    @property
    def planar_length(self) -> float:
        if len(self.points) < 2:
            return 0.0
        return planar_total(self.segments)

    @property
    def render_points(self) -> list[Point3]:
        if self._render_points is None:
            if self.is_point:
                self._render_points = list(self.points)
            else:
                self._render_points = polyline_render_points(self.points, self.bulges, self.closed)
        return self._render_points

    @property
    def first(self) -> Point3:
        return self.points[0] if self.points else (0.0, 0.0, 0.0)

    @property
    def last(self) -> Point3:
        return self.points[-1] if self.points else (0.0, 0.0, 0.0)

    def bbox_center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)

    def reversed(self) -> "EntityRecord":
        """返回点序反转后的副本（圆弧保持原弧线），供反向导出与属性展示使用。

        只反转展示/导出方向，不改原始实体，画布与缓存仍按原几何工作。
        """
        if self.kind == "point" or len(self.points) < 2:
            return self
        points, bulges = reverse_path(self.points, self.bulges, self.closed)
        return EntityRecord(
            handle=self.handle,
            dxftype=self.dxftype,
            layer=self.layer,
            color=self.color,
            points=points,
            source_handle=self.source_handle,
            bulges=bulges,
            closed=self.closed,
            kind=self.kind,
            bbox=self.bbox,
        )


@dataclass(slots=True)
class DrawingModel:
    path: str = ""
    version: str = ""
    insunits: int = 0
    entities: list[EntityRecord] = field(default_factory=list)
    layers: dict[str, LayerInfo] = field(default_factory=dict)
    origin: Point3 = (0.0, 0.0, 0.0)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    warnings: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    insert_count: int = 0
    _by_handle: dict[int, EntityRecord] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self._by_handle and self.entities:
            self._by_handle = {e.handle: e for e in self.entities}

    def get(self, handle: int) -> EntityRecord | None:
        return self._by_handle.get(handle)

    @property
    def unit_name(self) -> str:
        return INSUNITS.get(self.insunits, INSUNITS[0])[0]

    @property
    def unit_symbol(self) -> str:
        return INSUNITS.get(self.insunits, INSUNITS[0])[1]

    @property
    def meters_per_unit(self) -> float:
        return INSUNITS.get(self.insunits, INSUNITS[0])[2]

    def visible_layers(self) -> set[str]:
        return {name for name, info in self.layers.items() if info.visible}

    def selectable_count(self) -> int:
        return len(self.entities)
