"""点选模式的点序列模型。

一条线不再整条选中，而是按端点顺序逐个点选：每次单击记录一个图纸顶点，
按空格结束当前一轮并开始下一轮。每轮导出一块「坐标计算表」，与多选导出
的排版完全一致（点号、平距、方位、X/Y/Z 阶梯排列）。

模型本身不依赖 Qt，也不改图纸：原始实体只读，点选出来的序列另存为合成实体。
"""
from __future__ import annotations

from dataclasses import dataclass

from .geometry import Point3
from .model import DrawingModel, EntityRecord

PICK_LAYER_PREFIX = "点选"
PICK_DXFTYPE = "PICK"
PICK_COLOR = (127, 227, 168)

# 重合判定容差（图纸单位）：点直接取自实体顶点，理论上完全相等，
# 留一点容差是为了容纳同一位置在两条实体里各存一份时的极小差值
MATCH_TOL = 1e-6
# 连续两次点在同一位置视为误触，直接忽略
DUPLICATE_TOL = 1e-9
UNDO_LIMIT = 200


@dataclass(frozen=True, slots=True)
class Pick:
    """一个被点选的顶点。``handle``/``index`` 记录来源，便于复核。"""

    point: Point3
    handle: int = 0
    index: int = -1


def _same_plan(a: Point3, b: Point3, tol: float) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _run_matches(points: list[Point3], start: int, seq: list[Point3],
                 tol: float, step: int, closed: bool) -> bool:
    """从 ``points[start]`` 起沿 ``step`` 方向逐点比对 ``seq``。"""
    count = len(points)
    for offset, target in enumerate(seq):
        index = start + step * offset
        if closed:
            index %= count
        elif index < 0 or index >= count:
            return False
        if not _same_plan(points[index], target, tol):
            return False
    return True


def match_sequence(points: list[Point3], seq: list[Point3], tol: float = MATCH_TOL,
                   closed: bool = False) -> bool:
    """判断 ``seq`` 是否与 ``points`` 中一段连续顶点（正向或反向）重合。"""
    if len(seq) < 2 or len(points) < len(seq):
        return False
    first = seq[0]
    for start, point in enumerate(points):
        if not _same_plan(point, first, tol):
            continue
        if _run_matches(points, start, seq, tol, 1, closed):
            return True
        if _run_matches(points, start, seq, tol, -1, closed):
            return True
    return False


def match_whole(points: list[Point3], seq: list[Point3], tol: float = MATCH_TOL,
                closed: bool = False) -> bool:
    """判断 ``seq`` 是否与整条 ``points`` 重合（点数相同，正反方向或闭合线任意起点）。

    只有整条线被完整点一遍才算重合：半条线只是「沿着这条线取点」，

    不应该提示用户「选的就是这条线」，也不应该把整条线高亮出来。
    """
    count = len(points)
    if count < 2 or len(seq) != count:
        return False
    if closed:
        return any(_run_matches(points, start, seq, tol, 1, True)
                   or _run_matches(points, start, seq, tol, -1, True)
                   for start in range(count))
    return _run_matches(points, 0, seq, tol, 1, False) or \
        _run_matches(points, count - 1, seq, tol, -1, False)


