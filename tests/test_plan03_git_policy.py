"""Git publication boundaries (plan 05, B1 and B2); commit messages are not checked (D-R1)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import copilot_role_guard as roles
from scripts import copilot_safety_hook as safety
from scripts import git_workflow_policy as policy


class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def invoke(self, module, command=None, role="developer", tool="execute/runInTerminal", payload=None):
        event = {"cwd": str(self.root), "tool_name": tool,
                 "tool_input": payload if payload is not None else {"command": command}}
        out = StringIO()
        argv = ["hook", "--role", role] if module is roles else ["hook"]
        with patch("sys.stdin", StringIO(json.dumps(event))), patch("sys.argv", argv), \
                patch.object(module, "HARNESS_ROOT", self.root), patch.object(module, "_log_decision"), redirect_stdout(out):
            module.main()
        result = json.loads(out.getvalue())
        return "allow" if result.get("continue") else result["hookSpecificOutput"]["permissionDecision"]

    def test_everyday_git_is_allowed_for_every_role_with_any_commit_message(self):
        commands = (
            "git status", "git add .", "git add -A", "git commit -m 'unformatted subject'",
            "git commit -am '[WI-123] Work — AB#456'", "git commit --amend --no-edit",
            "git switch main", "git checkout -b arbitrary/name", "git branch -d merged/name",
            "git stash pop", "git fetch upstream", "git pull --rebase", "git rebase --abort",
            "git cherry-pick HEAD~2", "git clean -fd", "git tag -d old", "git config user.name Example",
            "git -C elsewhere status", "git -c color.ui=always status", "gh pr view 42",
            "gh repo view unrelated/project", "gh release view v1", "gh pr edit 42 --body-file b.md",
            "cd ../different/repository && git status", "git diff > /tmp/diff.patch",
        )
        for role in roles.ROLES:
            for command in commands:
                with self.subTest(role=role, command=command):
                    self.assertEqual("allow", self.invoke(roles, command, role))
        for command in commands:
            with self.subTest(hook="safety", command=command):
                self.assertEqual("allow", self.invoke(safety, command))

    def test_operations_reserved_for_a_person_are_denied_everywhere(self):
        # Plan 05, boundary B1.
        commands = (
            "git merge arbitrary", "git rebase main", "git reset --hard HEAD", "git branch -D old",
            "git branch -d -f old", "gh pr merge 42 --squash --admin", "gh pr review 42 --approve",
            "gh pr ready 42", "gh api repos/example/project", "gh release create v1",
            "gh repo delete example/project", "gh secret set TOKEN", "gh auth token",
            "git add . && git commit -m 'Save' && git merge main",
        )
        for command in commands:
            with self.subTest(hook="safety", command=command):
                self.assertEqual("deny", self.invoke(safety, command))
            for role in roles.ROLES:
                with self.subTest(role=role, command=command):
                    self.assertEqual("deny", self.invoke(roles, command, role))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True).stdout.strip()

    def test_push_only_feature_branches_by_the_git_agent(self):
        # Plan 05, boundary B2.
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "base")
        self.git("switch", "-q", "-c", "feat/1201-routing")
        for command in ("git push -u origin feat/1201-routing", "git push origin HEAD:feat/1201-routing", "git push"):
            with self.subTest(command=command):
                self.assertEqual("allow", self.invoke(roles, command, "git-agent"))
                self.assertEqual("allow", self.invoke(safety, command))
                self.assertEqual("deny", self.invoke(roles, command, "developer"))
        for command in ("git push origin main", "git push origin HEAD:main", "git push --force origin feat/x",
                        "git push -f", "git push origin +feat/x", "git push origin :feat/x",
                        "git push --delete origin feat/x", "git push --tags", "git push --mirror"):
            with self.subTest(command=command):
                self.assertEqual("deny", self.invoke(roles, command, "git-agent"))
                self.assertEqual("deny", self.invoke(safety, command))

    def test_draft_pr_needs_a_pass_delivery_check_for_head(self):
        # Plan 05, D-B1 and boundary B2.
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "base")
        head = self.git("rev-parse", "HEAD")
        create = "gh pr create --draft --title Routing --body-file .cache/github/pr-body.md"
        self.assertEqual("deny", self.invoke(roles, "gh pr create --title Routing", "git-agent"))
        self.assertEqual("deny", self.invoke(roles, create, "git-agent"))
        report = self.root / "work-items/1201-routing/delivery-check.json"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"status": "FAIL", "commit": head}), encoding="utf-8")
        self.assertEqual("deny", self.invoke(roles, create, "git-agent"))
        report.write_text(json.dumps({"status": "PASS", "commit": "0" * 40}), encoding="utf-8")
        self.assertEqual("deny", self.invoke(roles, create, "git-agent"))
        report.write_text(json.dumps({"status": "PASS", "commit": head}), encoding="utf-8")
        self.assertEqual("allow", self.invoke(roles, create, "git-agent"))
        self.assertEqual("allow", self.invoke(safety, create))
        self.assertEqual("deny", self.invoke(roles, create, "developer"))

    def test_mixed_shell_does_not_exempt_non_git_commands(self):
        for command in (
            "git status && rm -rf force-app", "git status; sf project deploy start --target-org prod",
            "git status | python -c 'print(1)'", "git commit -m \"[chore] $(rm -rf force-app)\"",
        ):
            with self.subTest(command=command):
                if "rm -rf" in command:
                    self.assertEqual("deny", self.invoke(safety, command))
                if "sf project" in command:
                    self.assertEqual("deny", self.invoke(roles, command, "reviewer"))
                if "python -c" in command:  # plan 05, D-T1: no role allowlist
                    self.assertEqual("allow", self.invoke(roles, command, "reviewer"))

    def test_pr_body_text_is_data_for_every_role(self):
        # Plan 05, D-R2: no per-role edit allowlist; the PR body may quote denied commands.
        payload = {"filePath": str(self.root / policy.PR_BODY), "content": "Describe git reset --hard as data."}
        for role in roles.ROLES:
            with self.subTest(role=role):
                self.assertEqual("allow", self.invoke(roles, role=role, tool="create_file", payload=payload))
        self.assertEqual("allow", self.invoke(safety, tool="create_file", payload=payload))

    def test_pr_body_editor_does_not_follow_symlinks_or_hard_links(self):
        protected = self.root / "protected.md"
        protected.write_text("Keep this content", encoding="utf-8")
        body = self.root / policy.PR_BODY
        body.parent.mkdir(parents=True)
        os.link(protected, body)
        self.assertFalse(policy.pr_body_path(self.root, policy.PR_BODY))
        body.unlink()
        try:
            body.symlink_to(protected)
        except OSError:
            self.skipTest("This host cannot create symlink fixtures")
        self.assertFalse(policy.pr_body_path(self.root, policy.PR_BODY))
        self.assertEqual("Keep this content", protected.read_text(encoding="utf-8"))


class ShellParsingTests(unittest.TestCase):
    def inspect(self, command, **kwargs):
        return policy.inspect_command(command, Path.cwd(), **kwargs)

    def test_paths_flags_chains_navigation_and_redirects_are_not_restrictions(self):
        for command in (
            '"C:\\Program Files\\Git\\cmd\\git.exe" -C "C:\\repo" status',
            '/usr/local/bin/git -c core.quotePath=false --git-dir=.git status',
            'cd /tmp && git add -A && git commit -m "[chore] Save; pipes | are literal"',
            'git status; git log > /tmp/log.txt 2>&1', 'git diff | git apply',
            "env GIT_INDEX_FILE=other-index git add -A", "command git status", "GIT_DIR=.git git status",
            'git -C ${PWD} status', 'if git status; then git diff; fi', 'git status &> /tmp/log.txt',
            "bash -c 'git status && git diff'", 'cmd /c "git status"',
            'git show HEAD~$((1 + 1))', 'git add -- $(git diff --name-only)',
        ):
            with self.subTest(command=command):
                result = self.inspect(command)
                self.assertTrue(result.has_git)
                self.assertEqual("allow", result.decision)
                self.assertEqual((), result.remaining_commands)

    def test_mixed_commands_and_nested_substitutions_stay_visible(self):
        for command, expected in (
            ("git status && sf project deploy start", "sf project deploy start"),
            ("git status; rm -rf force-app", "rm -rf force-app"),
            ('git commit -m "[chore] $(sf org display)"', "sf org display"),
            ('git status `rm -rf force-app`', "rm -rf force-app"),
            ('git status <(rm -rf force-app)', "rm -rf force-app"),
            ("bash -c 'git status && rm -rf force-app'", "rm -rf force-app"),
            ("cd /tmp && git status && sf project deploy start", "cd /tmp && sf project deploy start"),
            ('git show HEAD~$((1 + $(sf org display)))', "sf org display"),
        ):
            with self.subTest(command=command):
                result = self.inspect(command, windows=False)
                self.assertTrue(result.has_git)
                self.assertIn(expected, result.remaining_commands)
        literal = self.inspect("git commit -m '[chore] Document $(rm -rf) and git reset --hard'")
        self.assertEqual((), literal.remaining_commands)
        self.assertEqual("allow", literal.decision)

    def test_parse_errors_remain_on_normal_policy_path(self):
        for command in ('git commit -m "unterminated', "git status $(unfinished"):
            result = self.inspect(command)
            self.assertFalse(result.has_git)
            self.assertEqual((command,), result.remaining_commands)

    def test_wrapper_argument_values_cannot_masquerade_as_git_executables(self):
        for command in ("exec -a git rm -rf /tmp/example", "env -a git sf project deploy start",
                        "env --argv0 git sf project deploy start", "env --unknown-option git rm -rf /tmp/example"):
            with self.subTest(command=command):
                result = self.inspect(command)
                self.assertFalse(result.has_git)
                self.assertEqual((command,), result.remaining_commands)
                mixed = self.inspect("git status && " + command)
                self.assertTrue(mixed.has_git)
                self.assertEqual((command,), mixed.remaining_commands)

    def test_windows_messages_paths_and_non_git_chain(self):
        result = self.inspect('"C:\\Program Files\\Git\\cmd\\git.exe" commit -m "[chore] Windows"', windows=True)
        self.assertTrue(result.has_git)
        self.assertEqual("allow", result.decision)
        self.assertEqual(("Remove-Item -Recurse force-app",),
                         self.inspect("git status & Remove-Item -Recurse force-app", windows=True).remaining_commands)
        self.assertEqual("allow", self.inspect('git commit -m "%MESSAGE%"', windows=True).decision)
        self.assertEqual(("rm -rf force-app",), self.inspect(
            "bash -c 'git status `rm -rf force-app`'", windows=True).remaining_commands)


if __name__ == "__main__":
    unittest.main()
