import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from neon.lint import main


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("neon-lint")
    (root / "valid.neon").write_bytes(b"a: 1\n")
    (root / "invalid.neon").write_bytes(b"a: 1\n  b: 2\n")
    (root / "sub").mkdir()
    (root / "sub" / "utf8.neon").write_bytes(b"a: \xc3(")
    for skipped in ("vendor", ".hidden"):
        (root / skipped).mkdir()
        (root / skipped / "skipped.neon").write_bytes(b"{")
    (root / "other.txt").write_bytes(b"{")
    return root


def run(root: Path, *args: str, stdin: bytes = b"") -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    code = main(list(args), out, err, io.BytesIO(stdin))
    shown = out.getvalue().replace(str(root), "<dir>").replace("\\", "/")
    return code, shown, err.getvalue()


def test_valid_files(tree: Path) -> None:
    valid = str(tree / "valid.neon")
    assert run(tree, valid) == (0, "", "")
    assert run(tree, "--verbose", valid) == (0, "OK 1 files\n", "")
    assert run(tree, "--check", valid, valid)[0] == 0


def test_findings_in_a_directory(tree: Path) -> None:
    findings = (
        "<dir>/invalid.neon:2:3: Bad indentation\n"
        "<dir>/sub/utf8.neon:1:4: Invalid UTF-8 sequence.\n"
    )
    assert run(tree, str(tree)) == (1, findings, "")
    assert run(tree, "--quiet", str(tree)) == (1, "", "")
    out = io.StringIO()
    main(["--json", str(tree / "invalid.neon")], out)
    assert json.loads(out.getvalue()) == [
        {
            "path": str(tree / "invalid.neon"),
            "line": 2,
            "column": 3,
            "message": "Bad indentation",
        }
    ]


def test_standard_input(tree: Path) -> None:
    assert run(tree, "-", stdin=b"a: [") == (1, "-:1:5: Unexpected end\n", "")
    assert run(tree, "-", stdin=b"a: 1")[0] == 0


def test_wrong_invocations(tree: Path) -> None:
    assert run(tree)[0] == 2
    assert run(tree, "--bogus", str(tree))[0] == 2
    code, out, err = run(tree, "--dump", "-", stdin=b"a")
    assert (code, out) == (2, "")
    assert "Unknown option --dump" in err
    missing = str(tree / "missing")
    assert run(tree, missing) == (1, "<dir>/missing: No file found\n", "")
    assert run(tree, "--help")[0] == 0


def test_a_missing_path_is_a_finding_whatever_else_is_valid(tree: Path) -> None:
    missing = str(tree / "missing.neon")
    expected = (1, "<dir>/missing.neon: No file found\n", "")
    assert run(tree, missing, "-", stdin=b"a: 1") == expected
    assert run(tree, str(tree / "valid.neon"), missing)[0] == 1


def test_one_file_under_two_paths_is_linted_once(tree: Path) -> None:
    twice = run(
        tree,
        "--verbose",
        str(tree / "valid.neon"),
        str(tree / "sub" / ".." / "valid.neon"),
    )
    assert twice == (0, "OK 1 files\n", "")
    findings = (
        "<dir>/invalid.neon:2:3: Bad indentation\n"
        "<dir>/sub/utf8.neon:1:4: Invalid UTF-8 sequence.\n"
    )
    assert run(tree, str(tree / "sub"), str(tree / "invalid.neon"))[1] == findings


def test_the_output_is_utf8_whatever_the_code_page(tmp_path: Path) -> None:
    (tmp_path / "ž😀.neon").write_bytes(b"{")
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": ""}
    command = [sys.executable, "-m", "neon", str(tmp_path)]
    result = subprocess.run(command, capture_output=True, env=env, check=False)
    assert (result.returncode, result.stderr) == (1, b"")
    assert result.stdout.decode("utf-8").endswith("ž😀.neon:1:2: Unexpected end\n")


def test_check_finds_where_printing_differs(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neon import DocumentNode

    monkeypatch.setattr(DocumentNode, "print", lambda self: "a: 2\n")
    assert run(tree, "--check", str(tree / "valid.neon")) == (
        1,
        "<dir>/valid.neon:1:4: Printing the tree differs from the file\n",
        "",
    )
