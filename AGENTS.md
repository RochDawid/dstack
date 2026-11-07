# Working on dstack

Instructions for agents changing this repo. For what dstack is, read `README.md`.

This checkout is live: `~/.claude` and `~/.codex` link into it, and its guard and statusline run in every session. A broken commit on `main` breaks the agent you're running in.

## Rules

- **Python 3.9, stdlib only.** macOS ships 3.9.6. Use `from __future__ import annotations`; no `match`, no `X | Y` in runtime expressions, no third-party packages.
- **Never run `install` or `uninstall` against the real home in tests or experiments.** Set `DSTACK_HOME` (or `HOME`) to a temp dir. Read-only commands (`status`, `doctor`, `install --dry-run`) are fine.
- **Don't edit `vendor/`.** `sync` overwrites it. To change a vendored skill, copy it into `skills/<name>/`, which overrides it.
- **Keep `global/AGENTS.md` minimal.** It's loaded into every session in both harnesses.
- **Every behavior change gets a test** in `tests/`. Tests run the real scripts in subprocesses.
- **Guard changes need table cases** in `tests/test_guard.py` for both directions: what now blocks, and what must still pass. Write dangerous commands only inside test files; the live guard blocks them in your shell.
- **Commits** have no attribution trailers.

## Check before you push

```bash
bin/dstack test -v              # all suites, bash -n, shellcheck if installed
bin/dstack doctor --repo-only   # lock, vendor/, skill frontmatter, config parse
```

CI runs both on Ubuntu and macOS with Python 3.9 and 3.12.
