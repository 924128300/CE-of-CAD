import math
import os

import pytest

from core.dwg_loader import load_dwg
from core.model import DrawingModel, EntityRecord, LayerInfo

SAMPLE = r"D:/6月探采对比汇报资料/剖面图/EW000线.dwg"
SAMPLE_BIG = os.environ.get("DWG_SMOKE_BIG", r"D:/samples/穿爆计划图.dwg")


def test_load_sample_dwg():
    if not os.path.isfile(SAMPLE):
        pytest.skip("样例文件不存在")
    model = load_dwg(SAMPLE)
    assert model.version.startswith("AC")
    assert len(model.entities) > 1000
    assert model.bbox[2] > model.bbox[0]
    assert model.bbox[3] > model.bbox[1]
    assert model.origin[0] == pytest.approx((model.bbox[0] + model.bbox[2]) / 2)
    assert all(e.layer in model.layers for e in model.entities)


def test_entity_geometry_valid():
    if not os.path.isfile(SAMPLE):
        pytest.skip("样例文件不存在")
    model = load_dwg(SAMPLE)
    for entity in model.entities[:500]:
        assert len(entity.points) >= 1
        for x, y, z in entity.points:
            assert math.isfinite(x) and math.isfinite(y) and math.isfinite(z)
        if not entity.is_point:
            assert entity.length >= 0.0
            assert 0.0 <= entity.segments[0].azimuth < 360.0


def test_block_expansion():
    if not os.path.isfile(SAMPLE):
        pytest.skip("样例文件不存在")
    model = load_dwg(SAMPLE)
    assert model.insert_count > 0
    # 块内实体必须落在图框范围内
    x0, y0, x1, y1 = model.bbox
    for entity in model.entities:
        assert x0 - 1e-6 <= entity.bbox[0] <= x1 + 1e-6
        assert y0 - 1e-6 <= entity.bbox[1] <= y1 + 1e-6


def test_large_drawing_loads_within_budget():
    if not os.path.isfile(SAMPLE_BIG):
        pytest.skip("大样例文件不存在")
    model = load_dwg(SAMPLE_BIG)
    assert len(model.entities) > 5000
    assert model.elapsed < 30.0
