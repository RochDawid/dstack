---
name: full-send
description: Do the task, open a PR, address the Codex review, and merge once it's clean.
disable-model-invocation: true
---

Do the task in the arguments, or the one in the conversation, and take it all the way to merged:

1. If you're on the default branch, create a branch. Otherwise work on the current one.
2. Do the work, commit, push, and open a PR.
3. Wait for the Codex review from `chatgpt-codex-connector`. It comments with findings, or reacts 👍 when it has none. In T3 Code, wait with `watch_pull_request`.
4. Address each finding: fix it, or reply on the PR saying why not. Push, comment `@codex review`, and wait again.
5. When the latest Codex review has no open findings and every check passes, squash-merge the PR and delete the branch.
