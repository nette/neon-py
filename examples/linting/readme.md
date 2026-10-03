# Linting: a verdict for editors, CI and AI agents

`neon-lint` checks NEON files and says what is wrong and where, in a form both people and
machines read. It is the same command in every implementation of NEON, with the same output and
the same exit codes, so a hook written for one works with the others.

**You will learn:**

- the output, `<path>:<line>:<column>: <message>`, and the exit code that decides
- `--json` for tools, `--verbose` for people

```shell
uv run python examples/linting/lint.py
```

## Running it (lint.py)

```
$ neon-lint config
config/local.neon:3:2: Duplicated key 'user'
config/services.neon:3:1: Unexpected end
exit code 1

$ neon-lint --json config/local.neon
[{"path":"config/local.neon","line":3,"column":2,"message":"Duplicated key 'user'"}]
exit code 1

$ neon-lint --verbose config/common.neon
OK 1 files
exit code 0

```

Exit code 0 means every file is valid, 1 at least one finding (or no file found), 2 a wrong
invocation. A directory is searched for `*.neon`, skipping `vendor`, `node_modules` and hidden
directories. `--check` also verifies that printing the parsed tree gives back the file, which is
the promise of this library. On the command line the same runs as `neon-lint config/` in an
environment where the package is installed, or `uvx --from nette-neon neon-lint config/`.

For an AI agent editing configuration, this is the check to give it: after every edit of a
`.neon` file, run `neon-lint` and hand a finding back as an error. See `docs/skills/agents.md`.
