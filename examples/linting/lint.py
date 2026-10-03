"""
neon-lint: findings with positions, a verdict in the exit code, JSON for tools. Here it
runs from code over files of a temporary directory; on the command line it is
`uv run neon-lint config/`.

Usage: uv run python examples/linting/lint.py
"""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from neon.lint import main

with TemporaryDirectory() as directory:
    config = Path(directory, "config")
    config.mkdir()
    (config / "common.neon").write_text("database:\n\tdsn: sqlite:db.sqlite\n")
    (config / "local.neon").write_text("database:\n\tuser: root\n\tuser: admin\n")
    (config / "services.neon").write_text("services:\n\t- App\\Mailer(\n")
    os.chdir(directory)

    for args in (
        ["config"],
        ["--json", "config/local.neon"],
        ["--verbose", "config/common.neon"],
    ):
        print("$ neon-lint", " ".join(args))
        print(f"exit code {main(args, sys.stdout, sys.stdout)}\n")

    os.chdir(Path(directory).parent)
