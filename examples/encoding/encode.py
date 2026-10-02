"""
Encoding Python values as NEON, inline and as blocks, and which strings get quotes.

Usage: uv run python examples/encoding/encode.py
"""

import json
from datetime import datetime, timedelta, timezone

from neon import CHAIN, Entity, encode

database = {"dsn": "mysql:host=localhost", "user": "root", "options": {"lazy": True}}
config = {
    "database": database,
    "services": [Entity("App\\Mailer", ["@smtp", {"timeout": 30}])],
    "factory": Entity(CHAIN, [Entity("@builder", []), Entity("::create", [1])]),
    "started": datetime(2016, 6, 3, 19, 0, 0, 500, timezone(timedelta(hours=2))),
    "limit": 12345678901234567890,
    "ratio": 1.0,
    "note": "first line\nsecond line",
}

print(encode(config))
print()
print(encode(config, True))

# which arrays are blocks: only the first level, or all but lists
print(
    encode({"database": database, "hosts": ["alpha", "beta"]}, lambda _, path: not path)
)
print(
    encode(
        {"database": database, "hosts": ["alpha", "beta"]},
        lambda v, _: not isinstance(v, list),
    )
)

# a string is written without quotes only if it reads back as the same string
words = ["plain words", "yes", "On", "1.5", "-.5", "2016-06-03", "a: b", "a#b", "a #b"]
for value in [*words, "", " padded", "tab\there", "bell\u0007"]:
    print(f"{json.dumps(value):<14} ->", encode(value))
