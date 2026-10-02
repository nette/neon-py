from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from .nodes import ArrayItemNode, Node, ValueNode


class TraverseAction(Enum):
    """What a visitor returns to steer the walk."""

    SKIP_CHILDREN = "SkipChildren"
    STOP = "Stop"
    REMOVE = "Remove"


type VisitResult = ValueNode | TraverseAction | None
"""Nothing to go on, a node to take the place of the visited one, or an action."""

type Visitor = Callable[[Node], VisitResult]


class Traverser:
    """
    Walks the tree depth-first, calling enter() before the children of a node and leave()
    after them. The children of a node are taken when it is entered, so nodes inserted
    around the visited one later are not visited, and a child taken out of the node
    meanwhile is skipped; a node the visitor takes out of its place itself is neither
    walked into nor left. A replacement is visited from its children on. STOP ends the
    walk at once: no node is entered or left after it. The walk is not one atomic edit:
    the edits before a failure stay.
    """

    def __init__(self, enter: Visitor | None, leave: Visitor | None) -> None:
        self._enter = enter
        self._leave = leave
        self._stopped = False
        self._path: list[tuple[Node, Node | None]] = []
        """The nodes being walked, each with the parent it was entered under."""

    @staticmethod
    def traverse(
        node: Node, enter: Visitor | None = None, leave: Visitor | None = None
    ) -> Node | None:
        """Walks the tree; returns what stands in the place of the node afterwards."""
        return Traverser(enter, leave)._visit(node)

    def _visit(self, node: Node) -> Node | None:
        """The node in the place of the visited one afterwards, None if removed or taken out."""
        level = len(self._path)
        self._path.append((node, node.parent))
        try:
            result = self._enter(node) if self._enter else None
            current = self._apply(node, result)
            if current is None:
                return None
            self._path[level] = (current, self._path[level][1])
            if not self._is_in_place(level):
                return None
            if self._stopped:
                return current

            if result is not TraverseAction.SKIP_CHILDREN:
                for child in current.get_children():
                    if isinstance(child, Node) and child.parent is current:
                        self._visit(child)
                        if self._stopped:
                            return current
                        if not self._is_in_place(level):
                            return None

            result = self._leave(current) if self._leave else None
            return self._apply(current, result)
        finally:
            self._path.pop()

    def _is_in_place(self, level: int) -> bool:
        """Whether the node at the level and those above it stand where they were entered."""
        return all(node.parent is parent for node, parent in self._path[: level + 1])

    def _apply(self, node: Node, result: VisitResult) -> Node | None:
        if result is TraverseAction.STOP:
            self._stopped = True
        elif result is TraverseAction.REMOVE:
            if not isinstance(node, ArrayItemNode):
                raise TypeError("Only an item can be removed; replace any other node.")
            node.remove()
            return None
        elif isinstance(result, ValueNode):
            if not isinstance(node, ValueNode):
                raise TypeError("Only a value node can be replaced.")
            node.replace_with(result)
            return result
        elif result is not None and result is not TraverseAction.SKIP_CHILDREN:
            raise TypeError("A visitor returns None, a ValueNode or a TraverseAction.")
        return node
