# NEON for AI agents

An agent that edits configuration files should learn about a broken file the moment it breaks
it, not when the application fails to start. This guide sets that up with `neon-lint`, and shows
how an agent should edit NEON from a Python script when it has to.

`neon-lint` has the same output and exit codes in every implementation of NEON. In a Python
project, use this one; in any other, the JavaScript package `@nette/neon` has a ready hook for
Claude Code in its guide.


## 1. Run the linter

```shell
uv add --dev nette-neon
uv run neon-lint config/
```

or without installing anything, `uvx --from nette-neon neon-lint config/` (it needs the
network the first time, so a hook should call the installed one).

The output is one line per finding, `<path>:<line>:<column>: <message>`, and the exit code is the
verdict: 0 valid, 1 a finding, 2 a wrong invocation or a failure of the linter itself.


## 2. After every edit

A hook of the agent runs `neon-lint <file>` after each edit of a `.neon` file and hands the
output back to the agent when the exit code is 1, so it fixes the file before it goes on. Treat
any other non-zero code as a failure of the check, shown to the user, so that an unchecked file
never passes for a valid one. Where the agent has no hooks, put the rule into the instructions of
the project:

```markdown
## NEON files

- After every change of a `.neon` file, run `uv run neon-lint <file>`; exit code 0 is the only
  acceptable result. The message says the line and the column.
- Indentation is structure: a tab, or the spaces the file already uses. Never mix them in one block.
```


## 3. Editing NEON from a program

When an agent writes a script that changes configuration, it should edit the tree, not the text
with regular expressions. The tree keeps comments, blank lines, indentation and the style of
values, and every edit leaves a valid file:

```python
from pathlib import Path

from neon import parse_file

path = Path("config/common.neon")
doc = parse_file(path)
doc.set_value(["database", "host"], "db.example.com")
doc.set_value(["extensions", "my"], "App\\DI\\MyExtension")
doc.remove_item(["parameters", "legacyOption"])
path.write_text(doc.print(), encoding="utf-8", newline="")
```

`set_value()` on a path whose last key is missing adds it, a missing key in the middle of the path
is an error (a typo does not create a section), and writing a value that is already there changes
nothing. Write the file with `newline=""`, so that Python does not translate its line endings.
See `examples/editing` for what each operation does to the text.
