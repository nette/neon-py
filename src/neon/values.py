import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import Self

type Value = (
    bool | int | float | str | Date | Entity | list[Value] | dict[str, Value] | None
)

CHAIN = "!!chain"
"""The value of an entity that represents a chain; its attributes are the links."""

MAX_DEPTH = 500
"""How deep arrays nest (a block, an inline array and attributes each count as one)."""

INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)


@dataclass(slots=True)
class Entity:
    """The value of an entity, `value(attributes)`; a chain is an entity of CHAIN."""

    value: Value
    attributes: list[Value] | dict[str, Value] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Date:
    """A date as written: components and an offset, or none for a local date."""

    year: int
    month: int
    day: int
    hour: int | None = None
    minute: int | None = None
    second: int | None = None
    fraction: str | None = None
    """Digits of the fraction of a second as written, without the point."""
    offset: str | None = None
    """`+HH:MM` or `-HH:MM`, or None for a local date."""

    def __post_init__(self) -> None:
        if not (
            _in_range(self.year, 0, 9999)
            and _in_range(self.month, 1, 12)
            and _in_range(self.day, 1, _days_in_month(self.year, self.month))
            and self._has_valid_time()
            and (self.fraction is None or _FRACTION.fullmatch(self.fraction))
            and (self.offset is None or _OFFSET.fullmatch(self.offset))
        ):
            raise ValueError("A component of the date is out of range.")

    def _has_valid_time(self) -> bool:
        if self.hour is None:
            rest = (self.minute, self.second, self.fraction, self.offset)
            return rest == (None, None, None, None)
        return (
            _in_range(self.hour, 0, 23)
            and _in_range(self.minute, 0, 59)
            and _in_range(self.second, 0, 59)
        )

    @classmethod
    def parse(cls, text: str) -> Self | None:
        """The date of a literal; None for another text or components of no valid date."""
        m = _DATE.fullmatch(text)
        if not m:
            return None

        year, month, day, hour, minute, second, fraction, utc, sign, hours, minutes = (
            m.groups()
        )
        offset = None
        if utc:
            offset = "+00:00"
        elif sign:
            offset = f"{sign}{hours:0>2}:{minutes or '00'}"

        try:
            return cls(
                int(year),
                int(month),
                int(day),
                _number(hour),
                _number(minute),
                _number(second),
                fraction or None,
                offset,
            )
        except ValueError:
            return None

    @classmethod
    def from_datetime(cls, value: date) -> Self:
        """A date of Python: an aware datetime has an offset, a naive one is local."""
        if not isinstance(value, datetime):
            return cls(value.year, value.month, value.day)

        offset = None
        delta = value.utcoffset()
        if delta is not None:
            minutes, rest = divmod(abs(delta), timedelta(minutes=1))
            if rest:
                raise ValueError("An offset of the date has seconds.")
            sign = "-" if delta < timedelta(0) else "+"
            offset = f"{sign}{minutes // 60:02}:{minutes % 60:02}"
        fraction = f"{value.microsecond:06}".rstrip("0") or None
        return cls(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            fraction,
            offset,
        )

    def to_datetime(self, tz: tzinfo | None = None) -> datetime:
        """
        The date as a datetime, aware with its offset; a local date is naive unless
        given a time zone. The fraction is cut to microseconds, and the year 0, which
        datetime does not have, fails with ValueError.
        """
        if self.offset:
            hours, minutes = int(self.offset[1:3]), int(self.offset[4:6])
            delta = timedelta(hours=hours, minutes=minutes)
            tz = timezone(-delta if self.offset[0] == "-" else delta)
        return datetime(
            self.year,
            self.month,
            self.day,
            self.hour or 0,
            self.minute or 0,
            self.second or 0,
            int((self.fraction or "").ljust(6, "0")[:6]),
            tz,
        )

    def __str__(self) -> str:
        """The date as the encoder writes it, without the fraction of a second."""
        res = f"{self.year:04}-{self.month:02}-{self.day:02}"
        if self.hour is not None:
            res += f" {self.hour:02}:{self.minute:02}:{self.second:02}"
        if self.offset:
            res += " " + self.offset.replace(":", "")
        return res


_DATE = re.compile(
    r"([0-9]{4})-([0-9][0-9]?)-([0-9][0-9]?)"
    r"(?:(?:[Tt]| +)([0-9][0-9]?):([0-9][0-9]):([0-9][0-9])(?:\.([0-9]*))?"
    r" *(?:(Z)|([-+])([0-9][0-9]?)(?::?([0-9][0-9]))?)?)?"
)
_FRACTION = re.compile(r"[0-9]+")
_OFFSET = re.compile(r"[-+](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00)")


