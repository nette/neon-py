from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import Any

from .nodes import DocumentNode
from .parser import parse


def decode(input: str | bytes) -> Any:
    """Parses NEON and returns its value, typed as json.loads() is; bytes are UTF-8."""
    return parse(input).to_value()


def decode_file(path: str | PathLike[str]) -> Any:
    """Reads a NEON file and returns its value."""
    return decode(Path(path).read_bytes())


def parse_file(path: str | PathLike[str]) -> DocumentNode:
    """Reads a NEON file into the lossless syntax tree."""
    return parse(Path(path).read_bytes())
