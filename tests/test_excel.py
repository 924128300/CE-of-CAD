import math

from openpyxl import load_workbook

from core.excel_export import ExportOptions, export_excel
from core.model import DrawingModel, EntityRecord, LayerInfo


def make_model():
    layer = LayerInfo(name="测试层", entity_count=2)
    line = EntityRecord(
        handle=1, dxftype="LINE", layer="测试层", color=(255, 255, 255),
        points=[(34553190.455270186, 2734467.0141374185, 0.0),
                (34553204.323941655, 2734424.3305211375, 0.0)],
        source_handle=101,
        bbox=(34553190.455270186, 2734424.3305211375,
              34553204.323941655, 2734467.0141374185),
    )
    poly = EntityRecord(
        handle=2, dxftype="LWPOLYLINE", layer="测试层", color=(0, 255, 0),
        points=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)],
        source_handle=102, bbox=(0.0, 0.0, 10.0, 10.0),
    )
    model = DrawingModel(
        path="dwg_coord_exporter/tests/sample.dwg", version="AC1018",
        insunits=6, entities=[line, poly], layers={"测试层": layer},
        bbox=(0.0, 0.0, 34553204.32, 2734467.01),
        origin=(17276602.16, 1367233.5),
    )
    return model, [line, poly]


def test_layout_matches_reference(tmp_path):
    model, entities = make_model()
    path = tmp_path / "out.xlsx"
    result = export_excel(model, entities, ExportOptions(path=str(path)))
    assert result.line_rows == 2
    assert result.point_rows == 5
    assert path.exists()

    wb = load_workbook(path)
    assert wb.sheetnames == ["坐标计算表", "导出信息"]
    ws = wb["坐标计算表"]

    # 第一块：2 个点，占 C..F
    assert ws["A1"].value == "工程名称"
    assert ws["C1"].value == "线1"
    assert ws["A2"].value == "点号"
    assert ws["C2"].value == "P1"
    assert ws["E2"].value == "P2"
    assert ws["A3"].value == "平距(m)"
    assert ws["A4"].value == "巷道长(m)"
    assert ws["A5"].value == "方位"
    assert ws["A6"].value == "坐标(m)"
    assert ws["B6"].value == "X"
    assert ws["B7"].value == "Y"
    assert ws["B8"].value == "Z"
    assert ws["A9"].value == "坡度"

    merged = {str(item) for item in ws.merged_cells.ranges}
    assert "C1:F1" in merged
    assert "C2:D2" in merged
    assert "E2:F2" in merged
    assert "D3:E3" in merged
    assert "A6:A8" in merged
    assert "C6:D6" in merged

    # 平距在相邻两点之间，坐标按点逐列
    assert ws["D3"].value == 44.88
    assert ws["D3"].number_format == "0.000"
    assert ws["D4"].value is None
    assert ws["D4"].number_format == "0.000"
    assert ws["D5"].value == "162°00′00″"
    assert ws["D5"].number_format == "@"
    assert ws["C6"].value == 34553190.4553
    assert ws["C6"].number_format == "0.0000"
    assert ws["E6"].value == 34553204.3239
    assert ws["D9"].value is None
    assert ws["D9"].number_format == "0.00%"

    # 第二块从第 11 行开始，三个点占 C..H
    assert ws["A11"].value == "工程名称"
    assert ws["C11"].value == "线2"
    assert ws["C12"].value == "P1"
    assert ws["G12"].value == "P3"
    assert ws["D13"].value == 10.0
    assert ws["D13"].number_format == "0.000"
    assert ws["D14"].value is None
    assert ws["D15"].value == "90°00′00″"
    assert ws["F15"].value == "0°00′00″"


def test_percent_and_slope_rows_left_for_user(tmp_path):
    model, entities = make_model()
    path = tmp_path / "blank.xlsx"
    export_excel(model, [entities[1]], ExportOptions(path=str(path)))
    ws = load_workbook(path)["坐标计算表"]
    assert ws["D4"].value is None      # 巷道长
    assert ws["D9"].value is None      # 坡度
    assert ws["D4"].number_format == "0.000"
    assert ws["D9"].number_format == "0.00%"


