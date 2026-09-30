from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Self, cast

from ._journal import atomic, record
from .errors import NeonError
from .position import Position
from .scanner import TokenKind, TriviaKind
from .token import Token, Trivia
from .values import (
    CHAIN,
    INT64_MAX,
    Entity,
    EscapeError,
    Value,
    evaluate_literal,
    evaluate_number,
    evaluate_string,
    int_text,
    is_integer_key,
    literal_key,
)

type Child = Node | Token


class CommentPolicy(StrEnum):
    """What happens to the comments a removed item owns: on its line and directly above it."""

    DROP = "drop"
    """The comments that describe the item go with it."""
    MOVE_TO_NEXT_TOKEN = "move"
    """The comments stay, above whatever follows."""


@dataclass(frozen=True, slots=True)
class ItemIndex:
    """A segment of a path that finds an item by its order, not by its key."""

    index: int


type PathSegment = str | int | ItemIndex


class _Unset(Enum):
    UNSET = 0


_UNSET = _Unset.UNSET
"""A slot not given to _set_slots(), as None empties it."""


class Node(ABC):
    """Base of all nodes of the syntax tree."""

    __slots__ = ("_parent",)

    def __init__(self) -> None:
        self._parent: Node | None = None

    @property
    def parent(self) -> Node | None:
        return self._parent

    @abstractmethod
    def get_children(self) -> list[Child]:
        """The slots in order, without Nones."""

    @abstractmethod
    def clone(self) -> Node:
        """A deep copy without a parent; tokens keep their origin."""

    def get_tokens(self) -> list[Token]:
        res: list[Token] = []

        def collect(node: Node) -> None:
            for child in node.get_children():
                if isinstance(child, Token):
                    res.append(child)
                else:
                    collect(child)

        collect(self)
        return res

    @abstractmethod
    def get_first_token(self) -> Token: ...

    @abstractmethod
    def get_last_token(self) -> Token: ...

    def get_position(self) -> Position | None:
        """Current position of the first token, computed by a walk from the root."""
        return self.get_first_token().get_position()

    def print(self) -> str:
        """The source text of the node, with the trivia of its tokens."""
        return "".join(str(token) for token in self.get_tokens())

    def __str__(self) -> str:
        return self.print()

    def __repr__(self) -> str:
        text = self.print().strip()
        if len(text) > 40:
            text = text[:39] + "…"
        return f"{type(self).__name__}({text!r})"

    def is_multi_line(self) -> bool:
        """Whether the node spans more than one line, its outer trivia not counted."""
        tokens = self.get_tokens()
        return any(
            (i > 0 and _has_line_ending(token.leading_trivia))
            or "\n" in token.text
            or (i < len(tokens) - 1 and _has_line_ending(token.trailing_trivia))
            for i, token in enumerate(tokens)
        )

    def has_leading_comment(self) -> bool:
        return bool(self.get_leading_comments())

    def get_leading_comments(self) -> list[Trivia]:
        """Comments in the leading trivia of the first token."""
        trivia = self.get_first_token().leading_trivia
        return [t for t in trivia if t.kind == TriviaKind.COMMENT]

    def get_trailing_comments(self) -> list[Trivia]:
        """Comments in the trailing trivia of the last token."""
        trivia = self.get_last_token().trailing_trivia
        return [t for t in trivia if t.kind == TriviaKind.COMMENT]

    def find_ancestor[T: Node](self, cls: type[T]) -> T | None:
        node = self._parent
        while node is not None:
            if isinstance(node, cls):
                return node
            node = node.parent
        return None

    def get_next_sibling(self) -> Node | None:
        siblings = self._siblings()
        i = _index_of(siblings, self)
        return siblings[i + 1] if i + 1 < len(siblings) else None

    def get_previous_sibling(self) -> Node | None:
        siblings = self._siblings()
        i = _index_of(siblings, self)
        return siblings[i - 1] if i > 0 else None

    def _siblings(self) -> list[Node]:
        if self._parent is None:
            return []
        return [c for c in self._parent.get_children() if isinstance(c, Node)]

    def find[T: Node](
        self, cls: type[T], predicate: Callable[[T], bool] | None = None
    ) -> list[T]:
        """Descendants of the class, in document order."""
        res: list[T] = []
        for node in self._walk():
            if isinstance(node, cls) and (predicate is None or predicate(node)):
                res.append(node)
        return res

    def find_first[T: Node](
        self, cls: type[T], predicate: Callable[[T], bool] | None = None
    ) -> T | None:
        for node in self._walk():
            if isinstance(node, cls) and (predicate is None or predicate(node)):
                return node
        return None

    def _walk(self) -> Iterable[Node]:
        """The descendants in document order."""
        for child in self.get_children():
            if isinstance(child, Node):
                yield child
                yield from child._walk()

    def _set_parent(self, parent: Node | None) -> None:
        old = self._parent
        record(lambda: setattr(self, "_parent", old))
        self._parent = parent


