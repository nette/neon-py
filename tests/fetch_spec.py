# Checks out the specification with its corpus into tests/neon-spec, at the commit pinned in tests/neon-spec.lock.
# The repository is the one of NEON_SPEC_REPOSITORY, or GitHub. Usage: python tests/fetch_spec.py

import os
import subprocess
from pathlib import Path

here = Path(__file__).parent
target = here / "neon-spec"
commit = (here / "neon-spec.lock").read_text().strip()
repository = (
    os.environ.get("NEON_SPEC_REPOSITORY")
    or "https://github.com/nette/neon-specification.git"
)


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


if not (target / ".git").exists():
    git("init", "--quiet", str(target))
git("-C", str(target), "fetch", "--quiet", repository, commit)
git("-C", str(target), "checkout", "--quiet", "--detach", commit)
