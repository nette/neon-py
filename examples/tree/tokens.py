"""
Tokens and trivia: every character of the file is in a token or in the trivia around it,
and a line ends in the trailing trivia of the last token on it.

Usage: uv run python examples/tree/tokens.py
"""

import json
from collections.abc import Iterable

from neon import Trivia, dump, parse, tokenize


def show(trivia: Iterable[Trivia]) -> str:
    return ", ".join(f"{t.kind} {json.dumps(t.text)}" for t in trivia)


for token in tokenize("# header\nkey: value # note\n"):
    print(
        f"{token.kind:<10} {json.dumps(token.text):<8}",
        f"leading [{show(token.leading_trivia)}]",
        f"trailing [{show(token.trailing_trivia)}]",
    )

print()
print(dump(parse("a: [1, 2] # two\n")))
