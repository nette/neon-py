"""
Replacing a value by a structure and back: an empty option becomes a block indented like
the rest of the file, a block becomes a scalar, and an entity of the DI container is edited
inside.

Usage: uv run python examples/editing/structures.py
"""

from difflib import ndiff
from textwrap import dedent

from neon import parse

text = dedent("""\
    application:
        mapping: App\\*Module\\Presenters\\*Presenter

    services:
        mailer: App\\Mailer(@smtp, timeout: 30)

    session:
        expiration: 14 days
        autoStart: true
    includes:
""")

doc = parse(text)
doc.set_value(["includes"], ["services.neon", "local.neon"])
doc.set_value(["application", "mapping"], {"*": "App\\*Module\\**Presenter"})
doc.set_value(["services", "mailer", "timeout"], 60)
doc.set_value(["session"], None)

for line in ndiff(text.splitlines(), doc.print().splitlines()):
    if line[0] in "-+":
        print(line)
