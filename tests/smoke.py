# Installs the built wheel into a clean environment and uses it as a consumer would: the import, the types
# and the command. Usage: uv run python tests/smoke.py

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from textwrap import dedent

root = Path(__file__).parent.parent

with tempfile.TemporaryDirectory() as temp:
    directory = Path(temp)
    subprocess.run(
        ["uv", "build", "--wheel", "--quiet", "--out-dir", temp], cwd=root, check=True
    )
    wheel = next(directory.glob("*.whl"))
    if "neon/py.typed" not in zipfile.ZipFile(wheel).namelist():
        sys.exit(f"{wheel.name} holds no py.typed")

    venv = directory / "venv"
    subprocess.run(["uv", "venv", "--quiet", str(venv)], check=True)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        ["uv", "pip", "install", "--quiet", "--python", str(python), str(wheel)],
        check=True,
    )

    use = dedent("""\
        from neon import decode, encode, parse
        doc = parse("a: 1 # c\\n")
        doc.set_value(["a"], 2)
        assert doc.print() == "a: 2 # c\\n" and encode(decode("[1]")) == "[1]"
    """)
    subprocess.run([str(python), "-c", use], cwd=temp, check=True)

    (directory / "broken.neon").write_text("a: [")
    command = [str(python), "-m", "neon", "broken.neon"]
    lint = subprocess.run(command, cwd=temp, capture_output=True, check=False)
    if lint.returncode != 1:
        sys.exit(f"neon-lint gave exit code {lint.returncode} for a broken file")
    print(f"{wheel.name}: import, types and neon-lint work in a clean environment")