def test_sampling_mode_expands_points(tmp_path):
    model, entities = make_model()
    path = tmp_path / "step.xlsx"
    result = export_excel(model, [entities[1]], ExportOptions(
        path=str(path), include_vertices=False, sample_step=5.0))
    # 两段各 10 单位，按 5 采样 -> 每段 2 个点，加上起点共 5 个点
    assert result.point_rows == 5
    ws = load_workbook(path)["坐标计算表"]
    assert ws["C2"].value == "P1"
    assert ws["K2"].value == "P5"


def test_empty_selection_raises(tmp_path):
    model, _ = make_model()
    try:
        export_excel(model, [], ExportOptions(path=str(tmp_path / "empty.xlsx")))
    except ValueError as exc:
        assert "没有可导出" in str(exc)
    else:
        raise AssertionError("空选择应当抛出异常")

def test_huge_coordinate_falls_back_to_text(tmp_path):
    """超过 Excel 15 位有效数字的坐标写成文本，避免静默丢精度。"""
    layer = LayerInfo(name="大坐标", entity_count=1)
    line = EntityRecord(
        handle=1, dxftype="LINE", layer="大坐标", color=(255, 255, 255),
        points=[(1234567890123.4567, 0.0, 0.0), (1234567890123.4567, 10.0, 0.0)],
        source_handle=1, bbox=(1234567890123.4567, 0.0, 1234567890123.4567, 10.0),
    )
    model = DrawingModel(path="huge.dwg", version="AC1018", insunits=6,
                         entities=[line], layers={"大坐标": layer},
                         bbox=(1234567890123.4567, 0.0, 1234567890123.4567, 10.0))
    path = tmp_path / "huge.xlsx"
    export_excel(model, [line], ExportOptions(path=str(path), include_info=False))
    ws = load_workbook(path)["坐标计算表"]
    cell = ws["C6"]
    assert isinstance(cell.value, str)
    # 12 位整数 + 4 位小数已超过 Excel 的 15 位有效数字，必须写成文本
    assert cell.value == "1234567890123.4568"
    assert cell.number_format == "@"


def test_export_replaces_existing_file_without_residue(tmp_path):
    """重复导出同一路径应覆盖成功，且不留下 .part 临时文件。"""
    model, entities = make_model()
    path = tmp_path / "out.xlsx"
    export_excel(model, entities, ExportOptions(path=str(path)))
    first = path.stat().st_mtime_ns
    export_excel(model, entities, ExportOptions(path=str(path)))
    assert path.exists()
    assert path.stat().st_mtime_ns >= first
    assert not (tmp_path / "out.xlsx.part").exists()

def test_planar_distance_uses_scale_denominator(tmp_path):
    """平距按比例尺换算：1:500 时图上 1 单位 = 0.5 m。"""
    layer = LayerInfo(name="比例", entity_count=1)
    line = EntityRecord(
        handle=1, dxftype="LINE", layer="比例", color=(255, 255, 255),
        points=[(0.0, 0.0, 0.0), (20.0, 0.0, 0.0)], source_handle=1,
        bbox=(0.0, 0.0, 20.0, 0.0),
    )
    model = DrawingModel(path="scale.dwg", version="AC1018", insunits=6,
                         entities=[line], layers={"比例": layer},
                         bbox=(0.0, 0.0, 20.0, 0.0))
    for denominator, expected in ((500, 10.0), (1000, 20.0), (2000, 40.0)):
        path = tmp_path / f"scale_{denominator}.xlsx"
        export_excel(model, [line], ExportOptions(
            path=str(path), include_info=False, scale_denominator=denominator))
        ws = load_workbook(path)["坐标计算表"]
        assert ws["D3"].value == expected, denominator
        # 坐标不参与比例换算
        assert ws["C6"].value == 0.0


def test_planar_distance_uses_arc_length(tmp_path):
    """圆弧段的平距取弧长：半径 10 的半圆弧长 31.416，而不是弦长 20。"""
    layer = LayerInfo(name="弧", entity_count=1)
    arc = EntityRecord(
        handle=1, dxftype="LWPOLYLINE", layer="弧", color=(255, 255, 255),
        points=[(0.0, 0.0, 0.0), (20.0, 0.0, 0.0)], bulges=[1.0],
        source_handle=1, bbox=(0.0, 0.0, 20.0, 10.0),
    )
    model = DrawingModel(path="arc.dwg", version="AC1018", insunits=6,
                         entities=[arc], layers={"弧": layer},
                         bbox=(0.0, 0.0, 20.0, 10.0))
    path = tmp_path / "arc.xlsx"
    export_excel(model, [arc], ExportOptions(path=str(path), include_info=False))
    ws = load_workbook(path)["坐标计算表"]
    assert math.isclose(ws["D3"].value, 31.416, abs_tol=1e-3)


