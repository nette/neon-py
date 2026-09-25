from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal

from .errors import NeonError
from .scanner import Scanner, TokenKind
from .values import (
    CHAIN,
    MAX_DEPTH,
    Date,
    Entity,
    evaluate_literal,
    int_text,
    is_integer_key,
)

type BlockFilter = Callable[[object, list[str]], bool]
"""Decides whether the array is written as a block, given the keys on the way to it."""

type _Entries = list[tuple[str, object]]


def encode(
    value: object,
    block_mode: bool | BlockFilter = False,
    indentation: str = "\t",
) -> str:
    """
    Writes a value as NEON. In block mode, arrays are written one item per line; a
    function block_mode(value, path) is asked for every array and writes it as a block
    if true.
    """
    return Encoder(block_mode, indentation).encode(value)


CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f]")


class Encoder:
    """
    Writes values as NEON; double_quoted writes multiline strings in \"\"\", for a document
    where ''' would close an earlier string.
    """

    def __init__(
        self,
        block_mode: bool | BlockFilter,
        indentation: str = "\t",
        double_quoted: bool = False,
    ) -> None:
        if not isinstance(indentation, str) or not re.fullmatch(r"[\t ]+", indentation):
            raise ValueError("The indentation is a non-empty run of spaces and tabs.")
        if not isinstance(block_mode, bool) and not callable(block_mode):
            raise TypeError("The block_mode is a boolean or a function.")
        self._block_mode = block_mode
        self._indentation = indentation
        self._double_quoted = double_quoted
        self._stack: list[int] = []  # ids of the containers on the way to the value
        self._arrays = 0
        self._path: list[str] = []

    def encode(self, value: object) -> str:
        entries = self._entries(value)
        if entries is None or not self._is_block(value):
            return self._inline(value)
        if not entries:
            return "[]" if isinstance(value, list | tuple) else "{}"
        return self._block(value, entries)

    def _block(self, container: object, entries: _Entries) -> str:
        res: list[str] = []
        self._enter(container, array=True)
        for key, value, hidden in _with_hidden_keys(entries):
            self._path.append(key)
            prefix = "-" if hidden else self._key(key) + ":"
            nested = self._entries(value)
            if nested and self._is_block(value):
                text = _indent(self._block(value, nested), self._indentation)
                res.append(
                    prefix + "\n" + text + ("" if text.endswith("\n\n") else "\n")
                )
            else:
                res.append(prefix + " " + self._inline(value) + "\n")
            self._path.pop()
        self._leave(array=True)
        return "".join(res)

    def _is_block(self, value: object) -> bool:
        if callable(self._block_mode):
            return bool(self._block_mode(value, list(self._path)))
        return self._block_mode

    def _inline(self, value: object) -> str:
        if isinstance(value, Entity):
            self._enter(value)
            res = self._chain(value) if value.value == CHAIN else self._entity(value)
            self._leave()
            return res

        entries = self._entries(value)
        if entries is None:
            return self._scalar(value)
        brackets = "[]" if isinstance(value, list | tuple) else "{}"
        return brackets[0] + self._items(value) + brackets[1]

    def _entity(self, entity: Entity, link: bool = False) -> str:
        head = self._inline(entity.value)
        if isinstance(entity.value, Entity):
            raise self._error("the value of an entity cannot be an entity or a chain")
        if link and head[:1] in ("'", '"', "[", "{"):
            raise self._error(
                "a link of a chain after the first needs a head written as a literal"
            )
        return head + "(" + self._items(entity.attributes) + ")"

    def _chain(self, chain: Entity) -> str:
        links = chain.attributes
        if (
            not isinstance(links, list)
            or len(links) < 2
            or not all(
                isinstance(link, Entity) and link.value != CHAIN for link in links
            )
        ):
            raise self._error("a chain must hold a list of two or more entities")
        res = []
        for i, link in enumerate(links):
            assert isinstance(link, Entity)
            self._enter(link)
            res.append(self._entity(link, link=i > 0))
            self._leave()
        return "".join(res)

    def _items(self, container: object) -> str:
        entries = self._entries(container)
        if entries is None:
            raise self._error("attributes must be a list or a dict")
        self._enter(container, array=True)
        res = []
        for key, value, hidden in _with_hidden_keys(entries):
            self._path.append(key)
            res.append(("" if hidden else self._key(key) + ": ") + self._inline(value))
            self._path.pop()
        self._leave(array=True)
        return ", ".join(res)

    def _key(self, key: str) -> str:
        return key if is_integer_key(key) else self._string(key)

    def _scalar(self, value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return int_text(value)
        if isinstance(value, float):
            res = format_float(value)
            if res is None:
                raise NeonError("INF and NAN cannot be encoded to NEON")
            return res
        if isinstance(value, str):
            if re.search(r"[\ud800-\udfff]", value):
                raise self._error("a string with a lone surrogate")
            return self._string(value)
        if isinstance(value, Date):
            return str(value)
        if isinstance(value, date):
            try:
                return str(Date.from_datetime(value))
            except ValueError:
                raise self._error("a date whose offset has seconds") from None
        raise self._error(f"an instance of {type(value).__name__} cannot be encoded")

    def _string(self, s: str) -> str:
        if "\n" in s:
            return self._multiline(s)
        if not needs_quotes(s):
            return s
        if CONTROL_CHARACTERS.search(s):
            return json_string(s)
        return "'" + s.replace("'", "''") + "'"

    def _multiline(self, s: str) -> str:
        delimiter = "'''"
        content = s
        first_line = s.lstrip("\n").split("\n", 1)[0]
        if (
            self._double_quoted
            or CONTROL_CHARACTERS.search(s)
            or re.search(r"(?:^|\n)[\t ]*'''", s)
            or first_line[:1] in ("\t", " ")
        ):
            delimiter = '"""'
            content = re.sub(r"\\([nt\"])", _unescape_readable, json_string(s)[1:-1])
            content = content.replace('"""', '""\\"')
            content = re.sub(r"\A(\n*)([\t ]+)", _escape_indentation, content)
        return delimiter + "\n" + _indent(content, self._indentation) + "\n" + delimiter

    def _entries(self, value: object) -> _Entries | None:
        """Entries of a list, a tuple or a mapping; None for anything else."""
        if isinstance(value, list | tuple):
            return [(str(i), v) for i, v in enumerate(value)]
        if not isinstance(value, Mapping):
            return None
        res: _Entries = []
        keys: set[str] = set()
        for key, v in value.items():
            if isinstance(key, bool) or not isinstance(key, str | int):
                raise self._error("a key of a dict must be a string or an integer")
            text = key if isinstance(key, str) else int_text(key)
            if text in keys:
                raise self._error(f"the keys of a dict give the key '{text}' twice")
            keys.add(text)
            res.append((text, v))
        return res

    def _enter(self, container: object, array: bool = False) -> None:
        """Goes into a container, an array being one level of nesting."""
        if id(container) in self._stack:
            raise self._error("a cycle cannot be encoded")
        if array and self._arrays >= MAX_DEPTH:
            raise self._error(f"arrays nested deeper than {MAX_DEPTH} levels")
        self._stack.append(id(container))
        self._arrays += array

    def _leave(self, array: bool = False) -> None:
        self._stack.pop()
        self._arrays -= array

    def _error(self, reason: str) -> NeonError:
        at = f" at {'.'.join(self._path)}" if self._path else ""
        return NeonError(f"Cannot encode: {reason}{at}")


def _with_hidden_keys(entries: _Entries) -> list[tuple[str, object, bool]]:
    """Marks the keys that decoding would assign anyway."""
    counter = 0
    hiding = True
    res = []
    for key, value in entries:
        integer = is_integer_key(key)
        hidden = hiding and integer and int(key) == counter
        if integer and hiding:
            k = int(key)
            hiding = k == counter
            counter = max(k + 1, counter)
        res.append((key, value, hidden))
    return res


_RESERVED_WORDS = re.compile(r"true|false|yes|no|on|off|null", re.IGNORECASE)
_NUMBER_START = re.compile(r"[+\-.]?[0-9]")


def needs_quotes(s: str) -> bool:
    """Whether the string has to be quoted."""
    token = Scanner(s).next()
    return (
        token is None
        or token.kind != TokenKind.LITERAL
        or token.end != len(s)
        or bool(re.search(r"[\x00-\x1f]", s))
        or bool(_NUMBER_START.match(s))
        or bool(_RESERVED_WORDS.fullmatch(s))
        or evaluate_literal(s) != s
    )


def json_string(s: str) -> str:
    return (
        json.dumps(s, ensure_ascii=False)
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _unescape_readable(m: re.Match[str]) -> str:
    return {"n": "\n", "t": "\t", '"': '"'}[m[1]]


def _escape_indentation(m: re.Match[str]) -> str:
    return m[1] + m[2].replace(" ", "\\u0020").replace("\t", "\\t")


def format_float(f: float) -> str | None:
    """Shortest round-trip digits, positional for exponents -4 to 16; None for INF and NAN."""
    if not math.isfinite(f):
        return None
    if f == 0:
        return "-0.0" if math.copysign(1, f) < 0 else "0.0"

    _, digit_tuple, exponent = Decimal(repr(abs(f))).as_tuple()
    assert isinstance(exponent, int)
    digits = "".join(map(str, digit_tuple))
    e = exponent + len(digits) - 1
    sign = "-" if f < 0 else ""
    if -4 <= e < 17:
        if e < 0:
            return sign + "0." + "0" * (-e - 1) + digits
        whole = digits[: e + 1].ljust(e + 1, "0")
        return sign + whole + "." + (digits[e + 1 :] or "0")
    mantissa = digits[0] + "." + (digits[1:] or "0")
    return f"{sign}{mantissa}e{'-' if e < 0 else '+'}{abs(e)}"


def _indent(text: str, indentation: str) -> str:
    """Prefixes every non-empty line."""
    return "\n".join(indentation + line if line else line for line in text.split("\n"))