class ValueNode(Node):
    """A node that has a value."""

    __slots__ = ()

    @abstractmethod
    def to_value(self) -> Value: ...

    @abstractmethod
    def clone(self) -> ValueNode: ...

    def replace_with(self, node: ValueNode) -> None:
        """
        Puts the node into the slot of this one, which decides what that means; the node
        gets the trivia at the edges of this one in place of its own.
        """
        from .editing import replace_node

        with atomic():
            replace_node(self, node)

    def detach(self) -> Self:
        """Takes the node out of the tree, with the trivia at its edges; the slot gets None."""
        from .editing import detach_node

        with atomic():
            detach_node(self)
        return self


def _adopt[T: Child | None](parent: Node, child: T, previous: Child | None = None) -> T:
    """Puts a child into a slot of the parent and releases the previous one."""
    if child is previous:
        return child
    if child is not None:
        adopted = cast(Child, child)
        if adopted.parent is not None:
            raise ValueError(
                "The node already has a parent, detach() or clone() it first."
            )
        node: Node | None = parent
        while node is not None:
            if node is adopted:
                raise ValueError("A node cannot be put into its own subtree.")
            node = node.parent
        adopted._set_parent(parent)
    if previous is not None:
        previous._set_parent(None)
    return child


class DocumentNode(Node):
    """The root of a document."""

    __slots__ = ("_end_of_file", "_value", "nullable")

    def __init__(self, value: ValueNode | None, end_of_file: Token) -> None:
        super().__init__()
        self._value = _adopt(self, value)
        self._end_of_file = _adopt(self, end_of_file)
        self.nullable = False
        """Whether removing the last item leaves None instead of an empty collection."""

    @property
    def value(self) -> ValueNode | None:
        return self._value

    @value.setter
    def value(self, node: ValueNode | None) -> None:
        """The same as set_value([], node): the node takes the place of the root."""
        from .editing import set_document_node

        with atomic():
            set_document_node(self, node)

    @property
    def end_of_file(self) -> Token:
        return self._end_of_file

    def get_children(self) -> list[Child]:
        if self._value is None:
            return [self._end_of_file]
        return [self._value, self._end_of_file]

    def get_first_token(self) -> Token:
        return self._value.get_first_token() if self._value else self._end_of_file

    def get_last_token(self) -> Token:
        return self._end_of_file

    def clone(self) -> DocumentNode:
        value = self._value.clone() if self._value else None
        res = DocumentNode(value, self._end_of_file.clone())
        res.nullable = self.nullable
        return res

    def to_value(self) -> Value:
        return self._value.to_value() if self._value else None

    def find_item(self, path: Sequence[PathSegment]) -> ArrayItemNode | None:
        """
        The item at the path of keys, the same keys decode() gives; a path continues into
        the attributes of an entity.
        """
        from .editing import resolve_path

        try:
            return resolve_path(self, path) if path else None
        except NeonError:
            return None

    def set_value(
        self, path: Sequence[PathSegment], value: object, *, create: bool = True
    ) -> None:
        """Writes the value at the path; a missing last key is added, unless create is False."""
        from .editing import set_by_path

        with atomic():
            set_by_path(self, path, value, create=create)

    def add_item(
        self,
        path: Sequence[PathSegment],
        value: object,
        *,
        key: str | None = None,
        position: int | None = None,
    ) -> ArrayItemNode:
        """Adds an item to the array at the path, without a key unless given one."""
        from .editing import add_by_path

        with atomic():
            return add_by_path(self, path, value, key, position)

    def remove_item(
        self,
        path: Sequence[PathSegment],
        *,
        comments: CommentPolicy = CommentPolicy.DROP,
        nullable: bool | None = None,
        merge_blank_lines: bool = False,
    ) -> None:
        """Removes the item at the path with the comments it owns."""
        from .editing import remove_by_path

        with atomic():
            remove_by_path(self, path, comments, nullable, merge_blank_lines)

    def set_key(self, path: Sequence[PathSegment], key: str) -> None:
        """Renames the key of the item at the path."""
        from .editing import resolve_path, set_item_key

        with atomic():
            set_item_key(resolve_path(self, path), key)

    def _set_value(self, value: ValueNode | None) -> None:
        """Writes the slot as it is, for an edit that moves the trivia itself."""
        old = self._value
        self._value = _adopt(self, value, old)
        record(lambda: setattr(self, "_value", old))


