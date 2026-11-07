#!/usr/bin/env bash
# PreToolUse guardrail shared by Claude Code and Codex. The logic, every rule, and the reason
# for each live in guard.py next to this file; this wrapper only starts it and fails closed.
# Exit 2 + stderr = blocked (the agent sees the reason); exit 0 = allowed.
# Escape hatch: set DSTACK_GUARD=off in the environment that launches the agent.
[ "${DSTACK_GUARD:-on}" = "off" ] && exit 0

fail() {
  echo "dstack guard: $1; blocking to stay safe. Set DSTACK_GUARD=off in the agent's environment to bypass the guard." >&2
  exit 2
}

here=${BASH_SOURCE[0]%/*}
[ "$here" = "${BASH_SOURCE[0]}" ] && here=.
command -v python3 >/dev/null 2>&1 || fail "python3 not found on PATH"

# -I: ignore PYTHON* env vars and user site-packages. -S: skip site import (faster startup).
python3 -I -S "$here/guard.py"
rc=$?
case $rc in 0 | 2) exit "$rc" ;; esac
fail "guard.py exited with status $rc"
