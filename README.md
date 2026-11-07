<p align="center">
  <img src="assets/icon.svg" width="96" height="96" alt="dstack">
</p>

<h1 align="center">dstack</h1>

<p align="center">
  One source of truth for Claude Code and Codex: pinned skills, a shared guard hook,<br>
  and config merged without clobbering your own.
</p>

---

Both harnesses read the same skills, the same global instructions and the same safety hook, all from this repo. Upstream skills are vendored at a pinned commit, so updates arrive as a diff you review, not as a surprise. `install` only links and merges what it owns, backs up everything else, and can show you the plan first.

```bash
git clone git@github.com:RochDawid/dstack.git ~/.t3/projects/dstack
cd ~/.t3/projects/dstack
bin/dstack install --dry-run   # see every link, backup and merge it would make
bin/dstack install
bin/dstack doctor              # ✓/✗ health check
```

Requirements: Python 3.9+ (stdlib only), git, jq. `gh` is optional (PR number in the statusline).

## Why it's built this way

| Principle | How |
| --- | --- |
| **One source, two harnesses** | `global/AGENTS.md` is symlinked as both `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. Skills are symlinked into `~/.claude/skills` and `~/.agents/skills`. The same guard script runs as a PreToolUse hook in both. |
| **Reviewable upstream** | `dstack.json` names the sources; `sync` copies them into `vendor/` and pins the commit in `dstack.lock.json`. Updating is `sync` + `git diff`. A failed sync leaves `vendor/` and the lock untouched. |
| **Never clobber** | `install` touches only the keys in `config/`, writes atomically, and moves anything it replaces to `~/.dstack-backups/<timestamp>/`. It only removes links that point into this repo. |
| **Fast, but guarded** | Agents run without permission prompts. The guard parses every shell command and blocks the ones that destroy work (see [Guard](#guard)). |
| **Tested** | Installer, guard and statusline each have an end-to-end test suite, run in CI on Linux and macOS with Python 3.9 and 3.12. |

## Commands

```bash
bin/dstack sync [source...]       # fetch upstream into vendor/ and pin it in the lock
bin/dstack install [--dry-run]    # link skills, agents and instructions; merge config
bin/dstack status [--offline]     # links, config drift, and whether upstream moved
bin/dstack doctor [--repo-only]   # health check; --repo-only skips ~ (used by CI)
bin/dstack test [-v]              # unit tests, bash -n, shellcheck if installed
bin/dstack uninstall [--dry-run]  # remove the links dstack owns; settings stay
```

`status`, `doctor` and `test` exit non-zero when something is wrong, so they can be scripted. Set `DSTACK_HOME` to install into another home directory.

### Updating upstream skills

```bash
bin/dstack sync && git diff --stat vendor/   # review what changed upstream
bin/dstack install && git commit -am "Sync upstream skills"
```

### Adding a skill

- **Your own:** create `skills/<name>/SKILL.md`, then `bin/dstack install`. A skill here overrides a vendored one with the same name, which is also how you fork one.
- **From upstream:** add it to `dstack.json`, then `sync` and `install`.

## Layout

| Path | What it is |
| --- | --- |
| `bin/dstack` | The installer: one stdlib Python file. |
| `dstack.json` | What to vendor: upstream repos, which skills, extra files, which agents to link. |
| `dstack.lock.json` | The commit each source is pinned to. Written by `sync`. |
| `vendor/<source>/` | Vendored upstream. Don't edit by hand; changes are lost on the next `sync`. |
| `skills/<name>/` | Own skills. Override vendored skills with the same name. |
| `global/AGENTS.md` | Global instructions for both harnesses. |
| `global/pstack-models.md` | pstack's per-role models, linked into `~/.claude/rules/`. Both harnesses read it. |
| `adapters/codex.md` | Maps pstack's Cursor tool and model names to Codex. The Claude Code adapter ships with pstack. |
| `config/claude/` | Keys merged into `~/.claude/settings.json`, and the statusline script. |
| `config/codex/` | Keys merged into `~/.codex/config.toml`, and `hooks.json`. |
| `config/hooks/` | The guard: `guard.sh` (entry point) and `guard.py`. |
| `tests/` | `test_dstack.py`, `test_guard.py`, `test_statusline.py`. |
| `assets/` | Logo: `icon.svg`, `mark.svg`, `wordmark.svg`. |

## Where things land

| | Claude Code | Codex |
| --- | --- | --- |
| Skills | `~/.claude/skills/<name>` → symlink | `~/.agents/skills/<name>` → symlink |
| Global instructions | `~/.claude/CLAUDE.md` → `global/AGENTS.md` | `~/.codex/AGENTS.md` → `global/AGENTS.md` |
| pstack subagents | `~/.claude/agents/*.md` | Read from `vendor/pstack/agents/` via the adapter |
| Settings | `~/.claude/settings.json` (merged) | `~/.codex/config.toml` (merged) |
| Guard hook | `settings.json` → `hooks.PreToolUse` | `~/.codex/hooks.json` |

## Defaults

| | Claude Code | Codex |
| --- | --- | --- |
| Model | `opus[1m]` (Opus 5.5, 1M context) | `gpt-6.1-sol` (500K context) |
| Effort | medium | medium |
| Permissions | `bypassPermissions` + guard hook | `approval_policy = "never"`, `danger-full-access` + guard hook |
| Statusline | model · effort │ dir │ branch* │ #PR │ context bar of window │ cost | the same items, built in |
| Commit attribution | off | none by default |

## Guard

`config/hooks/guard.py` runs before every shell command in both harnesses. It doesn't grep the command text: it parses it the way a shell would (quotes, `&&`/`;`/`|`, `$(...)`, heredocs, `bash -c`, `sudo`/`env` prefixes, `cd` within the same line) and judges each command on its arguments. A commit message that mentions `git reset --hard` is just text.

| Blocked | Use instead |
| --- | --- |
| Force push (`-f`, `--force`, `+refspec`, `--mirror`) | `--force-with-lease` |
| Deleting a remote branch (`--delete`, `:branch`) | the GitHub UI, or ask |
| `reset --hard`, `checkout .`, `restore .`, `checkout -f` | `git stash` |
| `clean -f` | `git clean -n` first |
| `branch -D` | `git branch -d` |
| `stash drop` / `stash clear` | keep the stash |
| `filter-branch`, `filter-repo`, `reflog expire`, `gc --prune=now` | ask |
| `rm -r`/`find -delete` outside the project or temp dirs, on the project root, or on a path it can't resolve | an explicit path inside the project |

It fails closed: bad JSON, a missing `python3` or an internal error blocks. The full rule list, with reasons and known limits, is the docstring at the top of `guard.py`. To turn the guard off for one session, start the agent with `DSTACK_GUARD=off`.

## Skills

- **pstack** (all 58, [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack)): start rigorous work with `/poteto-mode`, and use `/poteto-help` when unsure. `/setup-pstack` re-picks per-role models.
- **Cursor team kit** (18): `fix-ci`, `loop-on-ci`, `review-and-ship`, `new-branch-and-pr`, `get-pr-comments`, `deslop`, `thermo-nuclear-code-quality-review`, `what-did-i-get-done`, and the rest.
- **Matt Pocock** spec → ship flow ([mattpocock/skills](https://github.com/mattpocock/skills)): `grill-me`, `grilling`, `grill-with-docs`, `to-spec`, `to-tickets`, `implement`, `implement-spec`, `wayfinder`, `to-questionnaire`, `setup-matt-pocock-skills`. `research` and `prototype` are included because `wayfinder` calls them. `tdd` and `teach` come from pstack.
- **find-skills** ([vercel-labs/skills](https://github.com/vercel-labs/skills)).

## Working on dstack

Agents working in this repo follow [`AGENTS.md`](AGENTS.md). Before a PR: `bin/dstack test -v` and `bin/dstack doctor --repo-only`; CI runs both.