def _number(s: str | None) -> int | None:
    return None if s is None else int(s)


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _in_range(n: int | None, low: int, high: int) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and low <= n <= high


_SIMPLE_TYPES: dict[str, bool | None] = {
    "true": True, "True": True, "TRUE": True, "yes": True, "Yes": True, "YES": True,
    "false": False, "False": False, "FALSE": False, "no": False, "No": False, "NO": False,
    "null": None, "Null": None, "NULL": None,
}  # fmt: skip

_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_INTEGER = re.compile(r"[+-]?[0-9]+")
_BASE = re.compile(r"0(?:x[0-9a-fA-F]+|o[0-7]+|b[01]+)")

_LONG = 4000  # digits beyond which int() and str() refuse the conversion


def evaluate_number(text: str) -> int | float | None:
    """A number literal as an int or a float, or None if the text is not a number."""
    if _INTEGER.fullmatch(text):
        return int(text) if len(text) < _LONG else int(Decimal(text))
    if _BASE.fullmatch(text):
        return int(text, 0)
    if _DECIMAL.fullmatch(text):
        return float(text)
    return None


def evaluate_literal(text: str) -> Value:
    """Value of a literal that is not a key."""
    if text in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[text]
    number = evaluate_number(text)
    if number is not None:
        return number
    return Date.parse(text) or text


def int_text(n: int) -> str:
    """Decimal digits of an integer of any size."""
    return str(n) if n.bit_length() < _LONG * 3 else format(Decimal(n), "f")


def literal_key(text: str) -> str:
    """Canonical key of a literal written as a key."""
    number = evaluate_number(text)
    if number is None:
        return text
    if isinstance(number, int):
        return int_text(number)
    return float_key(number)


def float_key(f: float) -> str:
    """A float as PHP converts it to a string: 14 significant digits."""
    if math.isnan(f):
        return "NAN"
    if math.isinf(f):
        return "INF" if f > 0 else "-INF"
    if f == 0:
        return "-0" if math.copysign(1, f) < 0 else "0"

    mantissa, exponent = f"{f:.13e}".split("e")
    e = int(exponent)
    if -4 <= e < 14:
        digits = f"{f:.{13 - e}f}"
        return digits.rstrip("0").rstrip(".") if "." in digits else digits
    m = mantissa.rstrip("0").rstrip(".")
    if "." not in m:
        m += ".0"
    return f"{m}E{'-' if e < 0 else '+'}{abs(e)}"


_INTEGER_KEY = re.compile(r"0|-?[1-9][0-9]{0,18}")


def is_integer_key(key: str) -> bool:
    """Whether a canonical key is what PHP converts to an integer array key."""
    return bool(_INTEGER_KEY.fullmatch(key)) and INT64_MIN <= int(key) <= INT64_MAX


_ESCAPES = {
    "t": "\t", "n": "\n", "r": "\r", "f": "\f", "b": "\b",
    '"': '"', "\\": "\\", "/": "/", "_": "\xa0",
}  # fmt: skip

# the pattern of nette/neon 3.x, case-insensitive, so \U0041 is one sequence too
_ESCAPE = re.compile(
    r"\\(?:ud[89ab][0-9a-f]{2}\\ud[c-f][0-9a-f]{2}|u[0-9a-f]{4}|[^\n])",
    re.IGNORECASE,
)


class EscapeError(Exception):
    """An invalid escape sequence; the parser reports it at the position of the string."""


def evaluate_string(text: str) -> str:
    """Value of a string token. Raises EscapeError for an invalid escape sequence."""
    text = text.replace("\r", "")
    if text.startswith(("'''\n", '"""\n')):
        first = text[3:].lstrip("\n")
        indent = first[: len(first) - len(first.lstrip("\t "))]
        res = text[3:-3]
        if indent:
            res = res.replace("\n" + indent, "\n")
        res = re.sub(r"\n[\t ]*\Z", "", res.removeprefix("\n"))
    else:
        res = text[1:-1]
        if text[0] == "'":
            res = res.replace("''", "'")

    if text[0] == "'":
        return res
    return _ESCAPE.sub(_unescape, res)


def _unescape(m: re.Match[str]) -> str:
    seq = m[0]
    c = seq[1]
    if c in _ESCAPES:
        return _ESCAPES[c]
    if c != "u" or len(seq) < 6:
        raise EscapeError(f"Invalid escaping sequence {seq}")
    if len(seq) == 12:
        if seq[7] != "u":
            raise EscapeError(f"Invalid UTF-8 sequence {seq}")
        high, low = int(seq[2:6], 16), int(seq[8:12], 16)
        return chr(0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00))
    code = int(seq[2:6], 16)
    if 0xD800 <= code <= 0xDFFF:
        raise EscapeError(f"Invalid UTF-8 sequence {seq}")
    return chr(code)
