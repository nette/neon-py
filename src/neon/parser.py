from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NoReturn

from .errors import NeonError
from .lexer import decode_utf8, quote, tokenize
from .nodes import (
    ArrayItemNode,
    BlockArrayNode,
    DocumentNode,
    EntityChainNode,
    EntityNode,
    InlineArrayNode,
    LiteralNode,
    StringNode,
    ValueNode,
)
from .position import Cursor
from .scanner import TokenKind, TriviaKind
from .token import Token
from .values import (
    CHAIN,
    INT64_MAX,
    MAX_DEPTH,
    EscapeError,
    evaluate_string,
    is_integer_key,
    literal_key,
)


def parse(input: str | bytes) -> DocumentNode:
    """Parses NEON into the lossless syntax tree; bytes are UTF-8."""
    if isinstance(input, bytes):
        input = decode_utf8(input)
    return _Parser(tokenize(input), input).parse()


NEWLINE: Literal["Newline"] = "Newline"
type Expected = TokenKind | Literal["Newline"]

_TOO_DEEP = "Too deep nesting"

_PAIRS = {
    TokenKind.OPEN_BRACKET: TokenKind.CLOSE_BRACKET,
    TokenKind.OPEN_BRACE: TokenKind.CLOSE_BRACE,
    TokenKind.OPEN_PAREN: TokenKind.CLOSE_PAREN,
}


@dataclass(slots=True)
class _Mark:
    i: int
    newline_taken: bool


@dataclass(slots=True)
class _PendingIndent:
    """The indentation of a block opened on the line of a dash, decided where first needed."""

    base: str | _PendingIndent
    resolved: str | None = None
    line: _Mark | None = None


type _Indent = str | _PendingIndent


