# pstack in Codex

pstack skills use Cursor names. In Codex, read this file once per session, then map each Cursor name in a skill with the tables below. `<pstack>` is the dstack repo, `/Users/dawidroch/.t3/projects/dstack`. If a Cursor field has no row, drop it and say so. Never pass a field or value the tool schema rejects. Check the schema of a tool before you use a field this file names, because Codex tool names and fields change between versions.

This file mirrors `<pstack>/docs/harness/claude-code.md`, which comes from upstream pstack. When the two disagree on something harness-neutral, the Claude Code adapter is the upstream source.

## Tools

| Cursor | Codex |
| --- | --- |
| `Task` | `spawn_agent` with the brief as the message, then `wait_agent` (or `wait`) for the result. Run independent agents together and wait on all of them. Close each one with `close_agent` when it is done. When the session has no multi-agent tools, do the subagent's work yourself, in order, and say so once. |
| `AskQuestion` | `request_user_input` if the session offers it. Otherwise ask in plain text and stop until the user answers. |
| Open a todolist | `update_plan`. |
| Run another pstack skill (`/name` or "the **name** skill") | Read `<pstack>/skills/<name>/SKILL.md` and follow it. When you tell the user to type it, write `$<name>` (Codex skill mention) or `/<name>`. |
| `Grep`, `Glob` | `rg` and `rg --files` in the shell. |
| `ReadFile`, `Write`, `StrReplace`, `Delete` | Read with the shell, edit with `apply_patch`. |
| `Shell` | The shell tool. |

## Subagent fields

| Cursor | Codex |
| --- | --- |
| `subagent_type: generalPurpose` | Default `spawn_agent`. |
| `poteto-agent`, `comment-sicko` | Read `<pstack>/agents/<name>.md` and put its body at the top of the brief. Pass an agent type only if the schema lists one with that name. |
| `readonly: true` | Add to the brief: "Read-only: do not edit, create, or delete files." Check `git status` afterward. |
| `readonly: false` | Default. |
| `environment: "cloud"` | Give the worker its own checkout: `git worktree add <path> -b <branch> <base>`, and name the path in the brief. With T3 Code, `delegate_task` with `isolation: "worktree"` does this for you. |
| `environment: "local"` | Omit. |
| `cloud_base_branch: <b>` | Base the worktree on `<b>`. |
| `run_in_background: true` | Omit. Spawned agents already run concurrently until you wait on them. |
| `resume` | `send_input` to the same agent if it is still open. Otherwise spawn a new one and paste the earlier result into its brief. |
| `file_attachments` | List the paths in the brief. |

## Models

| Cursor | Codex |
| --- | --- |
| `gpt-<family>-<effort>`, such as `gpt-6.1-sol-high` | `model: "gpt-6.1-sol"` and `reasoning_effort: "high"` on `spawn_agent`, if its schema has those fields. Otherwise omit them, so the agent runs on the session model, and say so. |
| A `claude-*`, `grok-*`, or other non-OpenAI slug | Through T3 Code's `delegate_task` when available (see `~/.codex/AGENTS.md`). Otherwise omit the model and say so. |
| `auto` or `inherit-parent` | Omit the model. |
| The `pstack-models.mdc` rule | `/Users/dawidroch/.t3/projects/dstack/global/pstack-models.md`. Codex does not load it on its own: read it when a skill needs a role's model. If the file or the role's line is missing, use the skill's default slug. |

## Paths

| Cursor | Codex |
| --- | --- |
| `.cursor/skills/`, `~/.cursor/skills/` | `.agents/skills/`, `~/.agents/skills/` |
| `~/.cursor/plugins/`, `.cursor-plugin/plugin.json` | `~/.codex/plugins/`, `.codex-plugin/plugin.json` |
| `.cursor/rules/*.mdc`, always-applied rules | `AGENTS.md` in the repo, or `~/.codex/AGENTS.md` for user-wide rules. Codex never reads `.mdc` files. |
| `https://github.com/cursor/plugins/blob/main/pstack/<path>` | `<pstack>/<path>` when that file exists. Never fetch it. Give the user the URL when they need a link. |
| Transcripts in `~/.cursor/projects/<slug>/agent-transcripts/` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Each file's first line holds the session metadata, including `cwd`. Read only sessions whose `cwd` is this workspace. The newest such file is the current session. |
| Cursor chat history (`what-did-i-get-done`, `workflow-from-chats`, `recall`) | Codex sessions above, plus Claude Code transcripts in `~/.claude/projects/<slug>/*.jsonl`. The slug is the workspace path with each `/` and `.` changed to `-`. |

## Cursor-only features

Codex has no Cursor Automations, Bugbot, Cursor cloud agents, or Cursor canvases. When a step needs one, put one line in your reply, `Skipped in Codex: <step>. <reason>.`, then go on to the next step. Do not stop, ask, or retry. When a later step needs what the skipped step made, such as a URL or a key, leave a placeholder and name it in the line. For a PR, use `gh`.