class ArrayNode(ValueNode):
    """Base of the two kinds of arrays."""

    __slots__ = ("_items",)

    def __init__(self) -> None:
        super().__init__()
        self._items: tuple[ArrayItemNode, ...] = ()

    @property
    def items(self) -> tuple[ArrayItemNode, ...]:
        return self._items

    @abstractmethod
    def _is_empty_map(self) -> bool:
        """Whether the array without items is a map, `{}`."""

    def _set_items(self, items: Iterable[ArrayItemNode]) -> None:
        """Replaces the list; items that leave it lose their parent, new ones must have none."""
        items = tuple(items)
        old = self._items
        kept = {id(item) for item in items}
        present = {id(item) for item in old}
        for item in old:
            if id(item) not in kept:
                item._set_parent(None)
        for item in items:
            if id(item) not in present:
                _adopt(self, item)
        self._items = items
        record(lambda: setattr(self, "_items", old))

    def find_item(self, key: str | int) -> ArrayItemNode | None:
        """The item with the canonical key, as decode() would find it."""
        return resolve_keys(self._items).get(_key_text(key))

    def add_item(
        self, value: object, *, key: str | None = None, position: int | None = None
    ) -> ArrayItemNode:
        """Adds an item built from the value, at the end or before the item at the position."""
        from .editing import add_item

        with atomic():
            return add_item(self, key, value, position)

    def remove_item(
        self, item: ArrayItemNode, comments: CommentPolicy = CommentPolicy.DROP
    ) -> None:
        """Removes the item with the comments it owns."""
        from .editing import remove_item

        if item.parent is not self:
            raise ValueError("The item is not in this array.")
        with atomic():
            remove_item(item, comments)

    def to_value(self) -> list[Value] | dict[str, Value]:
        entries = {
            key: item.get_value() for key, item in resolve_keys(self._items).items()
        }
        if not entries:
            return {} if self._is_empty_map() else []
        if all(key == str(i) for i, key in enumerate(entries)):
            return list(entries.values())
        return entries


def resolve_keys(items: Sequence[ArrayItemNode]) -> dict[str, ArrayItemNode]:
    """Keys of the items; an overwritten key has the winning item, at the first position."""
    return dict(zip(item_keys(items), items, strict=True))