class _Parser:
    """
    The parser of nette/neon 3.x ported onto tokens with trivia. Line endings are
    trivia, but the parser sees them as it saw the Newline tokens of 3.x: before token
    i stands a line break if the trivia between token i-1 and token i hold a line ending.
    """

    def __init__(self, tokens: list[Token], input: str) -> None:
        self._tokens = tokens
        self._cursor = Cursor(input)
        self._i = 0
        self._newline_taken = False
        self._depth = 0

    def parse(self) -> DocumentNode:
        self._skip_newlines()
        value = self._parse_block(self._get_indentation())

        self._skip_newlines()
        if self.is_next():
            self.error()

        document = DocumentNode(value, self._tokens[-1])
        self._verify(document)
        return document

    def _parse_block(
        self, indent: _Indent, only_bullets: bool = False
    ) -> ValueNode | None:
        depth = self._depth
        try:
            return self._parse_block_items(indent, only_bullets)
        finally:
            self._depth = depth

    def _parse_dash_block(self, base: _Indent) -> ValueNode | None:
        """
        A block opened on the line of a dash is indented by a tab if the line where its
        indentation is first compared starts with one, by two spaces otherwise. 3.x tries
        the tab and then the spaces, which costs time exponential in nested dashes; the
        spaces fail on that line whenever the tab was chosen, so a block that fails with
        the tab fails as the spaces would.
        """
        indent = _PendingIndent(base)
        try:
            return self._parse_block(indent)
        except NeonError as e:
            if (
                e.message != _TOO_DEEP
                and indent.resolved is not None
                and indent.resolved.endswith("\t")
                and indent.line
            ):
                self._i = indent.line.i
                self._newline_taken = indent.line.newline_taken
                self.error("Invalid combination of tabs and spaces")
            raise

    def _resolve(self, indent: _Indent, following: str) -> str:
        """The indentation of a block; of one opened on the line of a dash by the next line."""
        if isinstance(indent, str):
            return indent
        if indent.resolved is None:
            base = self._resolve(indent.base, following)
            tab = following.startswith(base + "\t")
            indent.resolved = base + ("\t" if tab else "  ")
            indent.line = self._mark()
        return indent.resolved

    def _parse_block_items(
        self, pending: _Indent, only_bullets: bool
    ) -> ValueNode | None:
        items: list[ArrayItemNode] = []
        keys = _KeyCheck(self)

        while True:
            bullet = self._consume_token(TokenKind.DASH)
            key: StringNode | LiteralNode | None = None
            colon: Token | None = None
            value: ValueNode | None = None

            if bullet:
                if not items:
                    self._enter(bullet)
            elif not self.is_next() or only_bullets:
                return BlockArrayNode(items) if items else None
            else:
                head = self._parse_value()
                colon = self._consume_token(TokenKind.COLON, TokenKind.EQUALS)
                if colon:
                    key = keys.add(head)
                    if not items:
                        self._enter(head.get_first_token())
                else:
                    if items:
                        self.error()
                    return head

            if self._consume_newline():
                self._skip_newlines()
                following = self._get_indentation()
                indent = self._resolve(pending, following)
                if not _comparable(following, indent):
                    self.error("Invalid combination of tabs and spaces")
                elif len(following) > len(indent):  # open new block
                    value = self._parse_block(following)
                elif len(following) < len(indent):  # close block
                    items.append(keys.item(bullet, key, colon, None))
                    return BlockArrayNode(items)
                elif key is not None and self.is_next(TokenKind.DASH):  # dash subblock
                    value = self._parse_block(indent, only_bullets=True)

            elif key is None:  # open new block after dash
                value = self._parse_dash_block(pending)

            elif self.is_next():
                value = self._parse_value()
                if self.is_next() and not self.is_next(NEWLINE):
                    self.error()

            items.append(keys.item(bullet, key, colon, value))

            self._skip_newlines()
            if not self.is_next():
                return BlockArrayNode(items)

            following = self._get_indentation()
            indent = self._resolve(pending, following)
            if not _comparable(following, indent):
                self.error("Invalid combination of tabs and spaces")
            elif len(following) > len(indent):
                self.error("Bad indentation")
            elif len(following) < len(indent):  # close block
                return BlockArrayNode(items)

    def _parse_value(self) -> ValueNode:
        node: ValueNode
        if token := self._consume_token(TokenKind.STRING):
            try:
                evaluate_string(token.text)
            except EscapeError as e:
                self.error(str(e), token)
            node = StringNode(token)
        elif token := self._consume_token(TokenKind.LITERAL):
            node = LiteralNode(token)
        elif self.is_next(
            TokenKind.OPEN_BRACKET, TokenKind.OPEN_PAREN, TokenKind.OPEN_BRACE
        ):
            node = self._parse_braces()
        else:
            self.error()
        return self._parse_entity(node)

    def _parse_entity(self, node: ValueNode) -> ValueNode:
        if not self.is_next(TokenKind.OPEN_PAREN):
            return node

        self._check_entity_head(node)
        entities = [EntityNode(node, self._parse_braces())]
        while token := self._consume_token(TokenKind.LITERAL):
            head = LiteralNode(token)
            self._check_entity_head(head)
            if self.is_next(TokenKind.OPEN_PAREN):
                entities.append(EntityNode(head, self._parse_braces()))
            else:
                entities.append(EntityNode(head, None))
                break

        return entities[0] if len(entities) == 1 else EntityChainNode(entities)

    def _parse_braces(self) -> InlineArrayNode:
        depth = self._depth
        try:
            return self._parse_braces_items()
        finally:
            self._depth = depth

    def _parse_braces_items(self) -> InlineArrayNode:
        opening = self._consume_token()
        assert opening
        self._enter(opening)
        end = _PAIRS[opening.kind]
        items: list[ArrayItemNode] = []
        keys = _KeyCheck(self)

        while True:
            self._skip_newlines()
            closing = self._consume_token(end)
            if closing:
                return InlineArrayNode(opening, items, closing)

            head = self._parse_value()
            colon = self._consume_token(TokenKind.COLON, TokenKind.EQUALS)
            if colon:
                key = keys.add(head)
                missing = self.is_next(NEWLINE, TokenKind.COMMA, end)
                value = None if missing else self._parse_value()
                item = keys.item(None, key, colon, value)
            else:
                item = keys.item(None, None, None, head)
            items.append(item)

            before = self._mark()
            self._skip_newlines()
            comma = self._consume_token(TokenKind.COMMA)
            if comma:
                item._set_slots(separator=comma)
            if before != self._mark():
                continue
            if not self.is_next(end):
                self.error()

    def _enter(self, token: Token) -> None:
        """One level deeper into arrays."""
        self._depth += 1
        if self._depth > MAX_DEPTH:
            self.error(_TOO_DEEP, token)

    def _check_entity_head(self, node: ValueNode) -> None:
        if isinstance(node, StringNode):
            value = node.to_value()
        elif isinstance(node, LiteralNode):
            value = node.token.text
        else:
            return
        if value == CHAIN:
            self.error(f"Entity name '{CHAIN}' is reserved", node.get_first_token())

    def _verify(self, document: DocumentNode) -> None:
        """Every token of the stream is in the tree exactly once, in the order of the stream."""
        tokens = document.get_tokens()
        if len(tokens) != len(self._tokens) or any(
            a is not b for a, b in zip(tokens, self._tokens, strict=True)
        ):
            raise RuntimeError(
                "Internal error: the tree does not hold the tokens of the input in order."
            )

    # stream of tokens with line breaks

    def _newline_before(self, i: int) -> bool:
        tokens = self._tokens
        trivia = tokens[0].leading_trivia if i == 0 else tokens[i - 1].trailing_trivia
        return any(t.kind == TriviaKind.LINE_ENDING for t in trivia)

    def _peek(self) -> Expected:
        if not self._newline_taken and self._newline_before(self._i):
            return NEWLINE
        return self._tokens[self._i].kind

    def is_next(self, *kinds: Expected) -> bool:
        """Whether the next item is of one of the kinds; without kinds, whether anything but the end follows."""
        following = self._peek()
        return following in kinds if kinds else following != TokenKind.END_OF_FILE

    def _consume_newline(self) -> bool:
        if self._peek() == NEWLINE:
            self._newline_taken = True
            return True
        return False

    def _skip_newlines(self) -> None:
        while self._consume_newline():
            pass

    def _consume_token(self, *kinds: TokenKind) -> Token | None:
        following = self._peek()
        if (
            following == NEWLINE
            or following == TokenKind.END_OF_FILE
            or (kinds and following not in kinds)
        ):
            return None
        self._newline_taken = False
        self._i += 1
        return self._tokens[self._i - 1]

    def _mark(self) -> _Mark:
        return _Mark(self._i, self._newline_taken)

    def _get_indentation(self) -> str:
        """Indentation of the next token if it starts a line: the whitespace after a line ending or the start."""
        i = self._i
        tokens = self._tokens
        if i == 0:
            trivia = [
                t
                for t in tokens[0].leading_trivia
                if t.kind != TriviaKind.BYTE_ORDER_MARK
            ]
        else:
            trivia = [*tokens[i - 1].trailing_trivia, *tokens[i].leading_trivia]
        if not trivia or trivia[-1].kind != TriviaKind.WHITESPACE:
            return ""
        if len(trivia) == 1:
            return trivia[-1].text if i == 0 else ""
        return trivia[-1].text if trivia[-2].kind == TriviaKind.LINE_ENDING else ""

    def error(self, message: str | None = None, token: Token | None = None) -> NoReturn:
        if token:
            raise NeonError(message or "", token.origin)

        following = self._peek()
        if following == NEWLINE:
            offset, count = self._locate_newline()
            text = "<new line>" * min(count, 40)
            raise NeonError(message or f"Unexpected '{text}'", self._cursor.at(offset))

        current = self._tokens[self._i]
        if message is None:
            message = (
                "Unexpected end"
                if following == TokenKind.END_OF_FILE
                else f"Unexpected '{quote(current.text)}'"
            )
        raise NeonError(message, current.origin)

    def _locate_newline(self) -> tuple[int, int]:
        """Offset of the line break before the current token, and how many line endings follow there."""
        i = self._i
        prev = self._tokens[i - 1] if i else None
        offset = 0
        trivia = list(self._tokens[i].leading_trivia)
        if prev:
            assert prev.origin
            offset = prev.origin.offset + len(prev.text)
            trivia = [*prev.trailing_trivia, *trivia]
        k = 0
        while trivia[k].kind != TriviaKind.LINE_ENDING:
            offset += len(trivia[k].text)
            k += 1
        count = 0
        while (
            k + count < len(trivia) and trivia[k + count].kind == TriviaKind.LINE_ENDING
        ):
            count += 1
        return offset, count


