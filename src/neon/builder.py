from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .encoder import Encoder, encode
from .errors import NeonError
from .nodes import ArrayItemNode, ArrayNode, ValueNode
from .parser import parse
from .values import is_integer_key


@dataclass(frozen=True, slots=True)
class Place:
    """Where a built node will stand."""

    block: bool
    """Write arrays as blocks."""
    indent: str
    """Indentation of the line of the item that will hold the value."""
    unit: str
    """Indentation unit of nested blocks."""
    eol: str
    """Line ending of the document."""
    double_quoted: bool = False
    """Write multiline strings in \"\"\", because ''' would close an earlier string."""


class Builder:
    """
    Makes nodes from values of the host. The text is what encode() writes, so new
    values look the same as encoded ones; it is parsed, so the nodes are valid by
    construction.
    """

    @staticmethod
    def value(value: object, place: Place) -> ValueNode:
        """A value as a node, without edge trivia; a non-empty array is a block if allowed."""
        block = place.block and _has_items(value)
        text = Encoder(block, place.unit, place.double_quoted).encode(value)
        if block:
            text = _indent(text.rstrip("\n"), place.indent + place.unit, first=True)
        else:
            text = _indent(text, place.indent, first=False)
        node = Builder.parse(text.replace("\n", place.eol))
        if not block:
            node.get_first_token()._set_leading(())
        node.get_last_token()._set_trailing(())
        return node

    @staticmethod
    def block_item(key: str | None, value: object, place: Place) -> ArrayItemNode:
        """An item of a block, `key: value` or `- value`, with its indentation and line ending."""
        head = "-" if key is None else Builder.key_text(key) + ":"
        if value is None and key is not None:
            text = head
        elif _has_items(value):
            body = Encoder(True, place.unit, place.double_quoted).encode(value)
            text = head + "\n" + _indent(body.rstrip("\n"), place.unit, first=True)
        else:
            encoded = Encoder(False, place.unit, place.double_quoted).encode(value)
            text = head + " " + encoded
        text = _indent(text, place.indent, first=True).replace("\n", place.eol)
        block = Builder.parse(text + place.eol)
        assert isinstance(block, ArrayNode)
        item = block.items[0]
        block._set_items(())
        return item

    @staticmethod
    def parse(text: str) -> ValueNode:
        """The value of a document made of the text, detached, its tokens without an origin."""
        document = parse(text)
        node = document.value
        assert node
        document._set_value(None)
        for token in node.get_tokens():
            token._forget_origin()
        return node

    @staticmethod
    def key_text(key: str) -> str:
        """The text of a key: an integer key as digits, anything else as a string."""
        if "\n" in key:
            raise NeonError("A key cannot contain a line break.")
        return key if is_integer_key(key) else encode(key)


def _has_items(value: object) -> bool:
    """A non-empty list, tuple or mapping."""
    return isinstance(value, list | tuple | Mapping) and len(value) > 0


def _indent(text: str, prefix: str, *, first: bool) -> str:
    """Prefixes non-empty lines; the first one only if asked."""
    return "\n".join(
        prefix + line if line and (i or first) else line
        for i, line in enumerate(text.split("\n"))
    )
