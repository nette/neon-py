import re
from collections.abc import Callable
from threading import Thread
from typing import Any

import pytest
from guarantees import check_tree, snapshot

from neon import (
    ArrayItemNode,
    BlockArrayNode,
    CommentPolicy,
    DocumentNode,
    Entity,
    EntityChainNode,
    EntityNode,
    InlineArrayNode,
    ItemIndex,
    NeonError,
    Token,
    TokenKind,
    Trivia,
    TriviaKind,
    ValueNode,
    dump,
    parse,
)
from neon._journal import atomic
from neon.values import Date

# Targeted cases of the editing API: the slots, the root, the refused operations and the low level.


def detached(text: str) -> ValueNode:
    value = parse(text).value
    assert value
    return value.detach()


def item_at(document: DocumentNode, *path: str | int) -> ArrayItemNode:
    item = document.find_item(path)
    assert item
    return item


def inline_of(document: DocumentNode) -> InlineArrayNode:
    assert isinstance(document.value, InlineArrayNode)
    return document.value


def block_of(document: DocumentNode) -> BlockArrayNode:
    assert isinstance(document.value, BlockArrayNode)
    return document.value


def put(item: ArrayItemNode, node: ValueNode | None) -> None:
    item.value = node


def expect_refused(
    operation: Callable[[], object],
    error: type[Exception],
    message: str,
    *nodes: DocumentNode,
) -> None:
    unchanged = snapshot(*nodes)
    with pytest.raises(error, match=re.escape(message)):
        operation()
    unchanged()
    for node in nodes:
        check_tree(node)


class TestSlots:
    def test_a_block_cannot_come_into_an_inline_array_through_any_door(self) -> None:
        doc = parse("[a]")
        donor = parse("x: 1\n")
        block = donor.value
        assert block
        inline = inline_of(doc)
        item = inline.items[0]
        assert item.value
        expect_refused(lambda: put(item, block), NeonError, "block", doc, donor)
        expect_refused(lambda: inline.add_item(block), NeonError, "block", doc, donor)
        expect_refused(
            lambda: item.value.replace_with(block),  # ty: ignore[unresolved-attribute]
            NeonError,
            "block",
            doc,
            donor,
        )

    def test_a_public_slot_setter_is_the_editing_operation(self) -> None:
        # a block is reindented under its key
        doc = parse("a: 1\nb: 2\n")
        put(item_at(doc, "a"), detached("x: 1\ny: 2\n"))
        assert doc.print() == "a:\n\tx: 1\n\ty: 2\nb: 2\n"
        check_tree(doc)

        put(item_at(doc, "b"), detached("- p\n- q\n"))
        assert doc.print() == "a:\n\tx: 1\n\ty: 2\nb:\n\t- p\n\t- q\n"
        check_tree(doc)

        items = parse("- 1\n- 2\n")
        items.add_item([], detached("k: v\nl: w\n"))
        assert items.print() == "- 1\n- 2\n-\n\tk: v\n\tl: w\n"
        check_tree(items)

    def test_replace_with_is_decided_by_the_slot(self) -> None:
        doc = parse("a: 1\n")
        key = item_at(doc, "a").key
        assert key
        key.replace_with(detached("b"))
        assert doc.print() == "b: 1\n"

        entity = parse("x: a(1)\n")
        node = item_at(entity, "x").value
        assert isinstance(node, EntityNode)
        node.value.replace_with(detached("b"))
        assert entity.print() == "x: b(1)\n"
        expect_refused(
            lambda: node.value.replace_with(detached("'!!chain'")),
            NeonError,
            "reserved",
            entity,
        )
        assert node.attributes
        source = parse("c(2, 3)").value
        assert isinstance(source, EntityNode)
        assert source.attributes
        node.attributes.replace_with(source.attributes.clone())
        assert entity.print() == "x: b(2, 3)\n"
        check_tree(entity)

        chain = parse("a()b()\n")
        assert isinstance(chain.value, EntityChainNode)
        links = chain.value.entities
        links[1].replace_with(detached("c(1)"))
        assert chain.print() == "a()c(1)\n"
        expect_refused(
            lambda: links[0].replace_with(detached("d")),
            TypeError,
            "EntityNode",
            chain,
        )
        expect_refused(
            lambda: chain.value.entities[1].value.replace_with(detached("'q'")),  # ty: ignore[unresolved-attribute]
            TypeError,
            "literal",
            chain,
        )

    def test_a_literal_key_gets_a_space_after_its_colon(self) -> None:
        # an inserted item has its value on the line of the key
        doc = parse('{"a":b}')
        key = inline_of(doc).items[0].key
        assert key
        key.replace_with(detached("new"))
        assert doc.print() == "{new: b}"
        check_tree(doc)

        source = parse("b:\n  two words\nc: 1\n")
        item = item_at(source, "b")
        item.remove()
        target = parse("E(a: 1)")
        assert isinstance(target.value, EntityNode)
        assert target.value.attributes
        target.value.attributes.insert(0, item)
        assert target.print() == "E(b: two words, a: 1)"
        check_tree(target)

    def test_slots_that_cannot_be_empty_refuse_detach(self) -> None:
        doc = parse("a: b(1)\n")
        key = item_at(doc, "a").key
        assert key
        expect_refused(key.detach, ValueError, "cannot be empty", doc)
        value = item_at(doc, "a").value
        assert isinstance(value, EntityNode)
        expect_refused(value.value.detach, ValueError, "cannot be empty", doc)
        inline = parse("[a]")
        expect_refused(
            lambda: put(inline_of(inline).items[0], None),
            NeonError,
            "cannot be empty",
            inline,
        )

    def test_detaching_the_root_leaves_the_preamble_and_the_byte_order_mark(
        self,
    ) -> None:
        bom = "\ufeff"
        doc = parse(bom + "# license\n\n# about a\na: 1\n")
        assert doc.value
        node = doc.value.detach()
        assert doc.print() == bom + "# license\n\n"
        assert node.print() == "# about a\na: 1\n"
        check_tree(doc)


