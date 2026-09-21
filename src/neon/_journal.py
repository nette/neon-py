from collections.abc import Callable
from contextvars import ContextVar, Token
from types import TracebackType

type _Entries = list[Callable[[], None]]

# per thread and per asyncio task, so that an edit never records into a journal of another
_journal: ContextVar[_Entries | None] = ContextVar("journal", default=None)


def record(undo: Callable[[], None]) -> None:
    """Notes how to undo a write of the tree, while an atomic() operation runs."""
    entries = _journal.get()
    if entries is not None:
        entries.append(undo)


class atomic:
    """Runs an operation; if it raises, every write it made is undone."""

    __slots__ = ("_token",)

    def __enter__(self) -> None:
        self._token: Token[_Entries | None] | None = None
        if _journal.get() is None:
            self._token = _journal.set([])

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._token is None:
            return
        entries = _journal.get()
        _journal.reset(self._token)
        if error is not None and entries:
            for undo in reversed(entries):
                undo()
