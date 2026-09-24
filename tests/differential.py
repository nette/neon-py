# Compares the outcome of this parser with the outcome of nette/neon 3.4 written by a PHP run as JSON lines,
# either `php-oracle.php outcomes <dir>` (lines with `file`) or `fuzz.php` (lines with `input` and `seed`).
# Usage: uv run python tests/differential.py <outcomes.jsonl>

import json
import sys
from collections import Counter
from pathlib import Path

from typed import equal, to_host

from neon import NeonError, parse

# the deviations the oracle reports, each with what this parser must do instead:
# accept the input, reject it, or either, when 3.x and the specification differ
DEVIATIONS = (
    ("a date without offset", "accepted"),  # 3.x adds the zone of the server
    ("a lone CR", "either"),  # 3.x strips it, the specification reads it as a space
    ("the quoted token is cut", "rejected"),  # 3.x cannot give a code point position
)

INVALID_DATE = object()

same = 0
reasons: Counter[str] = Counter()
differences: list[str] = []

for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line:
        continue
    php = json.loads(line)
    value = None
    try:
        source = php["input"] if "input" in php else Path(php["file"]).read_bytes()
        value = parse(source).to_value()
        actual = "accepted"
    except NeonError as e:
        assert e.position
        actual = f"{e.message}\n{e.position.line}:{e.position.column}\n"

    try:
        expected_value = to_host(php["value"]) if "value" in php else None
    except ValueError:  # 3.x normalizes an invalid date into another one
        expected_value = INVALID_DATE

    reason = None
    if expected_value is INVALID_DATE:
        reason = "an invalid date normalized by 3.x" if actual == "accepted" else None
    elif "deviation" in php:
        known = next((d for d in DEVIATIONS if php["deviation"].startswith(d[0])), None)
        if known and (
            known[1] == "either" or (known[1] == "accepted") == (actual == "accepted")
        ):
            reason = known[0]
    elif (
        actual == "accepted" and equal(value, expected_value)
        if "value" in php
        else actual == php.get("error")
    ):
        same += 1
        continue

    if reason:
        reasons[reason] += 1
    else:
        expected = (
            f"deviation: {php['deviation']}"
            if "deviation" in php
            else php.get("error", "accepted").strip().replace("\n", " @ ")
        )
        where = php.get("file") or f"seed {php.get('seed')} {php['input']!r}"
        got = actual.strip().replace("\n", " @ ")
        differences.append(f"{where}\n  php: {expected}\n  py:  {got}")

print("\n".join(differences[:40]))
print({"same": same, "deviation": sum(reasons.values()), "differs": len(differences)})
print(dict(reasons))
sys.exit(1 if differences else 0)
