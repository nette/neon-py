"""
Adding items: a new key gets the indentation of its siblings, a list item its dash, a
missing section is created under the key that exists, and a typo in a path fails instead
of adding a key.

Usage: uv run python examples/editing/adding.py
"""

from difflib import ndiff
from textwrap import dedent

from neon import NeonError, parse

text = dedent("""\
    parameters:
        mail: info@example.com

    services:
    \t- App\\Model\\UserFacade

    extensions:
""")

doc = parse(text)
doc.set_value(["parameters", "admin"], "admin@example.com")
doc.add_item(["services"], "App\\Model\\OrderFacade")
doc.set_value(["extensions", "console"], "Contributte\\Console\\DI\\ConsoleExtension")

for line in ndiff(text.splitlines(), doc.print().splitlines()):
    if line[0] in "-+":
        print(line)

print()
try:
    doc.set_value(["parametres", "admin"], "x")
except NeonError as e:
    print(e)
try:
    doc.set_value(["parameters", "amdin"], "x", create=False)
except NeonError as e:
    print(e)