def item_keys(items: Sequence[ArrayItemNode]) -> list[str]:
    """The key of each item, explicit or implicit."""
    res: list[str] = []
    top: int | None = None
    for item in items:
        key = item.get_key_value()
        if key is None:
            following = 0 if top is None else top + 1
            if following > INT64_MAX:
                raise NeonError("Implicit key overflow", item.get_position())
            key = str(following)
        if is_integer_key(key):
            n = int(key)
            top = n if top is None or n > top else top
        res.append(key)
    return res


def _key_text(key: str | int) -> str:
    if isinstance(key, bool) or not isinstance(key, str | int):
        raise TypeError("A key is a string or an integer.")
    return key if isinstance(key, str) else int_text(key)


class BlockArrayNode(ArrayNode):
    """An array written one item per line."""

    __slots__ = ()

    def __init__(self, items: Iterable[ArrayItemNode]) -> None:
        super().__init__()
        self._set_items(items)

    def _is_empty_map(self) -> bool:
        return False

    def get_children(self) -> list[Child]:
        return list(self._items)

    def get_first_token(self) -> Token:
        return self._items[0].get_first_token()

    def get_last_token(self) -> Token:
        return self._items[-1].get_last_token()

    def clone(self) -> BlockArrayNode:
        return BlockArrayNode(item.clone() for item in self._items)


class InlineArrayNode(ArrayNode):
    """An array in brackets, `[...]`, `{...}` or `(...)`."""

    __slots__ = ("_close_bracket", "_open_bracket")

    def __init__(
        self, open_bracket: Token, items: Iterable[ArrayItemNode], close_bracket: Token
    ) -> None:
        super().__init__()
        self._open_bracket = _adopt(self, open_bracket)
        self._set_items(items)
        self._close_bracket = _adopt(self, close_bracket)

    def _is_empty_map(self) -> bool:
        return self._open_bracket.kind == TokenKind.OPEN_BRACE

    @property
    def open_bracket(self) -> Token:
        return self._open_bracket

    @property
    def close_bracket(self) -> Token:
        return self._close_bracket

    def get_children(self) -> list[Child]:
        return [self._open_bracket, *self._items, self._close_bracket]

    def get_first_token(self) -> Token:
        return self._open_bracket

    def get_last_token(self) -> Token:
        return self._close_bracket

    def clone(self) -> InlineArrayNode:
        return InlineArrayNode(
            self._open_bracket.clone(),
            (item.clone() for item in self._items),
            self._close_bracket.clone(),
        )


