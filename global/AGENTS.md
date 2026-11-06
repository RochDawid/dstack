# Global instructions (managed by dstack)

Source: `/Users/dawidroch/.t3/projects/dstack/global/AGENTS.md`, linked as `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. Edit it there.

## pstack harness adapter

pstack skills (`architect`, `poteto-mode`, `principle-*`, and the rest) and the Cursor team-kit skills (`fix-ci`, `review-and-ship`, and the rest) are written for Cursor. Before you follow one of these skills, read the adapter for your harness once per session, and map each Cursor name in the skill with it:

- Claude Code: `/Users/dawidroch/.t3/projects/dstack/vendor/pstack/docs/harness/claude-code.md`
- Codex: `/Users/dawidroch/.t3/projects/dstack/adapters/codex.md`

dstack installs pstack as plain user skills, not as a plugin. That changes three things in either adapter:

- `<pstack>` is `/Users/dawidroch/.t3/projects/dstack/vendor/pstack`. Resolve a relative link in a pstack skill, such as `../../docs/...`, from `<pstack>/skills/<name>/`, not from `~/.claude/skills` or `~/.agents/skills`.
- Skills and agents have no `pstack:` prefix. The user types `/architect`, not `/pstack:architect`. The subagent types are `poteto-agent` and `comment-sicko`.
- Per-role models live in `/Users/dawidroch/.t3/projects/dstack/global/pstack-models.md`. Claude Code loads it from `~/.claude/rules/`. In Codex, read it when a skill asks for a role's model. `/setup-pstack` writes to that file, so the change reaches both harnesses.

Two overrides apply to both adapters:

- Cross-provider roles. When a role's slug belongs to the other provider (a `gpt-*` slug in Claude Code, a `claude-*` slug in Codex) and T3 Code's `delegate_task` tool is available, run that role through `delegate_task` with that provider and model, and keep the brief self-contained. Without `delegate_task`, follow the adapter: omit the model, so the role runs on the parent model, and say so.
- `/setup-pstack`. Write Cursor-style slugs (`claude-opus-5-5-high`, `gpt-6.1-sol-high`), not `opus high`, so one file serves both harnesses. Count the models of both providers as detected: Claude Code's `Agent` models, and the Codex models in `~/.codex/models_cache.json`.
