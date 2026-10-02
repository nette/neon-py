"""
Finding your way in the tree: items by path, nodes by class, the slots of an item, positions.

Usage: uv run python examples/tree/navigate.py
"""

from textwrap import dedent

from neon import ArrayItemNode, EntityNode, StringNode, parse

doc = parse(
    dedent("""\
        database:
        \tdsn: 'mysql:host=localhost'
        \tuser: root   # change me
        services:
        \t- App\\Mailer(@smtp)
        \tcache: App\\Cache(%tempDir%)
    """)
)

# an item by the path of keys, the same keys decode() gives
user = doc.find_item(["database", "user"])
assert user and user.key and user.colon and user.value
print("key:      ", user.get_key_value())
print("value:    ", user.get_value())
print("position: ", user.get_position())
print("comment:  ", [c.get_comment_text() for c in user.get_trailing_comments()])

# the slots of an item, each a node or a token
print(
    "slots:    ",
    type(user.key).__name__,
    repr(user.colon.text),
    type(user.value).__name__,
)

# nodes by class, anywhere below
for entity in doc.find(EntityNode):
    item = entity.find_ancestor(ArrayItemNode)
    assert item
    print(
        "entity:   ", item.get_key_value() or "(no key)", "->", entity.value.to_value()
    )
print("strings:  ", [node.to_value() for node in doc.find(StringNode)])
