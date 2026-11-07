"""End-to-end tests for bin/dstack. Run with `bin/dstack test` or `python3 -m unittest discover -s tests`."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path

from _dstack_fixture import (GIT_ENV, REPO, DstackTestCase, copy_real_repo, make_skill, skill_md, snapshot,
                             write)

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - 3.9/3.10
    tomllib = None


def backups(home: Path) -> list[Path]:
    root = home / ".dstack-backups"
    return sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink()) if root.exists() else []


class CliTest(DstackTestCase):
    def test_no_args_and_help_print_usage(self):
        repo = self.make_repo()
        for args in ([], ["-h"], ["--help"], ["help"]):
            out = self.run_dstack(repo, *args).stdout
            self.assertIn("usage: dstack", out)
            for cmd in ("sync", "install", "status", "doctor", "test", "uninstall"):
                self.assertIn(cmd, out)

    def test_subcommand_help(self):
        repo = self.make_repo()
        self.assertIn("--dry-run", self.run_dstack(repo, "install", "-h").stdout)
        self.assertIn("--repo-only", self.run_dstack(repo, "doctor", "--help").stdout)

    def test_unknown_command_and_flag_exit_2(self):
        repo = self.make_repo()
        proc = self.run_dstack(repo, "bogus", expect=2)
        self.assertIn("invalid choice", proc.stderr)
        self.run_dstack(repo, "install", "--bogus", expect=2)
        self.run_dstack(repo, "status", "extra-arg", expect=2)
        self.assertEqual(snapshot(self.home), {})


class InstallTest(DstackTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()

    def expected_links(self) -> dict[Path, Path]:
        r, h = self.repo, self.home
        links = {}
        for d in (h / ".claude/skills", h / ".agents/skills"):
            links[d / "one"] = r / "vendor/alpha/skills/one"
            links[d / "two"] = r / "vendor/alpha/skills/two"
            links[d / "three"] = r / "vendor/beta/skills/three"
        links[h / ".claude/agents/helper.md"] = r / "vendor/alpha/agents/helper.md"
        links[h / ".claude/CLAUDE.md"] = r / "global/AGENTS.md"
        links[h / ".codex/AGENTS.md"] = r / "global/AGENTS.md"
        links[h / ".claude/rules/pstack-models.md"] = r / "global/pstack-models.md"
        return links

    def test_install_creates_all_links_and_config(self):
        out = self.run_dstack(self.repo, "install").stdout
        for at, target in self.expected_links().items():
            self.assertLinksTo(at, target)
        self.assertIn("linked 3 skills", out)
        settings = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(settings["model"], "test-model")
        self.assertNotIn("$comment", settings)
        hooks = json.loads((self.home / ".codex/hooks.json").read_text())
        self.assertEqual(hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
                         f"{self.repo}/config/hooks/guard.sh")
        self.assertIn('model = "test-model"', (self.home / ".codex/config.toml").read_text())
        self.assertEqual(backups(self.home), [], "a fresh home has nothing to back up")

    def test_install_is_idempotent(self):
        self.run_dstack(self.repo, "install")
        before = snapshot(self.home)
        out = self.run_dstack(self.repo, "install").stdout
        self.assertNotIn("updated", out)
        self.assertNotIn("backed up", out)
        self.assertNotIn("backups in", out)
        self.assertEqual(snapshot(self.home), before, "second install changed the home directory")

    def test_dstack_home_overrides_home(self):
        other = self.tmp / "other-home"
        other.mkdir()
        self.run_dstack(self.repo, "install", env=self.env(DSTACK_HOME=str(other)))
        self.assertTrue((other / ".claude/skills/one").is_symlink())
        self.assertEqual(snapshot(self.home), {})

    def test_foreign_files_are_backed_up_not_deleted(self):
        write(self.home / ".claude/CLAUDE.md", "my own instructions\n")
        make_skill(self.home / ".claude/skills", "one")  # a real directory where a link goes
        (self.home / ".claude/skills/one/notes.txt").write_text("keep me")
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (self.home / ".agents/skills").mkdir(parents=True)
        (self.home / ".agents/skills/two").symlink_to(elsewhere)  # a foreign link
        unrelated = write(self.home / ".claude/skills/mine/SKILL.md", skill_md("mine"))

        out = self.run_dstack(self.repo, "install").stdout
        self.assertIn("backed up", out)
        self.assertIn("backups in", out)
        for at, target in self.expected_links().items():
            self.assertLinksTo(at, target)
        stamp = next((self.home / ".dstack-backups").iterdir())
        self.assertEqual((stamp / ".claude/CLAUDE.md").read_text(), "my own instructions\n")
        self.assertEqual((stamp / ".claude/skills/one/notes.txt").read_text(), "keep me")
        self.assertEqual(Path(os.readlink(stamp / ".agents/skills/two")), elsewhere)
        self.assertTrue(unrelated.exists(), "install touched a file it does not manage")

    def test_existing_settings_are_backed_up_before_merge(self):
        write(self.home / ".claude/settings.json", '{"theme": "dark"}\n')
        self.run_dstack(self.repo, "install")
        stamp = next((self.home / ".dstack-backups").iterdir())
        self.assertEqual(json.loads((stamp / ".claude/settings.json").read_text()), {"theme": "dark"})

    def test_backups_never_overwrite_each_other(self):
        for _ in range(2):  # both runs may land in the same timestamp directory
            claude_md = self.home / ".claude/CLAUDE.md"
            if claude_md.is_symlink():
                claude_md.unlink()
            write(claude_md, "foreign\n")
            self.run_dstack(self.repo, "install")
        saved = [p for p in backups(self.home) if p.name.startswith("CLAUDE.md")]
        self.assertEqual(len(saved), 2)

    def test_own_skills_override_vendored(self):
        make_skill(self.repo / "skills", "one")
        make_skill(self.repo / "skills", "four")
        self.run_dstack(self.repo, "install")
        for d in (".claude/skills", ".agents/skills"):
            self.assertLinksTo(self.home / d / "one", self.repo / "skills/one")
            self.assertLinksTo(self.home / d / "four", self.repo / "skills/four")
            self.assertLinksTo(self.home / d / "two", self.repo / "vendor/alpha/skills/two")

    def test_switching_to_own_skill_replaces_owned_link_without_backup(self):
        self.run_dstack(self.repo, "install")
        make_skill(self.repo / "skills", "one")
        self.run_dstack(self.repo, "install")
        self.assertLinksTo(self.home / ".claude/skills/one", self.repo / "skills/one")
        self.assertEqual(backups(self.home), [])

    def test_prunes_stale_owned_links_only(self):
        self.run_dstack(self.repo, "install")
        skills = self.home / ".claude/skills"
        (skills / "gone").symlink_to(self.repo / "vendor/alpha/skills/gone")  # dangling, ours
        (skills / "relative").symlink_to(os.path.relpath(self.repo / "vendor/alpha/skills/two", skills))
        (self.home / ".claude/agents/old.md").symlink_to(self.repo / "vendor/alpha/agents/old.md")
        foreign = skills / "foreign"
        foreign.symlink_to(self.tmp)

        proc = self.run_dstack(self.repo, "status", "--offline", expect=1)
        self.assertIn("stale links", proc.stdout)
        self.assertIn("gone (dangling)", proc.stdout)
        self.run_dstack(self.repo, "install")
        for p in (skills / "gone", skills / "relative", self.home / ".claude/agents/old.md"):
            self.assertFalse(os.path.lexists(p), f"{p} was not pruned")
        self.assertTrue(foreign.is_symlink(), "pruned a link dstack does not own")
        self.assertEqual(backups(self.home), [])

    def test_link_into_sibling_dir_with_repo_prefix_is_not_owned(self):
        # /tmp/x/dstack-old starts with the string "/tmp/x/dstack" but is not inside the repo.
        sibling = self.tmp / "dstack-old"
        make_skill(sibling / "skills", "one")
        make_skill(sibling / "skills", "zzz")
        skills = self.home / ".claude/skills"
        skills.mkdir(parents=True)
        (skills / "one").symlink_to(sibling / "skills/one")
        (skills / "zzz").symlink_to(sibling / "skills/zzz")

        self.run_dstack(self.repo, "install")
        self.assertLinksTo(skills / "zzz", sibling / "skills/zzz")  # not pruned
        self.assertLinksTo(skills / "one", self.repo / "vendor/alpha/skills/one")
        backed = [p for p in backups(self.home) if p.name == "one"]
        self.assertEqual(len(backed), 1, "the foreign `one` link was deleted instead of backed up")
        self.assertEqual(Path(os.readlink(backed[0])), sibling / "skills/one")
        self.assertIn("zzz", self.run_dstack(self.repo, "status", "--offline").stdout)

    def test_settings_deep_merge(self):
        write(self.home / ".claude/settings.json", json.dumps({
            "theme": "dark",
            "model": "old-model",
            "permissions": {"allow": ["Bash(ls)"], "defaultMode": "default"},
            "hooks": {
                "PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "old"}]}],
                "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "mine"}]}],
            },
            "statusLine": "not-an-object",
        }))
        self.run_dstack(self.repo, "install")
        s = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(s["theme"], "dark")
        self.assertEqual(s["model"], "test-model")
        self.assertEqual(s["permissions"], {"allow": ["Bash(ls)"], "defaultMode": "bypassPermissions"})
        guard = f"{self.repo}/config/hooks/guard.sh"
        self.assertEqual(s["hooks"]["PreToolUse"],
                         [{"matcher": "Bash", "hooks": [{"type": "command", "command": guard}]}],
                         "managed lists must be replaced, not appended")
        self.assertEqual(s["hooks"]["PostToolUse"][0]["hooks"][0]["command"], "mine")
        self.assertEqual(s["statusLine"], {"type": "command", "command": guard})
        self.assertEqual(list(s)[:2], ["theme", "model"], "key order of the user's file is kept")

    def test_dstack_variable_expansion(self):
        self.run_dstack(self.repo, "install")
        env = json.loads((self.home / ".claude/settings.json").read_text())["env"]
        self.assertEqual(env["KEEP_LITERAL"], "$DSTACK_NOT_A_VAR")
        self.assertEqual(env["BRACED"], f"{self.repo}/x")

    def test_invalid_settings_json_fails_cleanly(self):
        bad = write(self.home / ".claude/settings.json", "{not json")
        proc = self.run_dstack(self.repo, "install", expect=1)
        self.assertIn("not valid JSON", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(bad.read_text(), "{not json")

    def test_settings_symlink_and_mode_preserved(self):
        dotfiles = write(self.tmp / "dotfiles/settings.json", '{"theme": "dark"}\n', 0o600)
        (self.home / ".claude").mkdir()
        (self.home / ".claude/settings.json").symlink_to(dotfiles)
        self.run_dstack(self.repo, "install")
        self.assertTrue((self.home / ".claude/settings.json").is_symlink(), "atomic write replaced the symlink")
        self.assertEqual(json.loads(dotfiles.read_text())["model"], "test-model")
        self.assertEqual(stat.S_IMODE(dotfiles.stat().st_mode), 0o600)
        leftovers = [p for p in dotfiles.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_missing_vendor_skill_fails_before_writing(self):
        shutil.rmtree(self.repo / "vendor/beta/skills/three")
        proc = self.run_dstack(self.repo, "install", expect=1)
        self.assertIn("vendor/beta/skills/three", proc.stderr)
        self.assertEqual(snapshot(self.home), {})

    def test_adopts_skills_sh_managed_agents_dir(self):
        write(self.home / ".agents/.skill-lock.json", "{}")
        make_skill(self.home / ".agents/skills", "legacy")
        self.run_dstack(self.repo, "install")
        stamp = next((self.home / ".dstack-backups").iterdir())
        self.assertTrue((stamp / ".agents/skills/legacy/SKILL.md").exists())
        self.assertTrue((stamp / ".agents/.skill-lock.json").exists())
        self.assertFalse((self.home / ".agents/skills/legacy").exists())
        self.assertLinksTo(self.home / ".agents/skills/one", self.repo / "vendor/alpha/skills/one")


class CodexConfigTest(DstackTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()
        self.path = self.home / ".codex/config.toml"

    def install(self) -> str:
        self.run_dstack(self.repo, "install")
        text = self.path.read_text()
        if tomllib:
            tomllib.loads(text)
        return text

    def test_merge_into_existing_file(self):
        write(self.path, """
            # my codex config
            model = "gpt-old"  # trailing comment
            notify = ["a", "b"]

            [projects."/Users/me/code"]
            trust_level = "trusted"

            [tui] # the footer
            status_line = [
              "old-a",
              "old-b",
            ]
            theme = "dark"

            [mcp_servers.docs]
            command = "docs-mcp"
            args = ["--port", "1"]
        """)
        text = self.install()
        lines = text.splitlines()
        self.assertEqual(lines[0], "# my codex config")
        self.assertIn('model = "test-model"', lines)
        self.assertNotIn("gpt-old", text)
        self.assertEqual(text.count("model ="), 1)
        self.assertIn('approval_policy = "never"', lines)
        self.assertLess(lines.index('approval_policy = "never"'), lines.index('[projects."/Users/me/code"]'),
                        "root keys must stay above the first table")
        self.assertIn('notify = ["a", "b"]', lines)
        self.assertIn('trust_level = "trusted"', lines)
        self.assertIn('status_line = ["model", "dir"]', lines)
        self.assertNotIn("old-a", text, "a multi-line value must be replaced whole")
        self.assertIn('theme = "dark"', lines)
        self.assertIn("status_line_use_colors = true", lines)
        self.assertEqual(text.count("[tui]"), 1)
        self.assertIn("[tui] # the footer", lines)
        self.assertIn('args = ["--port", "1"]', lines)
        self.assertTrue(lines[-1].startswith("web_search"), "new tables are appended at the end")
        self.assertIn("[features]", lines)

    def test_new_file(self):
        text = self.install()
        self.assertTrue(text.startswith('model = "test-model"\n'))
        self.assertIn('\n\n[tui]\nstatus_line = ["model", "dir"]\nstatus_line_use_colors = true\n', text)

    def test_quoted_keys_and_tables_match_bare_spellings(self):
        write(self.path, '"model" = "x"\n\n[ "tui" ]\n"status_line" = []\n')
        text = self.install()
        self.assertEqual(text.count("model ="), 1)
        self.assertEqual(text.count("status_line ="), 1)
        self.assertNotIn("\n[tui]\n", text)

    def test_idempotent(self):
        write(self.path, '[tui]\ntheme = "dark"\n')
        self.install()
        before = self.path.read_text()
        out = self.run_dstack(self.repo, "install").stdout
        self.assertNotIn("updated", out)
        self.assertEqual(self.path.read_text(), before)


class DryRunTest(DstackTestCase):
    def test_dry_run_writes_nothing(self):
        repo = self.make_repo()
        write(self.home / ".claude/CLAUDE.md", "mine\n")
        write(self.home / ".claude/settings.json", '{"theme": "dark"}\n')
        write(self.home / ".codex/config.toml", 'model = "old"\n')
        (self.home / ".claude/skills").mkdir()
        (self.home / ".claude/skills/gone").symlink_to(repo / "vendor/alpha/skills/gone")
        before = snapshot(self.home)
        out = self.run_dstack(repo, "install", "--dry-run").stdout
        self.assertEqual(snapshot(self.home), before)
        self.assertIn("would link ~/.claude/skills/one ->", out)
        self.assertIn("would back up ~/.claude/CLAUDE.md ->", out)
        self.assertIn("would prune ~/.claude/skills/gone", out)
        self.assertIn("would update ~/.claude/settings.json (keys: model,", out)
        self.assertIn("would update ~/.codex/config.toml (keys: model, approval_policy,", out)
        self.assertIn("change(s) would be made", out)

    def test_dry_run_after_install_reports_up_to_date(self):
        repo = self.make_repo()
        self.run_dstack(repo, "install")
        out = self.run_dstack(repo, "install", "--dry-run").stdout
        self.assertIn("already up to date", out)
        self.assertNotIn("would", out)


class DoctorStatusTest(DstackTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()

    def test_doctor_fails_before_install_and_passes_after(self):
        self.assertIn("is missing", self.run_dstack(self.repo, "doctor", expect=1).stdout)
        self.run_dstack(self.repo, "install")
        out = self.run_dstack(self.repo, "doctor").stdout
        self.assertNotIn("✗", out)
        self.assertIn("✓ 10 managed links valid", out)
        self.assertIn("all good", out)

    def test_doctor_fails_on_broken_link(self):
        self.run_dstack(self.repo, "install")
        shutil.rmtree(self.repo / "vendor/beta/skills/three")
        out = self.run_dstack(self.repo, "doctor", expect=1).stdout
        self.assertIn("✗ ~/.claude/skills/three", out)
        self.assertIn("dangling", out)
        self.assertIn("vendor/beta: locked skills missing: three", out)
        self.assertIn("broken three", self.run_dstack(self.repo, "status", "--offline", expect=1).stdout)

    def test_doctor_fails_on_drifted_config_and_link(self):
        self.run_dstack(self.repo, "install")
        s = self.home / ".claude/settings.json"
        s.write_text(s.read_text().replace("test-model", "other"))
        (self.home / ".codex/AGENTS.md").unlink()
        (self.home / ".codex/AGENTS.md").symlink_to(self.tmp)
        out = self.run_dstack(self.repo, "doctor", expect=1).stdout
        self.assertIn("✗ ~/.claude/settings.json: managed keys differ", out)
        self.assertIn(f"✗ ~/.codex/AGENTS.md points to {self.tmp}", out)

    def test_doctor_checks_frontmatter_collisions_and_scripts(self):
        write(self.repo / "vendor/alpha/skills/two/SKILL.md", "---\nname: wrong\n---\n")
        make_skill(self.repo / "vendor/beta/skills", "one")
        lock = json.loads((self.repo / "dstack.lock.json").read_text())
        lock["sources"]["beta"]["skills"].append("one")
        (self.repo / "dstack.lock.json").write_text(json.dumps(lock))
        (self.repo / "config/hooks/guard.sh").chmod(0o644)
        out = self.run_dstack(self.repo, "doctor", "--repo-only", expect=1).stdout
        self.assertIn("name `wrong` does not match directory `two`", out)
        self.assertIn("no `description`", out)
        self.assertIn("`one` comes from both alpha and beta", out)
        self.assertIn("config/hooks/guard.sh is referenced by config but is not executable", out)

    def test_doctor_repo_only_ignores_home(self):
        out = self.run_dstack(self.repo, "doctor", "--repo-only").stdout
        self.assertNotIn("managed links", out)
        self.assertIn("✓ vendor/ matches the lock (3 skills)", out)
        self.assertEqual(snapshot(self.home), {})

    def test_doctor_repo_only_catches_lock_vendor_mismatch(self):
        make_skill(self.repo / "vendor/alpha/skills", "extra")
        (self.repo / "vendor/orphan").mkdir()
        out = self.run_dstack(self.repo, "doctor", "--repo-only", expect=1).stdout
        self.assertIn("vendor/alpha: skills not in the lock: extra", out)
        self.assertIn("vendor/ has directories no source owns: orphan", out)

    def test_doctor_repo_only_rejects_invalid_toml_value(self):
        path = self.repo / "config/codex/config.toml"
        path.write_text(path.read_text() + "\nmodel_verbosity = not-a-valid-value\n")
        out = self.run_dstack(self.repo, "doctor", "--repo-only", expect=1).stdout
        self.assertIn("repo config:", out)
        self.assertIn("not-a-valid-value", out)
        self.assertNotIn("all good", out)
        self.run_dstack(self.repo, "install", expect=1)
        self.assertFalse((self.home / ".codex/config.toml").exists(), "install wrote invalid TOML")

    def test_status_exit_codes(self):
        out = self.run_dstack(self.repo, "status", "--offline", expect=1).stdout
        self.assertIn(f"{self.home}/.claude/skills: 0/3 linked, missing one, two, three", out)
        self.run_dstack(self.repo, "install")
        out = self.run_dstack(self.repo, "status", "--offline").stdout
        self.assertIn(f"{self.home}/.claude/skills: 3/3 linked", out)
        self.assertIn("instructions and agents: 4/4 linked", out)
        self.assertIn("config: managed keys in sync", out)
        self.assertIn("alpha: 2 skills @ aaaaaaa (upstream not checked)", out)

    def test_status_reports_unreachable_upstream_without_failing(self):
        self.run_dstack(self.repo, "install")
        out = self.run_dstack(self.repo, "status").stdout
        self.assertIn("alpha: 2 skills @ aaaaaaa (upstream unreachable)", out)


class UninstallTest(DstackTestCase):
    def test_uninstall_removes_only_owned_links(self):
        repo = self.make_repo()
        write(self.home / ".claude/CLAUDE.md", "mine\n")
        self.run_dstack(repo, "install")
        foreign = self.home / ".claude/skills/foreign"
        foreign.symlink_to(self.tmp)
        mine = make_skill(self.home / ".agents/skills", "mine")
        settings = (self.home / ".claude/settings.json").read_text()

        before = snapshot(self.home)
        out = self.run_dstack(repo, "uninstall", "--dry-run").stdout
        self.assertEqual(snapshot(self.home), before)
        self.assertIn("would remove 10 link(s)", out)

        out = self.run_dstack(repo, "uninstall").stdout
        self.assertIn("removed 10 link(s)", out)
        self.assertIn(".dstack-backups", out)
        remaining = [p for p in self.home.rglob("*") if p.is_symlink()]
        self.assertEqual(remaining, [foreign])
        self.assertTrue(mine.exists())
        self.assertEqual((self.home / ".claude/settings.json").read_text(), settings)
        self.assertEqual(len(backups(self.home)), 1)


class SyncTest(DstackTestCase):
    """sync against a local bare repository, so no network is needed."""

    def git(self, *args: str, cwd: Path) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True,
                              capture_output=True, text=True).stdout.strip()

    def make_upstream(self) -> tuple[str, Path]:
        work = self.tmp / "upstream-work"
        for skill in ("one", "two", "three"):
            make_skill(work / "skills", skill)
        write(work / "LICENSE", "MIT\n")
        write(work / "agents/helper.md", "# helper\n")
        self.git("init", "--quiet", "-b", "main", cwd=work)
        self.git("add", ".", cwd=work)
        self.git("commit", "--quiet", "-m", "init", cwd=work)
        bare = self.tmp / "upstream.git"
        self.git("clone", "--quiet", "--bare", str(work), str(bare), cwd=self.tmp)
        return f"file://{bare}", work

    def configure(self, repo: Path, url: str, beta_skills: dict) -> None:
        manifest = json.loads((repo / "dstack.json").read_text())
        for name in ("alpha", "beta"):
            manifest["sources"][name]["repo"] = url
        manifest["sources"]["beta"]["skills"] = beta_skills
        (repo / "dstack.json").write_text(json.dumps(manifest, indent=2))

    def test_sync_vendors_and_locks(self):
        repo = self.make_repo()
        url, work = self.make_upstream()
        self.configure(repo, url, {"three": "skills/three"})
        shutil.rmtree(repo / "vendor")
        out = self.run_dstack(repo, "sync").stdout
        self.assertIn("alpha: 3 skills", out)
        self.assertIn("warning: `three` comes from both alpha and beta", out)
        lock = json.loads((repo / "dstack.lock.json").read_text())
        head = self.git("rev-parse", "HEAD", cwd=work)
        self.assertEqual(lock["sources"]["alpha"], {"repo": url, "ref": "main", "commit": head,
                                                    "skills": ["one", "three", "two"]})
        self.assertTrue((repo / "vendor/alpha/agents/helper.md").exists())
        self.assertTrue((repo / "vendor/beta/skills/three/SKILL.md").exists())
        self.assertEqual(sorted(p.name for p in (repo / "vendor").iterdir()), ["alpha", "beta"])
        self.assertFalse(list((repo / "vendor").glob(".*")), "staging directories were left behind")
        self.run_dstack(repo, "install")

    def test_sync_failure_keeps_vendor_and_lock(self):
        repo = self.make_repo()
        url, _ = self.make_upstream()
        self.configure(repo, url, {"three": "skills/three", "nope": "skills/nope"})
        before = snapshot(repo / "vendor")
        lock_before = (repo / "dstack.lock.json").read_text()
        proc = self.run_dstack(repo, "sync", expect=1)
        self.assertIn("beta: these skills have no SKILL.md upstream: nope (skills/nope)", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(snapshot(repo / "vendor"), before, "a failed sync changed vendor/")
        self.assertEqual((repo / "dstack.lock.json").read_text(), lock_before)

    def test_sync_missing_file_and_unknown_source(self):
        repo = self.make_repo()
        url, _ = self.make_upstream()
        self.configure(repo, url, {"three": "skills/three"})
        manifest = json.loads((repo / "dstack.json").read_text())
        manifest["sources"]["alpha"]["files"].append("NOPE.md")
        (repo / "dstack.json").write_text(json.dumps(manifest))
        self.assertIn("alpha: these files do not exist upstream: NOPE.md",
                      self.run_dstack(repo, "sync", expect=1).stderr)
        self.assertIn("unknown source(s): gamma", self.run_dstack(repo, "sync", "gamma", expect=1).stderr)

    def test_sync_one_source(self):
        repo = self.make_repo()
        url, _ = self.make_upstream()
        self.configure(repo, url, {"three": "skills/three"})
        self.run_dstack(repo, "sync", "beta")
        lock = json.loads((repo / "dstack.lock.json").read_text())
        self.assertEqual(lock["sources"]["alpha"]["commit"], "a" * 40, "sync beta touched alpha")
        self.assertNotEqual(lock["sources"]["beta"]["commit"], "b" * 40)


    def test_partial_sync_keeps_sources_removed_from_manifest(self):
        repo = self.make_repo()
        url, _ = self.make_upstream()
        self.configure(repo, url, {"three": "skills/three"})
        manifest = json.loads((repo / "dstack.json").read_text())
        del manifest["sources"]["alpha"]
        manifest["agents"] = []
        (repo / "dstack.json").write_text(json.dumps(manifest, indent=2))

        self.run_dstack(repo, "sync", "beta")
        lock = json.loads((repo / "dstack.lock.json").read_text())
        self.assertIn("alpha", lock["sources"], "a partial sync dropped an unselected source from the lock")
        self.assertTrue((repo / "vendor/alpha").is_dir())
        self.assertNotIn("no source owns", self.run_dstack(repo, "doctor", "--repo-only", expect=None).stdout)

        out = self.run_dstack(repo, "sync").stdout
        self.assertIn("alpha: removed (no longer in dstack.json)", out)
        lock = json.loads((repo / "dstack.lock.json").read_text())
        self.assertNotIn("alpha", lock["sources"])
        self.assertFalse((repo / "vendor/alpha").exists())


class TestCommandTest(DstackTestCase):
    def test_runs_unittest_and_shell_checks(self):
        repo = self.make_repo()
        write(repo / "tests/test_sample.py", """
            import unittest
            class T(unittest.TestCase):
                def test_ok(self):
                    pass
        """)
        proc = self.run_dstack(repo, "test", "-v")
        self.assertIn("test_ok", proc.stderr, "-v was not forwarded to unittest")
        self.assertIn("bash -n: 1/1 scripts parse", proc.stdout)
        self.assertIn("all checks passed", proc.stdout)

        write(repo / "config/hooks/broken.sh", "if then fi (\n", 0o755)
        proc = self.run_dstack(repo, "test", expect=1)
        self.assertIn("bash -n config/hooks/broken.sh", proc.stdout)

    def test_failing_test_fails(self):
        repo = self.make_repo()
        write(repo / "tests/test_sample.py", """
            import unittest
            class T(unittest.TestCase):
                def test_bad(self):
                    self.fail("nope")
        """)
        self.assertIn("FAILED: unittest", self.run_dstack(repo, "test", expect=1).stdout)


class RealRepoTest(DstackTestCase):
    """The repository as committed: install into a temp home, then doctor and a second install."""

    def test_real_repo_installs_cleanly(self):
        repo = copy_real_repo(self.tmp)
        lock = json.loads((REPO / "dstack.lock.json").read_text())
        nskills = len({s for e in lock["sources"].values() for s in e["skills"]}
                      | {p.name for p in (REPO / "skills").iterdir() if (p / "SKILL.md").exists()})
        out = self.run_dstack(repo, "install").stdout
        self.assertIn(f"linked {nskills} skills", out)
        self.assertEqual(len(list((self.home / ".claude/skills").iterdir())), nskills)
        self.run_dstack(repo, "doctor")
        before = snapshot(self.home)
        self.assertNotIn("updated", self.run_dstack(repo, "install").stdout)
        self.assertEqual(snapshot(self.home), before)
        if tomllib:
            tomllib.loads((self.home / ".codex/config.toml").read_text())


if __name__ == "__main__":
    unittest.main()
