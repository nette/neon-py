import re
from typing import Any

import pytest

from neon import (
    ArrayItemNode,
    LiteralNode,
    Node,
    TraverseAction,
    Traverser,
    VisitResult,
    parse,
)


def names(node: Node) -> str:
    return node.token.text if isinstance(node, LiteralNode) else type(node).__name__


def test_order_of_enter_and_leave() -> None:
    document = parse("a: [b, c]\nd: e")
    log: list[str] = []
    Traverser.traverse(
        document,
        lambda node: log.append("> " + names(node)),
        lambda node: log.append("< " + names(node)),
    )
    assert log == [
        "> DocumentNode", "> BlockArrayNode",
        "> ArrayItemNode", "> a", "< a", "> InlineArrayNode",
        "> ArrayItemNode", "> b", "< b", "< ArrayItemNode",
        "> ArrayItemNode", "> c", "< c", "< ArrayItemNode",
        "< InlineArrayNode", "< ArrayItemNode",
        "> ArrayItemNode", "> d", "< d", "> e", "< e", "< ArrayItemNode",
        "< BlockArrayNode", "< DocumentNode",
    ]  # fmt: skip


def test_a_value_that_is_not_an_action_is_refused() -> None:
    document = parse("a: [b, c]\nd: e")
    visited = 0

    def enter(node: Node) -> Any:
        nonlocal visited
        visited += 1
        return 1

    with pytest.raises(TypeError, match=re.escape("A visitor returns")):
        Traverser.traverse(document, enter, lambda node: 2)  # ty: ignore[invalid-argument-type]
    assert visited == 1
    assert document.print() == "a: [b, c]\nd: e"


def test_skipping_children_and_stopping() -> None:
    document = parse("a: [b, c]\nd: e")
    log: list[str] = []

    def enter(node: Node) -> VisitResult:
        log.append(names(node))
        if isinstance(node, ArrayItemNode) and node.get_key_value() == "a":
            return TraverseAction.SKIP_CHILDREN
        if isinstance(node, LiteralNode) and node.token.text == "d":
            return TraverseAction.STOP
        return None

    Traverser.traverse(document, enter)
    assert log == [
        "DocumentNode",
        "BlockArrayNode",
        "ArrayItemNode",
        "ArrayItemNode",
        "d",
    ]


def test_removing_and_replacing() -> None:
    document = parse("debug: yes # on\nlist: [x, y, z]\n")

    def enter(node: Node) -> VisitResult:
        if isinstance(node, ArrayItemNode) and node.get_value() == "y":
            return TraverseAction.REMOVE
        if isinstance(node, LiteralNode) and node.token.text == "yes":
            value = parse("no").value
            assert value
            return value.detach()
        return None

    Traverser.traverse(document, enter)
    assert document.print() == "debug: no # on\nlist: [x, z]\n"
    with pytest.raises(TypeError, match=re.escape("Only an item can be removed")):
        Traverser.traverse(document, lambda node: TraverseAction.REMOVE)


def test_stopping_enters_and_leaves_nothing_after() -> None:
    document = parse("a:\n\tb: 1\nc: 2")
    log: list[str] = []

    def enter(node: Node) -> VisitResult:
        log.append("> " + names(node))
        if isinstance(node, LiteralNode) and node.token.text == "1":
            return TraverseAction.STOP
        return None

    Traverser.traverse(document, enter, lambda node: log.append("< " + names(node)))
    assert log == [
        "> DocumentNode", "> BlockArrayNode", "> ArrayItemNode", "> a", "< a",
        "> BlockArrayNode", "> ArrayItemNode", "> b", "< b", "> 1",
    ]  # fmt: skip


def test_a_sibling_taken_out_by_the_visitor_is_skipped() -> None:
    document = parse("a: 1\nb: 2\nc: 3\n")
    log: list[str | None] = []

    def enter(node: Node) -> VisitResult:
        if isinstance(node, ArrayItemNode):
            log.append(node.get_key_value())
            if node.get_key_value() == "a":
                sibling = node.get_next_sibling()
                assert isinstance(sibling, ArrayItemNode)
                sibling.remove()
            elif node.get_key_value() == "b":
                return TraverseAction.REMOVE
        return None

    Traverser.traverse(document, enter)
    assert log == ["a", "c"]
    assert document.print() == "a: 1\nc: 3\n"


def test_a_node_the_visitor_takes_out_itself_is_neither_walked_into_nor_left() -> None:
    document = parse("a: [x, y]\nb: [z]\n")
    log: list[str] = []

    def enter(node: Node) -> VisitResult:
        log.append("> " + names(node))
        if isinstance(node, ArrayItemNode) and node.get_key_value() == "a":
            node.remove()
        return None

    root = document.value
    assert root
    res = Traverser.traverse(root, enter, lambda node: log.append("< " + names(node)))
    assert res is root
    assert log == [
        "> BlockArrayNode", "> ArrayItemNode", "> ArrayItemNode", "> b", "< b",
        "> InlineArrayNode", "> ArrayItemNode", "> z", "< z", "< ArrayItemNode",
        "< InlineArrayNode", "< ArrayItemNode", "< BlockArrayNode",
    ]  # fmt: skip
    assert document.print() == "b: [z]\n"


def test_a_node_taken_out_while_its_children_are_walked_is_not_left() -> None:
    document = parse("a: [x, y]\nb: 1\n")
    log: list[str] = []

    def enter(node: Node) -> VisitResult:
        log.append("> " + names(node))
        if isinstance(node, LiteralNode) and node.token.text == "x":
            outer = node.find_ancestor(ArrayItemNode)
            assert outer
            top = outer.find_ancestor(ArrayItemNode)
            assert top
            top.remove()
        return None

    Traverser.traverse(document, enter, lambda node: log.append("< " + names(node)))
    assert log == [
        "> DocumentNode", "> BlockArrayNode", "> ArrayItemNode", "> a", "< a",
        "> InlineArrayNode", "> ArrayItemNode", "> x", "> ArrayItemNode", "> b",
        "< b", "> 1", "< 1", "< ArrayItemNode", "< BlockArrayNode", "< DocumentNode",
    ]  # fmt: skip
    assert document.print() == "b: 1\n"