class ArrayItemNode(Node):
    """An item of an array: `- value`, `key: value`, or an item in brackets."""

    __slots__ = ("_bullet", "_colon", "_key", "_separator", "_value", "nullable")

    def __init__(
        self,
        bullet: Token | None,
        key: StringNode | LiteralNode | None,
        colon: Token | None,
        value: ValueNode | None,
        separator: Token | None = None,
    ) -> None:
        super().__init__()
        self._bullet = _adopt(self, bullet)
        self._key = _adopt(self, key)
        self._colon = _adopt(self, colon)
        self._value = _adopt(self, value)
        self._separator = _adopt(self, separator)
        self.nullable = False
        """Whether removing the last item of the value leaves None, not an empty collection."""

    @property
    def bullet(self) -> Token | None:
        return self._bullet

    @property
    def key(self) -> StringNode | LiteralNode | None:
        return self._key

    @property
    def colon(self) -> Token | None:
        return self._colon

    @property
    def value(self) -> ValueNode | None:
        return self._value

    @value.setter
    def value(self, node: ValueNode | None) -> None:
        """The same as set_value() with a node; None empties the value."""
        from .editing import set_item_node

        with atomic():
            set_item_node(self, node)

    @property
    def separator(self) -> Token | None:
        return self._separator

    def _set_slots(
        self,
        *,
        bullet: Token | _Unset | None = _UNSET,
        key: StringNode | LiteralNode | _Unset | None = _UNSET,
        colon: Token | _Unset | None = _UNSET,
        value: ValueNode | _Unset | None = _UNSET,
        separator: Token | _Unset | None = _UNSET,
    ) -> None:
        """Writes the given slots as they are, for an edit that moves the trivia itself."""
        old = (self._bullet, self._key, self._colon, self._value, self._separator)
        record(lambda: self._restore(*old))
        if bullet is not _UNSET:
            self._bullet = _adopt(self, bullet, self._bullet)
        if key is not _UNSET:
            self._key = _adopt(self, key, self._key)
        if colon is not _UNSET:
            self._colon = _adopt(self, colon, self._colon)
        if value is not _UNSET:
            self._value = _adopt(self, value, self._value)
        if separator is not _UNSET:
            self._separator = _adopt(self, separator, self._separator)

    def _restore(
        self,
        bullet: Token | None,
        key: StringNode | LiteralNode | None,
        colon: Token | None,
        value: ValueNode | None,
        separator: Token | None,
    ) -> None:
        self._bullet = bullet
        self._key = key
        self._colon = colon
        self._value = value
        self._separator = separator

    def get_children(self) -> list[Child]:
        slots = (self._bullet, self._key, self._colon, self._value, self._separator)
        return [child for child in slots if child is not None]

    def get_first_token(self) -> Token:
        if self._bullet:
            return self._bullet
        if self._key:
            return self._key.get_first_token()
        return cast(ValueNode, self._value).get_first_token()

    def get_last_token(self) -> Token:
        if self._separator:
            return self._separator
        if self._value:
            return self._value.get_last_token()
        return cast(Token, self._colon or self._bullet)

    def clone(self) -> ArrayItemNode:
        res = ArrayItemNode(
            self._bullet.clone() if self._bullet else None,
            self._key.clone() if self._key else None,
            self._colon.clone() if self._colon else None,
            self._value.clone() if self._value else None,
            self._separator.clone() if self._separator else None,
        )
        res.nullable = self.nullable
        return res

    def get_key_value(self) -> str | None:
        """The canonical key, or None for an item without a key."""
        if isinstance(self._key, StringNode):
            return self._key.to_value()
        if self._key:
            return literal_key(self._key.token.text)
        return None

    def get_value(self) -> Value:
        """The value of the item, None without one."""
        return self._value.to_value() if self._value else None

    def get_indentation(self) -> str:
        """The indentation of the line the item starts on."""
        trivia = self.get_first_token().leading_trivia
        if trivia and trivia[-1].kind == TriviaKind.WHITESPACE:
            return trivia[-1].text
        return ""

    def set_value(self, value: object) -> None:
        """
        Writes the value: a value of the host or a node. Writing an equal value changes
        nothing; a new scalar keeps the style of the old one where it can.
        """
        from .editing import set_item_value

        with atomic():
            set_item_value(self, value)

    def set_key(self, key: str) -> None:
        """Renames the key."""
        from .editing import set_item_key

        with atomic():
            set_item_key(self, key)

    def remove(
        self,
        comments: CommentPolicy = CommentPolicy.DROP,
        merge_blank_lines: bool = False,
    ) -> None:
        """Removes the item from its array, with the comments it owns."""
        from .editing import remove_item

        with atomic():
            remove_item(self, comments, None, merge_blank_lines)


