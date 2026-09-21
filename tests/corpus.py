"""The conformance corpus of the specification, loaded strictly."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CORPUS = Path(
    os.environ.get("NEON_CORPUS") or Path(__file__).parent / "neon-spec" / "corpus"
)

SPEC_VERSION = "1.0.0"
"""The version of the specification this implementation follows."""

HOSTS = ("js", "php", "py")

# the input of a case in each category, the groups of required expectations, all allowed ones
CATEGORIES: dict[str, tuple[str, list[list[str]], str]] = {
    "decode": (".neon", [[".json"]], r"\.json"),
    "errors": (".neon", [[".error"]], r"\.error"),
    "encode": (".json", [[".neon", ".error"]], r"\.(?:neon|block\.neon|error)"),
    "cst": (".neon", [[".dump"]], r"\.dump"),
    "roundtrip": (".neon", [[".dump"]], r"\.dump"),
    "mutations": (
        ".neon",
        [[".ops.json"], [".expected.neon"]],
        r"\.(?:ops\.json|expected(?:\.\d+)?\.(?:neon|json))",
    ),
}


@dataclass(frozen=True)
class Case:
    name: str
    base: Path
    meta: dict[str, Any]

    def read(self, ext: str) -> str | None:
        data = self.read_bytes(ext)
        return None if data is None else data.decode("utf-8")

    def read_bytes(self, ext: str) -> bytes | None:
        path = self.base.with_name(self.name + ext)
        return path.read_bytes() if path.exists() else None


def load_cases(category: str, root: Path = CORPUS) -> list[Case]:
    """Cases of a category, found by their input file; anything unknown is a failure."""
    _check_version(root)
    input_ext, required, allowed = CATEGORIES[category]
    directory = root / category
    if not directory.is_dir():
        raise RuntimeError(f"Missing category {directory}; run tests/fetch_spec.py")

    files = sorted(p.name for p in directory.iterdir())
    names = sorted(f[: -len(input_ext)] for f in files if _name(f) + input_ext == f)
    if not names:
        raise RuntimeError(f"Empty category {directory}")
    for file in files:
        name = _name(file)
        ext = file[len(name) :]
        if ext not in (input_ext, ".case.json") and not re.fullmatch(allowed, ext):
            raise RuntimeError(f"Unknown file {directory / file}")
        if name not in names:
            raise RuntimeError(f"An expectation without its input: {directory / file}")

    cases = []
    for name in names:
        base = directory / name
        for group in required:
            if not any(base.with_name(name + ext).exists() for ext in group):
                raise RuntimeError(f"Missing {' or '.join(group)} of {base}")
        meta = _read_meta(base.with_name(name + ".case.json"), category)
        cases.append(Case(name, base, meta))
    return cases


def runs_here(case: Case) -> bool:
    """Whether the case runs in this host."""
    return "py" in case.meta.get("hosts", ["py"])


def _name(file: str) -> str:
    return file.split(".", 1)[0]


def _check_version(root: Path) -> None:
    file = root.parent / "spec" / "VERSION"
    if not file.exists():
        raise RuntimeError(f"Missing {file}; the corpus belongs to the specification.")
    version = file.read_text().strip()
    if version != SPEC_VERSION:
        raise RuntimeError(
            f"The corpus is of specification {version}, this implementation follows"
            f" {SPEC_VERSION}."
        )


def _read_meta(file: Path, category: str) -> dict[str, Any]:
    """The sidecar of a case, checked field by field; an `open` deviation fails the run."""
    if not file.exists():
        return {"schema": 1}
    meta = json.loads(file.read_text(encoding="utf-8"))

    def fail(message: str) -> None:
        raise RuntimeError(f"{message} in {file}")

    known = {"schema", "hosts", "php3", "reason", "indentation", "blockMode"}
    for key in meta:
        if key not in known:
            fail(f"Unknown field '{key}'")
    hosts = meta.get("hosts")
    reason = meta.get("reason")
    indentation = meta.get("indentation")
    block_mode = meta.get("blockMode")
    if meta.get("schema") != 1:
        fail("Unknown schema")
    elif hosts is not None and (
        not isinstance(hosts, list) or not hosts or any(h not in HOSTS for h in hosts)
    ):
        fail("Invalid hosts")
    elif meta.get("php3") == "open":
        fail("An open deviation from nette/neon 3.x")
    elif meta.get("php3") not in (None, "fixed", "host"):
        fail("Invalid php3")
    elif (hosts or "php3" in meta) and not (isinstance(reason, str) and reason.strip()):
        fail("A sidecar without reason")
    elif reason is not None and not isinstance(reason, str):
        fail("Invalid reason")
    elif indentation is not None and (
        not isinstance(indentation, str)
        or not re.fullmatch(r"[\t ]+", indentation)
        or category != "encode"
    ):
        fail("Invalid indentation")
    elif block_mode is not None and (
        not (
            isinstance(block_mode, bool)
            or (isinstance(block_mode, int) and block_mode >= 0)
        )
        or category != "encode"
    ):
        fail("Invalid blockMode")
    return meta


def find_neon_files(directory: Path) -> list[Path]:
    """All .neon files below a directory, for the external corpus."""
    res = []
    for path, dirs, files in os.walk(directory):
        dirs[:] = [
            d for d in dirs if d not in ("vendor", "node_modules") and d[0] != "."
        ]
        res += [Path(path) / f for f in files if f.endswith(".neon")]
    return sorted(res)
