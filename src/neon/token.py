from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Self

from ._journal import record
from .position import Position
from .scanner import Scanner, TokenKind, TriviaKind

_WHITESPACE = re.compile(r"(?:[ \t]|\r(?!\n))+")
_COMMENT = re.compile(r"#[^\n]*")
_SURROGATE = re.compile(r"[\ud800-\udfff]")


def is_well_formed(s: str) -> bool:
    """Whether the string holds no lone surrogate."""
    return not _SURROGATE.search(s)


def _classify_trivia(text: str) -> TriviaKind | None:
    if _WHITESPACE.fullmatch(text):
        return TriviaKind.WHITESPACE
    if text in ("\n", "\r\n"):
        return TriviaKind.LINE_ENDING
    if _COMMENT.fullmatch(text) and is_well_formed(text):
        return TriviaKind.COMMENT
    if text == "﻿":
        return TriviaKind.BYTE_ORDER_MARK
    return None


@dataclass(frozen=True, slots=True)
class Trivia:
    """Whitespace, a line ending, a comment or a byte order mark around a token."""

    kind: TriviaKind
    text: str

    def __post_init__(self) -> None:
        if _classify_trivia(self.text) != self.kind:
            raise ValueError(f"{self.text!r} is not {self.kind}.")

    @classmethod
    def from_text(cls, text: str) -> Self:
        kind = _classify_trivia(text)
        if kind is None:
            raise ValueError(f"{text!r} is not one trivia.")
        return cls(kind, text)

    def with_text(self, text: str) -> Trivia:
        trivia = Trivia.from_text(text)
        if trivia.kind != self.kind:
            raise ValueError(f"{text!r} is not {self.kind}.")
        return trivia

    def is_(self, *kinds: TriviaKind) -> bool:
        return self.kind in kinds

    def get_comment_text(self) -> str:
        """Text of a comment without # and trimmed, or empty string for other trivia."""
        return self.text[1:].strip() if self.kind == TriviaKind.COMMENT else ""


class Token:
    """A token of the source with the trivia around it."""

    __slots__ = ("_kind", "_leading", "_origin", "_text", "_trailing")

    _kind: TokenKind
    _text: str
    _leading: tuple[Trivia, ...]
    _trailing: tuple[Trivia, ...]
    _origin: Position | None

    def __init__(
        self,
        kind: TokenKind,
        text: str,
        leading_trivia: Iterable[Trivia] = (),
        trailing_trivia: Iterable[Trivia] = (),
        origin: Position | None = None,
    ) -> None:
        """Prefer Token.from_text(); the text must be one token of the kind."""
        leading = tuple(leading_trivia)
        trailing = tuple(trailing_trivia)
        _check_text(kind, text)
        _check_trivia(leading, leading=True, end_of_file=kind == TokenKind.END_OF_FILE)
        _check_trivia(
            trailing, leading=False, end_of_file=kind == TokenKind.END_OF_FILE
        )
        self._set(kind, text, leading, trailing, origin)

    @classmethod
    def from_text(cls, text: str) -> Token:
        """Makes a token of the kind the scanner reads the text as."""
        kind = _scan_single_token(text) if is_well_formed(text) else None
        if kind is None:
            raise ValueError(f"{text!r} is not one token.")
        return cls(kind, text)

    @classmethod
    def _trusted(
        cls,
        kind: TokenKind,
        text: str,
        leading: tuple[Trivia, ...],
        trailing: tuple[Trivia, ...],
        origin: Position | None,
    ) -> Token:
        """A token whose text and trivia are known to be valid: one the lexer reads or a clone."""
        token = cls.__new__(cls)
        token._set(kind, text, leading, trailing, origin)
        return token

    def _set(
        self,
        kind: TokenKind,
        text: str,
        leading: tuple[Trivia, ...],
        trailing: tuple[Trivia, ...],
        origin: Position | None,
    ) -> None:
        self._kind = kind
        self._text = text
        self._leading = leading
        self._trailing = trailing
        self._origin = origin

    @property
    def kind(self) -> TokenKind:
        """A token changes its kind only by being replaced."""
        return self._kind

    @property
    def origin(self) -> Position | None:
        """Where the token stood in the source it was read from; None for one made otherwise."""
        return self._origin

    @property
    def text(self) -> str:
        return self._text

    @property
    def leading_trivia(self) -> tuple[Trivia, ...]:
        return self._leading

    @property
    def trailing_trivia(self) -> tuple[Trivia, ...]:
        return self._trailing

    def set_text(self, text: str) -> Self:
        """Replaces the text by another one of the same kind."""
        _check_text(self._kind, text)
        old = self._text
        record(lambda: setattr(self, "_text", old))
        self._text = text
        return self

    def set_leading_trivia(self, trivia: Iterable[Trivia]) -> Self:
        """Sets the leading trivia, in the canonical form."""
        return self._set_leading(tuple(trivia))

    def set_trailing_trivia(self, trivia: Iterable[Trivia]) -> Self:
        """Sets the trailing trivia, in the canonical form."""
        return self._set_trailing(tuple(trivia))

    def replace_trivia(self, old: Trivia, replacement: Trivia) -> Self:
        """Replaces a trivia, found by identity, in the leading or trailing trivia."""

        def replace(trivia: tuple[Trivia, ...]) -> list[Trivia]:
            return [replacement if t is old else t for t in trivia]

        if any(t is old for t in self._leading):
            self.set_leading_trivia(replace(self._leading))
        elif any(t is old for t in self._trailing):
            self.set_trailing_trivia(replace(self._trailing))
        else:
            raise ValueError("The trivia does not belong to the token.")
        return self

    def is_(self, *kinds_or_texts: str) -> bool:
        """Whether the token is of one of the kinds, or has one of the texts."""
        return any(
            self._kind == k if isinstance(k, TokenKind) else self._text == k
            for k in kinds_or_texts
        )

    def clone(self) -> Token:
        """A detached copy with the same text, trivia and origin."""
        return Token._trusted(
            self._kind, self._text, self._leading, self._trailing, self._origin
        )

    def __str__(self) -> str:
        """The source text of the token with its trivia."""
        return (
            "".join(t.text for t in self._leading)
            + self._text
            + "".join(t.text for t in self._trailing)
        )

    def __repr__(self) -> str:
        return f"Token({self._kind}, {self._text!r})"

    def _set_leading(self, trivia: Sequence[Trivia]) -> Self:
        """Sets the leading trivia without the checks of the place, for an edit that moves trivia in steps."""
        trivia = tuple(trivia)
        _check_trivia(trivia, leading=True, end_of_file=self.is_(TokenKind.END_OF_FILE))
        old = self._leading
        record(lambda: setattr(self, "_leading", old))
        self._leading = _unique_trivia(trivia)
        return self

    def _set_trailing(self, trivia: Sequence[Trivia]) -> Self:
        trivia = tuple(trivia)
        _check_trivia(
            trivia, leading=False, end_of_file=self.is_(TokenKind.END_OF_FILE)
        )
        old = self._trailing
        record(lambda: setattr(self, "_trailing", old))
        self._trailing = _unique_trivia(trivia)
        return self

    def _forget_origin(self) -> None:
        """For a token made from a text that is not the source of the document."""
        self._origin = None


