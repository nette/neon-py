"""
Changing values: the comment after a value stays, a number keeps its base, a boolean its
word, a string its quotes, and writing a value that is already there changes nothing.

Usage: uv run python examples/editing/values.py
"""

from difflib import ndiff
from textwrap import dedent

from neon import parse

text = dedent("""\
    # database connection
    database:
    \thost: localhost   # the server
    \tport: 0x0CEA
    \tdebug: yes
    \tuser: 'root'
    \tpassword: "s3cret"

    timeout: 30
""")

doc = parse(text)
doc.set_value(["database", "host"], "db.example.com")
doc.set_value(["database", "port"], 3307)
doc.set_value(["database", "debug"], False)
doc.set_value(["database", "user"], "admin")
doc.set_value(["database", "password"], 'it\'s "new"')
doc.set_value(["timeout"], 30)  # the same value: no change at all

for line in ndiff(text.splitlines(), doc.print().splitlines()):
    if line[0] in "-+":
        print(line)
