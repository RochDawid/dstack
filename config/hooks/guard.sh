#!/usr/bin/env bash
# PreToolUse guardrail shared by Claude Code and Codex (both send {"tool_input":{"command":...}} on stdin).
# Blocks commands that destroy work or history. Exit 2 + stderr = blocked; the agent sees the reason.
# Escape hatch: run the command yourself, or set DSTACK_GUARD=off in the environment that launches the agent.
[ "${DSTACK_GUARD:-on}" = "off" ] && exit 0
cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$cmd" ] && exit 0

block() { echo "dstack guard blocked this command: $1. Ask the user to run it themselves if it is really intended." >&2; exit 2; }

# Normalize whitespace so `git  push   -f` still matches.
c=$(printf '%s' "$cmd" | tr -s '[:space:]' ' ')

case "$c" in
  *"git push"*" --force"*|*"git push"*" -f "*|*"git push"*" -f"|*"git push"*"+"*:*)
    case "$c" in *"--force-with-lease"*) ;; *) block "force push (use --force-with-lease)";; esac ;;
esac
case "$c" in *"git reset --hard"*) block "git reset --hard discards uncommitted work";; esac
case "$c" in *"git clean -"*f*) block "git clean -f deletes untracked files";; esac
case "$c" in *"git checkout -- ."*|*"git checkout ."*|*"git restore ."*|*"git restore --staged --worktree ."*) block "discarding all working-tree changes";; esac
case "$c" in *"git branch -D"*) block "git branch -D deletes unmerged branches";; esac
case "$c" in *"git stash clear"*|*"git stash drop"*) block "dropping stashes";; esac
case "$c" in *"git filter-branch"*|*"git filter-repo"*) block "history rewrite";; esac
case "$c" in *"git push"*" --delete"*|*"git push"*" :"*) block "deleting a remote branch";; esac

# rm -rf on /, ~, $HOME, .., or absolute paths outside the current project.
if printf '%s' "$c" | grep -Eq '(^|[;&| ])(sudo )?rm (-[a-zA-Z]*[rR][a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*[rR]|-r -f|-f -r|--recursive --force|--force --recursive)( |$)'; then
  for arg in $(printf '%s' "$c" | sed -E 's/.*rm( -[^ ]+)+ //'); do
    case "$arg" in
      /|/*|"~"|"~/"*|'$HOME'*|'${HOME}'*|..|../*|"*"|.)
        case "$arg" in
          "$PWD"/*) ;;  # inside the project: allowed
          /tmp/*|/private/tmp/*|/var/folders/*) ;;
          *) block "rm -rf on $arg (outside the project)";;
        esac ;;
    esac
  done
fi
exit 0
