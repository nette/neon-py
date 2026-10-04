# Runs every example a chapter readme names under a heading and compares its output with the first
# plain fenced block under that heading; the Python blocks of the main readme must compile.
# Usage: uv run python examples/verify.py

import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).parent
failures = 0
checked = 0

for directory in sorted(
    p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))
):
    readme = directory / "readme.md"
    if not readme.exists():
        print(f"FAIL {directory.name}: no readme.md")
        failures += 1
        continue

    text = readme.read_text(encoding="utf-8").replace("\r\n", "\n")
    quoted: dict[str, str] = {}
    for m in re.finditer(
        r"^## [^\n]*\((\S+\.py)\)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    ):
        block = re.search(r"^```\n(.*?)^```$", m[2], re.MULTILINE | re.DOTALL)
        if not block:
            print(f"FAIL {directory.name}/{m[1]}: no output block under the heading")
            failures += 1
            continue
        quoted[m[1]] = block[1]

    for script in sorted(directory.glob("*.py")):
        expected = quoted.pop(script.name, None)
        if expected is None:
            print(
                f"FAIL {directory.name}/{script.name}: the readme quotes no output of it"
            )
            failures += 1
            continue
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        actual = result.stdout.replace("\r\n", "\n")
        checked += 1
        if result.returncode or actual != expected:
            print(
                f"FAIL {directory.name}/{script.name}: the output differs from the readme\n"
                f"--- expected\n{expected}--- actual\n{actual}{result.stderr}"
            )
            failures += 1

    for script in quoted:
        print(f"FAIL {directory.name}: the readme names {script}, which does not exist")
        failures += 1

# the Python blocks of the main readme must at least compile
readme = (root.parent / "readme.md").read_text(encoding="utf-8").replace("\r\n", "\n")
for m in re.finditer(r"^```python\n(.*?)^```$", readme, re.MULTILINE | re.DOTALL):
    checked += 1
    try:
        compile(m[1], "readme.md", "exec")
    except SyntaxError as e:
        print(f"FAIL readme.md: {e} in\n{m[1]}")
        failures += 1

print(f"{checked} examples, {failures} failures")
sys.exit(1 if failures else 0)
