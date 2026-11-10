import math

from core.geometry import (
    azimuth,
    decimal_to_dms,
    format_dms,
    build_segments,
    format_coord,
    format_decimal,
    arc_segment_length,
    bulge_to_arc,
    excel_cell_value,
    point_segment_distance_2d,
    planar_total,
    round_decimal,
    slope_ratio,
    walk_path_points,
)


def test_azimuth_quadrants():
    origin = (0.0, 0.0, 0.0)
    assert azimuth(origin, (0.0, 10.0, 0.0)) == 0.0        # 正北
    assert azimuth(origin, (10.0, 0.0, 0.0)) == 90.0       # 正东
    assert azimuth(origin, (0.0, -10.0, 0.0)) == 180.0     # 正南
    assert math.isclose(azimuth(origin, (-10.0, 0.0, 0.0)), 270.0)
    assert math.isclose(azimuth(origin, (10.0, 10.0, 0.0)), 45.0)
    assert math.isclose(azimuth(origin, (-10.0, 10.0, 0.0)), 315.0)


def test_azimuth_zero_length():
    assert azimuth((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)) == 0.0


def test_arc_length_semicircle():
    # 半径 10 的半圆，bulge = 1
    p0 = (0.0, 0.0, 0.0)
    p1 = (20.0, 0.0, 0.0)
    length = arc_segment_length(p0, p1, 1.0)
    assert math.isclose(length, math.pi * 10.0, rel_tol=1e-12)


def test_bulge_center():
    arc = bulge_to_arc((0.0, 0.0, 0.0), (20.0, 0.0, 0.0), 1.0)
    assert arc is not None
    assert math.isclose(arc.center[0], 10.0)
    assert math.isclose(arc.center[1], 0.0)
    assert math.isclose(arc.radius, 10.0)
    assert math.isclose(abs(arc.sweep), math.pi)


def test_segment_and_total_length():
    points = [(0.0, 0.0, 0.0), (30.0, 40.0, 0.0), (30.0, 40.0, 12.0)]
    segments = build_segments(points, [], False)
    assert math.isclose(segments[0].length, 50.0)
    assert math.isclose(segments[0].azimuth, math.degrees(math.atan2(30, 40)))
    assert math.isclose(segments[1].length, 12.0)
    assert math.isclose(planar_total(segments), 50.0)


def test_point_segment_distance():
    a = (0.0, 0.0, 0.0)
    b = (10.0, 0.0, 0.0)
    assert math.isclose(point_segment_distance_2d((5.0, 3.0, 0.0), a, b), 3.0)
    assert math.isclose(point_segment_distance_2d((-4.0, 3.0, 0.0), a, b), 5.0)


def test_walk_path_vertices_only():
    points = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]
    rows = walk_path_points(points, [], False, 1.0, include_vertices=True)
    assert [row[0] for row in rows] == points
    assert math.isclose(rows[-1][2], 20.0)


def test_walk_path_points_alignment():
    points = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    rows = walk_path_points(points, [], False, 1.0, include_vertices=False)
    assert len(rows) == 11
    assert rows[0][1] == 0 and rows[-1][1] == 0
    assert math.isclose(rows[-1][2], 10.0)


def test_walk_path_arc():
    points = [(0.0, 0.0, 0.0), (20.0, 0.0, 0.0)]
    rows = walk_path_points(points, [1.0], False, 5.0, include_vertices=False)
    assert len(rows) >= 3
    assert math.isclose(rows[-1][2], math.pi * 10.0, rel_tol=0.02)


def test_decimal_formatting_round_half_up():
    assert format_coord(12.34565) == "12.3457"
    assert format_coord(-12.34565) == "-12.3457"
    assert format_decimal(0.00005, 4) == "0.0001"
    assert format_decimal(12345678.12345, 4) == "12345678.1235"


def test_large_coordinate_precision():
    value = 34553190.455270186
    rounded = round_decimal(value, 4)
    assert rounded == 34553190.4553
    assert abs(rounded - value) < 1e-4
    text = format_coord(value)
    assert text == "34553190.4553"
    assert "e" not in text.lower()


def test_excel_cell_value_threshold():
    assert isinstance(excel_cell_value(34553190.4553, 4), float)
    big = excel_cell_value(1.2e11, 4)
    assert isinstance(big, str)
    assert "e" not in big.lower()


def test_negative_zero_normalized():
    assert format_decimal(-0.00001, 4) == "0.0000"
    assert format_decimal(-0.0, 3) == "0.000"


def test_azimuth_near_north_wraps():
    value = azimuth((0.0, 0.0, 0.0), (0.001, 10.0, 0.0))
    assert 0.0 <= value < 1.0
    value2 = azimuth((0.0, 0.0, 0.0), (-0.001, 10.0, 0.0))
    assert 359.0 < value2 < 360.0


def test_dms_basic_conversion():
    assert format_dms(162.0001) == "162°00′00″"
    assert format_dms(45.5) == "45°30′00″"
    assert format_dms(0.0) == "0°00′00″"
    assert format_dms(90.0) == "90°00′00″"


def test_dms_rounding_carry():
    # 59.99 秒进位到 1 分，359.99999 度归一为 0
    assert format_dms(59.99999) == "60°00′00″"
    assert format_dms(359.99999) == "0°00′00″"
    degrees, minutes, seconds = decimal_to_dms(12.999999)
    assert (degrees, minutes) == (13, 0)
    assert float(seconds) == 0.0


def test_dms_second_precision():
    assert format_dms(0.00014) == "0°00′01″"
    assert format_dms(1.0 / 3600.0) == "0°00′01″"


def test_slope_ratio_sign_and_units():
    # 10 米水平、升高 0.5 米 → 5% 上坡
    assert math.isclose(slope_ratio(0.0, 0.5, 10.0), 0.05)
    # 下坡为负，与现场表 -0.01 = -1% 的口径一致
    assert math.isclose(slope_ratio(10.0, 9.9, 10.0), -0.01)
    # 平坡
    assert slope_ratio(5.0, 5.0, 8.0) == 0.0
    # 两点重合（水平距离 0）无法反算
    assert slope_ratio(1.0, 2.0, 0.0) is None
