"""
The core of a configuration editor: list the options of a file as the fields of a form,
apply what the user changed, and save a file whose diff is exactly those changes.

Usage: uv run python examples/config-editor/editor.py
"""

from collections.abc import Iterator
from difflib import ndiff
from textwrap import dedent

from neon import ArrayNode, Node, PathSegment, parse

file = dedent("""\
    # Application settings
    # (edited by hand and by the admin panel)

    mail:
    \thost: smtp.example.com   # outgoing server
    \tport: 587
    \tsecure: yes

    cache:
    \tenabled: true
    \tttl: 3600   # seconds
    \tpaths: [temp/cache]
""")

doc = parse(file)


# 1. the fields of the form: every scalar with its path, its type and its comment
def fields(node: Node | None, path: list[PathSegment]) -> Iterator[tuple]:
    if not isinstance(node, ArrayNode):
        return
    for i, item in enumerate(node.items):
        key = item.get_key_value()
        item_path = [*path, i if key is None else key]
        if isinstance(item.value, ArrayNode):
            yield from fields(item.value, item_path)
        else:
            comment = " ".join(
                c.get_comment_text() for c in item.get_trailing_comments()
            )
            yield item_path, item.get_value(), comment


for path, value, comment in fields(doc.value, []):
    key = ".".join(map(str, path))
    print(f"{key:<14} {type(value).__name__:<8} {value!s:<18} {comment}".rstrip())

# 2. what the user submitted: all fields, most of them unchanged
submitted = {
    "mail.host": "smtp.example.com",
    "mail.port": 465,
    "mail.secure": True,
    "cache.enabled": False,
    "cache.ttl": 3600,
    "cache.paths.0": "temp/cache",
}

for key, value in submitted.items():
    doc.set_value([int(s) if s.isdigit() else s for s in key.split(".")], value)

# 3. save: only what changed is in the diff
print()
for line in ndiff(file.splitlines(), doc.print().splitlines()):
    if line[0] in "-+":
        print(line)