class TestRoot:
    def test_a_block_at_the_root_has_the_indentation_of_the_old_root_block_or_none(
        self,
    ) -> None:
        crlf = parse("42\r\n")
        crlf.set_value([], {"a": 1, "b": 2})
        assert crlf.print() == "a: 1\r\nb: 2\r\n"

        indented = parse("  a: 1\n  b: 2\n")
        indented.set_value([], {"x": [1, 2], "y": 2})
        assert indented.print() == "  x:\n  \t- 1\n  \t- 2\n\n  y: 2\n"
        check_tree(indented)

        scalar = parse("# c\na: 1\nb: 2\n")
        scalar.set_value([], "text")
        assert scalar.print() == "# c\ntext\n"

    @pytest.mark.parametrize(
        ("text", "value", "output"),
        [
            ("", {"a": 1, "b": 2}, "a: 1\nb: 2"),
            ("  ", 1, "1"),
            ("\n\n", 1, "\n\n1\n"),
            ("# a\n\n# b\n", [1], "# a\n\n# b\n- 1\n"),
        ],
    )
    def test_an_empty_document(self, text: str, value: object, output: str) -> None:
        doc = parse(text)
        doc.set_value([], value)
        assert doc.print() == output
        check_tree(doc)

    @pytest.mark.parametrize("text", ["", "a:\n"])
    def test_the_first_item_comes_into_an_empty_place_as_any_other(
        self, text: str
    ) -> None:
        path = ["a"] if text else []
        doc = parse(text)
        doc.add_item(path, detached("[x]"), key="k")
        assert doc.print() == ("a:\n\tk: [x]\n" if text else "k: [x]")
        check_tree(doc)

        doc = parse(text)
        with pytest.raises(
            IndexError, match=re.escape("Position 1 is out of the array.")
        ):
            doc.add_item(path, 1, position=1)
        assert doc.print() == text

    @pytest.mark.parametrize("text", ["[a]\n", "- a\n"])
    def test_nullable_removes_the_root_of_either_style(self, text: str) -> None:
        doc = parse(text)
        doc.nullable = True
        doc.remove_item([0])
        assert doc.to_value() is None
        check_tree(doc)


