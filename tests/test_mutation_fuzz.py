"""
Random sequences of edits over the documents of the corpus. After each edit the tree must stay valid
and its value must be what the same edit does to an independent model; an edit the library refuses
must change nothing, neither in the document nor in a donor of a node.
"""

import contextlib
import os
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from corpus import load_cases
from guarantees import check_tree, snapshot

from neon import (
    CHAIN,
    ArrayItemNode,
    ArrayNode,
    BlockArrayNode,
    CommentPolicy,
    Date,
    DocumentNode,
    Entity,
    EntityChainNode,
    EntityNode,
    InlineArrayNode,
    NeonError,
    Node,
    PathSegment,
    TokenKind,
    TriviaKind,
    ValueNode,
    parse,
)
from neon.nodes import item_keys
from neon.values import values_equal

# ---- an ordered model: a list is a list, a map is a dict in the order of the document


@dataclass
class EntityModel:
    value: Any
    attributes: Any


type Model = Any


def normalize(entries: dict[str, Model]) -> Model:
    """A dict with the keys 0..n-1 in order is a list."""
    if entries and all(key == str(i) for i, key in enumerate(entries)):
        return list(entries.values())
    return entries


def from_node(node: ValueNode | None) -> Model:
    if node is None:
        return None
    if isinstance(node, ArrayNode):
        keys = item_keys(node.items)
        entries: dict[str, Model] = {}
        for key, item in zip(keys, node.items, strict=True):
            entries[key] = from_node(
                item.value
            )  # an overwritten key keeps its first position
        if entries or not isinstance(node.to_value(), list):
            return normalize(entries)
        return []
    if isinstance(node, EntityChainNode):
        return EntityModel(CHAIN, [from_node(e) for e in node.entities])
    if isinstance(node, EntityNode):
        attributes = from_node(node.attributes) if node.attributes else []
        return EntityModel(from_node(node.value), attributes)
    return node.to_value()


def from_host(value: object) -> Model:
    if isinstance(value, list | tuple):
        return [from_host(v) for v in value]
    if isinstance(value, Mapping):
        return normalize({str(k): from_host(v) for k, v in value.items()})
    if isinstance(value, Entity):
        return EntityModel(from_host(value.value), from_host(value.attributes))
    return value


def same(a: Model, b: Model) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return (
            isinstance(a, list)
            and isinstance(b, list)
            and len(a) == len(b)
            and all(same(x, y) for x, y in zip(a, b, strict=True))
        )
    if isinstance(a, dict) or isinstance(b, dict):
        return (
            isinstance(a, dict)
            and isinstance(b, dict)
            and list(a) == list(b)
            and all(same(a[k], b[k]) for k in a)
        )
    if isinstance(a, EntityModel) or isinstance(b, EntityModel):
        return (
            isinstance(a, EntityModel)
            and isinstance(b, EntityModel)
            and same(a.value, b.value)
            and same(a.attributes, b.attributes)
        )
    return values_equal(a, b)


def container_at(model: Model, path: Sequence[PathSegment]) -> Model:
    """The array of the model at the path: a list, a map or the attributes of an entity."""
    node = model
    for segment in path:
        node = get(array_of_model(node), segment)
    return array_of_model(node)


def array_of_model(node: Model) -> Model:
    return node.attributes if isinstance(node, EntityModel) else node


def get(array: Model, key: PathSegment) -> Model:
    return array[int(str(key))] if isinstance(array, list) else array.get(str(key))


def update(
    model: Model,
    path: Sequence[PathSegment],
    edit: Callable[[dict[str, Model]], Model],
) -> Model:
    """Replaces the array at the path by a new one, with the edit applied."""

    def write(node: Model, rest: Sequence[PathSegment]) -> Model:
        array = array_of_model(node)
        entries = (
            {str(i): v for i, v in enumerate(array)}
            if isinstance(array, list)
            else dict(array)
        )
        if rest:
            res = normalize(
                {
                    k: write(v, rest[1:]) if k == str(rest[0]) else v
                    for k, v in entries.items()
                }
            )
        else:
            res = edit(entries)
        return EntityModel(node.value, res) if isinstance(node, EntityModel) else res

    return write(model, path)


