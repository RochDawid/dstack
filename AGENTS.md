# Working on dstack

Instructions for agents changing this repo. For what dstack is, read `README.md`.

This checkout is live: `~/.claude` and `~/.agents` link into it, and its statusline runs in every Claude Code session. A broken commit on `main` breaks the agent you're running in.

## Rules

- **Keep it small.** dstack is a folder of skills, an install script and a few config files. Don't add tooling, such as sync scripts, lock files or config merging, unless asked. A README step is fine for something done once.
- **Skills live flat in `skills/<name>/`.** Vendored skills are plain copies. Edit them freely, and update the "Vendored at" table in `README.md` when you refresh one from upstream.
- **Keep pstack's layout** (`skills/`, `agents/`, `docs/`) at the repo root. pstack skills link to `../../docs/...`, so moving those folders breaks the links.
- **Keep `global/AGENTS.md` minimal.** It's loaded into every session in both harnesses.
- **Shell only, macOS bash 3.2 compatible.** `install.sh` and `config/statusline.sh` must pass `shellcheck`.
- **Deny rules change in two places:** `permissions.deny` in `config/claude-settings.json` and `config/codex.rules`. Check Codex rules with `codex execpolicy check -r config/codex.rules <command...>`. Codex ignores symlinked rules files, which is why `install.sh` copies that one.
- **Commits** have no attribution trailers.

## Check before you push

```bash
shellcheck install.sh config/statusline.sh
./install.sh   # idempotent; re-run after adding or removing a skill
```

CI runs shellcheck, checks every `SKILL.md` for `name` and `description`, and renders a sample statusline.
