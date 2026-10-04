# To My Agents!

It is my fervent wish that this file guide every AI coding agent working with code in this repository.

## Documentation

`docs/internals.md` describes how the library works where the code does not say it: what is
specific to Python, how a refused edit is undone, why the recursion limit is raised. Read it
before changing `parser.py`, `nodes.py` or `editing.py`. `docs/skills/agents.md` is the guide for
users who want `neon-lint` in the loop of their agent.

The format, the value model, the tree and the editing semantics are defined by the
language-neutral specification in `tests/neon-spec/spec/` (checked out by
`python tests/fetch_spec.py` from `nette/neon-specification` at the commit of
`tests/neon-spec.lock`, with the conformance corpus). The specification is the source of truth;
`spec/model.md` is the one home of the names of token kinds, nodes, slots and methods. Do not copy
it here. The code is a port of `@nette/neon` (JavaScript), module by module.

## Project overview

`nette-neon` parses NEON into a lossless concrete syntax tree, prints it back byte for byte,
edits it while keeping comments and formatting, and decodes and encodes values. Python 3.13+,
fully typed, no runtime dependencies.

## Essential commands

```bash
python tests/fetch_spec.py        # the corpus; NEON_SPEC_REPOSITORY=<path> for a local checkout
uv sync                           # the toolchain of uv.lock
uv run pytest -q                  # the corpus and the unit tests
uv run ruff check && uv run ruff format --check
uv run ty check
uv run python examples/verify.py  # the examples print what their readmes quote
uv run python tests/smoke.py      # the built wheel installed into a clean environment
uv run neon-lint --check tests/neon-spec/corpus/roundtrip
NEON_EXTERNAL_CORPUS="/path/a;/path/b" uv run pytest -q   # round trip over real-world .neon files too
FUZZ_SEEDS=100000 uv run pytest -q tests/test_mutation_fuzz.py   # a long run of random edits
uv run python tests/differential.py <outcomes.jsonl>   # against nette/neon 3.4
```

## Conventions

- Strict typing checked by `ty`, the default formatting of `ruff` (4 spaces), PEP 695 generics,
  `from __future__ import annotations` in the modules of the package.
- The names are those of the specification in snake_case (`get_first_token()`, `to_value()`,
  `end_of_file`); a property is a stored value, a method is work. `is` is a keyword, so the query
  is `is_()`.
- Tests are pytest. `tests/test_corpus.py` and `tests/test_mutations.py` walk every category of
  the corpus, one test per case; a runner that skips an unknown field or an empty category is a
  bug. Unit tests cover only what the corpus cannot say (positions, host values, the CLI).
- `examples/` is the documentation of the API: a chapter readme quotes the real output of each
  of its programs, and `examples/verify.py` fails when they differ. An API change shows in the
  examples first.

## Working in this repo

- **The scanner is hand-written** (`scanner.py`) after grammar.md §1; a lone CR is a space in
  every rule. Positions are counted in code points, which is what a `str` is indexed by.
- **A behaviour that differs from nette/neon 3.x is a case of the corpus first**, with its
  classification in the sidecar, then code.
- A change of the corpus is a commit in `nette/neon-specification`; this repository then moves
  `tests/neon-spec.lock` in a commit of its own.