def set_entry(entries: dict[str, Model], key: str, value: Model) -> Model:
    entries[key] = value
    return normalize(entries)


def rename_entry(entries: dict[str, Model], old: str, new: str) -> Model:
    return normalize({(new if k == old else k): v for k, v in entries.items()})


# ---- the run

VALUES: list[object] = [
    None, True, 0, 42, -1.5, "x", "two words", "a: b", "-.5", "line\nbreak", [], {},
    [1, 2], {"k": "v"}, {"a": 1, "b": [True]}, Entity("E", [1]), Date(2024, 2, 29),
]  # fmt: skip
KEYS = ["new", "k", "two words", "5", "x:y"]
DONOR_TEXTS = [
    "scalar", "[1, 2]", "{a: 1}", "x: 1\ny: [2]\n", "- p\n- q\n", "E(a: 1)", "a()b()", "'quoted'",
]  # fmt: skip


def item_paths(document: DocumentNode) -> list[tuple[list[PathSegment], ArrayItemNode]]:
    """Paths of all items the decoded value can reach, with the items."""
    res: list[tuple[list[PathSegment], ArrayItemNode]] = []

    def walk(node: Node | None, path: list[PathSegment]) -> None:
        array = node.attributes if isinstance(node, EntityNode) else node
        if not isinstance(array, ArrayNode):
            return
        keys = item_keys(array.items)
        for key, item in zip(keys, array.items, strict=True):
            if array.find_item(key) is item:
                item_path = [*path, key]
                res.append((item_path, item))
                walk(item.value, item_path)

    walk(document.value, [])
    return res


def has_comment(item: ArrayItemNode) -> bool:
    """An item with comments may be refused on one line, after it was already taken out."""
    return any(
        trivia.kind == TriviaKind.COMMENT
        for token in item.get_tokens()
        for trivia in (*token.leading_trivia, *token.trailing_trivia)
    )


def is_inside(node: Node, ancestor: Node) -> bool:
    n: Node | None = node
    while n:
        if n is ancestor:
            return True
        n = n.parent
    return False


def corpus_inputs() -> list[str]:
    inputs = []
    for category in ("roundtrip", "decode", "mutations", "cst"):
        for c in load_cases(category):
            text = c.read(".neon")
            assert text is not None
            with contextlib.suppress(NeonError):
                parse(text).to_value()
                inputs.append(text)
    return [*inputs, "", "# only a comment\n", "﻿", "42\n"]


def test_random_edits_keep_the_tree_valid_and_the_value_right() -> None:
    # refused edits change nothing
    inputs = corpus_inputs()
    count = {"attempts": 0, "applied": 0, "noops": 0, "refused": 0, "skipped": 0}
    only = os.environ.get("FUZZ_SEED")
    first = int(only or 1)
    last = first if only else int(os.environ.get("FUZZ_SEEDS") or 1500)
    for seed in range(first, last + 1):
        rnd = random.Random(seed)
        document = parse(rnd.choice(inputs))
        model = from_node(document.value)
        for step in range(4):
            model = run_step(
                document, model, rnd, f"seed {seed}, step {step}", count, bool(only)
            )
    if os.environ.get("FUZZ_SEEDS"):
        print(count)
    assert count["applied"] > count["attempts"] / 2
    assert count["refused"] > count["attempts"] / 20


KIND_NAMES = [
    "set",
    "add",
    "remove",
    "setKey",
    "move",
    "root",
    "node",
    "key node",
    "refused",
]


def rename_node(key: str) -> ValueNode:
    value = parse(key).value
    assert value
    return value.detach()


