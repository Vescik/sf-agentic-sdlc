"""Solution documentation: editor and Git rules after plan 05.

Editor (D-R2): every role may write documentation; only the shared protected files and paths
outside the repository are denied, including through symlinks and traversal.
Git: local add and commit stay available to every role without editor path checks.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import copilot_role_guard as roles


class SolutionDocumentationFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"
        self.root.mkdir()
        self.paths = [f"docs/solutions/invoice-approval/{name}.md"
                      for name in ("overview", "flows", "components")]

    def write(self, path, content="# Source-backed documentation\n"):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return file

    def symlink(self, alias, target, *, directory=False):
        alias = self.root / alias
        alias.parent.mkdir(parents=True, exist_ok=True)
        try:
            alias.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            if os.name != "nt":
                raise
            self.skipTest("This host cannot create symlink fixtures: " + str(exc))
        return alias

    def invoke(self, payload, *, role="developer", tool="edit/editFiles", cwd=None):
        event = {"cwd": str(cwd or self.root), "tool_name": tool, "tool_input": payload}
        stdout = StringIO()
        with (patch("sys.stdin", StringIO(json.dumps(event))),
              patch("sys.argv", ["guard", "--role", role]),
              patch.object(roles, "HARNESS_ROOT", self.root),
              patch.object(roles, "_log_decision"), redirect_stdout(stdout)):
            self.assertEqual(0, roles.main())
        response = json.loads(stdout.getvalue())
        return "allow" if response.get("continue") else response["hookSpecificOutput"]["permissionDecision"]

    def edit(self, path, **kwargs):
        return self.invoke({"filePath": str(path), "content": "Updated documentation\n"}, **kwargs)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def git_decision(self, *args, role="developer"):
        command = subprocess.list2cmdline(["git", *args]) if os.name == "nt" else shlex.join(["git", *args])
        return self.invoke({"command": command}, role=role, tool="execute/runInTerminal")

    def init_git(self, branch="work-item/123-invoice-approval", *, with_context=True):
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Local test")
        self.git("config", "user.email", "local-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write(".gitignore", ".cache/\noutput/\n")
        if branch.startswith("work-item/") and with_context:
            self.write("work-items/123-invoice-approval/ado-context.md", "# Work Item 123\nType: User Story\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.git("switch", "-c", branch)


class SolutionDocumentationEditTests(SolutionDocumentationFixture):
    """Plan 05, D-R2: documentation is ordinary repository content for every role."""

    def test_every_role_can_create_and_update_solution_and_other_documentation(self):
        for role in roles.ROLES:
            for path in (*self.paths, "docs/solutions/Billing/extra.md", "docs/other/overview.md"):
                with self.subTest(role=role, path=path):
                    self.assertEqual("allow", self.edit(self.root / path, role=role))
                    self.write(path)
                    self.assertEqual("allow", self.edit(path, role=role))

    def test_aliases_cannot_reach_protected_files_or_leave_the_repository(self):
        protected = self.write("scripts/copilot_safety_hook.py", "# guard\n")
        outside = Path(self.temp.name) / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        self.symlink("docs/solutions/invoice-approval/overview.md", protected)
        self.symlink("docs/solutions/invoice-approval/flows.md", outside)
        for role in roles.ROLES:
            with self.subTest(role=role):
                expected = "ask" if role == roles.MAINTAINER_ROLE else "deny"
                self.assertEqual(expected, self.edit(self.paths[0], role=role))
                self.assertEqual("deny", self.edit(self.paths[1], role=role))
                self.assertEqual(expected, self.edit("docs/../scripts/copilot_safety_hook.py", role=role))
                self.assertEqual("deny", self.edit("../outside.md", role=role))
        self.assertEqual("# guard\n", protected.read_text(encoding="utf-8"))


class SolutionDocumentationGitTests(SolutionDocumentationFixture):
    def test_three_files_inherit_scoped_local_commit_and_preserve_unrelated_work(self):
        self.init_git()
        for path in self.paths:
            self.write(path)
        other = self.write("docs/unrelated.md", "Human notes\n")
        self.assertEqual("allow", self.git_decision("add", "--", *self.paths))
        self.git("add", "--", *self.paths)
        args = ("commit", "-m", "[WI-123] document invoice approval — AB#123", "--", *self.paths)
        self.assertEqual("allow", self.git_decision(*args))
        self.git(*args)
        self.assertEqual(set(self.paths), set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()))
        self.assertEqual("Human notes\n", other.read_text())
        self.assertEqual("?? docs/unrelated.md", self.git("status", "--short"))

    def test_git_authority_is_independent_of_editor_scope_for_every_role(self):
        self.init_git()
        for path in self.paths:
            self.write(path)
        self.write("docs/solutions/invoice-approval/extra.md")
        self.assertEqual("allow", self.git_decision("add", "--", *self.paths, "docs/solutions/invoice-approval/extra.md"))
        for role in roles.ROLES:
            with self.subTest(role=role):
                self.assertEqual("allow", self.git_decision("add", "--", *self.paths, role=role))

    def test_standalone_documentation_uses_existing_chore_commit_without_fictional_item(self):
        self.init_git("chore/document-invoice-approval")
        for path in self.paths:
            self.write(path)
        self.assertEqual("allow", self.git_decision("add", "--", *self.paths))
        self.git("add", "--", *self.paths)
        self.assertEqual("allow", self.git_decision("commit", "-m", "[docs] document invoice approval", "--", *self.paths))
        self.assertFalse((self.root / "work-items").exists())

    def test_existing_work_item_branch_can_commit_solution_docs_without_manufactured_intake(self):
        self.init_git(with_context=False)
        for path in self.paths:
            self.write(path)
        for additional in ("docs/solutions/invoice-approval/extra.md",
                           "force-app/main/default/classes/Example.cls",
                           "work-items/123-invoice-approval/design.md"):
            self.write(additional)
            self.assertEqual("allow", self.git_decision("add", "--", *self.paths, additional), additional)
            (self.root / additional).unlink()
        self.assertEqual("allow", self.git_decision("add", "--", *self.paths))
        self.git("add", "--", *self.paths)
        args = ("commit", "-m", "[WI-123] document invoice approval — AB#123", "--", *self.paths)
        self.assertEqual("allow", self.git_decision(*args))
        self.git(*args)
        self.assertEqual(set(self.paths), set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()))
        self.assertFalse((self.root / "work-items/123-invoice-approval/ado-context.md").exists())

    def test_git_path_handling_is_not_an_editor_permission_check(self):
        self.init_git()
        source = self.write("work-items/123-invoice-approval/design.md")
        self.symlink(self.paths[0], source)
        self.assertEqual("allow", self.git_decision("add", "--", self.paths[0]))
        self.assertEqual("allow", self.git_decision("add", "--", "docs/solutions/other/../invoice-approval/overview.md"))


if __name__ == "__main__":
    unittest.main()
