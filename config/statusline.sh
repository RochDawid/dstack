#!/usr/bin/env bash
# Claude Code statusline: model · effort │ dir │ branch* │ #PR │ context bar of window │ cost
# Matches the Codex footer items. Runs on every render, so: one jq, one git, gh only in the background.
set -u
IFS=$'\x1f' read -r model effort cwd win pct cost < <(jq -r '[
  .model.display_name // "", .effort.level // "", .workspace.current_dir // .cwd // "",
  (.context_window.context_window_size // 0 | if . >= 1000000 then "\(./1000000|floor)M" elif . > 0 then "\(./1000|floor)K" else "" end),
  (.context_window.used_percentage // "" | if . == "" then . else floor end),
  (.cost.total_cost_usd // "")
] | map(tostring) | join("\u001f")' 2>/dev/null)
cwd=${cwd:-$PWD}
d=$'\e[2m' r=$'\e[0m'; sep=" ${d}│${r} "
out=$'\e[36m'"${model}${r}${effort:+ ${d}·${r} ${effort}}${sep}${cwd##*/}"

status=$(git -C "$cwd" status --porcelain=v2 --branch --untracked-files=no 2>/dev/null)
branch=$(sed -n 's/^# branch.head //p' <<<"$status")
if [ -n "${branch}" ]; then
  grep -qv '^#' <<<"$status" && branch+="*"
  out+="${sep}"$'\e[35m'"${branch}${r}"
  cache="${TMPDIR:-/tmp}/dstack-pr-$(printf '%s' "$cwd:${branch}" | cksum | cut -d' ' -f1)"
  if [ -z "$(find "$cache" -mmin -5 2>/dev/null)" ]; then  # refresh at most every 5 minutes
    touch "$cache"
    (cd "$cwd" && gh pr view --json number -q .number > "$cache.tmp" 2>/dev/null && mv "$cache.tmp" "$cache") >/dev/null 2>&1 &
  fi
  pr=$(cat "$cache" 2>/dev/null); [ -n "${pr}" ] && out+="${sep}#${pr}"
fi

if [ -n "${pct}" ]; then
  c=$'\e[32m'; [ "${pct}" -ge 50 ] && c=$'\e[33m'; [ "${pct}" -ge 80 ] && c=$'\e[31m'
  bar=""; for i in 1 2 3 4 5 6 7 8 9 10; do [ "$i" -le $((pct / 10)) ] && bar+="▓" || bar+="░"; done
  out+="${sep}${c}${bar} ${pct}%${r}${win:+ ${d}of ${win}${r}}"
fi
[ -n "$cost" ] && out+="${sep}${d}$(printf '$%.2f' "$cost")${r}"
printf '%s' "$out"
