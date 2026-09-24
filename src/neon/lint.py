"""The command line linter, `neon-lint`."""

from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, TextIO

from .errors import NeonError
from .lexer import decode_utf8
from .parser import parse
from .position import Cursor

USAGE = """\
Usage: neon-lint [options] <path>...

Checks NEON files; a path is a file, a directory (searched for *.neon) or - for stdin.

Options:
  --check     also verify that printing the parsed tree gives back the file
  --json      print the findings as JSON
  --quiet     print nothing, only set the exit code
  --verbose   print the number of files when all are valid
"""

_OPTIONS = ("--check", "--json", "--quiet", "--verbose", "--help")
_SKIPPED_DIRECTORIES = ("vendor", "node_modules", ".git")


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int | None
    column: int | None
    message: str

    def __str__(self) -> str:
        if self.line is None:
            return f"{self.path}: {self.message}"
        return f"{self.path}:{self.line}:{self.column}: {self.message}"


def main(
    args: list[str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    stdin: BinaryIO | None = None,
) -> int:
    """Runs the linter and returns the exit code."""
    args = sys.argv[1:] if args is None else args
    out = stdout or _utf8(sys.stdout)
    err = stderr or _utf8(sys.stderr)
    options = {arg for arg in args if arg.startswith("--")}
    paths = [arg for arg in args if not arg.startswith("--")]
    unknown = next(
        (option for option in sorted(options) if option not in _OPTIONS), None
    )
    if "--help" in options:
        out.write(USAGE)
        return 0
    if unknown or not paths:
        err.write((f"Unknown option {unknown}\n\n" if unknown else "") + USAGE)
        return 2

    files, findings = _collect(paths)
    if not files and not findings:
        findings.append(Finding(" ".join(paths), None, None, "No file found"))
    for file in files:
        try:
            finding = _lint_file(file, "--check" in options, stdin or sys.stdin.buffer)
        except Exception as e:  # noqa: BLE001 a failed invariant of the tree
            err.write(
                f"Internal error in {file}: {e}\n"
                "Please report it at https://github.com/nette/neon-py/issues\n"
            )
            return 2
        if finding:
            findings.append(finding)

    findings.sort(key=lambda f: f.path)
    if "--quiet" in options:
        pass
    elif "--json" in options:
        out.write(
            json.dumps(
                [asdict(f) for f in findings], ensure_ascii=False, separators=(",", ":")
            )
            + "\n"
        )
    elif findings:
        out.write("".join(f"{f}\n" for f in findings))
    elif "--verbose" in options:
        out.write(f"OK {len(files)} files\n")
    return 1 if findings else 0


def _utf8(stream: TextIO) -> TextIO:
    """UTF-8 with LF on every system, so that no message fails to print and tools read it alike."""
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8", newline="\n")
    return stream


def _read(path: str, stdin: BinaryIO) -> str | Finding:
    """The text of a file, or the finding why it cannot be read."""
    try:
        data = stdin.read() if path == "-" else Path(path).read_bytes()
    except OSError as e:
        return Finding(path, None, None, e.strerror or str(e))
    try:
        return decode_utf8(data)
    except NeonError as e:
        assert e.position
        return Finding(path, e.position.line, e.position.column, e.message)


def _lint_file(path: str, check: bool, stdin: BinaryIO) -> Finding | None:
    text = _read(path, stdin)
    if isinstance(text, Finding):
        return text
    try:
        document = parse(text)
    except NeonError as e:
        if e.position is None:
            raise
        return Finding(path, e.position.line, e.position.column, e.message)
    if check:
        printed = document.print()
        if printed != text:
            i = next(
                (
                    k
                    for k, (a, b) in enumerate(zip(printed, text, strict=False))
                    if a != b
                ),
                min(len(printed), len(text)),
            )
            position = Cursor(text).at(i)
            message = "Printing the tree differs from the file"
            return Finding(path, position.line, position.column, message)
    return None


def _collect(paths: list[str]) -> tuple[list[str], list[Finding]]:
    """
    The files to lint, sorted by path, each once even when two paths name it; a path that
    does not exist, or a directory that cannot be read, is a finding. The recursion does
    not follow links, a path given is followed.
    """
    files: dict[str, str] = {}  # identity of the file => the path shown
    findings: list[Finding] = []

    def add(path: str) -> None:
        identity = path if path == "-" else os.path.normcase(os.path.realpath(path))
        files.setdefault(identity, path)

    def walk(directory: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError as e:
            findings.append(Finding(directory, None, None, e.strerror or str(e)))
            return
        for entry in entries:
            full = (
                directory.rstrip("/\\") + "/" + entry.name
            )  # the same output everywhere
            if (
                entry.is_symlink()
                or entry.name.startswith(".")
                or entry.name in _SKIPPED_DIRECTORIES
            ):
                continue
            if entry.is_dir():
                walk(full)
            elif entry.name.endswith(".neon"):
                add(full)

    for path in paths:
        if path == "-" or os.path.isfile(path):
            add(path)
        elif os.path.isdir(path):
            walk(path)
        else:
            message = (
                "Not a file or a directory" if os.path.exists(path) else "No file found"
            )
            findings.append(Finding(path, None, None, message))
    return sorted(files.values()), findings


if __name__ == "__main__":
    sys.exit(main())