def test_info_sheet_records_scale(tmp_path):
    model, entities = make_model()
    path = tmp_path / "info.xlsx"
    export_excel(model, entities, ExportOptions(path=str(path), scale_denominator=500))
    ws = load_workbook(path)["导出信息"]
    rows = {ws.cell(row=r, column=1).value: ws.cell(row=r, column=2).value
            for r in range(2, ws.max_row + 1)}
    assert rows["比例尺"].startswith("1:500")
    assert "弧长" in rows["平距口径"]

def test_three_lines_share_one_sheet_with_blank_row_between(tmp_path):
    """多条线一次导出：同一张 sheet 里一块接一块，块与块之间正好空一行。"""
    layer = LayerInfo(name="测试层", entity_count=3)
    entities = []
    for index in range(3):
        base = float(index) * 100.0
        entities.append(EntityRecord(
            handle=10 + index, dxftype="LWPOLYLINE", layer="测试层",
            color=(255, 255, 255),
            points=[(base, 0.0, 0.0), (base + 10.0, 0.0, 0.0),
                    (base + 10.0, 10.0, 0.0)],
            bbox=(base, 0.0, base + 10.0, 10.0),
        ))
    model = DrawingModel(path="multi.dwg", version="AC1018", insunits=6,
                         entities=entities, layers={"测试层": layer},
                         bbox=(0.0, 0.0, 210.0, 10.0))
    path = tmp_path / "multi.xlsx"
    result = export_excel(model, entities, ExportOptions(path=str(path), include_info=False))
    assert result.line_rows == 3 and result.point_rows == 9

    ws = load_workbook(path)["坐标计算表"]
    for block in range(3):
        start = 1 + block * 10
        assert ws.cell(row=start, column=1).value == "工程名称"
        assert ws.cell(row=start, column=3).value == f"线{block + 1}"
        assert ws.cell(row=start + 1, column=3).value == "P1"
        assert ws.cell(row=start + 5, column=3).value == block * 100.0
    for gap in (10, 20):
        assert all(ws.cell(row=gap, column=col).value is None for col in range(1, 9))


def _slope_model():
    layer = LayerInfo(name="坡线", entity_count=1)
    entity = EntityRecord(
        handle=99, dxftype="POLYLINE", layer="坡线", color=(255, 255, 255),
        points=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.5), (20.0, 0.0, 100.0)],
        bbox=(0.0, 0.0, 20.0, 0.0),
    )
    return DrawingModel(path="slope.dwg", version="AC1018", insunits=6,
                        entities=[entity], layers={"坡线": layer},
                        bbox=(0.0, 0.0, 20.0, 0.0)), entity


def test_slope_left_blank_when_switch_off(tmp_path):
    model, entity = _slope_model()
    path = tmp_path / "off.xlsx"
    export_excel(model, [entity], ExportOptions(path=str(path), include_info=False))
    ws = load_workbook(path)["坐标计算表"]
    for col in (4, 6):
        cell = ws.cell(row=9, column=col)
        assert cell.value is None
        assert cell.number_format == "0.00%"


def test_slope_filled_when_switch_on(tmp_path):
    model, entity = _slope_model()
    path = tmp_path / "on.xlsx"
    export_excel(model, [entity],
                 ExportOptions(path=str(path), include_info=False, fill_slope=True))
    ws = load_workbook(path)["坐标计算表"]
    up = ws.cell(row=9, column=4)
    down = ws.cell(row=9, column=6)
    assert abs(up.value - 0.05) < 1e-9      # 0.5 m / 10 m = 5%
    assert abs(down.value + 0.05) < 1e-9    # -0.5 m / 10 m = -5%
    assert up.number_format == "0.00%" and down.number_format == "0.00%"