def _check_text(kind: TokenKind, text: str) -> None:
    if not is_well_formed(text) or (
        text != ""
        if kind == TokenKind.END_OF_FILE
        else _scan_single_token(text) != kind
    ):
        raise ValueError(f"{text!r} is not one token of kind {kind}.")


def _check_trivia(
    trivia: tuple[Trivia, ...], *, leading: bool, end_of_file: bool
) -> None:
    if not leading and end_of_file and trivia:
        raise ValueError("EndOfFile has no trailing trivia.")
    for i, t in enumerate(trivia):
        following = trivia[i + 1] if i + 1 < len(trivia) else None
        if not isinstance(t, Trivia):
            raise TypeError("Trivia expected.")
        if t.kind == TriviaKind.WHITESPACE and following and following.kind == t.kind:
            raise ValueError("Two whitespace trivia must not stand next to each other.")
        if t.kind == TriviaKind.BYTE_ORDER_MARK and (not leading or i > 0):
            raise ValueError("A byte order mark may only be the first leading trivia.")
        if t.kind == TriviaKind.LINE_ENDING and not leading and following:
            raise ValueError("A line ending must be the last of the trailing trivia.")
        if (
            t.kind == TriviaKind.COMMENT
            and (following is None or following.kind != TriviaKind.LINE_ENDING)
            and (following or (leading and not end_of_file))
        ):
            raise ValueError("A comment must be followed by a line ending.")
        if t.text.endswith("\r") and following and following.text.startswith("\n"):
            raise ValueError(
                "A carriage return before a line feed would make one line ending of the two."
            )


def _unique_trivia(trivia: tuple[Trivia, ...]) -> tuple[Trivia, ...]:
    """A copy where an instance stands once, so that replace_trivia() finds the one meant."""
    seen: set[int] = set()
    res: list[Trivia] = []
    for t in trivia:
        if id(t) in seen:
            t = Trivia(t.kind, t.text)
        seen.add(id(t))
        res.append(t)
    return tuple(res)


def _scan_single_token(text: str) -> TokenKind | None:
    """Kind of the text if the scanner reads it as exactly one token without trivia."""
    token = Scanner(text).next()
    if token and token.end == len(text) and isinstance(token.kind, TokenKind):
        return token.kind
    return None
