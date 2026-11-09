# Global instructions (managed by dstack)

Source: `/Users/dawidroch/.t3/projects/dstack/global/AGENTS.md`, linked as `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. Edit it there.

## pstack harness adapter

pstack skills (`architect`, `poteto-mode`, `principle-*`, and the rest) and the Cursor team-kit skills (`fix-ci`, `review-and-ship`, and the rest) are written for Cursor. Before you follow one of these skills, read the adapter for your harness once per session, and map each Cursor name in the skill with it:

- Claude Code: `/Users/dawidroch/.t3/projects/dstack/docs/harness/claude-code.md`
- Codex: `/Users/dawidroch/.t3/projects/dstack/docs/harness/codex.md`

dstack installs pstack as plain user skills, not as a plugin. That changes three things in either adapter:

- `<pstack>` is the dstack repo, `/Users/dawidroch/.t3/projects/dstack`. It keeps pstack's layout (`skills/`, `agents/`, `docs/`), so resolve a relative link in a skill, such as `../../docs/...`, from `<pstack>/skills/<name>/`, not from `~/.claude/skills` or `~/.agents/skills`. pstack's own README is `<pstack>/docs/pstack-README.md`, not `<pstack>/README.md`.
- Skills and agents have no `pstack:` prefix. The user types `/architect`, not `/pstack:architect`. The subagent types are `poteto-agent` and `comment-sicko`.
- Per-role models live in `/Users/dawidroch/.t3/projects/dstack/global/pstack-models.md`. Claude Code loads it from `~/.claude/rules/`. In Codex, read it when a skill asks for a role's model. `/setup-pstack` writes to that file, so the change reaches both harnesses.

Two overrides apply to both adapters:

- Cross-provider roles. When a role's slug belongs to the other provider (a `gpt-*` slug in Claude Code, a `claude-*` slug in Codex) and T3 Code's `delegate_task` tool is available, run that role through `delegate_task` with that provider and model, and keep the brief self-contained. Without `delegate_task`, follow the adapter: omit the model, so the role runs on the parent model, and say so.
- `/setup-pstack`. Write Cursor-style slugs (`claude-opus-5-5-high`, `gpt-6.1-sol-high`), not `opus high`, so one file serves both harnesses. Count the models of both providers as detected: Claude Code's `Agent` models, and the Codex models in `~/.codex/models_cache.json`.

## New work ships as a merged PR

When I ask for a change in a new thread that starts clean on the default branch, take it all the way to merged:

1. Create a branch and do the work there.
2. Commit, push, and open a PR.
3. Wait for the Codex review from `chatgpt-codex-connector`. It comments with findings, or reacts 👍 when it has none. In T3 Code, wait with `watch_pull_request`.
4. Address each finding: fix it, or reply on the PR saying why not. Push, comment `@codex review`, and wait again.
5. When the latest Codex review has no open findings and every check passes, squash-merge the PR and delete the branch.

If the thread starts on a branch that already has changes, work there and don't merge unless I ask.
