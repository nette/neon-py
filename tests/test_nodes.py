import re

import pytest
from corpus import load_cases

from neon import (
    ArrayItemNode,
    BlockArrayNode,
    DocumentNode,
    EntityNode,
    InlineArrayNode,
    ItemIndex,
    LiteralNode,
    Node,
    Position,
    StringNode,
    Token,
    Trivia,
    locate_all,
    parse,
    print_text,
)


def check_parents(document: DocumentNode) -> None:
    """Parents agree with a walk of the tree, and every token stands once."""
    seen: set[int] = set()

    def walk(node: Node) -> None:
        for child in node.get_children():
            assert child.parent is node
            if isinstance(child, Node):
                walk(child)
            else:
                assert id(child) not in seen
                seen.add(id(child))

    assert document.parent is None
    walk(document)


def test_parents_over_the_corpus() -> None:
    for c in [*load_cases("roundtrip"), *load_cases("decode")]:
        text = c.read(".neon")
        assert text is not None
        check_parents(parse(text))


CONFIG = """# database
database:
\tdsn: 'mysql:host=127.0.0.1' # local
\tuser: root
\toptions: [lazy: yes, 0x10]

services:
\t- Foo(@bar)
"""


def test_repr_shows_the_class_and_the_text() -> None:
    document = parse(CONFIG)
    assert (
        repr(document.find_item(["database", "user"])) == "ArrayItemNode('user: root')"
    )
    assert repr(document) == f"DocumentNode({CONFIG[:39] + '…'!r})"  # cut to 40


def test_navigation() -> None:
    document = parse(CONFIG)
    root = document.value
    assert isinstance(root, BlockArrayNode)

    user = document.find_item(["database", "user"])
    assert isinstance(user, ArrayItemNode)
    assert user.get_key_value() == "user"
    assert user.get_value() == "root"
    assert user.get_indentation() == "\t"
    assert user.find_ancestor(DocumentNode) is document
    previous = user.get_previous_sibling()
    assert previous
    assert previous.get_first_token().text == "dsn"
    following = user.get_next_sibling()
    assert isinstance(following, ArrayItemNode)
    assert following.get_key_value() == "options"

    options = document.find_item(["database", "options"])
    assert options
    assert isinstance(options.value, InlineArrayNode)
    first = document.find_item(["database", "options", 0])
    assert first
    assert first.get_value() == 16
    lazy = document.find_item(["database", "options", "lazy"])
    assert lazy
    assert lazy.get_value() is True
    service = document.find_item(["services", 0])
    assert service
    assert isinstance(service.value, EntityNode)
    assert document.find_item(["services", ItemIndex(0)]) is service
    assert document.find_item(["nope"]) is None
    assert document.find_item(["database", "user", "x"]) is None

    assert [node.to_value() for node in document.find(StringNode)] == [
        "mysql:host=127.0.0.1"
    ]
    root_literal = document.find_first(LiteralNode, lambda n: n.token.text == "root")
    assert root_literal
    assert root_literal.to_value() == "root"

    dsn = document.find_item(["database", "dsn"])
    assert dsn
    assert [t.get_comment_text() for t in dsn.get_trailing_comments()] == ["local"]
    assert [t.text for t in root.items[0].get_leading_comments()] == ["# database"]
    assert root.items[0].has_leading_comment()
    assert root.items[0].is_multi_line()
    assert not dsn.is_multi_line()
    assert print_text(dsn) == "dsn: 'mysql:host=127.0.0.1'"


def test_positions_are_computed_from_the_current_tree() -> None:
    document = parse(CONFIG)
    user = document.find_item(["database", "user"])
    assert user
    offset = CONFIG.index("user")
    assert user.get_position() == Position(4, 2, offset)
    assert user.get_first_token().origin == user.get_position()

    all_positions = locate_all(document)
    for token in document.get_tokens():
        assert all_positions[token] == token.origin

    dsn = document.find_item(["database", "dsn"])
    assert dsn
    assert isinstance(dsn.value, StringNode)
    dsn.value.token.set_text("'x'")
    shift = len("'mysql:host=127.0.0.1'") - 3
    assert user.get_position() == Position(4, 2, offset - shift)
    origin = user.get_first_token().origin
    assert origin
    assert origin.offset == offset


class TestSlots:
    def test_a_node_stands_in_one_place(self) -> None:
        document = parse("a: 1\nb: 2")
        assert isinstance(document.value, BlockArrayNode)
        a, b = document.value.items
        with pytest.raises(ValueError, match=re.escape("already has a parent")):
            a.value = b.value
        assert document.print() == "a: 1\nb: 2"

        old = a.value
        assert old
        replacement = parse("3").value
        assert replacement
        a.value = replacement.detach()
        assert old.parent is None
        assert document.to_value() == {"a": 3, "b": 2}

    def test_no_node_into_its_own_subtree(self) -> None:
        document = parse("[b]")
        inline = document.value
        assert isinstance(inline, InlineArrayNode)
        document.value = None
        with pytest.raises(ValueError, match=re.escape("own subtree")):
            inline.items[0].value = inline

    def test_lists_are_read_only(self) -> None:
        document = parse("[a, b]")
        assert isinstance(document.value, InlineArrayNode)
        items = document.value.items
        assert isinstance(items, tuple)
        assert document.value.items is items


def test_values_of_the_tree() -> None:
    keys = parse("{__proto__: 1, constructor: 2, toString: 3}").to_value()
    assert isinstance(keys, dict)
    assert list(keys.items()) == [("__proto__", 1), ("constructor", 2), ("toString", 3)]
    assert parse("{__proto__: {polluted: 1}}").to_value() == {
        "__proto__": {"polluted": 1}
    }

    assert parse(
        "[9007199254740991, 9007199254740992, 0xffffffffffffffffffff]"
    ).to_value() == [
        9007199254740991,
        9007199254740992,
        0xFFFFFFFFFFFFFFFFFFFF,
    ]
    two = parse("{2: a, 1: b}").to_value()
    assert isinstance(two, dict)
    assert list(two.items()) == [("2", "a"), ("1", "b")]
    assert parse("[]").to_value() == []
    assert parse("{}").to_value() == {}
    assert parse("").to_value() is None


def test_first_editing_slice_a_scalar_changes_and_nothing_else() -> None:
    text = (
        "﻿# config\r\nparameters:\r\n\tkey: 0x10 # hex\r\n"
        "\tother: [a, b] # inline\r\nlast: 1"
    )
    document = parse(text)
    item = document.find_item(["parameters", "key"])
    assert item
    assert isinstance(item.value, LiteralNode)
    item.value.token.set_text("0x20")
    assert document.print() == text.replace("0x10", "0x20")
    assert document.to_value() == {
        "parameters": {"key": 32, "other": ["a", "b"]},
        "last": 1,
    }


def test_an_instance_of_trivia_stands_in_a_list_once() -> None:
    # so that replace_trivia() replaces the one meant
    document = parse("a: 1\nb: 2\n")
    item = document.find_item(["b"])
    assert item
    assert item.key
    token: Token = item.key.get_first_token()
    eol = Trivia.from_text("\n")
    token.set_leading_trivia([eol, eol])
    assert token.leading_trivia[0] is not token.leading_trivia[1]
    token.replace_trivia(eol, Trivia.from_text("\r\n"))
    assert document.print() == "a: 1\n\r\n\nb: 2\n"
