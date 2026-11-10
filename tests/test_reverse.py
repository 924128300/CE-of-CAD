"""反向输出：几何反转、方位角/平距重算与表格顺序。"""
from __future__ import annotations

import os

from openpyxl import load_workbook

from core.excel_export import ExportOptions, export_excel
from core.geometry import azimuth, reverse_path
from core.model import DrawingModel, EntityRecord, LayerInfo


def _entity(points, bulges=None, closed=False, handle=7) -> EntityRecord:
    if bulges is None:
        bulges = []
    return EntityRecord(
        handle=handle,
        dxftype="LWPOLYLINE",
        layer="0",
        color=(255, 255, 255),
        points=list(points),
        bulges=list(bulges),
        closed=closed,
        bbox=(min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points)),
    )


def test_reverse_path_roundtrip_open_and_closed() -> None:
    points = [(0.0, 0.0, 0.0), (10.0, 0.0, 1.0), (10.0, 10.0, 2.0)]
    bulges = [0.0, 0.5]
    reversed_points, reversed_bulges = reverse_path(points, bulges, False)
    assert reversed_points == list(reversed(points))
    assert reversed_bulges == [-0.5, 0.0]
    assert reverse_path(reversed_points, reversed_bulges, False) == (points, bulges)

    closed_points = points + [(4.0, 6.0, 0.5)]
    closed_bulges = [0.0, 0.0, 0.3, 0.6]
    rp, rb = reverse_path(closed_points, closed_bulges, True)
    assert reverse_path(rp, rb, True) == (closed_points, closed_bulges)


def test_reversed_entity_keeps_length_and_flips_azimuth() -> None:
    entity = _entity([(0.0, 0.0, 0.0), (10.0, 0.0, 1.0), (10.0, 10.0, 2.0)],
                     bulges=[0.0, 0.4])
    flipped = entity.reversed()
    assert flipped.first == entity.last
    assert flipped.last == entity.first
    assert abs(flipped.length - entity.length) < 1e-9
    assert abs(flipped.planar_length - entity.planar_length) < 1e-9
    # 段序反过来，每段方位角 = 原对应段反向（+180°）
    original = [seg.azimuth for seg in entity.segments]
    expected = [azimuth(seg.end, seg.start) for seg in reversed(entity.segments)]
    assert expected == [seg.azimuth for seg in flipped.segments]
    assert len(original) == len(flipped.segments)


def test_reversed_export_writes_new_order_and_azimuths(tmp_path) -> None:
    model = DrawingModel(
        path="D:/tmp/反向示例.dwg",
        entities=[_entity([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)])],
        layers={"0": LayerInfo("0")},
        bbox=(0.0, 0.0, 10.0, 10.0),
    )
    entity = model.entities[0].reversed()
    path = os.path.join(tmp_path, "反向.xlsx")
    export_excel(model, [entity], ExportOptions(path=path, include_info=False))
    ws = load_workbook(path)["坐标计算表"]

    assert [ws["C6"].value, ws["E6"].value, ws["G6"].value] == [10, 10, 0]
    assert [ws["D5"].value, ws["F5"].value] == ["180°00′00″", "270°00′00″"]
    assert [ws["D3"].value, ws["F3"].value] == [10.0, 10.0]
