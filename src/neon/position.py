from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    """Line and column are 1-based, offset 0-based; all in code points."""

    line: int
    column: int
    offset: int


class Cursor:
    """Computes positions of increasing offsets in one pass."""

    __slots__ = ("_column", "_index", "_line", "_s")

    def __init__(self, s: str) -> None:
        self._s = s
        self._index = 0
        self._line = 1
        self._column = 1

    def at(self, index: int) -> Position:
        if index < self._index:
            self._index = 0
            self._line = 1
            self._column = 1

        s = self._s
        lines = s.count("\n", self._index, index)
        if lines:
            self._line += lines
            self._column = index - s.rfind("\n", self._index, index)
        else:
            self._column += index - self._index
        self._index = index
        return Position(self._line, self._column, index)
