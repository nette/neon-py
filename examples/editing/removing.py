"""
Removing items: an item goes with the comments that describe it, a section heading
separated by a blank line stays, and removing the last item leaves an empty collection,
or nothing.

Usage: uv run python examples/editing/removing.py
"""

from difflib import ndiff
from textwrap import dedent

from neon import CommentPolicy, DocumentNode, parse

text = dedent("""\
    # --- Database ---

    database:
    \thost: localhost
    \t# legacy, will be removed
    \tdriver: mysql   # see #123
    \tuser: root

    # --- Mail ---
    mail:
    \tsmtp: true
    queue:
    \t- send
""")


def print_diff(doc: DocumentNode) -> None:
    for line in ndiff(text.splitlines(), doc.print().splitlines()):
        if line[0] in "-+":
            print(line)


# the comment above `driver` and the one after it describe the key, so they go with it
doc = parse(text)
doc.remove_item(["database", "driver"])
print_diff(doc)

# a heading right above the first key of a section belongs to that key ...
print()
doc = parse(text)
doc.remove_item(["mail"])
print_diff(doc)

# ... unless you ask to keep it above the next item
print()
doc = parse(text)
doc.remove_item(["mail"], comments=CommentPolicy.MOVE_TO_NEXT_TOKEN)
print_diff(doc)

# the last item: the collection stays, empty; where empty means nothing, mark it nullable
print()
doc = parse(text)
doc.remove_item(["queue", 0])
mail = doc.find_item(["mail"])
assert mail
mail.nullable = True
doc.remove_item(["mail", "smtp"])
print_diff(doc)