class TestRefusedOperationsChangeNothing:
    def test_an_implicit_key_out_of_range(self) -> None:
        add = parse("{9223372036854775807: a}")
        expect_refused(
            lambda: inline_of(add).add_item("b"),
            NeonError,
            "Implicit key overflow",
            add,
        )

        rename = parse("{5: a, b}")
        expect_refused(
            lambda: rename.set_key(["5"], "9223372036854775807"),
            NeonError,
            "Implicit key overflow",
            rename,
        )

    def test_a_donor_that_already_has_a_parent(self) -> None:
        target = parse("a # origin\n")
        donor = parse("b # donor\n")
        node = target.value
        other = donor.value
        assert node
        assert other
        expect_refused(
            lambda: node.replace_with(other),
            ValueError,
            "parent",
            target,
            donor,
        )
        expect_refused(
            lambda: setattr(target, "value", other),
            ValueError,
            "parent",
            target,
            donor,
        )

    def test_a_node_into_its_own_subtree(self) -> None:
        doc = parse("a:\n\tb: 1\n")
        block = block_of(doc)
        inner = block.items[0].value
        assert isinstance(inner, BlockArrayNode)
        expect_refused(lambda: put(inner.items[0], block), ValueError, "parent", doc)

    def test_arrays_nested_deeper_than_the_parser_reads(self) -> None:
        doc = parse("a: " + "[" * 498 + "x" + "]" * 498)
        path = ["a", *[0] * 497]
        doc.set_value([*path, 0], [1])  # level 500
        assert parse(doc.print()).to_value() == doc.to_value()
        expect_refused(
            lambda: doc.set_value([*path, 0], [[1]]), NeonError, "Too deep nesting", doc
        )
        expect_refused(
            lambda: put(item_at(doc, *path, 0), detached("[[1]]")),
            NeonError,
            "Too deep nesting",
            doc,
        )
        holder = item_at(doc, *path).value
        assert isinstance(holder, InlineArrayNode)
        expect_refused(
            lambda: holder.add_item(detached("[[1]]")),
            NeonError,
            "Too deep nesting",
            doc,
        )

        chain = parse("[a()b()]")
        link = detached("c(" + "[" * 499 + "1" + "]" * 499 + ")")
        entities = inline_of(chain).items[0].value
        assert isinstance(entities, EntityChainNode)
        expect_refused(
            lambda: entities.entities[1].replace_with(link),
            NeonError,
            "Too deep nesting",
            chain,
        )

    def test_a_value_the_encoder_refuses(self) -> None:
        doc = parse("a: 1\nb: [x]\n")
        expect_refused(
            lambda: doc.set_value(["a"], float("inf")), NeonError, "INF", doc
        )
        expect_refused(
            lambda: doc.set_value(["b"], [1, lambda: 0]),
            NeonError,
            "cannot be encoded",
            doc,
        )
        expect_refused(
            lambda: doc.add_item(["b"], {1: 1, "1": 2}), NeonError, "twice", doc
        )


