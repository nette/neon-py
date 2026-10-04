NEON for Python
===============

[![PyPI](https://img.shields.io/pypi/v/nette-neon.svg)](https://pypi.org/project/nette-neon/)
[![Tests](https://github.com/nette/neon-py/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/nette/neon-py/actions)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/nette/neon-py/blob/master/license.md)

 <!---->

<h3>

✅ A NEON parser that keeps [every comment and space](#the-tree-nodes-slots-tokens-trivia)<br>
✅ [Edit a configuration file](#format-preserving-editing) and the diff is only your change<br>
✅ [`neon-lint`](#for-editors-and-ai-agents) for editors, CI and AI agents<br>
✅ [No dependencies](#installation), fully typed, Python 3.13+

</h3>

 <!---->

**NEON parser, encoder and lossless editor for Python.** NEON is the human-friendly
configuration format of the Nette framework, a YAML alternative with entities, and the format of
`phpstan.neon`. This library parses it into a concrete syntax tree in which every character of
the file has its place, so printing the tree gives the file back byte for byte:

```python
doc = parse(text)
doc.print() == text   # True, for any input NEON accepts
```

That is what makes editing safe. Change a value, add a key, remove an item, and the rest of the
file stays as its author wrote it:

```python
doc.set_value(["database", "host"], "db.example.com")
```

```
- 	host: localhost   # the server
+ 	host: db.example.com   # the server
```

On that you build scripts that bump a setting in every `phpstan.neon` of a monorepo, installers
that register an extension in `config.neon`, migrations that rename a service, and tools that
read the configuration of a PHP project without running PHP.

The library comes from David Grudl, the author of [Nette](https://nette.org),
[Latte](https://latte.nette.org) and [Tracy](https://tracy.nette.org). NEON has been the
configuration format of Nette since 2011, read by every Nette application, and this
implementation follows the same specification as [nette/neon](https://github.com/nette/neon) for
PHP and [@nette/neon](https://github.com/nette/neon-js) for JavaScript.

 <!---->

NEON in one minute
==================

```neon
# mappings and sequences, indented by tabs or spaces
database:
	host: localhost
	port: 3306

roles: [guest, member, admin]   # inline arrays

# entities: a value with attributes, the way Nette writes services
mailer: App\Mailer(@smtp, timeout: 30)

note: '''
	multiline strings
	without escaping
'''
```

JSON is a subset of NEON. The format is described at [ne-on.org](https://ne-on.org) and in the
[manual](https://doc.nette.org/en/neon/format).

▶ Runnable examples: [examples/edge-cases](examples/edge-cases/)

 <!---->

Format-preserving editing
=========================

Most YAML libraries for Python, like PyYAML, drop comments and formatting when they write a
file. Here keeping them is an invariant, not an effort: every edit changes the tokens it edits,
and the four guarantees of the specification (the file reads back as the same tree, with the
expected value, with the change only where it was made) are checked after every operation of a
large corpus of edits.

```python
from neon import CommentPolicy, parse

doc = parse(text)
doc.set_value(["database", "port"], 3307)          # 0x0CEA stays hexadecimal: 0x0CEB
doc.set_value(["database", "debug"], False)        # yes becomes no, not false
doc.set_value(["timeout"], 30)                     # the same value: no change at all
doc.set_value(["parameters", "admin"], "a@b.cz")   # a new key, indented like its siblings
doc.add_item(["services"], "App\\OrderFacade")     # a new item of a list
doc.remove_item(["database", "driver"])            # with the comment that describes it
doc.remove_item(["mail"], comments=CommentPolicy.MOVE_TO_NEXT_TOKEN)
```

A missing key in the middle of a path is an error, so a typo does not create a new section.
Removing the last item of a collection leaves it empty (`services: []`), because in a
configuration empty and missing often mean different things; an item marked `nullable` loses its
value instead. A refused edit changes nothing at all.

▶ Runnable examples: [examples/editing](examples/editing/), [examples/config-editor](examples/config-editor/)

 <!---->

Installation
============

```shell
uv add nette-neon        # or: pip install nette-neon
```

The package is imported as `neon`. Python 3.13 or newer, fully typed (`py.typed`), no
dependencies.

 <!---->

The tree: nodes, slots, tokens, trivia
======================================

```python
item = doc.find_item(["database", "user"])
item.get_value()                    # 'root'
item.get_trailing_comments()        # the comment on its line
item.value.get_first_token().text   # the text exactly as written
item.get_position()                 # Position(line, column, offset), from the current tree
```

Eight node classes (`DocumentNode`, `BlockArrayNode`, `InlineArrayNode`, `ArrayItemNode`,
`EntityNode`, `EntityChainNode`, `StringNode`, `LiteralNode`) with named slots, tokens with their
trivia (whitespace, line endings, comments), `find()`, `find_ancestor()`, siblings, and
`Traverser` for a walk with replacements.

▶ Runnable examples: [examples/tree](examples/tree/)

 <!---->

Decoding and encoding
=====================

```python
from neon import decode, decode_file, encode

decode("a: [1, 2]")                  # {'a': [1, 2]}
decode_file("phpstan.neon")          # the value of a file
encode({"a": [1, 2]})                # '{a: [1, 2]}'
encode({"a": [1, 2]}, True)          # 'a:\n\t- 1\n\t- 2\n\n'
encode({"a": [1, 2]}, lambda _, path: not path)        # 'a: [1, 2]\n', one level of blocks
encode(config, lambda value, _: not isinstance(value, list))   # lists on one line
```

| NEON | Python |
|---|---|
| `null`, `true`, `yes` ... | `None`, `bool` |
| integer | `int`, of any size |
| float | `float` |
| string | `str` |
| date | `Date` (components and offset as written; `to_datetime()` for a `datetime`) |
| entity, chain | `Entity` |
| list | `list` |
| map | `dict` with string keys, in the order of the file |

The mapping is one-to-one: `1.0` stays a float, a big integer stays exact, `{}` is a `dict` and
`[]` a `list`, and a key keeps its place. `encode()` takes `datetime` and `date` as well.
`decode()` is typed as `json.loads()` is, `Any`; `to_value()` of the tree returns the exact
union `neon.Value`.

▶ Runnable examples: [examples/parsing](examples/parsing/), [examples/encoding](examples/encoding/)

 <!---->

One format, one specification
=============================

The format, the value model, the tree and the semantics of editing are written down in a
language-neutral [specification](https://github.com/nette/neon-specification) with a conformance
corpus, and every implementation runs that corpus in its tests. The values and the error messages
were checked against nette/neon for PHP over 30,000 real-world files and 100,000 generated ones.
The corpus is public; if you write an implementation of NEON for another language, use it.

 <!---->

For editors and AI agents
=========================

```shell
neon-lint config/
```

```
config/local.neon:3:2: Duplicated key 'user'
```

One line per finding, the exit code as the verdict, `--json` for tools; the same command, output
and exit codes as `neon-lint` of the other implementations. Without installing anything:
`uvx --from nette-neon neon-lint config/`.

For **AI agents**, run it after every edit of a `.neon` file and hand a finding back as an error,
so the agent fixes the file before it goes on. See [docs/skills/agents.md](docs/skills/agents.md).

▶ Runnable examples: [examples/linting](examples/linting/)

 <!---->

Limits
======

- No formatter: the library keeps your formatting, it does not impose one.
- No schema or validation of values.
- No error recovery: an invalid file is reported, not partially parsed.
- Positions are computed on request, from the current tree.

 <!---->

Documentation and credits
=========================

The [examples](examples/) are the documentation of the API, each chapter with the real output of
its programs. The format itself is documented in the [Nette manual](https://doc.nette.org/en/neon).

Released under the [MIT license](license.md).
