import re
from dataclasses import dataclass
from enum import StrEnum


class TokenKind(StrEnum):
    """Kind of a token; the value is its name in the specification."""

    STRING = "String"
    LITERAL = "Literal"
    COLON = "Colon"
    EQUALS = "Equals"
    COMMA = "Comma"
    DASH = "Dash"
    OPEN_BRACKET = "OpenBracket"
    CLOSE_BRACKET = "CloseBracket"
    OPEN_BRACE = "OpenBrace"
    CLOSE_BRACE = "CloseBrace"
    OPEN_PAREN = "OpenParen"
    CLOSE_PAREN = "CloseParen"
    END_OF_FILE = "EndOfFile"


class TriviaKind(StrEnum):
    """Kind of a trivia; the value is its name in the specification."""

    WHITESPACE = "Whitespace"
    LINE_ENDING = "LineEnding"
    COMMENT = "Comment"
    BYTE_ORDER_MARK = "ByteOrderMark"


@dataclass(slots=True)
class Scanned:
    kind: TokenKind | TriviaKind
    start: int
    end: int


_PUNCTUATION = {
    ",": TokenKind.COMMA,
    "=": TokenKind.EQUALS,
    "[": TokenKind.OPEN_BRACKET,
    "]": TokenKind.CLOSE_BRACKET,
    "{": TokenKind.OPEN_BRACE,
    "}": TokenKind.CLOSE_BRACE,
    "(": TokenKind.OPEN_PAREN,
    ")": TokenKind.CLOSE_PAREN,
}

_SPACE = " \t\n\r"
_LITERAL_RUN = re.compile(r"[^,:=\]})(\n\t \r]+")
_SPACE_RUN = re.compile(r"(?:[ \t]|\r(?!\n))+")
_COMMENT = re.compile(r"#(?:[^\r\n]|\r(?!\n))*")


def _match_end(pattern: re.Pattern[str], s: str, i: int) -> int:
    m = pattern.match(s, i)
    return m.end() if m else i


class Scanner:
    """Reads tokens and trivia one by one. Returns None on an error, with error_at set."""

    __slots__ = ("_s", "error_at", "position")

    def __init__(self, s: str) -> None:
        self._s = s
        self.position = 0
        self.error_at = -1

    def next(self) -> Scanned | None:
        s = self._s
        start = self.position
        if start >= len(s):
            return None
        c = s[start]
        kind: TokenKind | TriviaKind

        if start == 0 and c == "﻿":
            kind = TriviaKind.BYTE_ORDER_MARK
            end = 1

        elif c in "'\"":
            kind = TokenKind.STRING
            end = -1
            if s.startswith(c * 3, start) and self._is_line_ending(start + 3):
                end = self._scan_multiline(start, c * 3)
            if end < 0:  # a triple without a closing line is read as single-line quotes
                end = (
                    self._scan_single_quoted(start)
                    if c == "'"
                    else self._scan_double_quoted(start)
                )

        elif c == "#":
            kind = TriviaKind.COMMENT
            end = _match_end(_COMMENT, s, start)

        elif self._is_line_ending(start):
            kind = TriviaKind.LINE_ENDING
            end = start + (2 if c == "\r" else 1)

        elif self._is_space(start):
            kind = TriviaKind.WHITESPACE
            end = _match_end(_SPACE_RUN, s, start)

        elif c in _PUNCTUATION:
            kind = _PUNCTUATION[c]
            end = start + 1

        elif c in ":-":
            prev = s[start - 1] if start else ""
            if (
                not self._is_any(start + 1, "\"',=[]{}()")
                and prev != '"'
                and prev != "'"
            ):
                kind = TokenKind.LITERAL
                end = self._scan_literal(start + 2)  # the next character starts it too
            else:
                kind = TokenKind.COLON if c == ":" else TokenKind.DASH
                end = start + 1

        elif not self._is_any(start, "#\"',:=[]{}()`"):
            kind = TokenKind.LITERAL
            end = self._scan_literal(start + 1)

        else:
            self.error_at = start
            return None

        if end < 0:
            self.error_at = start
            return None
        self.position = end
        return Scanned(kind, start, end)

    def _is_any(self, i: int, chars: str) -> bool:
        """Is the character one of the given ones, a space, a line ending, or none?"""
        return i >= len(self._s) or self._s[i] in _SPACE or self._s[i] in chars

    def _is_space(self, i: int) -> bool:
        s = self._s
        return i < len(s) and (
            s[i] in " \t" or (s[i] == "\r" and s[i + 1 : i + 2] != "\n")
        )

    def _is_line_ending(self, i: int) -> bool:
        s = self._s
        return s[i : i + 1] == "\n" or s[i : i + 2] == "\r\n"

    def _scan_literal(self, i: int) -> int:
        s = self._s
        while True:
            if m := _LITERAL_RUN.match(s, i):
                i = m.end()
            elif s[i : i + 1] == ":" and not self._is_any(i + 1, ",]})"):
                i += 1
            elif m := _SPACE_RUN.match(s, i):
                if self._is_any(m.end(), "#,:=]})("):
                    return i
                i = m.end()
            else:
                return i

    def _scan_single_quoted(self, start: int) -> int:
        s = self._s
        i = start + 1
        while i < len(s):
            if s.startswith("''", i):
                i += 2
            elif s[i] in "'\n":
                break
            else:
                i += 1
        return i + 1 if s[i : i + 1] == "'" else -1

    def _scan_double_quoted(self, start: int) -> int:
        s = self._s
        i = start + 1
        while i < len(s):
            if s[i] == "\\" and i + 1 < len(s) and not self._is_line_ending(i + 1):
                i += 2
            elif s[i] in '"\\\n':
                break
            else:
                i += 1
        return i + 1 if s[i : i + 1] == '"' else -1

    def _scan_multiline(self, start: int, triple: str) -> int:
        """
        Content runs to the first line after the first one that starts with optional
        spaces and the closing triple; only without such a line may the first line
        itself close an empty string.
        """
        s = self._s
        first = s.find("\n", start) + 1
        i = s.find("\n", first)
        while i >= 0:
            end = self._closing_at(i + 1, triple)
            if end >= 0:
                return end
            i = s.find("\n", i + 1)
        return self._closing_at(first, triple)

    def _closing_at(self, i: int, triple: str) -> int:
        while self._is_space(i):
            i += 1
        return i + 3 if self._s.startswith(triple, i) else -1
