import json
import re
from typing import Any

import pytest
from corpus import Case, load_cases, runs_here
from guarantees import check_tree, snapshot
from typed import equal, to_host

from neon import (
    ArrayItemNode,
    ArrayNode,
    CommentPolicy,
    DocumentNode,
    Entity,
    ItemIndex,
    LiteralNode,
    PathSegment,
    StringNode,
    parse,
)

FIELDS = {
    "set": {"value", "create"},
    "add": {"value", "key", "position"},
    "remove": {"comments", "nullable", "mergeBlankLines"},
    "setKey": {"key"},
}


def path_of(op: dict[str, Any]) -> list[PathSegment]:
    path = op["path"]
    assert isinstance(path, list)
    return [ItemIndex(s["item"]) if isinstance(s, dict) else s for s in path]


def apply(document: DocumentNode, op: dict[str, Any]) -> ArrayItemNode | None:
    """Applies the operation; returns the item an `add` created."""
    known = FIELDS.get(op["op"])
    if known is None or set(op) - {"op", "path", "expectError", *known}:
        raise ValueError(f"Invalid operation {op}")
    if op.get("comments") not in (None, "drop", "move"):
        raise ValueError(f"Invalid operation {op}")
    path = path_of(op)
    value = to_host(op["value"]) if "value" in op else None
    match op["op"]:
        case "set":
            document.set_value(path, value, create=op.get("create", True))
        case "add":
            return document.add_item(
                path, value, key=op.get("key"), position=op.get("position")
            )
        case "remove":
            policy = CommentPolicy.MOVE_TO_NEXT_TOKEN
            document.remove_item(
                path,
                comments=policy if op.get("comments") == "move" else CommentPolicy.DROP,
                nullable=op.get("nullable"),
                merge_blank_lines=op.get("mergeBlankLines", False),
            )
        case "setKey":
            document.set_key(path, op["key"])
    return None


def item_lines(item: ArrayItemNode) -> tuple[int, int] | None:
    """
    The lines an item spans with the comment lines it owns above it, 0-based. Locality
    is checked only in arrays whose keys are all written or all implicit, where no repair
    of the grammar (keys written out, a null added) can happen.
    """
    parent = item.parent
    assert isinstance(parent, ArrayNode)
    keys = [other.key is not None for other in parent.items]
    if any(keys) and not all(keys):
        return None
    first = item.get_first_token()
    kinds = " ".join(t.kind for t in first.leading_trivia)
    lines = kinds.split("LineEnding")[:-1][::-1]
    owned = 0
    while owned < len(lines) and "Comment" in lines[owned]:
        owned += 1
    last = item.get_last_token()
    start = first.get_position()
    end = last.get_position()
    assert start and end
    return start.line - 1 - owned, end.line - 1 + last.text.count("\n")


def check_locality(with_item: str, without: str, lines: tuple[int, int]) -> None:
    """Only the lines of the item and one line on each side of it differ."""
    a = with_item.split("\n")
    b = without.split("\n")
    head = max(0, lines[0] - 1)
    tail = max(0, len(a) - lines[1] - 2)
    assert b[:head] == a[:head], "the lines before"
    assert (b[-tail:] if tail else []) == (a[-tail:] if tail else []), "the lines after"


# ---- an independent model of the value: plain values edited directly


def container(model: Any, path: list[PathSegment]) -> Any:
    node = model
    for segment in path:
        node = child(node, segment)
    return node.attributes if isinstance(node, Entity) else node


def child(node: Any, segment: PathSegment) -> Any:
    target = node.attributes if isinstance(node, Entity) else node
    if isinstance(segment, ItemIndex):
        return (
            list(target.values())[segment.index]
            if isinstance(target, dict)
            else target[segment.index]
        )
    return target[int(segment)] if isinstance(target, list) else target[str(segment)]


def set_in(parent: Any, key: PathSegment, value: Any) -> None:
    if isinstance(parent, list):
        parent[int(key)] = value  # ty: ignore[invalid-argument-type]
    else:
        parent[str(key)] = value


