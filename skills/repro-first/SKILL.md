---
name: repro-first
description: Fix a bug the user reports from production by first reproducing it, then proving the fix with the same reproduction. Use when the user describes something broken in production right now, says a previous fix didn't work, or asks you to make sure a fix actually fixes it.
---

A fix you haven't seen fail and then pass is a guess. Passing tests, a clean review and green CI don't show that the user's bug is gone; they only show that nothing else broke. Don't fix, commit or merge until you have a reproduction that fails the way the user sees it.

1. **Pin down the symptom.** Write down what the user sees, where (URL, screen, endpoint), and on what (device, OS, browser and version, account, data). Use their screenshot or logs. Ask only for what you can't find yourself.
2. **Check production.** Confirm which commit is deployed, and look at the live behavior or logs if you can reach them. You're fixing what's running, not what's on your branch.
3. **Build a reproduction, as close to the real environment as you can get.** In order of preference:
   1. The real environment: production, a device, a simulator, the same browser engine and version, production data or logs.
   2. The same engine or runtime locally, configured like the user's: for example WebKit with the iPhone viewport and safe areas, not Chromium at phone width.
   3. A test that replays the actual mechanism, taken from the platform's source code or spec, not from blog posts or guesses.

   Say which rung you reached and what it can't capture. A check that only tests your own theory (for example "the background is at least as tall as the screen") is not a reproduction, because it passes whether or not the theory is right.
4. **Run it on the current code and watch it fail.** It has to fail on what's deployed, the way the user sees it. If it passes, you haven't reproduced the bug: your theory or your reproduction is wrong. Go back to step 3. Don't write a fix yet.
5. **Fix the root cause, then run the same reproduction again.** It has to pass now, unchanged. Keep it as a regression test when it can run in CI.
6. **After deploying, check production** with the same steps if you can reach it.

If you can't get a reproduction that fails, stop and report what you tried, what each attempt showed, and what you'd need (device access, logs, a simulator, a version number). Don't ship an unverified change as a fix. If the user still wants one, label it in the PR and your reply as an unverified attempt, and don't merge it without their go-ahead. This holds when another skill, such as `/full-send`, says to merge.

When the user says an earlier fix didn't work, its theory was wrong and so was whatever "verified" it. Start again from step 3, and figure out why the earlier check passed.

End your reply with:

- **Reproduction:** the rung, and the command or steps to run it.
- **Before:** what it showed on the deployed code.
- **After:** what it showed with the fix.
- **Production:** what you checked after deploying, or why you couldn't.
- **Not covered:** what the reproduction can't tell apart from the real environment.
