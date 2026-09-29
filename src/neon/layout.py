from __future__ import annotations

from collections.abc import Iterable, Iterator

from .nodes import ArrayItemNode, BlockArrayNode, DocumentNode, Node
from .scanner import TriviaKind
from .token import Token, Trivia, iterate_neighbours


class Layout:
    """Layout of new text, derived from the neighbourhood of the place of an edit."""

    @staticmethod
    def unit(at: Node) -> str:
        """The difference of indentation between a nested block and its parent."""
        for candidate in _candidates(at):
            unit = _unit_of(candidate)
            if unit:
                return unit
        return "\t"

    @staticmethod
    def indentation(item: ArrayItemNode) -> str:
        """
        The indentation of the block the item is in. It is the indentation of the line
        of the item, except for the first item of a block opened on the line of a dash,
        which stands after the dash.
        """
        block = item.parent
        owner = block.parent if block else None
        if (
            isinstance(block, BlockArrayNode)
            and isinstance(owner, ArrayItemNode)
            and owner.bullet
            and not _has_line_ending(owner.bullet.trailing_trivia)
        ):
            if len(block.items) > 1:
                return block.items[1].get_indentation()
            # as the parser decides: a tab if the next line within the block starts with one
            outer = Layout.indentation(owner)
            following = next(
                (
                    token
                    for token in block.get_tokens()[1:]
                    if any(
                        t.kind == TriviaKind.WHITESPACE for t in token.leading_trivia
                    )
                ),
                None,
            )
            indent = following.leading_trivia[-1].text if following else ""
            return outer + ("\t" if indent.startswith(outer + "\t") else "  ")
        return item.get_indentation()

    @staticmethod
    def line_ending(at: Node | Token) -> str:
        """The line ending of the nearest preceding token, else the first of the document, else LF."""
        root = _root_of(at)
        if root is None:
            return "\n"
        token = at if isinstance(at, Token) else at.get_first_token()
        first = root.get_first_token()
        return (
            _find_line_ending(iterate_neighbours(token, backward=True))
            or _find_line_ending([first])
            or _find_line_ending(iterate_neighbours(first, backward=False))
            or "\n"
        )


def _find_line_ending(tokens: Iterable[Token]) -> str | None:
    for token in tokens:
        for t in (*token.trailing_trivia, *token.leading_trivia):
            if t.kind == TriviaKind.LINE_ENDING:
                return t.text
    return None


def _candidates(at: Node) -> Iterator[BlockArrayNode]:
    """The blocks to take the unit from: the siblings, the nearest first, the ancestors, all."""
    block = at if isinstance(at, BlockArrayNode) else at.find_ancestor(BlockArrayNode)
    if block:
        item = at if isinstance(at, ArrayItemNode) else at.find_ancestor(ArrayItemNode)
        items = block.items
        index = next((i for i, x in enumerate(items) if x is item), 0)
        for distance in range(len(items)):
            for i in (index - distance, index + distance) if distance else (index,):
                value = items[i].value if 0 <= i < len(items) else None
                if isinstance(value, BlockArrayNode):
                    yield value
    node: Node | None = block
    while node is not None:
        if isinstance(node, BlockArrayNode):
            yield node
        node = node.parent
    root = _root_of(at)
    if root:
        yield from root.find(BlockArrayNode)


def _unit_of(block: BlockArrayNode) -> str | None:
    """Unit of a nested block; None for a block opened on the line of a dash or not nested."""
    owner = block.parent
    if not isinstance(owner, ArrayItemNode):
        return None
    head = owner.colon or owner.bullet
    if not head or not _has_line_ending(head.trailing_trivia):
        return None  # opened on the line of the dash
    outer = owner.get_indentation()
    inner = block.items[0].get_indentation()
    if len(inner) > len(outer) and inner.startswith(outer):
        return inner[len(outer) :]
    return None


def _root_of(at: Node | Token) -> DocumentNode | None:
    if isinstance(at, DocumentNode):
        return at
    node = at.parent
    while node is not None and node.parent is not None:
        node = node.parent
    return node if isinstance(node, DocumentNode) else None


def _has_line_ending(trivia: Iterable[Trivia]) -> bool:
    return any(t.kind == TriviaKind.LINE_ENDING for t in trivia)
