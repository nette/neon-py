# Parsing: values, the tree, and errors that say where

Two ways in. `decode()` gives you the value, the way `json.loads()` does. `parse()` gives you
the syntax tree, and the tree prints back as exactly the text it came from.

**You will learn:**

- what Python values NEON maps to: `int` of any size, `float`, `Date`, `Entity`, `list`, `dict`
- what an error tells you, and where
- that printing a parsed document gives back every byte of it

```shell
uv run python examples/parsing/decode.py
uv run python examples/parsing/roundtrip.py
```

## Values (decode.py)

```
debug:   True
port:    8080
started: True 2016-06-03 19:00:00 +0200
          Date(year=2016, month=6, day=3, hour=19, minute=0, second=0, fraction=None, offset='+02:00')
hosts:   ['alpha', 'beta']
service: True Entity(value='Mailer', attributes={'0': '@smtp', 'timeout': 30})
big:     12345678901234567890123

Bad indentation Position(line=2, column=3, offset=7)
Bad indentation on line 2 at column 3
```

`yes` is `True` and `0x1F90` is `8080`. A date is a `Date`, the components as written, so a
date without an offset does not silently get the time zone of the machine; `to_datetime()`
turns it into a `datetime`, aware when the date has an offset. `Mailer(@smtp, timeout: 30)`
is an `Entity`, the value and the attributes, which is how the DI container of Nette writes a
service. Integers have any size, as Python's own do.

An error is a `NeonError` with the message and the position, in code points; `str()` joins
them the way the PHP library always did.

## The tree prints back as it was (roundtrip.py)

```
True {'key': 'value'}
True {'tabs': ['a'], 'spaces': [{'b': 1, 'c': 2}]}
True {'no final line ending': ['a', 'b', 'c']}
True {'multiline': 'keeps\n\tits indentation'}
```

A byte order mark, CRLF, tabs in one section and spaces in another, a comment in an odd place,
spaces around commas, no line ending at the end: `parse(text).print() == text` for every input
NEON accepts. That is what makes the editing in the next chapters possible: nothing that is in
the file is lost on the way through the tree.
