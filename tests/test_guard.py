"""Tests for config/hooks/guard.sh (the dstack PreToolUse guard).

Every case runs the real hook as a subprocess with a JSON payload on stdin,
exactly as Claude Code and Codex do. Nothing here executes the commands.

Run from the repo root:  python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "config", "hooks", "guard.sh")
HOME = os.path.expanduser("~")

B, A = "block", "allow"

# (command, expected, cwd key). cwd keys: repo (a temp git repo, default),
# sub (repo/src), plain (a temp dir that is not a repo), home ($HOME), slash (/).
CASES = [
    # ---- the verified holes in the old string-matching guard ----
    ("git push -fu origin main", B),
    ("git push origin +main", B),
    ('rm -rf "$HOME/Documents"', B),
    ("cd / && rm -rf usr", B),
    ("git -C repo reset --hard", B),
    ("find ~ -delete", B),
    # ---- the verified false positives ----
    ('git commit -m "never use git reset --hard"', A),
    ('git push origin main && echo "a+b: c"', A),

    # ---- push ----
    ("git push", A),
    ("git push origin main", A),
    ("git push -u origin feature", A),
    ("git push --force origin main", B),
    ("git push -f", B),
    ("git push origin main -f", B),
    ("git push -uf origin main", B),
    ("git push --forc origin main", B),
    ("git push --force-with-lease origin main", A),
    ("git push --force-with-lease=main:abc123 origin main", A),
    ("git push --force-with-lease --force-if-includes origin main", A),
    ("git push --force --force-with-lease origin main", B),
    ("git push origin +HEAD:main", B),
    ("git push origin main +dev", B),
    ("git push --mirror", B),
    ("git push --delete origin old", B),
    ("git push origin -d old", B),
    ("git push origin :old", B),
    ("git push origin :", A),
    ("git push --prune origin", B),
    ("git push -o ci.skip origin main", A),
    ("git push -o f origin main", A),
    ("git push --no-verify origin main", A),
    ("/usr/bin/git push -f", B),
    ("git --no-pager -c color.ui=never push -f", B),
    ("git --git-dir=.git --work-tree=. push --force", B),
    ("git --git-dir .git push --force", B),
    # ---- reset / clean / checkout / restore / switch / rm ----
    ("git reset --hard", B),
    ("git reset --hard HEAD~1", B),
    ("git reset --ha origin/main", B),
    ("git reset HEAD~1", A),
    ("git reset --soft HEAD~1", A),
    ("git reset --keep HEAD~1", A),
    ("git reset -- file.txt", A),
    ("git clean -fd", B),
    ("git clean -xdf", B),
    ("git clean --force", B),
    ("git clean -fdn", A),
    ("git clean -f --dry-run", A),
    ("git clean -n", A),
    ("git clean -e f -n", A),
    ("git checkout .", B),
    ("git checkout -- .", B),
    ("git checkout HEAD -- .", B),
    ("git checkout HEAD .", B),
    ("git checkout -- :/", B),
    ("git checkout --theirs .", B),
    ("git checkout -- ..", B, "sub"),
    ("git checkout -f main", B),
    ("git checkout --force main", B),
    ("git checkout main", A),
    ("git checkout -b feature", A),
    ("git checkout -- src/app.py", A),
    ("git checkout -", A),
    ("git restore .", B),
    ("git restore --worktree .", B),
    ("git restore --staged --worktree .", B),
    ("git restore -SW :/", B),
    ("git restore --source=HEAD~2 .", B),
    ("git restore --staged .", A),
    ("git restore src/app.py", A),
    ("git switch -f main", B),
    ("git switch --discard-changes main", B),
    ("git switch -c feature", A),
    ("git rm -rf .", B),
    ("git rm -r --cached .", A),
    ("git rm old.txt", A),
    # ---- branch / stash / history / reflog / gc / refs ----
    ("git branch -D feature", B),
    ("git branch -Dr origin/x", B),
    ("git branch --delete --force feature", B),
    ("git branch -d -f feature", B),
    ("git branch -df feature", B),
    ("git branch -d feature", A),
    ("git branch -f main origin/main", A),
    ("git branch -u origin/main", A),
    ("git stash", A),
    ("git stash pop", A),
    ("git stash list", A),
    ("git stash drop", B),
    ("git stash drop stash@{1}", B),
    ("git stash clear", B),
    ("git filter-branch --tree-filter 'rm x' HEAD", B),
    ("git filter-repo --path secret --invert-paths", B),
    ("git-filter-repo --path secret", B),
    ("git reflog", A),
    ("git reflog expire --expire=now --all", B),
    ("git reflog delete HEAD@{1}", B),
    ("git gc", A),
    ("git gc --aggressive", A),
    ("git gc --prune=now", B),
    ("git -c gc.pruneExpire=now gc", B),
    ("git prune", B),
    ("git prune -n", A),
    ("git fetch --prune", A),
    ("git remote prune origin", A),
    ("git update-ref -d refs/heads/x", B),
    ("git update-ref refs/heads/x HEAD", A),
    ("git submodule foreach 'git reset --hard'", B),
    ("git submodule foreach git status", A),
    ("git log --oneline -5", A),
    ("git status", A),
    ("git rebase -i HEAD~3", A),
    ("git push origin HEAD --force", B),
    ("git push origin 'main' -f", B),
    ("git checkout feature -- .", B),
    ("git -C .. checkout .", B),
    ("git clean -fX -n", A),
    ("git stash push -m 'wip' && git checkout main", A),
    ("git commit --amend --no-edit && git push --force-with-lease", A),
    ("git checkout .github/workflows/ci.yml", A),

    # ---- rm: flag spellings ----
    ("rm -rf /", B),
    ("rm -rf ~", B),
    ("rm -rf ~/", B),
    ("rm -Rf /usr", B),
    ("rm -fr /usr", B),
    ("rm -r -f /usr", B),
    ("rm --recursive --force /usr", B),
    ("rm --rec --force /usr", B),
    ("rm /usr -rf", B),
    ("rm -r /usr", B),
    ("rm -f /etc/hosts", A),
    ("rm file.txt", A),
    ("rm -rf -- /usr", B),
    ("rm -r -- -rf", A),
    ("rm -rf $'/usr'", B),
    ("rm -rf /usr/./local", B),
    ('rm -rf "$HOME"/Documents', B),
    ("rm -rf node_modules && npm ci", A),
    # ---- rm: inside the project and temp dirs ----
    ("rm -rf build", A),
    ("rm -rf ./build node_modules", A),
    ("rm -rf src/../build", A),
    ("rm -rf build/*", A),
    ("rm -rf *.log", A),
    ("rm -rf /tmp/scratch", A),
    ("rm -rf /tmp/scratch-*", A),
    ('rm -rf "$TMPDIR/x"', A, "repo", {"TMPDIR": "@tmp"}),
    ("rm -rf $PWD/build", A),
    ("rm -rf ${PWD}/build", A),
    # ---- rm: the root itself, globs at roots, .git ----
    ("rm -rf .", B),
    ("rm -rf ./", B),
    ("rm -rf *", B),
    ("rm -rf .*", B),
    ("rm -rf ./*", B),
    ("rm -rf /*", B),
    ("rm -rf ~/*", B),
    ("rm -rf /tmp/*", B),
    ("rm -rf /tmp", B),
    ("rm -rf .git", B),
    ("rm -rf sub/.git/", B),
    ("rm -rf ..", B, "sub"),
    ("rm -rf ../..", B, "sub"),
    ('rm -rf "*"', A),
    # ---- rm: expansion ----
    ("rm -rf $HOME", B),
    ("rm -rf ${HOME}/x", B),
    ("rm -rf '$HOME'", A),
    ('rm -rf "$UNKNOWN_VAR"', B),
    ("rm -rf $UNKNOWN_VAR/build", B),
    ('rm -rf "${DIR:-build}"', B),
    ("rm -rf $(pwd)/build", B),
    ("rm -rf `echo build`", B),
    ("X=/usr; rm -rf $X", B),
    ("X=build; rm -rf $X", A),
    ("export X=/usr && rm -rf $X", B),
    ("for d in a b; do rm -rf $d; done", B),
    ('rm -rf "$TMPDIR/x"', B, "repo", {"TMPDIR": None}),
    ("rm -rf ~root", B),
    # ---- rm: cd tracking ----
    ("cd /usr && rm -rf local", B),
    ("cd ~ && rm -rf Documents", B),
    ("cd && rm -rf Documents", B),
    ("cd /tmp && rm -rf scratch", A),
    ("cd src && rm -rf ../build", A),
    ("cd src; cd ..; rm -rf build", A),
    ("pushd /usr && rm -rf local", B),
    ("pushd /usr; popd; rm -rf build", A),
    ("(cd /usr) && rm -rf build", A),
    ("(cd /usr && rm -rf local)", B),
    ('cd "$SOMEWHERE" && rm -rf build', B),
    ("cd - && rm -rf build", B),
    ("cd $HOME/x && rm -rf y", B),
    ("env -C /usr rm -rf local", B),
    # ---- rm: cwd is not a safe root ----
    ("rm -rf build", B, "home"),
    ("rm -rf usr", B, "slash"),
    ("rm -rf build", A, "plain"),
    ("rm -rf .", B, "plain"),
    # ---- find ----
    ("find . -name '*.pyc' -delete", A),
    ("find build -delete", A),
    ("find . -delete", B),
    ("find . -type f -delete", B),
    ("find -delete", B),
    ("find / -name '*.log' -delete", B),
    ("find ~ -name node_modules -exec rm -rf {} +", B),
    ("find . -name node_modules -exec rm -rf {} +", A),
    ("find -L ~/x -delete", B),
    ("find . -name x -exec git reset --hard \\;", B),
    ("find ~ -name '*.txt'", A),
    ("find ~ -name x -print | xargs rm -rf", B),
    ("find . -name node_modules -print0 | xargs -0 rm -rf", A),
    ("ls | xargs rm -rf", B),
    ("ls | xargs rm -f", A),

    # ---- quoting: text is data ----
    ('echo "rm -rf ~"', A),
    ("echo 'git push --force'", A),
    ('git commit -m "fix: drop git push -f; use --force-with-lease"', A),
    ('git commit -m "cleanup && rm -rf / was a joke"', A),
    ('echo ";" rm -rf /', A),
    ('grep -r "reset --hard" .', A),
    ("printf '%s\\n' 'git stash clear'", A),
    ("# rm -rf ~\necho ok", A),
    ("echo ok # git push -f", A),
    # ---- heredocs ----
    ("cat <<EOF\nrm -rf ~\ngit push -f\nEOF", A),
    ("git commit -F - <<'EOF'\nnever run git reset --hard\nEOF", A),
    ("cat > notes.md <<EOF\ngit branch -D x\nEOF\necho done", A),
    ("bash <<EOF\nrm -rf ~\nEOF", B),
    ("sh <<'EOF'\ngit push -f\nEOF", B),
    ("cat <<EOF\n$(rm -rf ~)\nEOF", B),
    ("cat <<'EOF'\n$(rm -rf ~)\nEOF", A),
    ("cat <<-EOF\n\tok\n\tEOF\nrm -rf /usr", B),
    ("cat <<EOF | bash\ngit reset --hard\nEOF", B),
    ("bash <<< 'git reset --hard'", B),
    # ---- nesting ----
    ("bash -c 'git push -f'", B),
    ("sh -c \"rm -rf ~\"", B),
    ("bash -lc 'cd / && rm -rf usr'", B),
    ("zsh -c 'bash -c \"git reset --hard\"'", B),
    ("eval 'git push --force'", B),
    ("eval git stash clear", B),
    ("echo $(git reset --hard)", B),
    ('echo "$(rm -rf ~)"', B),
    ("echo `git stash clear`", B),
    ("diff <(git stash drop) x", B),
    ("echo 'git push -f' | bash", B),
    ("echo 'git status' | sh", A),
    ("bash -c 'git status && ls'", A),
    ("bash script.sh", A),
    ("watch -n 5 git push -f", B),
    ("watch 'git status'", A),
    ("trap 'rm -rf ~' EXIT", B),
    ("trap - EXIT", A),
    ("env -S 'git push -f'", B),
    ("sudo -s 'rm -rf /usr'", B),
    ("x=$(git stash clear)", B),
    ("f() { rm -rf ~; }; f", B),
    ("case x in x) git reset --hard;; esac", B),
    ("while true; do git stash drop; done", B),
    # ---- separators and prefixes ----
    ("ls; git push -f", B),
    ("ls && git push -f", B),
    ("false || git push -f", B),
    ("ls | git push -f", B),
    ("sleep 1 & git push -f", B),
    ("ls\ngit push -f", B),
    ("ls;git push -f", B),
    ("ls&&git reset --hard", B),
    ("(git reset --hard)", B),
    ("{ git reset --hard; }", B),
    ("if true; then git reset --hard; fi", B),
    ("FOO=1 git push -f", B),
    ("FOO=1 BAR=2 rm -rf ~", B),
    ("sudo rm -rf /usr", B),
    ("sudo -u root rm -rf /usr", B),
    ("sudo -E -- git push -f", B),
    ("env FOO=1 git push -f", B),
    ("env -i PATH=/bin rm -rf ~", B),
    ("command git push -f", B),
    ("command -v rm", A),
    ("nice -n 10 git push -f", B),
    ("time git push -f", B),
    ("timeout 10 git push -f", B),
    ("nohup rm -rf ~ &", B),
    ("exec git reset --hard", B),
    ("xargs git push -f", B),
    ("\\rm -rf ~", B),
    ("git status 2>&1 | head", A),
    ("rm -rf build 2>/dev/null", A),
    ("ls > out.txt && git push origin main", A),

    # ---- fallback for unparseable text ----
    ("echo 'unterminated && git push -f", B),
    ('echo "unterminated', A),
    ("echo $(git reset --hard", B),
]


class GuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix="dstack-guard-"))
        cls.repo = os.path.join(cls.tmp, "repo")
        os.makedirs(os.path.join(cls.repo, ".git"))
        os.makedirs(os.path.join(cls.repo, "src"))
        os.makedirs(os.path.join(cls.repo, "sub", ".git"))
        cls.plain = os.path.join(cls.tmp, "plain")
        os.makedirs(cls.plain)
        cls.cwds = {"repo": cls.repo, "sub": os.path.join(cls.repo, "src"),
                    "plain": cls.plain, "home": HOME, "slash": "/"}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_guard(self, payload, env=None, raw=None):
        e = dict(os.environ)
        e.pop("DSTACK_GUARD", None)
        e.update(env or {})
        e = {k: v for k, v in e.items() if v is not None}
        data = raw if raw is not None else json.dumps(payload)
        p = subprocess.run([GUARD], input=data.encode(), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=e, timeout=10)
        return p.returncode, p.stderr.decode()

    def check(self, command, expected, cwd="repo", env=None):
        env = dict(env or {})
        if env.get("TMPDIR") == "@tmp":
            env["TMPDIR"] = self.tmp
        payload = {"tool_input": {"command": command}, "cwd": self.cwds[cwd]}
        rc, err = self.run_guard(payload, env)
        want = 2 if expected == B else 0
        self.assertEqual(rc, want, "%r (cwd=%s): expected %s, got rc=%d %s"
                         % (command, cwd, expected, rc, err.strip()))
        if expected == B:
            self.assertTrue(err.startswith("dstack guard"), err)
            self.assertEqual(len(err.strip().splitlines()), 1, err)
        else:
            self.assertEqual(err, "")

    def test_cases(self):
        self.assertGreater(len(CASES), 100)
        for case in CASES:
            command, expected = case[0], case[1]
            cwd = case[2] if len(case) > 2 else "repo"
            env = case[3] if len(case) > 3 else None
            with self.subTest(command=command, cwd=cwd):
                self.check(command, expected, cwd, env)

    # ---- payload shapes ----

    def test_codex_argv(self):
        cases = [
            (["git", "push", "-f"], B),
            (["git", "push", "origin", "main"], A),
            (["bash", "-lc", "git reset --hard"], B),
            (["bash", "-lc", "git status"], A),
            (["rm", "-rf", "/usr"], B),
            # No shell runs an argv array, so "$HOME" and "~" are literal names here.
            (["rm", "-rf", "$HOME"], A),
            (["rm", "-rf", "build"], A),
            (["sudo", "git", "clean", "-fdx"], B),
            ([], A),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                rc, err = self.run_guard({"tool_input": {"command": argv}, "cwd": self.repo})
                self.assertEqual(rc, 2 if expected == B else 0, err)

    def test_codex_workdir(self):
        rc, _ = self.run_guard({"tool_input": {"command": ["rm", "-rf", "local"], "workdir": "/usr"},
                                "cwd": self.repo})
        self.assertEqual(rc, 2)
        rc, _ = self.run_guard({"tool_input": {"command": ["rm", "-rf", "x"], "workdir": "src"},
                                "cwd": self.repo})
        self.assertEqual(rc, 0)

    def test_message_names_rule_command_and_alternative(self):
        rc, err = self.run_guard({"tool_input": {"command": "ls && git push -f origin main"},
                                  "cwd": self.repo})
        self.assertEqual(rc, 2)
        self.assertIn("[push-force]", err)
        self.assertIn("`git push -f origin main`", err)
        self.assertIn("--force-with-lease", err)
        self.assertNotIn("ls &&", err)
        _, err = self.run_guard({"tool_input": {"command": "git branch -D x"}, "cwd": self.repo})
        self.assertIn("git branch -d", err)
        _, err = self.run_guard({"tool_input": {"command": "git reset --hard"}, "cwd": self.repo})
        self.assertIn("git stash", err)

    def test_fallback_says_so(self):
        _, err = self.run_guard({"tool_input": {"command": "git reset --hard 'oops"}, "cwd": self.repo})
        self.assertIn("could not be parsed", err)

    def test_off_switch(self):
        rc, err = self.run_guard({"tool_input": {"command": "git push -f"}, "cwd": self.repo},
                                 env={"DSTACK_GUARD": "off"})
        self.assertEqual((rc, err), (0, ""))
        rc, _ = self.run_guard(None, env={"DSTACK_GUARD": "off"}, raw="not json")
        self.assertEqual(rc, 0)

    def test_malformed_json_blocks(self):
        for raw in ("", "not json", "{\"tool_input\": "):
            with self.subTest(raw=raw):
                rc, err = self.run_guard(None, raw=raw)
                self.assertEqual(rc, 2)
                self.assertIn("DSTACK_GUARD=off", err)

    def test_non_shell_payloads_allow(self):
        for payload in ({}, {"tool_input": {}}, {"tool_input": {"command": ""}}, [1, 2],
                        {"tool_input": {"file_path": "x"}}):
            with self.subTest(payload=payload):
                rc, _ = self.run_guard(payload)
                self.assertEqual(rc, 0)

    def test_missing_cwd_uses_process_cwd(self):
        rc, _ = self.run_guard({"tool_input": {"command": "git push -f"}})
        self.assertEqual(rc, 2)

    def test_missing_python_blocks(self):
        empty = tempfile.mkdtemp(dir=self.tmp)
        bash = shutil.which("bash")
        p = subprocess.run([bash, GUARD], input=b"{}", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env={"PATH": empty, "HOME": HOME})
        self.assertEqual(p.returncode, 2)
        self.assertIn(b"python3 not found", p.stderr)
        self.assertIn(b"DSTACK_GUARD=off", p.stderr)

    def test_python_crash_blocks(self):
        # A python3 that exits 1 (for example a syntax error on an old interpreter) must not allow.
        fake = tempfile.mkdtemp(dir=self.tmp)
        with open(os.path.join(fake, "python3"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(fake, "python3"), 0o755)
        p = subprocess.run([shutil.which("bash"), GUARD], input=b"{}", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,
                           env={"PATH": fake + os.pathsep + "/usr/bin:/bin", "HOME": HOME})
        self.assertEqual(p.returncode, 2)
        self.assertIn(b"exited with status 1", p.stderr)

    def test_speed(self):
        command = ("cd src && FOO=1 sudo env BAR=2 bash -c 'git status && rm -rf build' | "
                   "tee log && git push --force-with-lease origin main && "
                   "git commit -m \"$(date) never git reset --hard\"")
        payload = {"tool_input": {"command": command}, "cwd": self.repo}
        times = []
        for _ in range(15):
            t = time.perf_counter()
            rc, _ = self.run_guard(payload)
            times.append(time.perf_counter() - t)
            self.assertEqual(rc, 0)
        median = statistics.median(times)
        sys.stderr.write("\nguard median latency: %.1f ms\n" % (median * 1000))
        self.assertLess(median, 0.150)


if __name__ == "__main__":
    unittest.main()
