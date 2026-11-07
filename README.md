<p align="center">
  <img src="assets/icon.svg" width="96" height="96" alt="dstack">
</p>

<h1 align="center">dstack</h1>

<p align="center">
  My skills and agent-harness config, shared by Claude Code and Codex.<br>
  One folder of skills, one install script, settings you apply once.
</p>

---

## Install

```bash
git clone git@github.com:RochDawid/dstack.git ~/.t3/projects/dstack
~/.t3/projects/dstack/install.sh
```

`install.sh` symlinks each skill into `~/.claude/skills/` (Claude Code) and `~/.agents/skills/` (Codex), and links the global instructions and pstack's subagents. It's safe to re-run, and you need to after adding or removing a skill. Editing a skill takes effect immediately because the files are linked, not copied.

`global/AGENTS.md` hardcodes the clone path above, so clone to the same place on every machine or update the paths in that file.

### One-time settings

`install.sh` doesn't touch harness settings. Apply them once per machine:

```bash
# Claude Code: merge config/claude-settings.json into your settings
jq -s '.[0] * .[1]' ~/.claude/settings.json config/claude-settings.json > /tmp/s.json && mv /tmp/s.json ~/.claude/settings.json
```

For Codex, paste `config/codex-config.toml` into `~/.codex/config.toml`.

| | Claude Code | Codex |
| --- | --- | --- |
| Model | `opus[1m]` (Opus 5.5, 1M context) | `gpt-6.1-sol` (500K context) |
| Effort | medium | medium |
| Permissions | `bypassPermissions`, with a `permissions.deny` list | `approval_policy = "never"`, `danger-full-access`, with `config/codex.rules` |
| Statusline | `config/statusline.sh`: model · effort │ dir │ branch* │ #PR │ context bar │ cost | built-in items, the same set |
| Commit attribution | off | none by default |

Both deny lists block force pushes (`--force-with-lease` is allowed), remote branch deletes, `reset --hard`, `clean -f`, `branch -D`, `checkout .` / `restore .`, stash drops, history rewrites, and `rm -rf` on `/`, `~` or `..`. Codex rules only match a command's leading words, so `git push origin --delete x` gets past them. Codex ignores symlinked rules files, so `install.sh` copies `config/codex.rules` to `~/.codex/rules/dstack.rules`. Re-run it after editing the rules.

## Layout

| Path | What it is |
| --- | --- |
| `skills/<name>/` | Every skill, mine and vendored, in one flat folder. |
| `agents/` | pstack's subagents (`poteto-agent`, `comment-sicko`), linked into `~/.claude/agents/`. |
| `docs/harness/` | How pstack's Cursor names map to Claude Code (`claude-code.md`, from upstream) and to Codex (`codex.md`, mine). |
| `docs/guide/`, `docs/pstack-README.md` | pstack's guide and README, which `poteto-help` links to. |
| `global/AGENTS.md` | Global instructions, linked as `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. |
| `global/pstack-models.md` | pstack's per-role models, linked into `~/.claude/rules/`. `/setup-pstack` rewrites it. |
| `config/` | The statusline, the Codex rules, and the one-time settings. |
| `licenses/` | Upstream licenses for the vendored skills. |
| `AGENTS.md`, `CLAUDE.md` | Instructions for agents working on this repo. Not installed globally. |

The repo root keeps pstack's layout (`skills/`, `agents/`, `docs/`), so pstack's relative links, such as `../../docs/guide/...`, resolve without changes.

## Skills

| Source | Skills | Vendored at |
| --- | --- | --- |
| [pstack](https://github.com/cursor/plugins/tree/main/pstack) | All 58. Start rigorous work with `/poteto-mode`; ask `/poteto-help` when unsure. | `2776ddd` |
| [Cursor team kit](https://github.com/cursor/plugins/tree/main/cursor-team-kit) | All 18: `fix-ci`, `loop-on-ci`, `review-and-ship`, `new-branch-and-pr`, `get-pr-comments`, `deslop`, `what-did-i-get-done`, … | `2776ddd` |
| [Matt Pocock](https://github.com/mattpocock/skills) | The spec → ship flow: `grill-me`, `grilling`, `grill-with-docs`, `to-spec`, `to-tickets`, `implement`, `implement-spec`, `wayfinder`, `to-questionnaire`, `setup-matt-pocock-skills`, plus `research` and `prototype`, which `wayfinder` calls. `tdd` and `teach` come from pstack. | `4ae2317` |
| [find-skills](https://github.com/vercel-labs/skills) | `find-skills` | `d3701c1` |

### Adding or updating a skill

- **Your own:** create `skills/<name>/SKILL.md`, then run `install.sh`.
- **From upstream:** copy the skill folder into `skills/`, run `install.sh`, and update the table above.
- **Refreshing upstream:** clone the source and copy its skill folders over the ones in `skills/`. Review the result with `git diff`, keep or revert your local edits, then update the "Vendored at" commit. For example:

  ```bash
  git clone --depth 1 https://github.com/cursor/plugins /tmp/cursor-plugins
  cp -R /tmp/cursor-plugins/pstack/skills/* skills/
  cp -R /tmp/cursor-plugins/pstack/docs/guide docs/
  cp /tmp/cursor-plugins/pstack/docs/harness/claude-code.md docs/harness/
  git diff --stat
  ```