class TestRemovingKeepsTheCommentsOfOthers:
    def test_a_block_opened_on_the_line_of_a_dash(self) -> None:
        dropped = parse("- a: 1\n  # about b\n  b: 2\n")
        dropped.remove_item([0, "a"])
        assert dropped.print() == "-\n  # about b\n  b: 2\n"
        check_tree(dropped)

        moved = parse("- a: 1 # about a\n  b: 2\n")
        moved.remove_item([0, "a"], comments=CommentPolicy.MOVE_TO_NEXT_TOKEN)
        assert moved.print() == "-\n  # about a\n  b: 2\n"
        check_tree(moved)

        plain = parse("- a: 1\n  b: 2\n")
        plain.remove_item([0, "a"])
        assert plain.print() == "- b: 2\n"

    @pytest.mark.parametrize(
        ("text", "path", "output"),
        [
            ("[a, b, c]", [1], "[a, c]"),
            ("[a, b]", [1], "[a]"),
            ("[a, b,]", [1], "[a,]"),
            ("[\n\ta,\n\tb\n]", [1], "[\n\ta\n]"),
            ("[\n\ta, b\n]", [0], "[\n\tb\n]"),
            ("[x, a # c\n, b]", [1], "[x,\nb]"),
        ],
    )
    def test_an_inline_array(self, text: str, path: list[int], output: str) -> None:
        doc = parse(text)
        doc.remove_item(path)
        assert doc.print() == output
        check_tree(doc)


class TestInsertingIntoAnInlineArrayKeepsTheComments:
    @staticmethod
    def take(source: str) -> ArrayItemNode:
        item = item_at(parse(source), "x")
        item.remove()
        return item

    COMMENTED = "# belongs to x\nx: 1 # note\n"

    def test_the_comments_of_the_item_become_lines_above_it_or_it_is_refused_on_one_line(
        self,
    ) -> None:
        doc = parse("{\n\ta: 1, b: 2\n}\n")
        inline_of(doc).insert(1, self.take(self.COMMENTED))
        assert (
            doc.print()
            == "{\n\ta: 1,\n\t# belongs to x\n\t# note\n\tx: 1,\n\tb: 2\n}\n"
        )
        check_tree(doc)

        doc = parse("{\n\ta: 1\n}\n")
        inline_of(doc).insert(
            0, self.take("x: # after colon\n\t# above the value\n\t1\n")
        )
        assert (
            doc.print()
            == "{\n\t# after colon\n\t# above the value\n\tx: 1,\n\ta: 1\n}\n"
        )

        for text in ("{}", "{a: 1}"):
            target = parse(text)
            item = self.take(self.COMMENTED)
            restore = snapshot(target, item)
            with pytest.raises(
                NeonError,
                match=re.escape(
                    "An item with comments cannot stand in an inline array on one line."
                ),
            ):
                inline_of(target).insert(0, item)
            restore()
        doc = parse("{a: 1}")
        inline_of(doc).insert(1, self.take("x: 1\n"))
        assert doc.print() == "{a: 1, x: 1}"

    def test_an_item_added_before_another_takes_only_its_preamble(self) -> None:
        doc = parse("[\n\t# header\n\n\t# about b\n\tb\n]")
        inline_of(doc).add_item("a", position=0)
        assert doc.print() == "[\n\t# header\n\n\ta,\n\t# about b\n\tb\n]"
        inline_of(doc).items[0].remove()
        assert doc.print() == "[\n\t# header\n\n\t# about b\n\tb\n]"


class TestEqualValues:
    @pytest.mark.parametrize(
        ("text", "value"),
        [
            ("a: 9007199254740993\n", 9007199254740993),
            ("a: 1\n", 1),
            ("a: 0x10\n", 16),
            ("a: 1e999\n", float("inf")),
            ("a: -0.0\n", -0.0),
            ("a: 2024-02-29\n", Date(2024, 2, 29)),
            ("a: 2024-02-30\n", "2024-02-30"),
            ("a: b(1, x: 2)\n", Entity("b", {0: 1, "x": 2})),  # ty: ignore[invalid-argument-type]
            ("a: {x: 1, y: 2}\n", {"x": 1, "y": 2}),
            ("a: []\n", []),
            ("a: {}\n", {}),
        ],
    )
    def test_are_a_no_op(self, text: str, value: object) -> None:
        doc = parse(text)
        doc.set_value(["a"], value)
        assert doc.print() == text

    @pytest.mark.parametrize(
        ("text", "value", "output"),
        [
            ("a: {x: 1, y: 2}\n", {"y": 2, "x": 1}, "a:\n\ty: 2\n\tx: 1\n"),
            ("a: []\n", {}, "a: {}\n"),
            ("a: 1\n", 1.5, "a: 1.5\n"),
        ],
    )
    def test_change(self, text: str, value: object, output: str) -> None:
        doc = parse(text)
        doc.set_value(["a"], value)
        assert doc.print() == output