class _KeyCheck:
    """Checks explicit keys of one array for duplicates and implicit keys for overflow."""

    def __init__(self, parser: _Parser) -> None:
        self._parser = parser
        self._seen: set[str] = set()
        self._top: int | None = None

    def add(self, node: ValueNode) -> StringNode | LiteralNode:
        if isinstance(node, StringNode):
            key = node.to_value()
        elif isinstance(node, LiteralNode):
            key = literal_key(node.token.text)
        else:
            self._parser.error("Unacceptable key", node.get_first_token())

        if key in self._seen:
            self._parser.error(f"Duplicated key '{key}'", node.token)
        self._seen.add(key)
        return node

    def item(
        self,
        bullet: Token | None,
        key: StringNode | LiteralNode | None,
        colon: Token | None,
        value: ValueNode | None,
    ) -> ArrayItemNode:
        """Makes the item and accounts its key, explicit or implicit."""
        item = ArrayItemNode(bullet, key, colon, value)
        canonical = item.get_key_value()
        if canonical is None:
            following = 0 if self._top is None else self._top + 1
            if following > INT64_MAX:
                self._parser.error(
                    "Implicit key overflow", (value or item).get_first_token()
                )
            canonical = str(following)
        if is_integer_key(canonical):
            n = int(canonical)
            self._top = n if self._top is None or n > self._top else self._top
        return item


def _comparable(a: str, b: str) -> bool:
    n = min(len(a), len(b))
    return a[:n] == b[:n]
