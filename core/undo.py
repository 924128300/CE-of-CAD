"""选择集与撤销栈。"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack


class SelectionModel(QObject):
    """按选择顺序保存句柄，保持唯一。"""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handles: list[int] = []
        self._set: set[int] = set()
        # 已反向的要素句柄：随图纸保存，取消选中再选回来仍保持反向
        self._reversed: set[int] = set()

    @property
    def handles(self) -> list[int]:
        return list(self._handles)

    def __len__(self) -> int:
        return len(self._handles)

    def __contains__(self, handle: int) -> bool:
        return handle in self._set

    def snapshot(self) -> list[int]:
        return list(self._handles)

    @property
    def reversed_handles(self) -> set[int]:
        return set(self._reversed)

    def is_reversed(self, handle: int) -> bool:
        return handle in self._reversed

    def reversed_snapshot(self) -> set[int]:
        return set(self._reversed)

    def set_reversed_handles(self, handles: set[int]) -> None:
        new = set(handles)
        if new == self._reversed:
            return
        self._reversed = new
        self.changed.emit()

    def reset(self) -> None:
        """换图/清空图纸时重置选择与反向状态。"""
        self._handles = []
        self._set = set()
        self._reversed = set()
        self.changed.emit()

    def apply(self, handles: list[int]) -> None:
        seen: set[int] = set()
        ordered: list[int] = []
        for handle in handles:
            if handle not in seen:
                seen.add(handle)
                ordered.append(handle)
        self._handles = ordered
        self._set = seen
        self.changed.emit()


class _ReverseCommand(QUndoCommand):
    """反向/恢复：只改 reversed 集合，不动选择集。"""

    def __init__(self, model: SelectionModel, before: set[int], after: set[int],
                 text: str) -> None:
        super().__init__(text)
        self._model = model
        self._before = set(before)
        self._after = set(after)

    def redo(self) -> None:
        self._model.set_reversed_handles(self._after)

    def undo(self) -> None:
        self._model.set_reversed_handles(self._before)

class _ReplaceCommand(QUndoCommand):
    def __init__(self, model: SelectionModel, before: list[int], after: list[int], text: str) -> None:
        super().__init__(text)
        self._model = model
        self._before = list(before)
        self._after = list(after)

    def redo(self) -> None:
        self._model.apply(self._after)

    def undo(self) -> None:
        self._model.apply(self._before)


class SelectionHistory:
    """把选择集变更封装成可撤销命令。"""

    def __init__(self, model: SelectionModel, parent: QObject | None = None) -> None:
        self.model = model
        self.stack = QUndoStack(parent)
        self.stack.setUndoLimit(200)

    def replace(self, handles: list[int], text: str) -> None:
        before = self.model.snapshot()
        after = list(handles)
        if before == after:
            return
        self.stack.push(_ReplaceCommand(self.model, before, after, text))

    def add(self, handles: list[int]) -> None:
        before = self.model.snapshot()
        merged = list(before)
        seen = set(before)
        for handle in handles:
            if handle not in seen:
                seen.add(handle)
                merged.append(handle)
        self.replace(merged, f"选择 {len(handles)} 条要素")

    def remove(self, handles: list[int]) -> None:
        drop = set(handles)
        self.replace([h for h in self.model.snapshot() if h not in drop],
                     f"移除 {len(handles)} 条要素")

    def clear(self) -> None:
        self.replace([], "清空选择")

    def toggle_reversed(self, handles: list[int]) -> None:
        """逐条翻转点序方向（已反向的恢复正向），作为一条可撤销命令。"""
        before = self.model.reversed_snapshot()
        after = set(before)
        for handle in handles:
            if handle in after:
                after.discard(handle)
            else:
                after.add(handle)
        if before == after:
            return
        self.stack.push(_ReverseCommand(self.model, before, after,
                                        f"反向 {len(handles)} 条要素"))

    def undo(self) -> None:
        self.stack.undo()

    def redo(self) -> None:
        self.stack.redo()

    @property
    def can_undo(self) -> bool:
        return self.stack.canUndo()

    @property
    def can_redo(self) -> bool:
        return self.stack.canRedo()

    @property
    def undo_text(self) -> str:
        return self.stack.undoText()

    @property
    def redo_text(self) -> str:
        return self.stack.redoText()
