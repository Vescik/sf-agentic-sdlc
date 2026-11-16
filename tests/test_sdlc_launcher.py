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
