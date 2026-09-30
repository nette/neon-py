"""The editing operations of the tree. The node classes expose them as methods."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date

from .builder import Builder, Place
from .encoder import CONTROL_CHARACTERS, encode, json_string
from .errors import NeonError
from .layout import Layout
from .nodes import (
    ArrayItemNode,
    ArrayNode,
    BlockArrayNode,
    CommentPolicy,
    DocumentNode,
    EntityChainNode,
    EntityNode,
    InlineArrayNode,
    ItemIndex,
    LiteralNode,
    Node,
    PathSegment,
    StringNode,
    ValueNode,
    item_keys,
)
from .scanner import TokenKind, TriviaKind
from .token import Token, Trivia, find_neighbour, is_well_formed
from .values import (
    CHAIN,
    MAX_DEPTH,
    Date,
    Entity,
    entries_of,
    int_text,
    literal_key,
    values_equal,
)

type _KeysBefore = tuple[dict[ArrayItemNode, str], bool]


# ---- values of items


def set_item_value(item: ArrayItemNode, value: object) -> None:
    """Writes the value of an item; an equal value is a no-op, a changed one keeps the style."""
    old = item.value
    if isinstance(value, ValueNode):
        set_item_node(item, value)
        return
    if _same_value(value, old) if old is not None else value is None:
        return
    if value is None and not item.colon and not item.bullet:
        _replace_value(
            item, _literal("null")
        )  # an inline item without a key keeps a value
    elif value is None:
        _replace_value(item, None)
    else:
        node = _styled_scalar(old, value)
        _replace_value(item, node or Builder.value(value, _place_of(item, old, value)))
    _guard_dash_subblocks(item.parent)


def set_item_node(item: ArrayItemNode, node: ValueNode | None) -> None:
    """Puts the node into the value slot or empties it, without comparing and styling."""
    _replace_value(item, node)
    _guard_dash_subblocks(item.parent)


def _guard_dash_subblocks(block: Node | None) -> None:
    """
    A dash right after a key at the same indentation reads as a dash subblock of that
    key. So a key without a value followed by a dash gets an explicit null, and a dash
    right after a dash subblock gets its key written out, which ends the subblock.
    """
    if not isinstance(block, BlockArrayNode):
        return
    _guard_end(block)
    items = block.items
    for i, item in enumerate(items[:-1]):
        following = items[i + 1]
        if item.key is None or following.bullet is None:
            continue
        if item.value is None:
            _replace_value(item, _literal("null"))
        elif isinstance(item.value, BlockArrayNode) and Layout.indentation(
            item.value.items[0]
        ) == Layout.indentation(item):
            _give_key(following, item_keys(block.items)[i + 1])


def _guard_end(at: Node) -> None:
    """Spaces on the last line would be read as the indentation of a missing value."""
    root = at
    while root.parent is not None:
        root = root.parent
    if not isinstance(root, DocumentNode):
        return
    end = root.end_of_file
    last = _token_before(end)
    item = last.parent if last else None
    if (
        isinstance(item, ArrayItemNode)
        and item.value is None
        and end.leading_trivia
        and end.leading_trivia[-1].kind == TriviaKind.WHITESPACE
    ):
        _lead(end, _without_indentation(end.leading_trivia))


def _place_of(item: ArrayItemNode, old: ValueNode | None, value: object) -> Place:
    """Where a value of the item is built; a replaced block keeps its indentation."""
    indent = Layout.indentation(item)
    unit = Layout.unit(item)
    if isinstance(old, BlockArrayNode):
        block_indent = Layout.indentation(old.items[0])
        if block_indent.startswith(indent) and len(block_indent) > len(indent):
            unit = block_indent[len(indent) :]
    return Place(
        block=isinstance(item.parent, BlockArrayNode),
        indent=indent,
        unit=unit,
        eol=Layout.line_ending(item),
        double_quoted=_has_fragile_string(item, value),
    )


def _replace_value(item: ArrayItemNode, node: ValueNode | None) -> None:
    """Puts a node into the value slot, moving the trivia so that the lines stay."""
    old = item.value
    head = item.colon or item.bullet
    if node is old:
        return
    if isinstance(node, BlockArrayNode) and (
        isinstance(item.parent, InlineArrayNode) or head is None
    ):
        raise NeonError("A block cannot stand in an inline array.")
    if node is not None:
        _check_placeable(item, node)
    elif head is None:
        raise NeonError("The value of an item without a key cannot be empty.")

    if (
        head is None
    ):  # an item of an inline array without a key: the node takes the place
        assert node and old
        _take_edges(node, old)
        item._set_slots(value=node)
        return

    head_ends = _has_line_ending(head.trailing_trivia)
    old_on_own_line = old is not None and head_ends
    final_line_ending = (
        _has_line_ending(old.get_last_token().trailing_trivia) if old else head_ends
    )

    if node is None:
        assert old
        if not old_on_own_line:
            _trail(head, old.get_last_token().trailing_trivia)
        elif not final_line_ending:
            _trail(head, _without_line_ending(head.trailing_trivia))
        item._set_slots(value=None)
        end = _token_after(head)
        if (
            end and end.kind == TokenKind.END_OF_FILE
        ):  # spaces would read as indentation
            _lead(end, _without_indentation(end.leading_trivia))
        return

    eol = Layout.line_ending(head)
    if isinstance(node, BlockArrayNode):
        place = _place_of(item, old, None)
        _reindent_block(node, place.indent + place.unit)
        if old and not old_on_own_line:
            _trail(head, old.get_last_token().trailing_trivia)
        if not _has_line_ending(head.trailing_trivia):
            trailing = _without_trailing_space(head.trailing_trivia)
            _trail(head, [*trailing, Trivia(TriviaKind.LINE_ENDING, eol)])
        if (
            isinstance(old, BlockArrayNode) and old_on_own_line
        ):  # the lines above it stay
            first = node.get_first_token()
            above = _without_indentation(old.get_first_token().leading_trivia)
            _lead(first, _join_trivia(above, first.leading_trivia))
        line_ending = [Trivia(TriviaKind.LINE_ENDING, eol)] if final_line_ending else []
        _trail(node.get_last_token(), line_ending)
        item._set_slots(value=node)
        return

    if old is not None and not isinstance(
        old, BlockArrayNode
    ):  # on the line of the old
        _take_edges(node, old)
    else:
        # a block opened on the line of a dash ends the line itself; otherwise the line
        # ending, and a comment, of the head move after the value
        if old is not None and not old_on_own_line:
            trailing = old.get_last_token().trailing_trivia
        else:
            trailing = head.trailing_trivia
        _lead(node.get_first_token(), [])
        if not final_line_ending:
            trailing = _without_line_ending(trailing)
        _trail(node.get_last_token(), trailing)
        _trail(head, [Trivia(TriviaKind.WHITESPACE, " ")])
    item._set_slots(value=node)


def _check_placeable(owner: Node, node: Node) -> None:
    """A node that comes into a slot of the owner must be free, and must not hold it."""
    _check_movable(owner, node)
    if isinstance(node, EntityNode) and node.attributes is None:
        raise TypeError("An entity without parentheses can only be a link of a chain.")
    _check_depth(owner, node)


def _check_movable(owner: Node, node: Node) -> None:
    if node.parent is not None:
        raise ValueError("The node already has a parent, detach() or clone() it first.")
    ancestor: Node | None = owner
    while ancestor is not None:
        if ancestor is node:
            raise ValueError("A node cannot be put into its own subtree.")
        ancestor = ancestor.parent


def _check_depth(owner: Node, node: Node | None) -> None:
    """The arrays around the owner and in the node must not nest deeper than allowed."""
    around = 0
    ancestor: Node | None = owner
    while ancestor is not None:
        around += isinstance(ancestor, ArrayNode)
        ancestor = ancestor.parent

    def depth(n: Node) -> int:
        nested = [
            depth(child)
            for child in n.get_children()
            if isinstance(child, ArrayItemNode | ValueNode)
        ]
        return isinstance(n, ArrayNode) + max(nested, default=0)

    if node is not None and around + depth(node) > MAX_DEPTH:
        raise NeonError("Too deep nesting")


def _reindent_block(block: BlockArrayNode, to: str) -> None:
    """Shifts the indentation of all lines of a block, so that its items stand at `to`."""
    items = block.items
    source = (
        items[1] if len(items) > 1 else items[0]
    ).get_indentation()  # not on a dash
    _reindent(block, source, to)
    first = block.get_first_token()
    _lead(first, [*_without_indentation(first.leading_trivia), *_indent_trivia(to)])


def _take_edges(node: Node, old: Node) -> None:
    """The new node takes the leading trivia of the first token and trailing of the last."""
    _lead(node.get_first_token(), old.get_first_token().leading_trivia)
    _trail(node.get_last_token(), old.get_last_token().trailing_trivia)


def _same_value(value: object, node: ValueNode) -> bool:
    """Equality of a value of the host and the value of a node, in the order of the document."""
    if not isinstance(node, ArrayNode):
        return values_equal(value, node.to_value())
    host = entries_of(value)
    if host is None:
        return False
    entries: dict[str, ArrayItemNode] = {}
    for key, item in zip(item_keys(node.items), node.items, strict=True):
        entries[key] = item  # an overwritten key keeps its first position
    if entries:
        is_list = all(key == str(i) for i, key in enumerate(entries))
    else:
        is_list = isinstance(node.to_value(), list)
    if host.is_list != is_list or len(host.entries) != len(entries):
        return False
    for (key, v), (own, item) in zip(host.entries, entries.items(), strict=True):
        if key != own:
            return False
        if not (_same_value(v, item.value) if item.value is not None else v is None):
            return False
    return True


_BOOLEAN_WORDS = (("true", "false"), ("yes", "no"))


def _styled_scalar(old: ValueNode | None, value: object) -> ValueNode | None:
    """A scalar in the style of the old one: base of an integer, word of a boolean, quotes."""
    if isinstance(old, LiteralNode):
        text = old.token.text
        base = re.fullmatch(r"0([xob])([0-9a-fA-F]+)", text)
        if (
            base
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        ):
            digits = format(value, base[1]).zfill(len(base[2]))
            if re.search("[A-F]", base[2]):
                digits = digits.upper()
            return _literal(f"0{base[1]}{digits}")
        if isinstance(value, bool):
            word = next((w for w in _BOOLEAN_WORDS if text.lower() in w), None)
            if word:
                res = word[0] if value else word[1]
                if text == text.upper():
                    res = res.upper()
                elif "A" <= text[0] <= "Z":
                    res = res.capitalize()
                return _literal(res)
        elif (
            isinstance(value, str)
            and "\n" not in value
            and isinstance(old.to_value(), str)
        ):
            res = encode(value)
            return _literal(res) if res == value else None
    elif isinstance(old, StringNode) and isinstance(value, str):
        quote = old.token.text[0]
        multiline = re.match(r"(?:'''|\"\"\")\r?\n", old.token.text)
        if not multiline and "\n" not in value and is_well_formed(value):
            if quote == "'" and not CONTROL_CHARACTERS.search(value):
                return _string("'" + value.replace("'", "''") + "'")
            if quote == '"':
                return _string(json_string(value))
    return None


def _literal(text: str) -> LiteralNode:
    return LiteralNode(Token.from_text(text))


def _string(text: str) -> StringNode:
    return StringNode(Token.from_text(text))


# ---- adding


def add_item(
    array: ArrayNode, key: str | None, value: object, position: int | None = None
) -> ArrayItemNode:
    """Adds an item to an array, at the end or before the item at the position."""
    items = array.items
    at = len(items) if position is None else position
    if isinstance(at, bool) or not isinstance(at, int) or not 0 <= at <= len(items):
        raise IndexError(f"Position {at} is out of the array.")
    if key is not None and array.find_item(key) is not None:
        raise NeonError(f"Duplicated key '{key}'")
    if isinstance(value, ValueNode):
        if isinstance(value, BlockArrayNode) and isinstance(array, InlineArrayNode):
            raise NeonError("A block cannot stand in an inline array.")
        _check_placeable(array, value)

    before = _keys_before(array)
    if isinstance(array, BlockArrayNode):
        item = _add_to_block(array, key, value, at)
    else:
        assert isinstance(array, InlineArrayNode)
        item = _add_to_inline(array, key, value, at)
    _keep_keys(array, before, keyless=key is None)
    _guard_dash_subblocks(array)
    return item


def add_by_path(
    document: DocumentNode,
    path: Sequence[PathSegment],
    value: object,
    key: str | None,
    position: int | None,
) -> ArrayItemNode:
    """Adds an item to the array at the path; a missing array becomes one."""
    owner = resolve_path(document, path) if path else None
    container = owner.value if owner else document.value
    array = array_of(container)
    if array is not None:
        return add_item(array, key, value, position)
    if container is not None:
        raise NeonError(f"The value at {_path_text(path)} is not an array")
    if position not in (None, 0):
        raise IndexError(f"Position {position} is out of the array.")
    placeholder = (
        None if isinstance(value, ValueNode) else value
    )  # a node comes in later
    set_by_path(
        document,
        path,
        [placeholder] if key is None else {key: placeholder},
        create=True,
    )
    array = array_of(owner.value if owner else document.value)
    assert array
    item = array.items[0]
    if isinstance(value, ValueNode):
        set_item_value(item, value)
    return item


def _keys_before(array: ArrayNode) -> _KeysBefore:
    """The keys of the items before an edit, and whether they made a list."""
    keys = item_keys(array.items)
    return dict(zip(array.items, keys, strict=True)), _list_length(
        array, keys
    ) is not None


def _list_length(array: ArrayNode, keys: Sequence[str]) -> int | None:
    """
    The length of the list the items make in the decoded array, where an overwritten key
    keeps the place of its first item; None when they make no list.
    """
    if not keys:
        return 0 if isinstance(array.to_value(), list) else None  # `{}` is no list
    seen: set[str] = set()
    for key in keys:
        if key not in seen:
            if key != str(len(seen)):
                return None
            seen.add(key)
    return len(seen)


def _keep_keys(array: ArrayNode, before: _KeysBefore, *, keyless: bool) -> None:
    """
    An edit must not change the keys of the other items. In a list, an item added or
    removed without a key renumbers the following ones, which is what a list means;
    anywhere else, an item whose implicit key would change gets its old key written out
    (`{5: a, b}` without `5: a` is `{6: b}`).
    """
    keys_before, was_list = before
    if was_list and keyless:
        item_keys(array.items)  # an implicit key out of range fails here
        return
    changed = True
    while changed:
        changed = False
        keys = item_keys(array.items)
        for item, key in zip(array.items, keys, strict=True):
            old = keys_before.get(item)
            if old is not None and item.key is None and key != old:
                _give_key(item, old)
                changed = True
                break  # the key changes the implicit keys after it


def _give_key(item: ArrayItemNode, key: str) -> None:
    """Writes the key out: `- b` becomes `6: b`, an inline `b` becomes `6: b`."""
    key_node, colon = _key_tokens(key)
    if item.bullet:
        _lead(key_node.get_first_token(), item.bullet.leading_trivia)
        if isinstance(item.value, BlockArrayNode) and not _has_line_ending(
            item.bullet.trailing_trivia
        ):  # a block opened on the line of the dash moves below the key
            first = item.value.items[0]
            _lead(first.get_first_token(), _indent_trivia(Layout.indentation(first)))
            _trail(colon, [Trivia(TriviaKind.LINE_ENDING, Layout.line_ending(item))])
        else:
            _trail(colon, item.bullet.trailing_trivia)
        item._set_slots(bullet=None, key=key_node, colon=colon)
    else:
        first = item.get_first_token()
        _lead(key_node.get_first_token(), first.leading_trivia)
        _lead(first, [])
        item._set_slots(key=key_node, colon=colon)


def _add_to_block(
    block: BlockArrayNode, key: str | None, value: object, at: int
) -> ArrayItemNode:
    items = block.items
    sibling = items[min(at, len(items) - 1)]
    indent = Layout.indentation(sibling)
    eol = Layout.line_ending(sibling)
    unit = Layout.unit(block)
    if isinstance(
        value, ValueNode
    ):  # the head first, then the node comes in as the value
        placeholder = 0 if key is None else None
        item = Builder.block_item(key, placeholder, Place(True, indent, unit, eol))
        _place_in_block(block, item, at, indent, eol)
        _replace_value(item, value)
        return item
    fragile = _has_fragile_string(block, value)
    item = Builder.block_item(key, value, Place(True, indent, unit, eol, fragile))
    _check_depth(block, item.value)
    _place_in_block(block, item, at, indent, eol)
    return item


def _place_in_block(
    block: BlockArrayNode, item: ArrayItemNode, at: int, indent: str, eol: str
) -> None:
    """Puts a finished item into a block; its first token holds its comments and indentation."""
    items = block.items
    sibling = items[min(at, len(items) - 1)]
    if at == len(items):
        last = sibling.get_last_token()
        if not _has_line_ending(
            last.trailing_trivia
        ):  # a missing final line ending stays
            _trail(last, [*last.trailing_trivia, Trivia(TriviaKind.LINE_ENDING, eol)])
            _trail(item.get_last_token(), [])
    elif not _starts_line(sibling):  # the first item of a block opened on a dash line
        _lead(item.get_first_token(), [])
        _lead(sibling.get_first_token(), _indent_trivia(indent))
    else:
        preamble, owned = _split_leading(sibling.get_first_token().leading_trivia)
        _lead(
            item.get_first_token(), [*preamble, *item.get_first_token().leading_trivia]
        )
        _lead(sibling.get_first_token(), owned)
    block._set_items([*items[:at], item, *items[at:]])


def _reindent(node: Node, source: str, to: str) -> None:
    """Replaces the indentation prefix of every line of the node, its comment lines too."""
    tokens = node.get_tokens()
    for k, token in enumerate(tokens):
        at_line_start = k == 0 or _has_line_ending(tokens[k - 1].trailing_trivia)
        trivia: list[Trivia] = []
        for t in token.leading_trivia:
            if (
                at_line_start
                and t.kind == TriviaKind.WHITESPACE
                and t.text.startswith(source)
            ):
                trivia += _indent_trivia(to + t.text[len(source) :])
            else:
                if (
                    at_line_start
                    and source == ""
                    and t.kind
                    not in (TriviaKind.LINE_ENDING, TriviaKind.BYTE_ORDER_MARK)
                ):
                    trivia += _indent_trivia(
                        to
                    )  # a line without indentation gets the new one
                trivia.append(t)
            at_line_start = t.kind == TriviaKind.LINE_ENDING
        if at_line_start and source == "":  # the line of the token itself
            trivia += _indent_trivia(to)
        _lead(token, _join_all(trivia))


def _key_tokens(key: str) -> tuple[StringNode | LiteralNode, Token]:
    """The key node and the colon of an item with the key."""
    return _key_node(key), _with_space(Token.from_text(":"))


def _key_node(key: str) -> StringNode | LiteralNode:
    text = Builder.key_text(key)
    return _string(text) if text[0] in "'\"" else _literal(text)


def _with_space(token: Token) -> Token:
    return _trail(token, [Trivia(TriviaKind.WHITESPACE, " ")])


def _add_to_inline(
    array: InlineArrayNode, key: str | None, value: object, at: int
) -> ArrayItemNode:
    items = array.items
    multiline = _is_spread(array)
    eol = Layout.line_ending(array)
    indentation = _item_indentation(array)
    if isinstance(value, ArrayItemNode):  # a finished item, inserted
        item = value
    else:
        if isinstance(value, ValueNode):
            node = value
            _lead(node.get_first_token(), [])
            _trail(node.get_last_token(), [])
        else:
            unit = Layout.unit(array)
            fragile = _has_fragile_string(array, value)
            node = Builder.value(value, Place(False, indentation, unit, eol, fragile))
        key_node, colon = _key_tokens(key) if key is not None else (None, None)
        _check_depth(array, node)
        item = ArrayItemNode(None, key_node, colon, node)

    def space() -> list[Trivia]:
        if multiline:
            return [Trivia(TriviaKind.LINE_ENDING, eol)]
        return [Trivia(TriviaKind.WHITESPACE, " ")]

    if not items:
        pass  # nothing to separate
    elif at == len(items):
        last = items[-1]
        if last.separator:  # a trailing comma: the new item gets one too
            comma = _trail(Token.from_text(","), last.separator.trailing_trivia)
            _trail(last.separator, space())
            item._set_slots(separator=comma)
        else:
            last_token = last.get_last_token()
            # else the bracket closes the line of the last item
            line_end = multiline and _has_line_ending(last_token.trailing_trivia)
            if line_end:
                _trail(item.get_last_token(), [Trivia(TriviaKind.LINE_ENDING, eol)])
                comma = _trail(Token.from_text(","), last_token.trailing_trivia)
            else:
                _trail(item.get_last_token(), last_token.trailing_trivia)
                comma = _trail(Token.from_text(","), space())
            _trail(last_token, [])
            last._set_slots(separator=comma)
        if multiline:
            _lead(item.get_first_token(), _indent_trivia(indentation))
    else:
        following = items[at]
        preamble, owned = _split_leading(following.get_first_token().leading_trivia)
        comments = _without_indentation(owned)
        own_indentation = _indentation_of(owned)
        following_indentation = (
            own_indentation if _starts_line(following) else indentation
        )
        _lead(item.get_first_token(), [*preamble, *_indent_trivia(own_indentation)])
        if multiline:
            comments = [*comments, *_indent_trivia(following_indentation)]
        _lead(following.get_first_token(), comments)
        item._set_slots(separator=_trail(Token.from_text(","), space()))

    array._set_items([*items[:at], item, *items[at:]])
    return item


def _item_indentation(array: InlineArrayNode) -> str:
    """The indentation of the first item of an inline array that begins its line, or none."""
    item = next((item for item in array.items if _starts_line(item)), None)
    return item.get_indentation() if item else ""


def _is_spread(array: InlineArrayNode) -> bool:
    """Whether the items of an inline array stand on lines of their own."""
    return _has_line_ending(array.open_bracket.trailing_trivia) or any(
        item.separator and _has_line_ending(item.separator.trailing_trivia)
        for item in array.items
    )


# ---- removing


def remove_by_path(
    document: DocumentNode,
    path: Sequence[PathSegment],
    comments: CommentPolicy,
    nullable: bool | None,
    merge_blank_lines: bool = False,
) -> None:
    """Removes the key at the path: the item found, and the items whose value it overwrote."""
    item = resolve_path(document, path)
    array = item.parent
    assert isinstance(array, ArrayNode)
    if isinstance(path[-1], ItemIndex):
        remove_item(item, comments, nullable, merge_blank_lines)
        return
    keys = item_keys(array.items)
    key = keys[_index_of(array.items, item)]
    victims = [other for other, k in zip(array.items, keys, strict=True) if k == key]
    for victim in reversed(victims):
        remove_item(victim, comments, nullable, merge_blank_lines)


def remove_item(
    item: ArrayItemNode,
    comments: CommentPolicy,
    nullable: bool | None = None,
    merge_blank_lines: bool = False,
) -> None:
    """Removes an item with the comments it owns."""
    array = item.parent
    if not isinstance(array, BlockArrayNode | InlineArrayNode):
        raise NeonError("The item is not in an array.")

    items = array.items
    index = _index_of(items, item)
    remaining = [other for other in items if other is not item]
    owner = array.parent
    if nullable is not None:
        leave_null = nullable
    else:
        leave_null = isinstance(owner, ArrayItemNode | DocumentNode) and owner.nullable
    before = _keys_before(array)

    if (
        isinstance(array, BlockArrayNode)
        and not remaining
        and isinstance(owner, DocumentNode)
    ):
        _empty_document(owner, item, comments, leave_null)
        return
    if isinstance(array, BlockArrayNode):
        _remove_from_block(item, comments, merge_blank_lines)
        if not remaining:
            _empty_block(array, item, leave_null)
            return
    else:
        _remove_from_inline(array, item, index, comments)
        if not remaining and leave_null and isinstance(owner, ArrayItemNode):
            array._set_items([])
            _replace_value(owner, None)
            return
        if not remaining and leave_null and isinstance(owner, DocumentNode):
            array._set_items([])
            _empty_root(owner)
            return
    array._set_items(remaining)
    _keep_keys(
        array, before, keyless=True
    )  # an item removed from a list renumbers the rest
    _guard_dash_subblocks(array)


def _remove_from_block(
    item: ArrayItemNode, comments: CommentPolicy, merge_blank_lines: bool
) -> None:
    preamble, owned = _split_leading(item.get_first_token().leading_trivia)
    following = _token_after(item.get_last_token())
    kept = (
        [*_without_indentation(owned), *_comment_line(item, Layout.indentation(item))]
        if comments == CommentPolicy.MOVE_TO_NEXT_TOKEN
        else []
    )
    block = item.parent
    assert isinstance(block, BlockArrayNode)
    if not _starts_line(item):  # the first item of a block opened on the line of a dash
        second = block.items[1] if len(block.items) > 1 else None
        leading = second.get_first_token().leading_trivia if second else ()
        if second and (kept or any(t.kind == TriviaKind.COMMENT for t in leading)):
            # the dash ends its line, the comments stay below it
            owner = block.parent
            assert isinstance(owner, ArrayItemNode) and owner.bullet
            line_ending = Trivia(TriviaKind.LINE_ENDING, Layout.line_ending(item))
            _trail(owner.bullet, [line_ending])
            _lead(second.get_first_token(), _join_trivia(kept, leading))
        elif second:  # the next one moves up
            _lead(second.get_first_token(), [])
    elif following and merge_blank_lines and not kept:  # the narrower of the gaps stays
        gap = min(
            _blank_lines(preamble),
            _blank_lines(following.leading_trivia, at_start=True),
        )
        _lead(
            following,
            _join_trivia(
                _without_blank_lines(preamble, gap),
                _without_blank_lines(following.leading_trivia, 0, at_start=True),
            ),
        )
    elif following:
        _lead(following, _join_trivia([*preamble, *kept], following.leading_trivia))
    if (
        not _has_line_ending(item.get_last_token().trailing_trivia)
        and following
        and following.kind == TokenKind.END_OF_FILE
        and not preamble
        and not kept
    ):
        before = _token_before(item.get_first_token())
        if before:  # the file keeps ending without a line ending
            _trail(before, _without_line_ending(before.trailing_trivia))
    _lead(
        item.get_first_token(), owned
    )  # the item goes with what it owns, for insert()


def _comment_line(item: ArrayItemNode, indent: str) -> list[Trivia]:
    """The comment on the line of the item as a comment line of its own."""
    for token in item.get_tokens():
        comment = next(
            (t for t in token.trailing_trivia if t.kind == TriviaKind.COMMENT), None
        )
        if comment:
            line_ending = Trivia(TriviaKind.LINE_ENDING, Layout.line_ending(item))
            return [*_indent_trivia(indent), comment, line_ending]
        if _has_line_ending(token.trailing_trivia):
            break
    return []


def _empty_block(block: BlockArrayNode, last: ArrayItemNode, leave_null: bool) -> None:
    """The block lost its last item: an empty inline array takes its place, or null."""
    owner = block.parent
    assert isinstance(owner, ArrayItemNode)
    head = owner.colon or owner.bullet
    assert head
    on_dash_line = not _has_line_ending(
        head.trailing_trivia
    )  # the line ending was the item's
    block._set_items([])
    owner._set_slots(
        value=None
    )  # the tokens of the block are gone, the head keeps its line
    if on_dash_line:
        _trail(head, last.get_last_token().trailing_trivia)
    if not leave_null:
        _replace_value(owner, _empty_array("{}" if last.key else "[]"))
    _guard_dash_subblocks(owner.parent)


def _empty_document(
    document: DocumentNode,
    last: ArrayItemNode,
    comments: CommentPolicy,
    leave_null: bool,
) -> None:
    """The document lost its last item: the empty array, or nothing, keeps what stood above."""
    preamble, owned = _split_leading(last.get_first_token().leading_trivia)
    kept = list(preamble)
    if comments == CommentPolicy.MOVE_TO_NEXT_TOKEN:
        kept += [*_without_indentation(owned), *_comment_line(last, "")]
    trailing = last.get_last_token().trailing_trivia
    block = document.value
    assert isinstance(block, BlockArrayNode)
    block._set_items([])
    if leave_null:
        document._set_value(None)
        end = document.end_of_file
        _lead(end, _join_trivia(kept, end.leading_trivia))
        return
    node = _empty_array("{}" if last.key else "[]")
    _lead(node.get_first_token(), kept)
    _trail(node.get_last_token(), _without_comment(trailing))  # it went with the item
    document._set_value(node)


def _empty_array(brackets: str) -> ValueNode:
    return Builder.parse(brackets)


def _remove_from_inline(
    array: InlineArrayNode, item: ArrayItemNode, index: int, comments: CommentPolicy
) -> None:
    """
    Removes an item of an inline array. The item goes with what it owns; the lines around
    it stay lines: an item that started its line takes the line ending before itself
    along, one that did not leaves the line ending after itself, and what stood above the
    next item stays there.
    """
    items = array.items
    following = items[index + 1] if index + 1 < len(items) else None
    prev = items[index - 1] if index > 0 else None
    first = item.get_first_token()
    eol = Layout.line_ending(item)
    preamble, owned = _split_leading(first.leading_trivia)
    own_line = _starts_line(item)
    ends_line = any(_has_line_ending(t.trailing_trivia) for t in item.get_tokens())
    kept = (
        [*_without_indentation(owned), *_comment_line(item, "")]
        if comments == CommentPolicy.MOVE_TO_NEXT_TOKEN
        else []
    )

    before = _token_before(
        first
    )  # the opening bracket, or the comma of the previous item
    assert before
    between: list[Trivia]
    if following is None and prev and prev.separator and not item.separator:
        comma = prev.separator  # the comma before the last item goes with it
        prev._set_slots(separator=None)
        before = prev.get_last_token()
        between = [
            *before.trailing_trivia,
            *(comma.trailing_trivia if own_line else ()),
        ]
    elif own_line or (following and not ends_line):
        between = list(before.trailing_trivia)
    else:
        between = _without_trailing_space(before.trailing_trivia)
    if not own_line and ends_line:
        between = [
            *_without_trailing_space(between),
            Trivia(TriviaKind.LINE_ENDING, eol),
        ]
    between += [*preamble, *kept]
    if (
        following and own_line and not ends_line
    ):  # the next was on the line of the removed
        between += _indent_trivia(_indentation_of(owned))
    after = following.get_first_token() if following else array.close_bracket
    _reattach(before, after, [*between, *after.leading_trivia])
    item._set_slots(separator=None)  # the comma separated it in this array
    _lead(first, owned)  # the item goes with what it owns, for insert()


def _reattach(before: Token, after: Token, trivia: Sequence[Trivia]) -> None:
    """Splits the trivia between two tokens: up to the first line ending trailing, the rest leading."""
    merged = _join_all(trivia)
    split = next(
        (i + 1 for i, t in enumerate(merged) if t.kind == TriviaKind.LINE_ENDING),
        len(merged),
    )
    _trail(before, merged[:split])
    _lead(after, merged[split:])


# ---- keys


def set_item_key(item: ArrayItemNode, key: str | StringNode | LiteralNode) -> None:
    """Replaces the key of an item, in the quotes of the old one if it fits; or by a node."""
    array = item.parent if isinstance(item.parent, ArrayNode) else None
    old = item.key
    if old is None:
        raise NeonError("The item has no key.")
    if not isinstance(key, str):
        if not isinstance(key, StringNode | LiteralNode) or "\n" in key.token.text:
            raise TypeError("A key is a StringNode or a LiteralNode on one line.")
        _check_placeable(item, key)
    elif item.get_key_value() == key:
        return
    if isinstance(key, str):
        value = key
    elif isinstance(key, StringNode):
        value = key.to_value()
    else:
        value = literal_key(key.token.text)
    found = array.find_item(value) if array else None
    if found is not None and found is not item:
        raise NeonError(f"Duplicated key '{value}'")

    before = _keys_before(array) if array else None
    if not isinstance(key, str):
        node = key
    else:
        styled = _styled_scalar(old, key)
        assert styled is None or isinstance(styled, StringNode | LiteralNode)
        node = styled or _key_node(key)
    _take_edges(node, old)
    item._set_slots(key=node)
    colon = item.colon
    if (
        isinstance(node, LiteralNode)
        and colon
        and colon.kind == TokenKind.COLON
        and item.value
        and not colon.trailing_trivia
    ):
        _trail(
            colon, [Trivia(TriviaKind.WHITESPACE, " ")]
        )  # `a:b` would be one literal
    if array and before:
        before[0][item] = value
        _keep_keys(array, before, keyless=False)
        _guard_dash_subblocks(array)


# ---- nodes in slots


def replace_node(old: ValueNode, node: ValueNode) -> None:
    """Puts the node into the slot the old one stands in; the slot decides what that means."""
    parent = old.parent
    if node is old:
        return
    if not isinstance(node, ValueNode):
        raise TypeError("ValueNode expected.")
    if isinstance(parent, ArrayItemNode) and parent.value is old:
        set_item_node(parent, node)
    elif isinstance(parent, ArrayItemNode):
        _check_node(node, StringNode, LiteralNode)
        assert isinstance(node, StringNode | LiteralNode)
        set_item_key(parent, node)
    elif isinstance(parent, DocumentNode):
        set_document_node(parent, node)
    elif isinstance(parent, EntityNode) and parent.value is old:
        _check_head(node)
        chain = parent.parent
        if (
            isinstance(chain, EntityChainNode)
            and chain.entities[0] is not parent
            and not isinstance(node, LiteralNode)
        ):
            raise TypeError("A link of a chain after the first has a literal head.")
        _check_placeable(parent, node)
        _take_edges(node, old)
        parent._set_slots(value=node)
    elif isinstance(parent, EntityNode):
        _check_node(node, InlineArrayNode)
        assert isinstance(node, InlineArrayNode)
        if node.open_bracket.kind != TokenKind.OPEN_PAREN:
            raise TypeError("A token OpenParen expected.")
        _check_placeable(parent, node)
        _take_edges(node, old)
        parent._set_slots(attributes=node)
    elif isinstance(parent, EntityChainNode):
        _check_node(node, EntityNode)
        assert isinstance(node, EntityNode) and isinstance(old, EntityNode)
        entities = [node if entity is old else entity for entity in parent.entities]
        _check_links(entities)
        if node.attributes is None and old.attributes is not None:
            raise TypeError("The link had parentheses, its replacement needs them too.")
        _check_movable(parent, node)
        _check_depth(parent, node)
        _take_edges(node, old)
        parent._set_entities(entities)
    else:
        raise ValueError("The node is not in a tree.")


def _check_head(node: ValueNode) -> None:
    """The head of an entity is a scalar or an inline array, not the reserved name of a chain."""
    _check_node(node, StringNode, LiteralNode, InlineArrayNode)
    if isinstance(node, StringNode):
        name = node.to_value()
    elif isinstance(node, LiteralNode):
        name = node.token.text
    else:
        return
    if name == CHAIN:
        raise NeonError(f"Entity name '{CHAIN}' is reserved")


def _check_links(entities: Sequence[EntityNode]) -> None:
    """The links after the first have a literal head; only the last may lack parentheses."""
    for i, entity in enumerate(entities):
        _check_node(entity, EntityNode)
        if (i > 0 and not isinstance(entity.value, LiteralNode)) or (
            i < len(entities) - 1 and entity.attributes is None
        ):
            raise TypeError(
                "A link of a chain after the first is a literal, and only the last one"
                " may be without parentheses."
            )


def _check_node(node: object, *types: type[Node]) -> None:
    if not isinstance(node, types):
        raise TypeError(" or ".join(t.__name__ for t in types) + " expected.")


def detach_node(node: ValueNode) -> None:
    """Takes the node out with its edge trivia; only some slots can be empty."""
    parent = node.parent
    if (
        isinstance(parent, ArrayItemNode)
        and parent.value is node
        and (parent.colon or parent.bullet)
    ):
        set_item_node(parent, None)
    elif isinstance(parent, DocumentNode):  # the preamble and the byte order mark stay
        first = node.get_first_token()
        preamble, owned = _split_leading(first.leading_trivia)
        _lead(first, owned)
        parent._set_value(None)
        end = parent.end_of_file
        _lead(end, _join_trivia(preamble, end.leading_trivia))
    elif parent is not None:
        raise ValueError("The slot of the node cannot be empty; use replace_with().")


def set_document_node(document: DocumentNode, node: ValueNode | None) -> None:
    """Puts the node into the place of the root: a block gets the indentation of the old one."""
    old = document.value
    if node is old:
        return
    if node is None:
        _empty_root(document)
        return
    if not isinstance(node, ValueNode):
        raise TypeError("ValueNode expected.")
    _check_placeable(document, node)

    end = document.end_of_file
    if isinstance(node, BlockArrayNode):
        indent = (
            old.items[0].get_indentation() if isinstance(old, BlockArrayNode) else ""
        )
        _reindent_block(node, indent)
    first = node.get_first_token()
    block_leading = first.leading_trivia if isinstance(node, BlockArrayNode) else ()
    if old is not None:
        leading = old.get_first_token().leading_trivia
        if isinstance(node, BlockArrayNode):
            leading = _join_trivia(_without_indentation(leading), block_leading)
        _lead(first, leading)
        _trail(node.get_last_token(), old.get_last_token().trailing_trivia)
    else:  # the first value of an empty document comes after what the document holds
        leading = _without_indentation(end.leading_trivia)
        eol = Layout.line_ending(end)
        if leading and leading[-1].kind == TriviaKind.COMMENT:
            leading.append(Trivia(TriviaKind.LINE_ENDING, eol))
        _lead(first, _join_trivia(leading, block_leading))
        has_line_ending = _has_line_ending(end.leading_trivia)
        line_ending = [Trivia(TriviaKind.LINE_ENDING, eol)] if has_line_ending else []
        _trail(node.get_last_token(), line_ending)
        _lead(end, [])
    document._set_value(node)


def _empty_root(document: DocumentNode) -> None:
    """Empties the document; what stood above the value and the comment on its line stay."""
    old = document.value
    if old is None:
        return
    end = document.end_of_file
    trailing = old.get_last_token().trailing_trivia
    comment = [t for t in trailing if t.kind == TriviaKind.COMMENT]
    kept = [*_without_indentation(old.get_first_token().leading_trivia), *comment]
    if comment and (_has_line_ending(trailing) or end.leading_trivia):
        kept.append(Trivia(TriviaKind.LINE_ENDING, Layout.line_ending(old)))
    document._set_value(None)
    _lead(end, _join_trivia(kept, end.leading_trivia))


# ---- paths


def resolve_path(
    document: DocumentNode,
    path: Sequence[PathSegment],
    full_path: Sequence[PathSegment] | None = None,
) -> ArrayItemNode:
    """The item at the path, or an error naming the first key that is not there."""
    if not path:
        raise ValueError("An empty path leads to no item.")
    container: Node | None = document.value
    item: ArrayItemNode | None = None
    for segment in path:
        array = array_of(container)
        item = _find_segment(array, segment) if array else None
        if item is None:
            text = _path_text(path if full_path is None else full_path)
            raise NeonError(f"No item '{_segment_text(segment)}' in the path {text}")
        container = item.value
    assert item
    return item


def _find_segment(array: ArrayNode, segment: PathSegment) -> ArrayItemNode | None:
    if isinstance(segment, ItemIndex):
        items = array.items
        return items[segment.index] if 0 <= segment.index < len(items) else None
    return array.find_item(segment)


def array_of(node: Node | None) -> ArrayNode | None:
    """The array of a container: the array itself, or the attributes of an entity."""
    if isinstance(node, EntityNode):
        return node.attributes
    return node if isinstance(node, ArrayNode) else None


def set_by_path(
    document: DocumentNode, path: Sequence[PathSegment], value: object, *, create: bool
) -> None:
    if not path:
        _set_document_value(document, value)
        return

    last = path[-1]
    owner = resolve_path(document, path[:-1], path) if len(path) > 1 else None
    container = owner.value if owner else document.value
    array = array_of(container)
    existing = _find_segment(array, last) if array else None
    if existing:
        set_item_value(existing, value)
        return
    if not create or isinstance(last, ItemIndex):  # an item by its order is never made
        missing = f"No item '{_segment_text(last)}' in the path {_path_text(path)}"
        raise NeonError(missing if create else missing + ", and create is false")

    key = _segment_text(last)
    if array:
        add_item(array, None if _is_implicit_key(array, key) else key, value)
    elif container is None and owner:
        set_item_value(owner, {key: value})
    elif container is None:
        _set_document_value(document, {key: value})
    else:
        raise NeonError(f"The value at {_path_text(path[:-1])} is not an array")


def _is_implicit_key(array: ArrayNode, key: str) -> bool:
    """Whether a key is the one the array would assign to an item without a key."""
    length = _list_length(array, item_keys(array.items))
    return length is not None and str(length) == key


def _set_document_value(document: DocumentNode, value: object) -> None:
    old = document.value
    if isinstance(value, ValueNode):
        set_document_node(document, value)
    elif _same_value(value, old) if old is not None else value is None:
        pass  # nothing changes
    elif value is None:
        _empty_root(document)
    else:
        node = _styled_scalar(old, value) or Builder.value(
            value,
            Place(
                block=True,
                indent="",
                unit=Layout.unit(document),
                eol=Layout.line_ending(document.end_of_file),
                double_quoted=_has_fragile_string(document, value),
            ),
        )
        set_document_node(document, node)


def _segment_text(segment: PathSegment) -> str:
    if isinstance(segment, ItemIndex):
        return f"#{segment.index}"
    if isinstance(segment, bool) or not isinstance(segment, str | int):
        raise TypeError("A segment of a path is a string, an integer or an ItemIndex.")
    return segment if isinstance(segment, str) else int_text(segment)


def _path_text(path: Sequence[PathSegment]) -> str:
    return ".".join(_segment_text(segment) for segment in path)


# ---- trivia


def _lead(token: Token, trivia: Sequence[Trivia]) -> Token:
    return token._set_leading(_keep_carriage_returns(trivia))


def _trail(token: Token, trivia: Sequence[Trivia]) -> Token:
    return token._set_trailing(_keep_carriage_returns(trivia))


def _keep_carriage_returns(trivia: Sequence[Trivia]) -> Sequence[Trivia]:
    """A line feed after a lone carriage return is written as CRLF, so the CR stays its text."""
    return [
        Trivia(TriviaKind.LINE_ENDING, "\r\n")
        if t.text == "\n" and i and trivia[i - 1].text.endswith("\r")
        else t
        for i, t in enumerate(trivia)
    ]


def _split_leading(trivia: Sequence[Trivia]) -> tuple[list[Trivia], list[Trivia]]:
    """
    Splits the leading trivia of the first token of an item into the preamble (lines
    separated from the item by a blank line, and the blank lines) and what the item owns:
    the comment lines directly above it and its indentation.
    """
    lines = _split_lines(trivia)
    split = len(lines) - 1  # the last line is the indentation
    while split > 0 and any(t.kind == TriviaKind.COMMENT for t in lines[split - 1]):
        split -= 1
    preamble = [t for line in lines[:split] for t in line]
    owned = [t for line in lines[split:] for t in line]
    if (
        owned and owned[0].kind == TriviaKind.BYTE_ORDER_MARK
    ):  # it belongs to the document
        preamble.append(owned.pop(0))
    return preamble, owned


def _blank_lines(trivia: Sequence[Trivia], at_start: bool = False) -> int:
    """Number of blank lines at the end of the trivia, or at their start."""
    lines = _split_lines(trivia)
    if not at_start:
        lines.pop()  # the indentation of the line that follows
        lines.reverse()
    count = 0
    while count < len(lines) and _is_blank_line(lines[count]):
        count += 1
    return count


def _is_blank_line(line: Sequence[Trivia]) -> bool:
    kinds = {t.kind for t in line}
    return TriviaKind.COMMENT not in kinds and TriviaKind.LINE_ENDING in kinds


def _without_blank_lines(
    trivia: Sequence[Trivia], keep: int, at_start: bool = False
) -> list[Trivia]:
    """The trivia with only the given number of blank lines left at the end, or at the start."""
    lines = _split_lines(trivia)
    blank = _blank_lines(trivia, at_start)
    if at_start:
        del lines[keep:blank]
    else:
        del lines[len(lines) - 1 - blank + keep : len(lines) - 1]
    return [t for line in lines for t in line]


def _split_lines(trivia: Iterable[Trivia]) -> list[list[Trivia]]:
    """Groups trivia into lines, each ending with its line ending; the last group has none."""
    lines: list[list[Trivia]] = [[]]
    for t in trivia:
        lines[-1].append(t)
        if t.kind == TriviaKind.LINE_ENDING:
            lines.append([])
    return lines


def _without_indentation(owned: Sequence[Trivia]) -> list[Trivia]:
    """The comment lines without the indentation of the item they stood above."""
    if owned and owned[-1].kind == TriviaKind.WHITESPACE:
        return list(owned[:-1])
    return list(owned)


def _without_trailing_space(trivia: Sequence[Trivia]) -> list[Trivia]:
    if trivia and trivia[-1].kind == TriviaKind.WHITESPACE:
        return list(trivia[:-1])
    return list(trivia)


def _without_comment(trivia: Sequence[Trivia]) -> list[Trivia]:
    """The trivia without a comment and the space before it."""
    i = next((k for k, t in enumerate(trivia) if t.kind == TriviaKind.COMMENT), -1)
    if i < 0:
        return list(trivia)
    start = i - 1 if i > 0 and trivia[i - 1].kind == TriviaKind.WHITESPACE else i
    return _join_all([*trivia[:start], *trivia[i + 1 :]])


def _indentation_of(owned: Sequence[Trivia]) -> str:
    if owned and owned[-1].kind == TriviaKind.WHITESPACE:
        return owned[-1].text
    return ""


def _indent_trivia(indent: str) -> list[Trivia]:
    return [Trivia(TriviaKind.WHITESPACE, indent)] if indent else []


def _join_trivia(a: Sequence[Trivia], b: Sequence[Trivia]) -> list[Trivia]:
    """Concatenates two lists of trivia, merging whitespace that would meet."""
    if (
        a
        and b
        and a[-1].kind == TriviaKind.WHITESPACE
        and b[0].kind == TriviaKind.WHITESPACE
    ):
        return [*a[:-1], *b]
    return [*a, *b]


def _join_all(trivia: Iterable[Trivia]) -> list[Trivia]:
    res: list[Trivia] = []
    for t in trivia:
        res = _join_trivia(res, [t])
    return res


def _has_fragile_string(at: Node, value: object) -> bool:
    """
    Whether a multiline string of the value has to use \"\"\": the document holds an empty
    ''' string closed on the line right after its opening, which a later line starting
    with ''' would close instead.
    """
    if not _has_multiline_string(value):
        return False
    root = at
    while root.parent is not None:
        root = root.parent
    return any(
        token.kind == TokenKind.STRING and _FRAGILE.fullmatch(token.text)
        for token in root.get_tokens()
    )


_FRAGILE = re.compile(r"'''\r?\n[\t ]*'''")


def _has_multiline_string(value: object, depth: int = 0) -> bool:
    """Whether the value holds a string written on more lines; too deep or unknown counts."""
    if isinstance(value, str):
        return "\n" in value
    if value is None or isinstance(value, bool | int | float | Date | date):
        return False
    if depth > MAX_DEPTH:
        return True
    if isinstance(value, Entity):
        return _has_multiline_string(value.value, depth + 1) or _has_multiline_string(
            value.attributes, depth + 1
        )
    host = entries_of(value)
    return host is None or any(
        _has_multiline_string(v, depth + 1) for _, v in host.entries
    )


def _starts_line(item: ArrayItemNode) -> bool:
    """Whether the item begins its line; not so the first item of a block on a dash line."""
    before = _token_before(item.get_first_token())
    return before is None or _has_line_ending(before.trailing_trivia)


def _has_line_ending(trivia: Iterable[Trivia]) -> bool:
    return any(t.kind == TriviaKind.LINE_ENDING for t in trivia)


def _without_line_ending(trivia: Iterable[Trivia]) -> list[Trivia]:
    return [t for t in trivia if t.kind != TriviaKind.LINE_ENDING]


def _token_after(token: Token) -> Token | None:
    return find_neighbour(token, backward=False)


def _token_before(token: Token) -> Token | None:
    return find_neighbour(token, backward=True)


def _index_of(items: Sequence[object], item: object) -> int:
    return next(i for i, x in enumerate(items) if x is item)
