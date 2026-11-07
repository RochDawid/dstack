"""Builds throwaway dstack repos and home directories for tests/test_dstack.py.

Every test runs the real bin/dstack in a subprocess, against a temporary HOME and,
where it writes to the repo, a temporary copy of the repo. Nothing here touches the real home.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DSTACK = REPO / "bin" / "dstack"
TMP_ROOT = Path(os.path.realpath(tempfile.gettempdir()))

GIT_ENV = {
    "GIT_AUTHOR_NAME": "dstack-test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "dstack-test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
}


def write(path: Path, text: str, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    if mode is not None:
        path.chmod(mode)
    return path


def skill_md(name: str, description: str = "A test skill.") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


def make_skill(dir: Path, name: str) -> Path:
    write(dir / name / "SKILL.md", skill_md(name))
    return dir / name


GUARD = """\
#!/usr/bin/env bash
# test guard: allow everything
exit 0
"""

SETTINGS = {
    "$comment": "test settings",
    "model": "test-model",
    "permissions": {"defaultMode": "bypassPermissions"},
    "statusLine": {"type": "command", "command": "$DSTACK/config/hooks/guard.sh"},
    "env": {"KEEP_LITERAL": "$DSTACK_NOT_A_VAR", "BRACED": "${DSTACK}/x"},
    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "$DSTACK/config/hooks/guard.sh"}]}]},
}

HOOKS = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "$DSTACK/config/hooks/guard.sh"}]}]}}

CODEX_CONFIG = """\
# managed keys
model = "test-model"
approval_policy = "never"

[tui]
status_line = ["model", "dir"]
status_line_use_colors = true

[features]
web_search = true
"""


def make_repo(base: Path, name: str = "dstack") -> Path:
    """A minimal dstack repo: two vendored sources, two agents, config and the real bin/dstack."""
    repo = base / name
    (repo / "bin").mkdir(parents=True)
    shutil.copy2(DSTACK, repo / "bin" / "dstack")
    manifest = {
        "sources": {
            "alpha": {"repo": "file:///nonexistent/alpha.git", "ref": "main", "root": "", "skills": "*",
                      "files": ["LICENSE", "agents"]},
            "beta": {"repo": "file:///nonexistent/beta.git", "ref": "main", "root": "",
                     "skills": {"three": "skills/three"}, "files": []},
        },
        "agents": ["vendor/alpha/agents/helper.md"],
    }
    lock = {"sources": {
        "alpha": {"repo": "file:///nonexistent/alpha.git", "ref": "main", "commit": "a" * 40, "skills": ["one", "two"]},
        "beta": {"repo": "file:///nonexistent/beta.git", "ref": "main", "commit": "b" * 40, "skills": ["three"]},
    }}
    write(repo / "dstack.json", json.dumps(manifest, indent=2))
    write(repo / "dstack.lock.json", json.dumps(lock, indent=2))
    for skill in ("one", "two"):
        make_skill(repo / "vendor" / "alpha" / "skills", skill)
    make_skill(repo / "vendor" / "beta" / "skills", "three")
    write(repo / "vendor" / "alpha" / "LICENSE", "MIT\n")
    write(repo / "vendor" / "alpha" / "agents" / "helper.md", "# helper agent\n")
    write(repo / "global" / "AGENTS.md", "# global instructions\n")
    write(repo / "global" / "pstack-models.md", "# models\n")
    write(repo / "config" / "claude" / "settings.json", json.dumps(SETTINGS, indent=2))
    write(repo / "config" / "codex" / "hooks.json", json.dumps(HOOKS, indent=2))
    write(repo / "config" / "codex" / "config.toml", CODEX_CONFIG)
    write(repo / "config" / "hooks" / "guard.sh", GUARD, 0o755)
    (repo / "skills").mkdir()
    return repo


def copy_real_repo(base: Path) -> Path:
    """A copy of this repository (without .git), for tests that need the real vendor/ and config/."""
    dest = base / "dstack"
    shutil.copytree(REPO, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
    return dest


def snapshot(root: Path) -> dict[str, tuple]:
    """Every path under `root` with its link target, or its bytes and mode, to compare before and after."""
    out: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if Path(dirpath) == root and "Library" in dirnames:
            dirnames.remove("Library")  # macOS tools (e.g. the git shim) cache under $HOME/Library
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            elif p.is_dir():
                out[rel] = ("dir",)
            else:
                st = p.stat()
                out[rel] = ("file", p.read_bytes(), st.st_mode, st.st_mtime_ns)
    return out


class DstackTestCase(unittest.TestCase):
    """Gives each test a temp dir with a `home/` and helpers to run bin/dstack against it."""

    def setUp(self) -> None:
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="dstack-test-")))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()

    def make_repo(self, name: str = "dstack") -> Path:
        return make_repo(self.tmp, name)

    def env(self, home: Path | None = None, **extra: str) -> dict[str, str]:
        home = home or self.home
        if not os.path.realpath(home).startswith(str(TMP_ROOT) + os.sep):
            raise AssertionError(f"refusing to run dstack against non-temporary home {home}")
        env = {k: v for k, v in os.environ.items()
               if k not in ("HOME", "DSTACK_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR")}
        env.update(GIT_ENV, HOME=str(home), PYTHONIOENCODING="utf-8", **extra)
        return env

    def run_dstack(self, repo: Path, *args: str, expect: int | None = 0, env: dict | None = None,
                   ) -> subprocess.CompletedProcess:
        proc = subprocess.run([sys.executable, str(repo / "bin" / "dstack"), *args], cwd=self.tmp,
                              env=env or self.env(), capture_output=True, text=True, encoding="utf-8",
                              timeout=120)
        if expect is not None and proc.returncode != expect:
            self.fail(f"`dstack {' '.join(args)}` exited {proc.returncode}, expected {expect}\n"
                      f"--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}")
        return proc

    def assertLinksTo(self, link: Path, target: Path) -> None:
        self.assertTrue(link.is_symlink(), f"{link} is not a symlink")
        self.assertEqual(Path(os.readlink(link)), target)
