"""点选模型：轮次、撤销、合成导出实体、与多段线重合判定。"""
from __future__ import annotations

from openpyxl import load_workbook

from core.excel_export import ExportOptions, export_excel
from core.model import DrawingModel, EntityRecord, LayerInfo
from core.pick_model import PickModel, match_sequence, match_whole

POINTS = [
    (0.0, 0.0, 0.0),
    (100.0, 0.0, 1.0),
    (100.0, 100.0, 2.0),
    (0.0, 100.0, 3.0),
]


def _model(closed: bool = False) -> DrawingModel:
    entity = EntityRecord(
        handle=11,
        dxftype="LWPOLYLINE",
        layer="0",
        color=(255, 255, 255),
        points=list(POINTS),
        closed=closed,
        bbox=(0.0, 0.0, 100.0, 100.0),
    )
    return DrawingModel(
        path="D:/tmp/点选.dwg",
        version="AC1015",
        entities=[entity],
        layers={"0": LayerInfo("0", entity_count=1)},
        bbox=(0.0, 0.0, 100.0, 100.0),
    )


def _picks(*indexes: int) -> PickModel:
    picks = PickModel()
    for index in indexes:
        assert picks.add(POINTS[index], 11, index)
    return picks


def test_rounds_duplicate_and_remove() -> None:
    picks = _picks(0)
    assert not picks.add(POINTS[0], 11, 0), "与上一个点重合应被忽略"
    assert picks.add(POINTS[1], 11, 1)
    assert picks.total_points == 2
    assert picks.round_count == 1
    assert picks.current_length == 2
    assert picks.current_block_index == 0
    assert picks.block_points() == [[POINTS[0], POINTS[1]]]

    assert picks.finish_round()
    assert picks.round_count == 1
    assert picks.current_block_index == -1
    assert not picks.finish_round(), "空轮不应再开出新一轮"

    assert picks.add(POINTS[2], 11, 2)
    assert picks.round_count == 2
    assert picks.current_block_index == 1
    assert picks.block_points() == [[POINTS[0], POINTS[1]], [POINTS[2]]]

    assert picks.remove_last()
    assert picks.current_length == 0
    # 当前轮为空时右键回退到上一轮最后一个点，被回退的轮次重新打开
    assert picks.remove_last()
    assert picks.current_length == 1 and picks.round_count == 1
    assert picks.block_points() == [[POINTS[0]]]
    picks.undo()
    assert picks.current_length == 0
    assert picks.block_points() == [[POINTS[0], POINTS[1]]]
    picks.undo()
    assert picks.current_length == 1  # 回到「刚点完 p2」


def test_undo_redo_and_clear() -> None:
    picks = _picks(0, 1)
    picks.finish_round()
    picks.add(POINTS[2], 11, 2)

    assert picks.total_points == 3 and picks.round_count == 2

    picks.undo()  # 撤销第三个点
    assert picks.total_points == 2 and picks.round_count == 1
    assert picks.current_length == 0

    picks.undo()  # 撤销「结束本轮」
    assert picks.current_length == 2 and picks.rounds == []
    assert picks.round_count == 1

    picks.redo()
    assert picks.current_length == 0 and picks.round_count == 1

    assert picks.clear()
    assert picks.total_points == 0
    picks.undo()
    assert picks.total_points == 2

    picks.reset()
    assert picks.total_points == 0
    assert not picks.can_undo and not picks.can_redo


def test_entities_are_synthetic_blocks() -> None:
    picks = _picks(0, 1)
    picks.finish_round()
    picks.add(POINTS[2], 11, 2)
    entities = picks.entities()

    assert len(entities) == 2
    first, second = entities
    assert first.handle == -1 and second.handle == -2
    assert first.dxftype == "PICK" and first.layer == "点选1"
    assert second.layer == "点选2"
    assert first.points == [POINTS[0], POINTS[1]]
    assert second.points == [POINTS[2]]
    assert first.bbox == (0.0, 0.0, 100.0, 0.0)
    assert first.closed is False
    assert first.source_handle == 11


def test_match_sequence_forward_reverse_and_wrap() -> None:
    points = list(POINTS)
    assert match_sequence(points, [POINTS[1], POINTS[2], POINTS[3]])
    assert match_sequence(points, [POINTS[3], POINTS[2], POINTS[1]]), "反方向也应视为重合"
    assert not match_sequence(points, [POINTS[0], POINTS[2]])
    assert not match_sequence(points, [POINTS[0], POINTS[1], POINTS[3]])
    assert match_sequence(points, [POINTS[3], POINTS[0]], closed=True), "闭合线允许跨首尾"
    assert not match_sequence(points, [POINTS[3], POINTS[0]], closed=False)


def test_match_whole_requires_same_point_count() -> None:
    points = list(POINTS)
    assert match_whole(points, [POINTS[0], POINTS[1], POINTS[2], POINTS[3]])
    assert match_whole(points, [POINTS[3], POINTS[2], POINTS[1], POINTS[0]])
    assert not match_whole(points, [POINTS[0], POINTS[1], POINTS[2]]), "半条线不算重合"
    assert not match_whole(points, [POINTS[0], POINTS[2], POINTS[3], POINTS[1]])
    # 闭合线允许任意起点
    assert match_whole(points, [POINTS[2], POINTS[3], POINTS[0], POINTS[1]],
                       closed=True)
    assert not match_whole(points, [POINTS[2], POINTS[3], POINTS[0], POINTS[1]],
                           closed=False)


def test_match_entity_respects_layer_and_type() -> None:
    picks = _picks(0, 1, 2, 3)
    model = _model()
    assert picks.match_entity(model) == 11

    assert picks.match_entity(model, visible_layers=set()) is None
    assert picks.match_entity(model, allowed_types={"LINE"}) is None
    assert picks.match_entity(None) is None

    # 当前轮只有 1 个点：退回比对最后完成的一轮
    picks.finish_round()
    picks.add(POINTS[0], 11, 0)
    assert picks.match_entity(model) == 11

    # 半条线、跳点、中间有圆弧的线都不算重合
    partial = _picks(0, 1, 2)
    assert partial.match_entity(model) is None
    broken = PickModel()
    broken.add(POINTS[0], 11, 0)
    broken.add(POINTS[2], 11, 2)
    broken.add(POINTS[3], 11, 3)
    broken.add(POINTS[1], 11, 1)
    assert broken.match_entity(model) is None
    assert partial.match_entity(model, allowed_types={"LINE"}) is None


def test_pick_entities_export(tmp_path) -> None:
    picks = _picks(0, 1, 2)
    target = tmp_path / "点选导出.xlsx"
    result = export_excel(_model(), picks.entities(),
                          ExportOptions(path=str(target), pick_mode=True))

    assert result.line_rows == 1 and result.point_rows == 3
    wb = load_workbook(target)
    ws = wb["坐标计算表"]
    assert ws["A1"].value == "工程名称"
    assert ws["C1"].value == "点选1"
    assert ws["C2"].value == "P1" and ws["E2"].value == "P2"
    assert ws["C6"].value == 0 and ws["E6"].value == 100 and ws["G6"].value == 100
    assert ws["C7"].value == 0 and ws["G7"].value == 100
    assert ws["D3"].value == 100 and ws["F3"].value == 100
    assert ws["D5"].value == "90°00′00″" and ws["F5"].value == "0°00′00″"

    info = wb["导出信息"]
    values = {info.cell(row=row, column=1).value: info.cell(row=row, column=2).value
              for row in range(2, info.max_row + 1)}
    assert "点选" in values["选择方式"]
