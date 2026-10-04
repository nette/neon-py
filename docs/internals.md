# Internals

How `nette-neon` works where it is not obvious from the code. The format, the tree and the
semantics of editing are defined by the specification (`tests/neon-spec/spec/`); the
implementation is a port of `@nette/neon` for JavaScript, module by module, so the two can be
read side by side. This document covers what is specific to this implementation.


## Map

| module | role |
|---|---|
| `scanner.py` | the hand-written scanner of grammar.md §1, `TokenKind`, `TriviaKind` |
| `lexer.py` | tokens with trivia attached by the convention; `decode_utf8()`; `quote()` of messages |
| `token.py` | `Token`, `Trivia`, the setters that keep trivia canonical, neighbours of a token |
| `parser.py` | the parser of nette/neon 3.x ported onto tokens |
| `nodes.py` | node classes, slots, queries, the facade methods of editing |
| `values.py` | evaluation of literals and strings, canonical keys, `Date`, `Entity`, equality |
| `encoder.py` | `encode()`, the one source of how a value is written |
| `builder.py` | nodes from host values: encode, then parse |
| `editing.py` | every mutation (mutations.md) |
| `layout.py` | indentation unit, indentation of an item, line ending |
| `_journal.py` | `atomic()` and `record()`, the undo of a refused edit, per thread and task |
| `facade.py` | `decode()`, `decode_file()`, `parse_file()` |
| `printer.py`, `dumper.py`, `traverser.py`, `lint.py` | as named |


## Parsing

- **The parser is the algorithm of 3.x**, kept parallel to `parser.ts` and to
  `Nette\Neon\Parser`: the error messages and positions come from the order in which it looks
  at tokens. Line endings are trivia, but the stream presents a line break before a token as
  the pseudo-kind `Newline`, consumed once per gap.
- **The block on the line of a dash does not backtrack**: its indentation is a `_PendingIndent`
  decided on the line where the block first compares it.
- **Positions are code points, which is what a Python `str` is indexed by**, so an offset is an
  index into the string and `Cursor` only counts lines.
- **Integers have any size.** `int()` and `str()` refuse more than 4300 digits, so beyond about
  4000 digits `values.py` converts through `Decimal`, which has no such limit.
- **Arrays nest at most 500 levels** (`MAX_DEPTH`), and walking such a tree recursively
  (`to_value()`, `get_tokens()`, `dump()`, the parser itself) takes several frames a level,
  more than the default recursion limit of 1000. Importing the package raises the limit to at
  least 10,000 frames; since Python 3.12 that costs no C stack.


## The tree

- Slots are private attributes behind read-only properties; a slot is written through
  `_adopt()`, which refuses a node with a parent or one that would become its own ancestor. The
  raw writes of the editing code are `_set_slots()`, `_set_items()`, `_set_value()`,
  `_set_entities()`, `_set_leading()` and `_set_trailing()`; the public setters
  (`item.value = node`, `document.value = node`, the trivia setters of a token) are editing
  operations or check the neighbours.
- Lists are tuples, so `items`, `entities` and the trivia of a token can be returned without a
  copy and cannot be changed from outside. Identity matters: `Trivia` is a frozen dataclass and
  two trivia with the same text are equal, so the code that looks for one (`replace_trivia()`,
  the snapshots of the tests) compares with `is`.
- `nodes.py` imports `editing.py` inside its methods, and `token.py` imports `nodes.py` inside
  its functions, because each needs the other; keep the imports there.
- `TokenKind` is a `StrEnum` whose values are the names of the specification, so the dump
  prints them as they are and `token.is_(":")` (a text) is told from
  `token.is_(TokenKind.COLON)` (a kind) by the type.


## Editing

- **A refused edit changes nothing.** The checks that can run first do so, and every public
  mutation runs in `with atomic():`, which collects how to undo each raw write (`record()`) and
  replays them in reverse when the block raises. A new mutation must run in `atomic()`, and a
  new private attribute that an edit writes must `record()` its old value.
- The rest follows `editing.ts` function by function: `replace_node()` and `detach_node()` decide
  by the slot, writing an equal value is a no-op by `values_equal()`, new text comes from
  `encode()` through `Builder`, and every operation that changes an array ends with
  `_keep_keys()` and `_guard_dash_subblocks()`.
- A Python `dict` keeps its order, so a host map is compared with the tree in order, and the
  key of a `dict` may be a `str` or an `int` (never a `bool`).


## Tests

- `tests/test_corpus.py` and `tests/test_mutations.py` run every category of the corpus,
  loaded by the strict validator of `tests/corpus.py`; `tests/test_mutation_fuzz.py` edits the
  documents of the corpus at random against an independent model.
- `tests/differential.py` compares with nette/neon 3.4 over the output of
  `php-oracle.php outcomes` or `fuzz.php` from the specification repository.
- `examples/verify.py` runs the examples and compares their output with the readmes.