class TestConstruction:
    def test_a_token_and_a_trivia_check_their_text(self) -> None:
        with pytest.raises(ValueError, match=re.escape("is not one token")):
            Token(TokenKind.COLON, "abc")
        with pytest.raises(ValueError, match=re.escape("is not")):
            Trivia(TriviaKind.COMMENT, "abc")

    def test_the_kind_and_the_origin_of_a_token_cannot_be_written(self) -> None:
        token: Any = Token.from_text("a")
        with pytest.raises(AttributeError):
            token.kind = TokenKind.COLON
        with pytest.raises(AttributeError):
            token.origin = None
        assert token.kind == "Literal"
        lone = "\ud800"
        with pytest.raises(ValueError, match=re.escape("is not one token")):
            Token.from_text(lone)
        with pytest.raises(ValueError, match=re.escape("is not one token")):
            token.set_text("a" + lone)

    def test_trivia_setters_of_an_attached_token_check_the_place(self) -> None:
        doc = parse("a: 1\nb: 2\n")
        key = item_at(doc, "a").key
        assert key
        expect_refused(
            lambda: key.token.set_trailing_trivia([Trivia.from_text("# hi")]),
            ValueError,
            "line ending",
            doc,
        )
        b_key = item_at(doc, "b").key
        assert b_key
        expect_refused(
            lambda: b_key.token.set_leading_trivia([Trivia.from_text("\ufeff")]),
            ValueError,
            "byte order mark",
            doc,
        )
        a_value = item_at(doc, "a").value
        assert a_value
        expect_refused(
            lambda: a_value.get_first_token().set_leading_trivia(
                [Trivia.from_text(" ")]
            ),
            ValueError,
            "same line",
            doc,
        )
        b_value = item_at(doc, "b").value
        assert b_value
        b_value.get_first_token().set_trailing_trivia(
            [Trivia.from_text(" "), Trivia.from_text("# two"), Trivia.from_text("\n")]
        )
        assert doc.print() == "a: 1\nb: 2 # two\n"
        check_tree(doc)

        free = Token.from_text("x").set_trailing_trivia([Trivia.from_text("# free")])
        assert str(free) == "x# free"

    def test_clone_is_deep_and_detached(self) -> None:
        doc = parse("a: b(1, [2]) # c\n")
        copy = doc.clone()
        assert copy.print() == doc.print()
        original = {id(token) for token in doc.get_tokens()}
        assert not any(id(token) in original for token in copy.get_tokens())
        assert copy.get_tokens()[0].origin == doc.get_tokens()[0].origin

        item = item_at(doc, "a").clone()
        assert item.parent is None
        target = parse("x: 1\n")
        block_of(target).insert(1, item)
        assert target.print() == "x: 1\na: b(1, [2]) # c\n"
        check_tree(target)

        inline = parse("x: [k: 1, l: 2]\n")
        block_of(target).insert(2, item_at(inline, "x", "k").clone())
        assert target.print() == "x: 1\na: b(1, [2]) # c\nk: 1\n"
        check_tree(target)

    def test_a_built_token_has_no_origin(self) -> None:
        doc = parse("a: 1\nb: 2\n")
        doc.set_value(["a"], "new")
        doc.set_value(["c"], [1])
        a_value = item_at(doc, "a").value
        assert a_value
        assert a_value.get_first_token().origin is None
        assert all(token.origin is None for token in item_at(doc, "c").get_tokens())
        b_value = item_at(doc, "b").value
        assert b_value
        origin = b_value.get_first_token().origin
        assert origin
        assert (origin.line, origin.column) == (2, 4)


