"""
Parsing into the syntax tree and printing it back: byte for byte, whatever the file is.

Usage: uv run python examples/parsing/roundtrip.py
"""

from neon import parse

files = [
    "﻿# BOM, CRLF, a comment at the end\r\nkey: value # here\r\n",
    "tabs:\n\t- a\nspaces:\n    - b: 1\n      # a comment you would not expect\n      c: 2\n",
    "no final line ending:   [a ,b,c ,]",
    "multiline: '''\n\t  keeps\n\tits indentation\n'''\n\n\n",
]

for text in files:
    document = parse(text)
    print(document.print() == text, document.to_value())
