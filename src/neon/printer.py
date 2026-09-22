from __future__ import annotations

from collections.abc import Iterable

from .nodes import Node
from .position import Cursor, Position
from .token import Token, Trivia


def print_node(node: Node) -> str:
    """The source text of the node, with the trivia of its tokens."""
    return node.print()


def print_text(node: Node) -> str:
    """The text of the node without the outer trivia of its first and last token."""
    tokens = node.get_tokens()
    parts: list[str] = []
    for i, token in enumerate(tokens):
        if i > 0:
            parts.append(_trivia_text(token.leading_trivia))
        parts.append(token.text)
        if i < len(tokens) - 1:
            parts.append(_trivia_text(token.trailing_trivia))
    return "".join(parts)


def locate_all(root: Node) -> dict[Token, Position]:
    """Current positions of all tokens of the tree in one walk, for an editor asking many."""
    tokens = root.get_tokens()
    offsets: list[int] = []
    parts: list[str] = []
    length = 0
    for token in tokens:
        leading = _trivia_text(token.leading_trivia)
        rest = token.text + _trivia_text(token.trailing_trivia)
        offsets.append(length + len(leading))
        parts += (leading, rest)
        length += len(leading) + len(rest)

    cursor = Cursor("".join(parts))
    return {
        token: cursor.at(offset) for token, offset in zip(tokens, offsets, strict=True)
    }


def _trivia_text(trivia: Iterable[Trivia]) -> str:
    return "".join(t.text for t in trivia)
