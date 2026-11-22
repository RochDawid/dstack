# pstack model configuration. One line per role. Delete a line to fall back to the skill default.
# `inherit-parent` or `auto` as a value: the role runs on the parent chat model (omit the model). Alias entries in a panel list still count toward its fan-out.
# Slugs are Cursor-style so one file serves both harnesses: each adapter maps `claude-*` and `gpt-*` slugs to its own model fields.
# A slug from the other provider runs through T3 Code's `delegate_task` when that tool exists; otherwise the role inherits the parent model.
# budget: medium (high)
# Owner preference (2026-11-22): coding on Claude Opus 5.5 at medium effort with ultracode (option `ultracode=true`) where the harness supports it; code reviews on gpt-6.2-sol-high.
# Fallback: when the Claude usage limit is hit, run any claude-* coding role on gpt-6.2-sol-high instead and say so.
feature, refactoring: claude-opus-5-5-medium # ultracode on
bug-fix: claude-opus-5-5-medium # ultracode on
perf-issue: claude-opus-5-5-medium # ultracode on
hillclimb: claude-opus-5-5-medium # ultracode on
judgment and prose: claude-opus-5-5-high
hardest tasks: claude-opus-5-5-high
how explorer: gpt-6.2-sol-high
how explainer: claude-opus-5-5-high
why investigators: gpt-6.2-sol-high
why synthesizer: claude-opus-5-5-high
reflect tooling: gpt-6.2-sol-high
reflect judgment, divergent, synthesizer: claude-opus-5-5-high
arena runners: claude-opus-5-5-high, gpt-6.2-sol-high
arena cross-judge pool: claude-opus-5-5-high, gpt-6.2-sol-high
swarm workers: claude-opus-5-5-medium # ultracode on
architect runners: claude-opus-5-5-high, gpt-6.2-sol-high
interrogate reviewers: gpt-6.2-sol-high
code review: gpt-6.2-sol-high
