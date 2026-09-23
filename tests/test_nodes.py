from corpus import load_cases

from neon import (
    DocumentNode,
    InlineArrayNode,
    Node,
    parse,
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
    assert repr(parse("user: root").value) == "BlockArrayNode('user: root')"
    assert repr(document) == f"DocumentNode({CONFIG[:39] + '…'!r})"  # cut to 40


class TestSlots:
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