def test_a_refused_operation_leaves_the_tree_as_it_was() -> None:
    doc = parse("a: {x: 1}\nb: [1]\n")
    before = dump(doc)
    x = item_at(doc, "a", "x")
    with pytest.raises(NeonError, match=re.escape("block cannot stand")):
        x.set_value(detached("- x\n- y"))
    b_value = item_at(doc, "b").value
    with pytest.raises(ValueError, match=re.escape("already has a parent")):
        x.set_value(b_value)
    with pytest.raises(NeonError):
        doc.set_value(["a", "x", "y"], 1)
    with pytest.raises(IndexError):
        doc.add_item(["b"], 2, position=5)
    with pytest.raises(NeonError, match=re.escape("cannot be encoded")):
        doc.set_value(["a"], object())
    assert dump(doc) == before


def test_replace_with_and_detach() -> None:
    doc = parse("a: 1 # one\nb: [x]\n")
    one = item_at(doc, "a").value
    assert one
    one.replace_with(detached("2"))
    assert doc.print() == "a: 2 # one\nb: [x]\n"
    assert one.parent is None

    items = item_at(doc, "b").value
    assert items
    detached_list = items.detach()
    assert doc.print() == "a: 2 # one\nb:\n"
    assert detached_list.print() == "[x]\n"  # with the trivia at its edges


def test_an_item_moves_to_another_indentation_with_its_comments_and_strings() -> None:
    lines = [
        "a:",
        "\tkeep: 1",
        "\t# about db",
        "\tdb:",
        "\t\thost: x",
        "\t\tnote: '''",
        "\t\t\tfirst",
        "\t\t\t  second",
        "\t\t'''",
        "b:",
        "    x: 1",
        "",
    ]
    doc = parse("\n".join(lines))
    db = item_at(doc, "a", "db")
    db.remove()
    target = item_at(doc, "b").value
    assert isinstance(target, BlockArrayNode)
    target.insert(1, db)
    expected = [
        "a:",
        "\tkeep: 1",
        "b:",
        "    x: 1",
        "    # about db",
        "    db:",
        "    \thost: x",
        "    \tnote: '''",
        "\t\t\tfirst",
        "\t\t\t  second",
        "\t\t'''",
        "",
    ]
    assert doc.print() == "\n".join(expected)
    check_tree(doc)
    assert doc.to_value() == {
        "a": {"keep": 1},
        "b": {"x": 1, "db": {"host": "x", "note": "first\n  second"}},
    }
    with pytest.raises(ValueError, match=re.escape("already has a parent")):
        target.insert(0, item_at(doc, "a", "keep"))

    inline = parse("a: [x, y]\nb: [z]\n")
    y = item_at(inline, "a", 1)
    y.remove()
    holder = item_at(inline, "b").value
    assert isinstance(holder, InlineArrayNode)
    holder.insert(0, y)
    assert inline.print() == "a: [x]\nb: [y, z]\n"


def test_an_item_by_its_order_is_never_created() -> None:
    document = parse("a: [1]\n")
    with pytest.raises(NeonError, match=r"^No item '#5' in the path a\.#5$"):
        document.set_value(["a", ItemIndex(5)], 2)
    with pytest.raises(NeonError, match=r"in the path a\.#5, and create is false$"):
        document.set_value(["a", ItemIndex(5)], 2, create=False)


def test_an_edit_in_another_thread_keeps_its_own_journal() -> None:
    first = parse("a: 1\n")
    second = parse("b: 1\n")

    def edit_second() -> None:
        second.set_value(["b"], 2)

    with pytest.raises(RuntimeError), atomic():
        first.set_value(["a"], 2)
        thread = Thread(target=edit_second)
        thread.start()
        thread.join()
        raise RuntimeError
    assert first.print() == "a: 1\n"
    assert second.print() == "b: 2\n"
