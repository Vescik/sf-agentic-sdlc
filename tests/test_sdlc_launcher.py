"""Delivery launcher (plan 05, D-A2 and D-SR): developer org only, root and trust handling."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import sdlc


def config(tmp: Path, salesforce: dict) -> Path:
    path = tmp / "harness.local.json"
    path.write_text(json.dumps({"salesforce": salesforce}), encoding="utf-8")
    return path


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_accepts_only_a_configured_developer_org(self):
        orgs = [{"alias": "agent-dev", "environment": "dev"}, {"alias": "legacy", "environment": "development"},
                {"alias": "qa", "environment": "uat"}, {"alias": "prod", "environment": "prod"}]
        self.assertEqual("agent-dev", sdlc.developer_agent_org(config(self.dir, {"agentOrg": "agent-dev", "orgs": orgs})))
        self.assertEqual("legacy", sdlc.developer_agent_org(config(self.dir, {"agentOrg": "legacy", "orgs": orgs})))
        for alias in ("qa", "prod"):
            with self.subTest(alias=alias), self.assertRaisesRegex(sdlc.LaunchError, "developer org"):
                sdlc.developer_agent_org(config(self.dir, {"agentOrg": alias, "orgs": orgs}))
        with self.assertRaisesRegex(sdlc.LaunchError, "not a salesforce.orgs entry"):
            sdlc.developer_agent_org(config(self.dir, {"agentOrg": "unknown", "orgs": orgs}))
        with self.assertRaisesRegex(sdlc.LaunchError, "agentOrg is not set"):
            sdlc.developer_agent_org(config(self.dir, {"orgs": orgs}))
        with self.assertRaisesRegex(sdlc.LaunchError, "missing or invalid"):
            sdlc.developer_agent_org(self.dir / "missing.json")

    def test_command_defaults_the_agent_and_trusts_prompt_mode_only(self):
        agents = self.dir / "agents"
        agents.mkdir()
        self.assertEqual(["copilot", "--agent", "designer"], sdlc.copilot_command([], agents))
        (agents / "sdlc-conductor.agent.md").write_text("---\n---\n")
        self.assertEqual(["copilot", "--agent", "sdlc-conductor"], sdlc.copilot_command([], agents))
        self.assertEqual(["copilot", "--agent", "developer", "-p", "go", "--trust-folder"],
                         sdlc.copilot_command(["--agent", "developer", "-p", "go"], agents))
        self.assertEqual(["copilot", "--agent=reviewer", "--prompt=go", "--trust-folder"],
                         sdlc.copilot_command(["--agent=reviewer", "--prompt=go"], agents))


if __name__ == "__main__":
    unittest.main()


class FinishDeliveryTest(unittest.TestCase):
    """Plan 05: the launcher starts S6 and S7 when the conductor skipped them after a PASS."""

    def setUp(self):
        import subprocess
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.wi = self.root / "work-items" / "1-case-routing"
        self.wi.mkdir(parents=True)
        self.head = "a" * 40
        self.prs = "[]"
        self.calls = []
        for name, value in (("ROOT", self.root), ("DELIVERY_CACHE", self.root / ".cache/delivery"),
                            ("PR_BODY", self.root / ".cache/github/pr-body.md")):
            patcher = mock.patch.object(sdlc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.subprocess = subprocess

    def report(self, status="PASS", commit=None):
        (self.wi / "delivery-check.json").write_text(json.dumps({
            "status": status, "commit": commit or self.head,
            "criteria": [{"id": "SC1", "status": status, "title": "covered"}], "manualSteps": []}))

    def runner(self, command, **kwargs):
        self.calls.append(command)
        out = ""
        if command[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            out = "feat/1-case-routing\n"
        elif command[:2] == ["git", "rev-parse"]:
            out = self.head + "\n"
        elif command[:3] == ["gh", "pr", "list"]:
            out = self.prs
        elif command[0] == "copilot":
            agent = command[command.index("--agent") + 1]
            out = json.dumps({"type": "assistant.message", "data": {"content": f"{agent} answer"}}) + "\n"
        return self.subprocess.CompletedProcess(command, 0, out, "")

    def agents(self):
        return [c[c.index("--agent") + 1] for c in self.calls if c[0] == "copilot"]

    def test_pass_without_review_or_pr_runs_reviewer_then_git_agent(self):
        self.report()
        notes = sdlc.finish_delivery(["--model", "auto"], {}, self.runner)
        self.assertEqual(["reviewer", "git-agent"], self.agents())
        copilot = [c for c in self.calls if c[0] == "copilot"][1]
        self.assertIn("--model", copilot)
        self.assertIn("--draft", copilot[copilot.index("-p") + 1])
        body = (self.root / ".cache/github/pr-body.md").read_text()
        self.assertIn("## S6 implementation review", body)
        self.assertIn("reviewer answer", body)
        self.assertTrue(any("S7" in note for note in notes))

    def test_nothing_runs_without_a_pass_for_head(self):
        self.report(status="FAIL")
        self.assertIn("not finishing", sdlc.finish_delivery([], {}, self.runner)[0])
        self.report(commit="b" * 40)
        self.assertIn("not finishing", sdlc.finish_delivery([], {}, self.runner)[0])
        self.assertEqual([], self.agents())

    def test_existing_review_and_open_pr_are_not_redone(self):
        self.report()
        (self.root / ".cache/delivery").mkdir(parents=True)
        (self.root / ".cache/delivery/1-case-routing-implementation-review.md").write_text("# S6\n\nok\n")
        self.prs = '[{"url": "https://example.invalid/pr/1"}]'
        notes = sdlc.finish_delivery([], {}, self.runner)
        self.assertEqual([], self.agents())
        self.assertIn("already done", notes[-1])

    def test_session_args_drop_agent_prompt_and_output_format(self):
        self.assertEqual(["--model", "auto", "--allow-all-tools"], sdlc.strip_session_args(
            ["--agent", "sdlc-conductor", "-p", "deliver x", "--model", "auto", "--output-format", "json",
             "--allow-all-tools", "--trust-folder", "--no-finish"]))