def run_step(
    document: DocumentNode,
    model: Model,
    rnd: random.Random,
    label: str,
    count: dict[str, int],
    verbose: bool,
) -> Model:
    """One random edit; returns the model after it."""
    next_ = rnd.random

    def pick[T](items: Sequence[T]) -> T:
        return items[int(next_() * len(items))]

    count["attempts"] += 1
    paths = item_paths(document)
    kind = int(next_() * 9) if paths else 5
    path: list[PathSegment] = []
    item = cast(ArrayItemNode, None)
    if paths:
        path, item = pick(paths)
    parent_path = path[:-1]
    parent: Any = container_at(model, parent_path) if paths else None
    before = document.print()
    description = f"{label}: {KIND_NAMES[kind]} {path!r} in\n{before}"
    donor: DocumentNode | None = None
    donor_node: Node | None = None
    expect_refusal: str | None = None
    operation: Callable[[], object]
    after: Callable[[], Model]

    if kind == 0:  # a value of the host
        value = pick(VALUES)
        operation = lambda: document.set_value(path, value)
        after = lambda: update(
            model,
            parent_path,
            lambda entries: set_entry(entries, str(path[-1]), from_host(value)),
        )

    elif kind == 1:  # a new item
        value = pick(VALUES)
        array = cast(ArrayNode, item.parent)
        if isinstance(parent, list) and next_() < 0.5:
            operation = lambda: array.add_item(value)
            after = lambda: update(
                model,
                parent_path,
                lambda entries: set_entry(entries, str(len(entries)), from_host(value)),
            )
        else:
            key = pick(KEYS)
            if isinstance(parent, list) or key in parent:
                expect_refusal = "Duplicated key"
                duplicate = "0" if isinstance(parent, list) else key
                operation = lambda: array.add_item(value, key=duplicate)
                after = lambda: model
            else:
                operation = lambda: document.set_value([*parent_path, key], value)
                after = lambda: update(
                    model,
                    parent_path,
                    lambda entries: set_entry(entries, key, from_host(value)),
                )

    elif kind == 2:  # removing
        array = cast(ArrayNode, item.parent)
        if isinstance(parent, list) and any(s.key for s in array.items):
            count["skipped"] += (
                1  # keys written in a list stay, so the model cannot just renumber
            )
            return model
        comments = (
            CommentPolicy.DROP if next_() < 0.5 else CommentPolicy.MOVE_TO_NEXT_TOKEN
        )
        keys = item_keys(array.items)
        emptied = all(
            other is item or keys[i] == str(path[-1])
            for i, other in enumerate(array.items)
        )
        if isinstance(array, InlineArrayNode):
            empty: Model = {} if array.open_bracket.kind == TokenKind.OPEN_BRACE else []
        else:
            empty = {} if item.key else []

        def remove_edit(entries: dict[str, Model]) -> Model:
            if emptied:
                return empty
            del entries[str(path[-1])]
            return (
                list(entries.values())
                if isinstance(parent, list)
                else normalize(entries)
            )

        operation = lambda: document.remove_item(path, comments=comments)
        after = lambda: update(model, parent_path, remove_edit)

    elif kind == 3:  # renaming
        key = pick(KEYS)
        if not item.key or isinstance(parent, list):
            count["skipped"] += 1
            return model
        if key in parent and key != str(path[-1]):
            expect_refusal = "Duplicated key"
            after = lambda: model
        else:
            after = lambda: update(
                model,
                parent_path,
                lambda entries: rename_entry(entries, str(path[-1]), key),
            )
        operation = lambda: document.set_key(path, key)

    elif kind == 4:  # a keyed item moves into another map
        target_path, target_item = pick(paths)
        target_array = (
            target_item.value.attributes
            if isinstance(target_item.value, EntityNode)
            else target_item.value
        )
        item_key = item.get_key_value()
        target_model = container_at(model, target_path)
        if (
            not item_key
            or isinstance(parent, list)
            or not isinstance(target_array, ArrayNode)
            or is_inside(target_item, item)
            or not isinstance(target_model, dict)
            or item_key in target_model
            or len(cast(ArrayNode, item.parent).items) == 1
            or (isinstance(target_array, InlineArrayNode) and has_comment(item))
        ):
            count["skipped"] += 1
            return model
        position = int(next_() * (len(target_array.items) + 1))
        if isinstance(target_array, InlineArrayNode) and (
            item.bullet is not None or isinstance(item.value, BlockArrayNode)
        ):
            expect_refusal = "cannot stand"
            copy = item.clone()
            operation = lambda: target_array.insert(position, copy)
            after = lambda: model
        else:
            moved = get(parent, item_key)

            def move() -> None:
                item.remove()
                target_array.insert(position, item)

            def moved_model() -> Model:
                removed = update(
                    model,
                    parent_path,
                    lambda entries: normalize(
                        {k: v for k, v in entries.items() if k != item_key}
                    ),
                )

                def insert(entries: dict[str, Model]) -> Model:
                    listed = list(entries.items())
                    listed.insert(position, (item_key, moved))
                    return normalize(dict(listed))

                return update(removed, target_path, insert)

            operation = move
            after = moved_model

    elif kind == 5:  # the root
        value = pick(VALUES)
        operation = lambda: document.set_value([], value)
        after = lambda: from_host(value)

    elif kind == 6:  # a node from another document into the value slot
        donor = parse(pick(DONOR_TEXTS))
        donor_value = donor.value
        assert donor_value
        inline = isinstance(item.parent, InlineArrayNode) or (
            not item.key and not item.bullet
        )
        if next_() < 0.3:
            expect_refusal = "parent|block"  # not detached first
            operation = lambda: setattr(item, "value", donor_value)
            after = lambda: model
        else:
            node_value = from_node(donor_value)
            node = donor_value.detach()
            donor_node = node
            if isinstance(node, BlockArrayNode) and inline:
                expect_refusal = "(?i:block)"
                operation = lambda: setattr(item, "value", node)
                after = lambda: model
            else:
                operation = lambda: item.set_value(node)
                after = lambda: update(
                    model,
                    parent_path,
                    lambda entries: set_entry(entries, str(path[-1]), node_value),
                )

    elif kind == 7:  # a key node
        key = pick(["new", "k", "zz"])
        key_node = item.key
        if not key_node or isinstance(parent, list):
            count["skipped"] += 1
            return model
        if next_() < 0.3:
            expect_refusal = "cannot be empty"
            operation = key_node.detach
            after = lambda: model
        elif key in parent and key != str(path[-1]):
            expect_refusal = "Duplicated key"
            operation = lambda: key_node.replace_with(rename_node(key))
            after = lambda: model
        else:
            operation = lambda: key_node.replace_with(rename_node(key))
            after = lambda: update(
                model,
                parent_path,
                lambda entries: rename_entry(entries, str(path[-1]), key),
            )

    else:  # operations refused by their shape
        array = cast(ArrayNode, item.parent)
        block = parse("x: 1\n").value
        assert block
        shape_node = block.detach()
        if isinstance(array, InlineArrayNode):
            expect_refusal = "(?i:block)"
            operation = lambda: array.add_item(shape_node)
        else:
            expect_refusal = "out of the array"
            operation = lambda: array.add_item(1, position=len(array.items) + 1)
        after = lambda: model

    unchanged = snapshot(
        document, *([donor] if donor else []), *([donor_node] if donor_node else [])
    )
    try:
        operation()
    except Exception as e:
        if not expect_refusal or not re.search(expect_refusal, str(e)):
            raise AssertionError(f"{description}\n{e!r}") from e
        try:
            unchanged()
        except AssertionError as failure:
            raise AssertionError(
                f"{description}\nthe refused operation changed something\n{failure}"
            ) from failure
        count["refused"] += 1
    else:
        if expect_refusal:
            raise AssertionError(f"{description}\nexpected a refusal {expect_refusal}")
    model = after()
    if not expect_refusal:
        count["noops" if document.print() == before else "applied"] += 1
    if verbose:
        print(description, "\n=>\n" + document.print())
    try:
        check_tree(document)
        if donor:
            check_tree(donor)
    except AssertionError as e:
        raise AssertionError(f"{description}\n{e}\nafter:\n{document.print()}") from e
    assert same(from_node(parse(document.print()).value), model), (
        f"{description}\nafter:\n{document.print()}"
    )
    return model
