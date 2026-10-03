"""
Inline arrays: an item is added with the separator its neighbours use, on its own line in
an array that spans lines, and the trailing comma stays where it was.

Usage: uv run python examples/editing/inline.py
"""

from difflib import ndiff
from textwrap import dedent

from neon import parse

text = dedent("""\
    roles: [guest, member]
    hosts: [
    \talpha,
    \tbeta,
    ]
    limits: {cpu: 2, memory: 512}
    empty: []
""")

doc = parse(text)
doc.add_item(["roles"], "admin")
doc.add_item(["roles"], "root", position=0)
doc.add_item(["hosts"], "gamma")
doc.set_value(["limits", "disk"], 100)
doc.remove_item(["limits", "cpu"])
doc.add_item(["empty"], "first")

for line in ndiff(text.splitlines(), doc.print().splitlines()):
    if line[0] in "-+":
        print(line)
