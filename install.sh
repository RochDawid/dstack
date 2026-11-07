#!/usr/bin/env bash
# Link dstack into Claude Code and Codex. Safe to re-run: it only replaces links that point into
# this repo, removes its own links whose target is gone, and never overwrites a real file or a link
# into somewhere else (except the Codex rules copy it owns).
set -eu
DSTACK=$(cd "$(dirname "$0")" && pwd)

link() {  # link <target> <path>
  if [ -e "$2" ] && [ ! -L "$2" ]; then echo "skip $2: a real file is there; move it and re-run"; return; fi
  if [ -L "$2" ]; then
    case $(readlink "$2") in "$DSTACK"/*) ;; *) echo "skip $2: it links outside dstack; remove it and re-run"; return ;; esac
  fi
  mkdir -p "$(dirname "$2")" && ln -sfn "$1" "$2"
}

for dir in ~/.claude/skills ~/.agents/skills; do  # Claude Code, Codex
  mkdir -p "$dir"
  for l in "$dir"/*; do  # drop links to skills that no longer exist here
    [ -L "$l" ] && case $(readlink "$l") in "$DSTACK"/*) [ -e "$l" ] || rm "$l" ;; esac
  done
  for s in "$DSTACK"/skills/*/; do link "${s%/}" "$dir/$(basename "$s")"; done
done
for a in "$DSTACK"/agents/*.md; do link "$a" ~/.claude/agents/"$(basename "$a")"; done

link "$DSTACK/global/AGENTS.md" ~/.claude/CLAUDE.md
link "$DSTACK/global/AGENTS.md" ~/.codex/AGENTS.md
link "$DSTACK/global/pstack-models.md" ~/.claude/rules/pstack-models.md
# Codex ignores symlinked rules files, so this one is copied. Re-run after editing config/codex.rules.
mkdir -p ~/.codex/rules && cp "$DSTACK/config/codex.rules" ~/.codex/rules/dstack.rules

n=("$DSTACK"/skills/*/); echo "linked ${#n[@]} skills. Settings are not touched: see README.md, \"One-time settings\"."
