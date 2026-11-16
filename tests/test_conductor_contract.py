"""Plan 05 phase 3: the validator pins the conductor's delegation and its end-of-run success."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import validate_harness as vh

ROOT = Path(__file__).resolve().parents[1]
AGENT = ".github/agents/sdlc-conductor.agent.md"
SKILL = ".github/skills/deliver-requirement/SKILL.md"


class ConductorContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for relative in (AGENT, SKILL):
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, self.root / relative)

    def errors(self):
        audit = vh.Audit()
        vh.check_delivery_conductor(audit, self.root)
        return audit.errors

    def replace(self, relative, old, new):
        path = self.root / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_current_files_pass(self):
        self.assertEqual([], self.errors())

    def test_direct_org_tools_or_extra_delegates_fail(self):
        self.replace(AGENT, '"agent"]', '"agent", "salesforce/review_soql_query"]')
        self.replace(AGENT, '"git-agent"]', '"git-agent", "workspace-maintainer"]')
        errors = " ".join(self.errors())
        self.assertIn("reaches orgs only through its stations", errors)
        self.assertIn("delegates exactly to", errors)

    def test_skill_must_keep_budget_check_and_stations(self):
        self.replace(SKILL, "6 delivery checks", "unlimited checks")
        self.replace(SKILL, "| S6 implementation review", "| implementation review")
        errors = " ".join(self.errors())
        self.assertIn("attempt budget", errors)
        self.assertIn("missing S6", errors)


if __name__ == "__main__":
    unittest.main()
