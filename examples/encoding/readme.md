# Encoding: from Python values to NEON

`encode()` writes a value the way the PHP library writes it, so a file written by a Python tool
and one written by a PHP one look the same, and both decode back to the value.

**You will learn:**

- how dicts, lists, entities, chains, dates and big integers are written
- the inline and the block mode, and the indentation
- which strings are written without quotes, and why

```shell
uv run python examples/encoding/encode.py
```

## Values, inline and as blocks (encode.py)

```
{database: {dsn: 'mysql:host=localhost', user: root, options: {lazy: true}}, services: [App\Mailer(@smtp, {timeout: 30})], factory: @builder()::create(1), started: 2016-06-03 19:00:00 +0200, limit: 12345678901234567890, ratio: 1.0, note: '''
	first line
	second line
'''}

database:
	dsn: 'mysql:host=localhost'
	user: root
	options:
		lazy: true

services:
	- App\Mailer(@smtp, {timeout: 30})

factory: @builder()::create(1)
started: 2016-06-03 19:00:00 +0200
limit: 12345678901234567890
ratio: 1.0
note: '''
	first line
	second line
'''

database: {dsn: 'mysql:host=localhost', user: root, options: {lazy: true}}
hosts: [alpha, beta]

database:
	dsn: 'mysql:host=localhost'
	user: root
	options:
		lazy: true

hosts: [alpha, beta]

"plain words"  -> plain words
"yes"          -> 'yes'
"On"           -> 'On'
"1.5"          -> '1.5'
"-.5"          -> '-.5'
"2016-06-03"   -> '2016-06-03'
"a: b"         -> 'a: b'
"a#b"          -> a#b
"a #b"         -> 'a #b'
""             -> ''
" padded"      -> ' padded'
"tab\there"    -> 'tab	here'
"bell\u0007"   -> "bell\u0007"
```

The inline mode writes one line, the block mode one item per line, with a blank line after a
nested block; the third argument is the indentation, a tab by default. Which arrays are blocks is
yours to say: a function `block_mode(value, path)` instead of `True` is asked for every array, here
first for the first level only, then for all but lists. An `Entity` is `value(attributes)`, and a
chain, an entity whose value is `CHAIN`, is its links written one after another, as in
`@builder()::create(1)`. A `Date` and a `datetime` are written as their components, without the
fraction of a second; an aware `datetime` with its offset, a naive one as a local date. `1.0`
stays a float, and an integer of any size is written as it is.

A string is written without quotes only when the scanner reads it as a single literal that
evaluates to the same string: so `yes` gets quotes because it is a boolean, `On` because every
spelling of `true`, `false`, `yes`, `no`, `on`, `off` and `null` is quoted, so that no reader takes
it for one, `1.5` and `-.5` because they are numbers, `a: b` and `a #b` because the
colon and the hash would be syntax there, while `a#b` is a plain literal. A string with a control
character is written in double quotes with escapes.
