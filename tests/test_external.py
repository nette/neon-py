import os
import re
from pathlib import Path

import pytest
from corpus import find_neon_files

from neon import NeonError, parse

# NEON_EXTERNAL_CORPUS lists directories of real-world .neon files, separated by ; or ,
# The parity of values and errors with nette/neon 3.x is checked by tests/differential.py.
DIRECTORIES = [
    d for d in re.split(r"[;,]", os.environ.get("NEON_EXTERNAL_CORPUS", "")) if d
]


@pytest.mark.skipif(not DIRECTORIES, reason="NEON_EXTERNAL_CORPUS is not set")
def test_round_trip_over_the_external_corpus() -> None:
    files = rejected = 0
    for directory in DIRECTORIES:
        for file in find_neon_files(Path(directory)):
            files += 1
            data = file.read_bytes()
            try:
                document = parse(data)
                document.to_value()
            except NeonError:
                rejected += 1
                continue
            assert document.print() == data.decode("utf-8"), file
    assert files > 0
    print(f"{files} files, {rejected} rejected")
