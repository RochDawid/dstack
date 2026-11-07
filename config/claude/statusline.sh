#!/usr/bin/env bash
# Claude Code statusline: model · effort │ dir │ branch* │ #PR │ context bar of window │ cost
# Mirrors the Codex footer: model-with-reasoning, current-dir, git-branch, pull-request-number, context-used, context-window-size.
#
# Claude Code runs this on every render with the session JSON on stdin, so it must stay fast:
# one jq, one git, and no gh in the foreground. Works with bash 3.2 (macOS) and GNU/Linux.
#
#   dir     cwd basename; "project/sub" or "project/…/sub" when cwd is below the project dir.
#   branch  branch name, or the short commit id on a detached HEAD. "*" means tracked changes;
#           untracked files are ignored (--untracked-files=no) to keep big repos cheap.
#   #PR     from `gh pr view`, cached per dir+branch in ${XDG_CACHE_HOME:-~/.cache}/dstack and
#           refreshed in the background every DSTACK_STATUSLINE_PR_TTL seconds (default 300).
#   NO_COLOR=1 turns colors off.
set -u
export LC_ALL=C GIT_OPTIONAL_LOCKS=0

IFS= read -r -d '' in || :

if [ -n "${NO_COLOR:-}" ]; then
  dim='' reset='' cyan='' green='' yellow='' red='' magenta=''
else
  dim=$'\e[2m' reset=$'\e[0m' cyan=$'\e[36m' green=$'\e[32m' yellow=$'\e[33m' red=$'\e[31m' magenta=$'\e[35m'
fi
sep=" ${dim}│${reset} "

# One jq call. Every field is a single line of text with control characters stripped, and numbers
# are formatted here so the shell never does float math. Fields are joined by \x1f (unit separator).
# shellcheck disable=SC2016  # $vars below are jq's, not the shell's.
fields=$(command -v jq >/dev/null 2>&1 && jq -r '
  def s: if type == "string" or type == "number" then tostring | gsub("[\u0000-\u001f\u007f]"; "") else "" end;
  def n: if type == "number" then . elif type == "string" then (tonumber? // null) else null end;
  def dec1: (. * 10 + 0.5 | floor) as $t
    | if $t % 10 == 0 then "\($t / 10)" else "\(($t - $t % 10) / 10).\($t % 10)" end;
  def window: if . == null or . <= 0 then ""
    elif . >= 999500 then "\(. / 1000000 | dec1)M"
    elif . >= 1000 then "\(. / 1000 + 0.5 | floor)K"
    else "\(floor)" end;
  def money: if . == null or . < 0 then ""
    else (. * 100 + 0.5 | floor) as $c
      | ($c % 100) as $f
      | "\(($c - $f) / 100).\(if $f < 10 then "0" else "" end)\($f)" end;
  (.context_window // {}) as $cw
  | [ (.model.display_name | s),
      (.effort.level | s),
      ((.workspace.current_dir | s) as $d | if $d != "" then $d else (.cwd | s) end),
      (.workspace.project_dir | s),
      ($cw.context_window_size | n | window),
      ($cw.used_percentage | n | if . == null then "" else ([([floor, 0] | max), 100] | min | tostring) end),
      (.cost.total_cost_usd | n | money)
    ] | join("\u001f")' <<<"$in" 2>/dev/null)

if [ -z "$fields" ]; then
  # No jq, or input jq cannot parse: still show where we are instead of a blank line.
  why="no jq"; command -v jq >/dev/null 2>&1 && why="bad input"
  printf '%s' "${PWD##*/}${sep}${dim}statusline: ${why}${reset}"
  exit 0
fi

IFS=$'\x1f' read -r model effort cwd project win pct cost <<<"$fields"
[ -n "$cwd" ] || cwd=$PWD

seg=()
if [ -n "$model" ] && [ -n "$effort" ]; then seg+=("${cyan}${model}${reset} ${dim}·${reset} ${effort}")
elif [ -n "$model$effort" ]; then seg+=("${cyan}${model}${reset}${effort}")
fi

dir=${cwd%/}; dir=${dir##*/}; [ -n "$dir" ] || dir=/
project=${project%/}
if [ -n "$project" ] && [ "$cwd" != "$project" ] && [ "${cwd#"$project"/}" != "$cwd" ]; then
  rel=${cwd#"$project"/}
  if [ "$rel" = "$dir" ]; then dir="${project##*/}/$dir"; else dir="${project##*/}/…/$dir"; fi
fi
seg+=("$dir")

# Branch, detached commit and dirtiness from one porcelain v2 call.
branch="" oid="" dirty=""
while IFS= read -r line; do
  case $line in
    '# branch.oid '*) oid=${line#\# branch.oid } ;;
    '# branch.head '*) branch=${line#\# branch.head } ;;
    '#'*) ;;
    *) dirty="*"; break ;;
  esac
done < <(git -C "$cwd" status --porcelain=v2 --branch --untracked-files=no --ignore-submodules=dirty 2>/dev/null)

if [ -n "$branch" ]; then
  detached=""
  if [ "$branch" = "(detached)" ]; then
    detached=1; branch=${oid:0:7}
  fi
  seg+=("${magenta}${branch}${dirty}${reset}")

  if [ -z "$detached" ] && command -v gh >/dev/null 2>&1; then
    # The cache file holds "<epoch> <pr>". A stale entry is re-stamped before gh starts, which keeps
    # other renders from starting a second gh for the same key while this one runs.
    cdir="${XDG_CACHE_HOME:-$HOME/.cache}/dstack"
    [ -d "$cdir" ] || mkdir -p "$cdir" 2>/dev/null
    key=$(printf '%s' "$cwd:$branch" | cksum); key=${key%% *}
    cache="$cdir/statusline-pr-$key"
    ts=0 pr=""
    [ -f "$cache" ] && read -r ts pr < "$cache" 2>/dev/null
    case $ts in ''|*[!0-9]*) ts=0 ;; esac
    now=$(date +%s)
    if [ $(( now - ts )) -ge "${DSTACK_STATUSLINE_PR_TTL:-300}" ]; then
      tmp="$cache.$$"
      if printf '%s %s\n' "$now" "$pr" > "$tmp" 2>/dev/null && mv -f "$tmp" "$cache" 2>/dev/null; then
        (
          cd "$cwd" || exit
          # On failure (offline, auth, rate limit) keep the last known number.
          new=$(gh pr view --json number -q .number 2>/dev/null) && pr=$new
          case $pr in *[!0-9]*) pr="" ;; esac
          printf '%s %s\n' "$(date +%s)" "$pr" > "$tmp" && mv -f "$tmp" "$cache"
        ) </dev/null >/dev/null 2>&1 &
      else
        rm -f "$tmp" 2>/dev/null
      fi
    fi
    case $pr in ''|*[!0-9]*) ;; *) seg+=("#${pr}") ;; esac
  fi
fi

if [ -n "$pct" ]; then
  color=$green; [ "$pct" -ge 50 ] && color=$yellow; [ "$pct" -ge 80 ] && color=$red
  filled=$(( pct / 10 )) bar="" i=0
  while [ "$i" -lt 10 ]; do
    if [ "$i" -lt "$filled" ]; then bar+="▓"; else bar+="░"; fi
    i=$(( i + 1 ))
  done
  s="${color}${bar} ${pct}%${reset}"
  [ -n "$win" ] && s+=" ${dim}of ${win}${reset}"
  seg+=("$s")
fi

[ -n "$cost" ] && seg+=("${dim}\$${cost}${reset}")

out=""
for s in "${seg[@]}"; do
  out+="${out:+$sep}$s"
done
printf '%s' "$out"
