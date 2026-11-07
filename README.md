<img src="assets/icon.svg" width="64" height="64" alt="">

# dstack

My skills and agent-harness config, shared by Claude Code and Codex.

## Layout

| Path | What it is |
| --- | --- |
| `dstack.json` | What to vendor: upstream repos, which skills, extra files. |
| `dstack.lock.json` | The upstream commit each source is pinned to. Written by `sync`. |
| `vendor/<source>/` | Vendored upstream skills. Don't edit by hand: changes are lost on the next `sync`. Copy a skill into `skills/` to fork it. |
| `skills/<name>/SKILL.md` | My own skills. A skill here overrides a vendored skill with the same name. |
| `global/AGENTS.md` | Global instructions, linked as `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. |
| `global/pstack-models.md` | pstack's per-role models, linked into `~/.claude/rules/`. Both harnesses read it. |
| `adapters/codex.md` | Maps pstack's Cursor tool and model names to Codex. The Claude Code adapter ships with pstack. |
| `config/claude/` | `settings.json` keys merged into `~/.claude/settings.json`, and the statusline script. |
| `config/codex/` | `config.toml` keys merged into `~/.codex/config.toml`, and `hooks.json`. |
| `config/hooks/guard.sh` | PreToolUse guardrail shared by both harnesses. |

## Commands

```bash
bin/dstack sync [source...]   # pull upstream into vendor/ and update the lock
bin/dstack install            # link skills, agents and instructions, then merge config
bin/dstack status             # what's linked, unmanaged leftovers, upstream drift
```

`install` is idempotent. It never deletes a file it doesn't own: anything it replaces goes to `~/.dstack-backups/<timestamp>/`. Config merges only touch the keys listed in `config/`.

### Updating upstream skills

```bash
bin/dstack sync && git diff --stat vendor/   # review what changed upstream
bin/dstack install && git commit -am "sync upstream skills"
```

### Adding a skill

- Your own: create `skills/<name>/SKILL.md`, then run `bin/dstack install`.
- From upstream: add it to `dstack.json`, then run `sync` and `install`.

## Where things land

| | Claude Code | Codex |
| --- | --- | --- |
| Skills | `~/.claude/skills/<name>` → symlink | `~/.agents/skills/<name>` → symlink |
| Global instructions | `~/.claude/CLAUDE.md` → `global/AGENTS.md` | `~/.codex/AGENTS.md` → `global/AGENTS.md` |
| pstack subagents | `~/.claude/agents/*.md` | Read from `vendor/pstack/agents/` via the adapter |
| Settings | `~/.claude/settings.json` (merged) | `~/.codex/config.toml` (merged) |
| Guard hook | `settings.json` `hooks.PreToolUse` | `~/.codex/hooks.json` |

## Defaults

| | Claude Code | Codex |
| --- | --- | --- |
| Model | `opus[1m]` (Opus 5.5, 1M context) | `gpt-6.1-sol` (500K context) |
| Effort | medium | medium |
| Permissions | `bypassPermissions` + guard hook | `approval_policy = "never"`, `danger-full-access` + guard hook |
| Statusline | model · effort │ dir │ branch* │ #PR │ context bar of window │ cost | the same items, built in |
| Commit attribution | off | none by default |

The guard blocks force pushes (`--force-with-lease` is allowed), `reset --hard`, `clean -f`, `branch -D`, `checkout .`/`restore .`, stash drops, history rewrites, remote branch deletes, and `rm -rf` outside the project or temp dirs. To turn it off for one session, start the agent with `DSTACK_GUARD=off`.

## Skills

- **pstack** (all 58, [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack)): start rigorous work with `/poteto-mode`, and use `/poteto-help` when unsure. `/setup-pstack` re-picks per-role models.
- **Cursor team kit** (18): `fix-ci`, `loop-on-ci`, `review-and-ship`, `new-branch-and-pr`, `get-pr-comments`, `deslop`, `thermo-nuclear-code-quality-review`, `what-did-i-get-done`, and the rest.
- **Matt Pocock** spec → ship flow ([mattpocock/skills](https://github.com/mattpocock/skills)): `grill-me`, `grilling`, `grill-with-docs`, `to-spec`, `to-tickets`, `implement`, `implement-spec`, `wayfinder`, `to-questionnaire`, `setup-matt-pocock-skills`. `research` and `prototype` are included because `wayfinder` calls them. `tdd` and `teach` come from pstack.
- **find-skills** ([vercel-labs/skills](https://github.com/vercel-labs/skills)).
