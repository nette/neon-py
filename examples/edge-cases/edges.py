"""
The corners of the format that a tool meets in real files, and what the library does.

Usage: uv run python examples/edge-cases/edges.py
"""

import json

from neon import NeonError, decode, encode, parse


def show(label: str, text: str) -> None:
    try:
        print(f"{label:<26}", json.dumps(decode(text)))
    except NeonError as e:
        print(f"{label:<26}", e)


show("BOM and CRLF", "\ufeffa: 1\r\nb: 2\r\n")
show("dash subblock", "list:\n- a\n- b\nnext: 1")
show("block on a dash, tab", "- a: 1\n\tb: 2")
show("block on a dash, 2 spaces", "- a: 1\n  b: 2")
show("block on a dash, 4 spaces", "- a: 1\n    b: 2")
show("value on the next line", "a:\n\tx")
show("multiline indentation", "a: '''\n\t\tdeeper\n\tshallower\n'''")
show("words that are not bool", "[on, off, tRuE]")
show("implicit keys", "{5: a, b}")

# edits keep what is not edited, the missing final line ending included
doc = parse("a: 1\r\nb: 2")
doc.set_value(["c"], 3)
print("\nadd to CRLF without EOL  ", json.dumps(doc.print()))

# a value whose first line starts with spaces is written so that it reads back the same
value = "  indented first line\nsecond"
print(
    "encode leading spaces    ",
    json.dumps(encode(value)),
    decode(encode(value)) == value,
)
