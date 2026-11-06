# pstack model configuration. One line per role. Delete a line to fall back to the skill default.
# `inherit-parent` or `auto` as a value: the role runs on the parent chat model (omit the model). Alias entries in a panel list still count toward its fan-out.
# Slugs are Cursor-style so one file serves both harnesses: each adapter maps `claude-*` and `gpt-*` slugs to its own model fields.
# A slug from the other provider runs through T3 Code's `delegate_task` when that tool exists; otherwise the role inherits the parent model.
# budget: medium (high)
feature, refactoring: gpt-6.1-sol-high
bug-fix: gpt-6.1-sol-high
perf-issue: gpt-6.1-sol-high
hillclimb: gpt-6.1-sol-high
judgment and prose: claude-opus-5-5-high
hardest tasks: claude-opus-5-5-high
how explorer: gpt-6.1-sol-high
how explainer: claude-opus-5-5-high
why investigators: gpt-6.1-sol-high
why synthesizer: claude-opus-5-5-high
reflect tooling: gpt-6.1-sol-high
reflect judgment, divergent, synthesizer: claude-opus-5-5-high
arena runners: claude-opus-5-5-high, gpt-6.1-sol-high
arena cross-judge pool: claude-opus-5-5-high, gpt-6.1-sol-high
swarm workers: gpt-6.1-sol-high
architect runners: claude-opus-5-5-high, gpt-6.1-sol-high
interrogate reviewers: claude-opus-5-5-high, gpt-6.1-sol-high
