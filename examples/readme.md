# Examples

Runnable programs, one idea per file, each chapter with a readme that quotes what its programs
print. The samples are imperfect on purpose: comments in odd places, mixed indentation, CRLF.
A tool that survives only tidy input is not a tool.

| chapter | what it shows |
|---|---|
| [parsing](parsing/) | `decode()` into values, `parse()` into the tree and `print()` back byte for byte, errors with positions |
| [tree](tree/) | nodes, slots, tokens and trivia; finding items by path and nodes by class; the dump |
| [editing](editing/) | **the main chapter**: changing, adding and removing values while the rest of the file stays as it was |
| [config-editor](config-editor/) | a form over a configuration file: fields with types and comments, a save whose diff is the change |
| [encoding](encoding/) | `encode()` of Python values, inline and as blocks, and which strings get quotes |
| [edge-cases](edge-cases/) | BOM, CRLF, dash subblocks, multiline strings and the other corners of the format |
| [linting](linting/) | `neon-lint` for editors, CI and AI agents |

Run any of them with `uv run python examples/<chapter>/<file>.py`. `uv run python
examples/verify.py` runs them all and compares their output with the readmes.
