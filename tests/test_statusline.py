"""Tests for config/claude/statusline.sh.

Run from the repo root: python3 -m unittest discover -s tests
Each test runs the real script in a subprocess with a JSON payload on stdin.
"""

import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "config", "claude", "statusline.sh")
BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git")


def comma_locale():
    """A locale whose decimal separator is a comma, or None if none is installed."""
    try:
        names = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.split()
    except OSError:
        return None
    for want in ("de_DE.UTF-8", "de_DE.utf8", "fr_FR.UTF-8", "fr_FR.utf8"):
        if want in names:
            return want
    return None


COMMA_LOCALE = comma_locale()
JQ = shutil.which("jq")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
SEP = " │ "


def strip(s):
    return ANSI.sub("", s)


class StatuslineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="statusline-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = os.path.join(self.tmp, "cache")
        self.plain = os.path.join(self.tmp, "plain")
        os.mkdir(self.plain)
        # A bin dir that holds the stub gh; it comes first on PATH so a real gh is never called.
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        self.gh_log = os.path.join(self.tmp, "gh.log")

    def env(self, **extra):
        env = {
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.tmp,
            "XDG_CACHE_HOME": self.cache,
            "LC_ALL": "C",  # always installed; a missing locale makes bash warn on stderr
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        env.update(extra)
        return env

    def run_raw(self, payload, cwd=None, **env):
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        proc = subprocess.run(
            [BASH, SCRIPT],
            input=payload.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd or self.plain,
            env=self.env(**env),
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr.decode(), "")
        return proc.stdout.decode()

    def run_sl(self, payload, cwd=None, **env):
        return strip(self.run_raw(payload, cwd=cwd, **env))

    def payload(self, cwd=None, **over):
        p = {
            "model": {"display_name": "Opus 5.5"},
            "effort": {"level": "high"},
            "workspace": {"current_dir": cwd or self.plain},
            "context_window": {"context_window_size": 200000, "used_percentage": 42.7},
            "cost": {"total_cost_usd": 1.234},
        }
        p.update(over)
        return p

    # --- git helpers -------------------------------------------------------

    def git(self, repo, *args):
        subprocess.run(
            [GIT, "-C", repo, *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=self.env(
                GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"
            ),
        )

    def make_repo(self):
        repo = os.path.join(self.tmp, "repo")
        os.mkdir(repo)
        self.git(repo, "init", "-q", "-b", "main")
        with open(os.path.join(repo, "a.txt"), "w") as f:
            f.write("a\n")
        self.git(repo, "add", "a.txt")
        self.git(repo, "commit", "-q", "-m", "init")
        return repo

    def stub_gh(self, number="123", delay=0):
        path = os.path.join(self.bin, "gh")
        with open(path, "w") as f:
            f.write(
                "#!/bin/sh\n"
                'echo called >> "{log}"\n'
                "sleep {delay}\n"
                "echo {number}\n".format(log=self.gh_log, delay=delay, number=number)
            )
        os.chmod(path, 0o755)

    def gh_calls(self):
        if not os.path.exists(self.gh_log):
            return 0
        with open(self.gh_log) as f:
            return len(f.read().splitlines())

    def wait_for(self, cond, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.05)
        return cond()


class PayloadTests(StatuslineCase):
    def test_full_payload(self):
        out = self.run_sl(self.payload())
        self.assertEqual(out, "Opus 5.5 · high │ plain │ ▓▓▓▓░░░░░░ 42% of 200K │ $1.23")

    def test_minimal_payload(self):
        out = self.run_sl({"model": {"display_name": "Opus"}})
        # No cwd in the payload: the script falls back to its working directory.
        self.assertEqual(out, "Opus │ plain")

    def test_empty_object(self):
        self.assertEqual(self.run_sl({}), "plain")

    def test_cwd_fallback_field(self):
        out = self.run_sl({"model": {"display_name": "Opus"}, "cwd": "/var/some/where"})
        self.assertEqual(out, "Opus │ where")

    def test_nulls(self):
        p = {
            "model": {"display_name": None},
            "effort": None,
            "workspace": None,
            "cwd": None,
            "context_window": {"context_window_size": None, "used_percentage": None},
            "cost": {"total_cost_usd": None},
        }
        self.assertEqual(self.run_sl(p), "plain")

    def test_missing_window_size(self):
        p = self.payload(context_window={"used_percentage": 10})
        self.assertIn("│ ▓░░░░░░░░░ 10% │", self.run_sl(p))

    def test_over_100_percent_is_clamped(self):
        p = self.payload(context_window={"context_window_size": 200000, "used_percentage": 130.5})
        self.assertIn("▓▓▓▓▓▓▓▓▓▓ 100% of 200K", self.run_sl(p))

    def test_negative_percent_is_clamped(self):
        p = self.payload(context_window={"used_percentage": -4})
        self.assertIn("░░░░░░░░░░ 0%", self.run_sl(p))

    def test_fractional_percent(self):
        p = self.payload(context_window={"context_window_size": 200000, "used_percentage": 79.99})
        self.assertIn("▓▓▓▓▓▓▓░░░ 79% of 200K", self.run_sl(p))

    def test_percent_as_string(self):
        p = self.payload(context_window={"used_percentage": "55.5"})
        self.assertIn("▓▓▓▓▓░░░░░ 55%", self.run_sl(p))

    def test_percent_colors(self):
        for pct, color in ((10, "\x1b[32m"), (50, "\x1b[33m"), (80, "\x1b[31m")):
            raw = self.run_raw(self.payload(context_window={"used_percentage": pct}))
            self.assertIn(color + ("▓" * (pct // 10)), raw)

    def test_window_sizes(self):
        cases = {
            200000: "200K",
            128000: "128K",
            131072: "131K",
            1000000: "1M",
            1500000: "1.5M",
            2000000: "2M",
            999999: "1M",
            500: "500",
        }
        for size, label in cases.items():
            p = self.payload(context_window={"context_window_size": size, "used_percentage": 1})
            self.assertIn("1% of " + label + " ", self.run_sl(p) + " ", size)

    def test_cost_formatting(self):
        cases = {0: "$0.00", 0.005: "$0.01", 1.999: "$2.00", 12.3: "$12.30", 1234.567: "$1234.57", "2.5": "$2.50"}
        for cost, label in cases.items():
            out = self.run_sl(self.payload(cost={"total_cost_usd": cost}))
            self.assertTrue(out.endswith(SEP + label), (cost, out))

    @unittest.skipUnless(COMMA_LOCALE, "no comma-decimal locale installed")
    def test_comma_locale(self):
        loc = COMMA_LOCALE
        out = self.run_sl(self.payload(), LC_ALL=loc, LANG=loc, LC_NUMERIC=loc)
        self.assertEqual(out, "Opus 5.5 · high │ plain │ ▓▓▓▓░░░░░░ 42% of 200K │ $1.23")

    def test_no_color(self):
        raw = self.run_raw(self.payload(), NO_COLOR="1")
        self.assertNotIn("\x1b", raw)
        self.assertEqual(raw, "Opus 5.5 · high │ plain │ ▓▓▓▓░░░░░░ 42% of 200K │ $1.23")

    def test_colors_by_default(self):
        self.assertIn("\x1b[36mOpus 5.5", self.run_raw(self.payload()))

    def test_control_characters_are_stripped(self):
        p = self.payload(model={"display_name": "Op\x1b[31mus\nX\x1fY"})
        raw = self.run_raw(p, NO_COLOR="1")
        self.assertTrue(raw.startswith("Op[31musXY · high │ plain"), raw)

    def test_invalid_json(self):
        self.assertEqual(self.run_sl("not json"), "plain │ statusline: bad input")

    def test_empty_input(self):
        self.assertEqual(self.run_sl(""), "plain │ statusline: bad input")

    def test_subdirectory_of_project(self):
        sub = os.path.join(self.plain, "a")
        deep = os.path.join(sub, "b", "c")
        os.makedirs(deep)
        p = self.payload(cwd=sub)
        p["workspace"]["project_dir"] = self.plain
        self.assertIn("│ plain/a │", self.run_sl(p))
        p = self.payload(cwd=deep)
        p["workspace"]["project_dir"] = self.plain + "/"
        self.assertIn("│ plain/…/c │", self.run_sl(p))
        p = self.payload()
        p["workspace"]["project_dir"] = self.plain
        self.assertIn("│ plain │", self.run_sl(p))

    def test_project_dir_prefix_is_not_a_parent(self):
        other = self.plain + "-other"
        os.mkdir(other)
        p = self.payload(cwd=other)
        p["workspace"]["project_dir"] = self.plain
        self.assertIn("│ plain-other │", self.run_sl(p))

    @unittest.skipUnless(JQ, "jq not installed")
    def test_no_jq_fallback(self):
        # PATH with only the tools the script might need, minus jq.
        nojq = os.path.join(self.tmp, "nojq")
        os.mkdir(nojq)
        for tool in ("git", "date", "cksum", "mkdir", "mv", "rm", "cat"):
            found = shutil.which(tool)
            if found:
                os.symlink(found, os.path.join(nojq, tool))
        out = self.run_raw(self.payload(), PATH=nojq, NO_COLOR="1")
        self.assertEqual(out, "plain │ statusline: no jq")


@unittest.skipUnless(GIT, "git not installed")
class GitTests(StatuslineCase):
    def test_not_a_repo(self):
        out = self.run_sl(self.payload())
        self.assertEqual(out.split(SEP)[1:3], ["plain", "▓▓▓▓░░░░░░ 42% of 200K"])

    def test_clean_repo(self):
        repo = self.make_repo()
        self.assertEqual(self.run_sl(self.payload(cwd=repo)).split(SEP)[1:3], ["repo", "main"])

    def test_dirty_repo(self):
        repo = self.make_repo()
        with open(os.path.join(repo, "a.txt"), "a") as f:
            f.write("more\n")
        self.assertEqual(self.run_sl(self.payload(cwd=repo)).split(SEP)[2], "main*")

    def test_staged_change_is_dirty(self):
        repo = self.make_repo()
        with open(os.path.join(repo, "b.txt"), "w") as f:
            f.write("b\n")
        self.git(repo, "add", "b.txt")
        self.assertEqual(self.run_sl(self.payload(cwd=repo)).split(SEP)[2], "main*")

    def test_untracked_only_is_clean(self):
        repo = self.make_repo()
        with open(os.path.join(repo, "new.txt"), "w") as f:
            f.write("x\n")
        self.assertEqual(self.run_sl(self.payload(cwd=repo)).split(SEP)[2], "main")

    def test_detached_head(self):
        repo = self.make_repo()
        sha = subprocess.check_output([GIT, "-C", repo, "rev-parse", "HEAD"]).decode().strip()
        self.git(repo, "checkout", "-q", "--detach")
        self.stub_gh()
        out = self.run_sl(self.payload(cwd=repo))
        self.assertEqual(out.split(SEP)[2], sha[:7])
        time.sleep(0.3)
        self.assertEqual(self.gh_calls(), 0, "gh must not run on a detached HEAD")

    def test_unborn_branch(self):
        repo = os.path.join(self.tmp, "empty")
        os.mkdir(repo)
        self.git(repo, "init", "-q", "-b", "trunk")
        self.assertEqual(self.run_sl(self.payload(cwd=repo)).split(SEP)[2], "trunk")

    def test_worktree(self):
        repo = self.make_repo()
        wt = os.path.join(self.tmp, "wt-feature")
        self.git(repo, "worktree", "add", "-q", "-b", "feature", wt)
        self.assertEqual(self.run_sl(self.payload(cwd=wt)).split(SEP)[1:3], ["wt-feature", "feature"])

    def test_pr_number_cached_and_not_refetched(self):
        repo = self.make_repo()
        self.stub_gh("4242")
        first = self.run_sl(self.payload(cwd=repo))
        self.assertNotIn("#4242", first)
        self.assertTrue(self.wait_for(lambda: "#4242" in self.run_sl(self.payload(cwd=repo))))
        for _ in range(5):
            self.assertIn("│ main │ #4242 │", self.run_sl(self.payload(cwd=repo)))
        time.sleep(0.2)
        self.assertEqual(self.gh_calls(), 1)
        cache_dir = os.path.join(self.cache, "dstack")
        self.assertTrue(os.path.isdir(cache_dir))
        files = os.listdir(cache_dir)
        self.assertEqual(len(files), 1, files)

    def test_no_second_gh_while_one_runs(self):
        repo = self.make_repo()
        self.stub_gh("7", delay=1)
        for _ in range(5):
            self.run_sl(self.payload(cwd=repo))
        self.assertTrue(self.wait_for(lambda: "#7" in self.run_sl(self.payload(cwd=repo))))
        self.assertEqual(self.gh_calls(), 1)

    def test_pr_refreshes_after_ttl(self):
        repo = self.make_repo()
        self.stub_gh("1")
        self.run_sl(self.payload(cwd=repo), DSTACK_STATUSLINE_PR_TTL="0")
        self.assertTrue(self.wait_for(lambda: self.gh_calls() == 1))
        self.wait_for(lambda: "#1" in self.run_sl(self.payload(cwd=repo)))
        self.run_sl(self.payload(cwd=repo), DSTACK_STATUSLINE_PR_TTL="0")
        self.assertTrue(self.wait_for(lambda: self.gh_calls() >= 2))

    def test_gh_failure_keeps_last_number(self):
        repo = self.make_repo()
        self.stub_gh("55")
        self.run_sl(self.payload(cwd=repo))
        self.assertTrue(self.wait_for(lambda: "#55" in self.run_sl(self.payload(cwd=repo))))
        with open(os.path.join(self.bin, "gh"), "w") as f:
            f.write('#!/bin/sh\necho called >> "{}"\nexit 1\n'.format(self.gh_log))
        self.run_sl(self.payload(cwd=repo), DSTACK_STATUSLINE_PR_TTL="0")
        self.assertTrue(self.wait_for(lambda: self.gh_calls() == 2))
        time.sleep(0.2)
        self.assertIn("#55", self.run_sl(self.payload(cwd=repo)))

    def test_non_numeric_gh_output_is_ignored(self):
        repo = self.make_repo()
        self.stub_gh("'oops; rm'")
        self.run_sl(self.payload(cwd=repo))
        self.assertTrue(self.wait_for(lambda: self.gh_calls() == 1))
        time.sleep(0.2)
        self.assertNotIn("#", self.run_sl(self.payload(cwd=repo)))

    def test_without_gh(self):
        repo = self.make_repo()
        path = os.pathsep.join(
            d for d in os.environ.get("PATH", "").split(os.pathsep) if not os.path.exists(os.path.join(d, "gh"))
        )
        out = self.run_sl(self.payload(cwd=repo), PATH=path)
        self.assertEqual(out.split(SEP)[2], "main")
        self.assertFalse(os.path.exists(os.path.join(self.cache, "dstack")))

    def test_render_is_fast_with_warm_cache(self):
        repo = self.make_repo()
        self.stub_gh("9")
        self.run_sl(self.payload(cwd=repo))
        self.assertTrue(self.wait_for(lambda: "#9" in self.run_sl(self.payload(cwd=repo))))
        payload = json.dumps(self.payload(cwd=repo)).encode()
        env = self.env()
        times = []
        for _ in range(21):
            start = time.perf_counter()
            subprocess.run([BASH, SCRIPT], input=payload, stdout=subprocess.PIPE, env=env, check=True)
            times.append(time.perf_counter() - start)
        median_ms = statistics.median(times) * 1000
        print("\nstatusline warm render median: {:.1f} ms".format(median_ms))
        self.assertLess(median_ms, 100)
        self.assertEqual(self.gh_calls(), 1)


class SyntaxTests(unittest.TestCase):
    def test_bash_n(self):
        subprocess.run([BASH, "-n", SCRIPT], check=True)

    def test_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