class PickModel:
    """按轮次保存点选序列，并提供撤销、合成实体与重合判定。"""

    def __init__(self) -> None:
        self._rounds: list[list[Pick]] = []
        self._current: list[Pick] = []
        self._undo: list[tuple[list[list[Pick]], list[Pick]]] = []
        self._redo: list[tuple[list[list[Pick]], list[Pick]]] = []

    # ------------------------------------------------------------ 状态
    def blocks(self) -> list[list[Pick]]:
        """所有点选块：已结束的各轮 + 正在进行的这一轮。"""
        blocks = [list(block) for block in self._rounds]
        if self._current:
            blocks.append(list(self._current))
        return blocks

    def block_points(self) -> list[list[Point3]]:
        return [[pick.point for pick in block] for block in self.blocks()]

    @property
    def rounds(self) -> list[list[Pick]]:
        return [list(block) for block in self._rounds]

    @property
    def current(self) -> list[Pick]:
        return list(self._current)

    @property
    def current_length(self) -> int:
        return len(self._current)

    @property
    def round_count(self) -> int:
        return len(self._rounds) + (1 if self._current else 0)

    @property
    def total_points(self) -> int:
        return sum(len(block) for block in self._rounds) + len(self._current)

    @property
    def current_block_index(self) -> int:
        """当前轮在 :meth:`blocks` 中的下标；当前轮为空时为 -1。"""
        if not self._current:
            return -1
        return len(self._rounds)

    def points(self) -> list[Point3]:
        return [pick.point for block in self._rounds for pick in block] + \
               [pick.point for pick in self._current]

    # ------------------------------------------------------------ 变更
    def _snapshot(self) -> tuple[list[list[Pick]], list[Pick]]:
        return ([list(block) for block in self._rounds], list(self._current))

    def _push(self) -> None:
        self._undo.append(self._snapshot())
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, state: tuple[list[list[Pick]], list[Pick]]) -> None:
        rounds, current = state
        self._rounds = [list(block) for block in rounds]
        self._current = list(current)

    def add(self, point: Point3, handle: int = 0, index: int = -1) -> bool:
        """追加一个点；与上一个点重合时不加并返回 ``False``。"""
        if self._current and _same_plan(self._current[-1].point, point, DUPLICATE_TOL):
            return False
        self._push()
        self._current.append(Pick(point=tuple(point), handle=handle, index=index))
        return True

    def remove_last(self) -> bool:
        """撤销最后一个点（鼠标右键）。

        当前轮为空时回退到上一轮：把那一轮重新打开，再撤掉它的最后一个点，
        这样按空格之后发现多点了一个，也能直接用右键改掉。
        """
        if self._current:
            self._push()
            self._current.pop()
            return True
        if self._rounds and self._rounds[-1]:
            self._push()
            self._current = self._rounds.pop()
            self._current.pop()
            return True
        return False

    def finish_round(self) -> bool:
        """结束当前轮并开始下一轮（空格）；当前轮为空时不产生新轮。"""
        if not self._current:
            return False
        self._push()
        self._rounds.append(self._current)
        self._current = []
        return True

    def clear_current(self) -> bool:
        if not self._current:
            return False
        self._push()
        self._current = []
        return True

    def clear(self) -> bool:
        if not self._rounds and not self._current:
            return False
        self._push()
        self._rounds = []
        self._current = []
        return True

    def reset(self) -> None:
        """换图/清空图纸：连同撤销记录一起丢弃。"""
        self._rounds = []
        self._current = []
        self._undo = []
        self._redo = []

    # ------------------------------------------------------------ 撤销
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    # ------------------------------------------------------------ 导出
    def entities(self) -> list[EntityRecord]:
        """把每一轮点选合成一条开口折线，供表格排版与待导出列表复用。

        句柄取负数，避免与图纸里的真实句柄冲突；图层名带轮次（点选1、点选2…），
        在待导出列表里能直接看出这是第几轮点选。
        """
        result: list[EntityRecord] = []
        for index, block in enumerate(self.blocks()):
            points = [pick.point for pick in block]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            result.append(EntityRecord(
                handle=-1 - index,
                dxftype=PICK_DXFTYPE,
                layer=f"{PICK_LAYER_PREFIX}{index + 1}",
                color=PICK_COLOR,
                points=points,
                source_handle=block[0].handle,
                bbox=(min(xs), min(ys), max(xs), max(ys)),
            ))
        return result

    # ------------------------------------------------------------ 重合判定
    def match_entity(self, model: DrawingModel | None,
                     visible_layers: set[str] | None = None,
                     allowed_types: set[str] | None = None,
                     tol: float = MATCH_TOL) -> int | None:
        """返回与当前点选序列**整条重合**的实体句柄。

        优先比对正在进行的这一轮（点数 >= 2），否则比对最后完成的一轮；
        点数必须与实体顶点数相同，正反两个方向都算，闭合线允许任意起点。
        """
        if model is None:
            return None
        seq = self._match_sequence_points()
        if len(seq) < 2:
            return None
        xs = [point[0] for point in seq]
        ys = [point[1] for point in seq]
        sx0, sx1 = min(xs) - tol, max(xs) + tol
        sy0, sy1 = min(ys) - tol, max(ys) + tol
        visible = visible_layers if visible_layers is not None else model.visible_layers()
        for entity in model.entities:
            if entity.is_point or len(entity.points) != len(seq):
                continue
            if any(entity.bulges):
                # 有圆弧的线：直着连起来的点不可能与它重合
                continue
            if entity.layer not in visible:
                continue
            if allowed_types is not None and entity.dxftype not in allowed_types:
                continue
            bx0, by0, bx1, by1 = entity.bbox
            if bx1 < sx0 or bx0 > sx1 or by1 < sy0 or by0 > sy1:
                continue
            if match_whole(entity.points, seq, tol, entity.closed):
                return entity.handle
        return None

    def _match_sequence_points(self) -> list[Point3]:
        if len(self._current) >= 2:
            return [pick.point for pick in self._current]
        for block in reversed(self._rounds):
            if len(block) >= 2:
                return [pick.point for pick in block]
        return []