def apply_to_model(model: Any, op: dict[str, Any]) -> Any:
    path = path_of(op)
    value = to_host(op["value"]) if "value" in op else None
    if op["op"] == "set":
        if not path:
            return value
        parent = container(model, path[:-1])
        if parent is None:
            set_in(container(model, path[:-2]), path[-2], {str(path[-1]): value})
        else:
            set_in(parent, path[-1], value)
    elif op["op"] == "add":
        parent = container(model, path)
        position = op.get("position")
        if isinstance(parent, list) and "key" not in op:
            parent.insert(len(parent) if position is None else position, value)
        else:
            entries = list(parent.items())
            entries.insert(
                len(entries) if position is None else position, (op["key"], value)
            )
            parent.clear()
            parent.update(entries)
    elif op["op"] == "remove":
        parent = container(model, path[:-1])
        key = path[-1]
        if isinstance(parent, list):
            del parent[int(key)]  # ty: ignore[invalid-argument-type]
        else:
            del parent[str(key)]
        if not parent and op.get("nullable") and len(path) > 1:
            set_in(container(model, path[:-2]), path[-2], None)
        elif not parent and op.get("nullable"):
            return None
    elif op["op"] == "setKey":
        parent = container(model, path[:-1])
        entries = [
            (op["key"] if k == str(path[-1]) else k, v) for k, v in parent.items()
        ]
        parent.clear()
        parent.update(entries)
    return model


def scalar_lexeme(
    document: DocumentNode, path: list[PathSegment]
) -> tuple[int, int] | None:
    """Where the token of a scalar at the path stands in the printed text."""
    item = document.find_item(path)
    node = item.value if item else None
    if not isinstance(node, LiteralNode | StringNode):
        return None
    position = node.token.get_position()
    assert position
    return position.offset, position.offset + len(node.token.text)


def cases() -> list[Case]:
    return [c for c in load_cases("mutations") if runs_here(c)]


@pytest.mark.parametrize("case", cases(), ids=[c.name for c in cases()])
def test_mutations(case: Case) -> None:
    text = case.read(".neon")
    assert text is not None
    ops = json.loads(case.read(".ops.json") or "")
    document = parse(text)
    model = document.to_value()
    expected_value = case.read(
        ".expected.json"
    )  # where a repair makes the value differ

    for n, op in enumerate(ops):
        before = document.print()
        lexeme = scalar_lexeme(document, path_of(op)) if op["op"] == "set" else None
        removed = (
            document.find_item(path_of(op))
            if op["op"] == "remove" and "expectError" not in op
            else None
        )
        removed_lines = item_lines(removed) if removed else None
        if "expectError" in op:
            unchanged = snapshot(document)
            with pytest.raises(Exception, match=re.escape(op["expectError"])):
                apply(document, op)
            unchanged()
        else:
            added = apply(document, op)
            model = apply_to_model(model, op)
            added_lines = item_lines(added) if added else None
            if added_lines:
                check_locality(document.print(), before, added_lines)
        if removed_lines:
            check_locality(before, document.print(), removed_lines)
        check_tree(document)

        step_value = (
            expected_value
            if n == len(ops) - 1
            else case.read(f".expected.{n + 1}.json")
        )
        if expected_value is not None and len(ops) > 1 and n < len(ops) - 1:
            assert step_value is not None, f"missing .expected.{n + 1}.json"
        value = parse(document.print()).to_value()
        wanted = to_host(json.loads(step_value)) if step_value is not None else model
        assert equal(value, wanted), (
            f"the value after operation {n + 1}: {value!r} {wanted!r}"
        )

        scalar = "value" in op and op["value"]["type"] not in ("list", "map", "null")
        if lexeme and scalar:  # locality of a scalar change
            after = document.print()
            assert after[: lexeme[0]] == before[: lexeme[0]]
            assert (
                after[len(after) - (len(before) - lexeme[1]) :] == before[lexeme[1] :]
            )
        step = case.read(f".expected.{n + 1}.neon")
        if step is not None:
            assert document.print() == step

    assert document.print() == case.read(".expected.neon")
    if expected_value is not None:
        assert equal(document.to_value(), to_host(json.loads(expected_value)))
