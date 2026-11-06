#!/usr/bin/env bash
# Claude Code statusline: model · effort │ dir │ branch* │ #PR │ context bar │ cost
# Mirrors the Codex footer: model-with-reasoning, current-dir, git-branch, pull-request-number, context-used, context-window-size.
set -u
in=$(cat)
j() { jq -r "$1 // empty" <<<"$in" 2>/dev/null; }

dim=$'\e[2m' reset=$'\e[0m' cyan=$'\e[36m' green=$'\e[32m' yellow=$'\e[33m' red=$'\e[31m' magenta=$'\e[35m'
sep=" ${dim}│${reset} "

model=$(j '.model.display_name')
effort=$(j '.effort.level')
cwd=$(j '.workspace.current_dir'); [ -z "$cwd" ] && cwd=$(j '.cwd')
size=$(j '.context_window.context_window_size')
used=$(j '.context_window.used_percentage')
cost=$(j '.cost.total_cost_usd')

out="${cyan}${model}${reset}"
[ -n "$effort" ] && out+=" ${dim}·${reset} ${effort}"
out+="${sep}${cwd##*/}"

if branch=$(git -C "$cwd" symbolic-ref --short -q HEAD 2>/dev/null || git -C "$cwd" rev-parse --short HEAD 2>/dev/null); then
  dirty=""; [ -n "$(git -C "$cwd" status --porcelain -uno 2>/dev/null | head -1)" ] && dirty="*"
  out+="${sep}${magenta}${branch}${dirty}${reset}"
  # PR number, cached per repo+branch for 5 minutes so `gh` never blocks a render.
  cache="${TMPDIR:-/tmp}/dstack-statusline-pr-$(printf '%s' "$cwd:$branch" | shasum | cut -c1-12)"
  if [ ! -f "$cache" ] || [ $(( $(date +%s) - $(stat -f %m "$cache") )) -gt 300 ]; then
    : > "$cache"
    ( cd "$cwd" && gh pr view --json number -q .number 2>/dev/null > "$cache.tmp"; mv "$cache.tmp" "$cache" ) >/dev/null 2>&1 &
  fi
  pr=$(cat "$cache" 2>/dev/null)
  [ -n "$pr" ] && out+="${sep}#${pr}"
fi

if [ -n "$used" ]; then
  pct=${used%.*}
  color=$green; [ "$pct" -ge 50 ] && color=$yellow; [ "$pct" -ge 80 ] && color=$red
  filled=$(( pct / 10 )); bar=""
  for i in 0 1 2 3 4 5 6 7 8 9; do [ $i -lt $filled ] && bar+="▓" || bar+="░"; done
  if [ -n "$size" ]; then
    if [ "$size" -ge 1000000 ]; then win="$(( size / 1000000 ))M"; else win="$(( size / 1000 ))K"; fi
    out+="${sep}${color}${bar} ${pct}%${reset} ${dim}of ${win}${reset}"
  else
    out+="${sep}${color}${bar} ${pct}%${reset}"
  fi
fi

[ -n "$cost" ] && out+="${sep}${dim}\$$(printf '%.2f' "$cost")${reset}"
printf '%s' "$out"