class EntityNode(ValueNode):
    """An entity, `value(attributes)`."""

    __slots__ = ("_attributes", "_value")

    def __init__(self, value: ValueNode, attributes: InlineArrayNode | None) -> None:
        super().__init__()
        self._value = _adopt(self, value)
        self._attributes = _adopt(self, attributes)

    @property
    def value(self) -> ValueNode:
        return self._value

    @property
    def attributes(self) -> InlineArrayNode | None:
        return self._attributes

    def _set_slots(
        self, value: ValueNode | None = None, attributes: InlineArrayNode | None = None
    ) -> None:
        old = (self._value, self._attributes)
        record(lambda: self._restore(*old))
        if value:
            self._value = _adopt(self, value, self._value)
        if attributes:
            self._attributes = _adopt(self, attributes, self._attributes)

    def _restore(self, value: ValueNode, attributes: InlineArrayNode | None) -> None:
        self._value = value
        self._attributes = attributes

    def get_children(self) -> list[Child]:
        if self._attributes is None:
            return [self._value]
        return [self._value, self._attributes]

    def get_first_token(self) -> Token:
        return self._value.get_first_token()

    def get_last_token(self) -> Token:
        if self._attributes:
            return self._attributes.close_bracket
        return self._value.get_last_token()

    def clone(self) -> EntityNode:
        attributes = self._attributes.clone() if self._attributes else None
        return EntityNode(self._value.clone(), attributes)

    def to_value(self) -> Entity:
        attributes = self._attributes.to_value() if self._attributes else []
        return Entity(self._value.to_value(), attributes)


class EntityChainNode(ValueNode):
    """Two or more entities written one after another, `a(1) b(2)`."""

    __slots__ = ("_entities",)

    def __init__(self, entities: Iterable[EntityNode]) -> None:
        super().__init__()
        self._entities = tuple(entities)
        for entity in self._entities:
            _adopt(self, entity)

    @property
    def entities(self) -> tuple[EntityNode, ...]:
        return self._entities

    def _set_entities(self, entities: Iterable[EntityNode]) -> None:
        entities = tuple(entities)
        old = self._entities
        for entity in old:
            if not any(entity is e for e in entities):
                entity._set_parent(None)
        for entity in entities:
            if not any(entity is e for e in old):
                _adopt(self, entity)
        self._entities = entities
        record(lambda: setattr(self, "_entities", old))

    def get_children(self) -> list[Child]:
        return list(self._entities)

    def get_first_token(self) -> Token:
        return self._entities[0].get_first_token()

    def get_last_token(self) -> Token:
        return self._entities[-1].get_last_token()

    def clone(self) -> EntityChainNode:
        return EntityChainNode(entity.clone() for entity in self._entities)

    def to_value(self) -> Entity:
        links: list[Value] = [entity.to_value() for entity in self._entities]
        return Entity(CHAIN, links)


class StringNode(ValueNode):
    """A quoted string."""

    __slots__ = ("_token",)

    def __init__(self, token: Token) -> None:
        super().__init__()
        self._token = _adopt(self, token)

    @property
    def token(self) -> Token:
        return self._token

    def get_children(self) -> list[Child]:
        return [self._token]

    def get_first_token(self) -> Token:
        return self._token

    def get_last_token(self) -> Token:
        return self._token

    def clone(self) -> StringNode:
        return StringNode(self._token.clone())

    def to_value(self) -> str:
        try:
            return evaluate_string(self._token.text)
        except EscapeError as e:
            position = self._token.get_position() or self._token.origin
            raise NeonError(str(e), position) from None


class LiteralNode(ValueNode):
    """An unquoted scalar: a number, a word, a date or a string."""

    __slots__ = ("_token",)

    def __init__(self, token: Token) -> None:
        super().__init__()
        self._token = _adopt(self, token)

    @property
    def token(self) -> Token:
        return self._token

    def get_children(self) -> list[Child]:
        return [self._token]

    def get_first_token(self) -> Token:
        return self._token

    def get_last_token(self) -> Token:
        return self._token

    def clone(self) -> LiteralNode:
        return LiteralNode(self._token.clone())

    def to_value(self, is_key: bool = False) -> Value:
        """The value of the literal; a key keeps words and dates as strings."""
        text = self._token.text
        if is_key:
            number = evaluate_number(text)
            return text if number is None else number
        return evaluate_literal(text)


def _has_line_ending(trivia: Iterable[Trivia]) -> bool:
    return any(t.kind == TriviaKind.LINE_ENDING for t in trivia)


def _index_of(items: Sequence[object], item: object) -> int:
    return next(i for i, x in enumerate(items) if x is item)
