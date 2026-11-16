"""End-of-run delivery check (SC1–SC5): contract .ai/contracts/delivery-success.md.

Each test builds a throwaway Git repository with a small SFDX project. Git runs for real; `sf`
and `npm` are answered from recorded JSON shapes, so no org is needed.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import check_delivery as cd

HANDLER = """public with sharing class CaseRouter {
    public static String route(String priority) {
        return priority == 'High' ? 'Tier2' : 'Tier1';
    }
}
"""
HANDLER_TEST = """@isTest
private class CaseRouterTest {
    @isTest static void routesHighToTier2() { System.assertEquals('Tier2', CaseRouter.route('High')); }
    @isTest static void routesOtherToTier1() { System.assertEquals('Tier1', CaseRouter.route('Low')); }
}
"""
META = '<?xml version="1.0" encoding="UTF-8"?>\n<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata"><apiVersion>67.0</apiVersion></ApexClass>\n'
REQUIREMENTS = """# Requirements

- AC-1: a High priority case is routed to Tier2.
- AC-2: any other case is routed to Tier1.
- AC-3: the routing field is visible on the case layout.
"""
TRACE = """# Acceptance trace

| AC | Covered by |
| --- | --- |
| AC-1 | CaseRouterTest.routesHighToTier2 |
| AC-2 | `CaseRouterTest.routesOtherToTier1` |
| AC-3 | manual: open a case and check the Routing field on the layout |
"""
CHANGED = [
    "force-app/main/default/classes/CaseRouter.cls",
    "force-app/main/default/classes/CaseRouter.cls-meta.xml",
    "force-app/main/default/classes/CaseRouterTest.cls",
    "force-app/main/default/classes/CaseRouterTest.cls-meta.xml",
    "force-app/main/default/lwc/routingBadge/routingBadge.js",
    "force-app/main/default/objects/Case/fields/Routing__c.field-meta.xml",
]
JOB = "0Af000000000001AAA"


def sh(root: Path, *args: str) -> None:
    subprocess.run(args, cwd=root, check=True, capture_output=True)


class FakeSalesforce:
    """Answers sf/npm; passes git through to the real repository."""

    def __init__(self):
        self.tests = [
            {"FullName": "CaseRouterTest.routesHighToTier2", "Outcome": "Pass"},
            {"FullName": "CaseRouterTest.routesOtherToTier1", "Outcome": "Pass"},
        ]
        self.outcome = "Passed"
        self.coverage = [{"name": "CaseRouter", "coveredPercent": 100}]
        self.deploy: dict = {
            "status": "Succeeded", "success": True, "checkOnly": False,
            "completedDate": "2999-01-01T00:00:00.000Z",
            "files": [{"state": "Changed", "filePath": p} for p in CHANGED],
        }
        self.npm_code = 0
        self.calls: list[list[str]] = []

    def __call__(self, command, cwd):
        self.calls.append(command)
        if command[0] == "git":
            return cd.run_command(command, cwd)
        if command[:4] == ["sf", "apex", "run", "test"]:
            result = {"summary": {"outcome": self.outcome, "testsRan": len(self.tests)},
                      "tests": self.tests, "coverage": {"coverage": self.coverage}}
            return (0 if self.outcome == "Passed" else 100), json.dumps({"status": 0, "result": result}), ""
        if command[:4] == ["sf", "project", "deploy", "report"]:
            return 0, json.dumps({"status": 0, "result": self.deploy}), ""
        if command[0] == "npm":
            return self.npm_code, "", "jest failed" if self.npm_code else ""
        raise AssertionError(f"unexpected command {command}")


class CheckDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        r = self.root
        sh(r, "git", "init", "-q", "-b", "main")
        sh(r, "git", "config", "user.email", "t@example.invalid")
        sh(r, "git", "config", "user.name", "t")
        (r / "sfdx-project.json").write_text(json.dumps({"packageDirectories": [{"path": "force-app", "default": True}]}))
        (r / "config").mkdir()
        (r / "config/harness.local.json").write_text(json.dumps({"salesforce": {"agentOrg": "agent-dev"}}))
        (r / ".gitignore").write_text("config/harness.local.json\nwork-items/*/delivery-check.json\n")
        (r / "force-app/main/default/classes").mkdir(parents=True)
        (r / "README.md").write_text("x\n")
        sh(r, "git", "add", "-A")
        sh(r, "git", "commit", "-qm", "base")
        sh(r, "git", "switch", "-qc", "feat/1201-routing")
        classes = r / "force-app/main/default/classes"
        (classes / "CaseRouter.cls").write_text(HANDLER)
        (classes / "CaseRouter.cls-meta.xml").write_text(META)
        (classes / "CaseRouterTest.cls").write_text(HANDLER_TEST)
        (classes / "CaseRouterTest.cls-meta.xml").write_text(META)
        (r / "force-app/main/default/lwc/routingBadge").mkdir(parents=True)
        (r / "force-app/main/default/lwc/routingBadge/routingBadge.js").write_text("export default class {}\n")
        (r / "force-app/main/default/objects/Case/fields").mkdir(parents=True)
        (r / "force-app/main/default/objects/Case/fields/Routing__c.field-meta.xml").write_text("<CustomField/>\n")
        self.wi = r / "work-items/1201-routing"
        self.wi.mkdir(parents=True)
        (self.wi / "requirements.md").write_text(REQUIREMENTS)
        (self.wi / "acceptance-trace.md").write_text(TRACE)
        (self.wi / "deploy-job-id").write_text(JOB + "\n")
        sh(r, "git", "add", "-A")
        sh(r, "git", "commit", "-qm", "routing")
        self.sf = FakeSalesforce()

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, **kwargs):
        return cd.check(Path("work-items/1201-routing"), root=self.root, runner=self.sf, **kwargs)

    def status(self, report, criterion):
        return next(c for c in report["criteria"] if c["id"] == criterion)

    def test_all_criteria_pass(self):
        report = self.run_check()
        self.assertEqual(report["status"], "PASS", json.dumps(report["criteria"], indent=1))
        self.assertEqual(report["agentOrg"], "agent-dev")
        self.assertEqual(report["deployJobId"], JOB)
        self.assertEqual(report["manualSteps"], ["AC-3: open a case and check the Routing field on the layout"])
        self.assertEqual(report["changedSourceFiles"], sorted(CHANGED))
        test_call = next(c for c in self.sf.calls if c[:4] == ["sf", "apex", "run", "test"])
        self.assertIn("RunLocalTests", test_call)
        self.assertEqual(test_call[test_call.index("--target-org") + 1], "agent-dev")

    def test_sc1_missing_trace_row_fails(self):
        (self.wi / "acceptance-trace.md").write_text(TRACE.replace("| AC-2 | `CaseRouterTest.routesOtherToTier1` |\n", ""))
        sh(self.root, "git", "commit", "-qam", "drop AC-2")
        sc1 = self.status(self.run_check(), "SC1")
        self.assertEqual(sc1["status"], "FAIL")
        self.assertIn("AC-2: no test or manual step", sc1["details"][0])

    def test_sc1_failing_or_invented_test_fails(self):
        self.sf.tests[0]["Outcome"] = "Fail"
        (self.wi / "acceptance-trace.md").write_text(TRACE.replace("CaseRouterTest.routesOtherToTier1", "CaseRouterTest.doesNotExist"))
        sh(self.root, "git", "commit", "-qam", "invented test")
        details = " ".join(self.status(self.run_check(), "SC1")["details"])
        self.assertIn("AC-1: CaseRouterTest.routesHighToTier2 outcome Fail", details)
        self.assertIn("AC-2: CaseRouterTest.doesNotExist does not exist", details)

    def test_sc2_failing_test_or_jest_fails(self):
        self.sf.outcome = "Failed"
        self.sf.tests.append({"FullName": "OtherTest.breaks", "Outcome": "Fail"})
        sc2 = self.status(self.run_check(), "SC2")
        self.assertEqual(sc2["status"], "FAIL")
        self.assertIn("OtherTest.breaks", " ".join(sc2["details"]))

        self.sf = FakeSalesforce()
        self.sf.npm_code = 1
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test:unit": "sfdx-lwc-jest"}}))
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-qm", "jest")
        self.assertEqual(self.status(self.run_check(), "SC2")["status"], "FAIL")

    def test_sc2_unrelated_org_failures_block_and_delivery_failures_are_repaired(self):
        # Owner rule 2026-11-16: an old failure outside the delivery is a blocker for a person;
        # a failure of the delivery's own tests, or one that names a changed component, is the
        # agent's to fix.
        self.sf.outcome = "Failed"
        self.sf.tests.append({"FullName": "LegacyTest.oldBreak", "ApexClass": {"Name": "LegacyTest"},
                              "Outcome": "CompileFail", "Message": "Method does not exist", "StackTrace": ""})
        report = self.run_check()
        self.assertEqual("BLOCKED", report["status"])
        self.assertEqual(["LegacyTest.oldBreak"], report["blockers"])
        self.assertIn("BLOCKER", " ".join(self.status(report, "SC2")["details"]))

        self.sf = FakeSalesforce()
        self.sf.outcome = "Failed"
        self.sf.tests[0]["Outcome"] = "Fail"
        self.sf.tests.append({"FullName": "AccountTest.regression", "ApexClass": {"Name": "AccountTest"},
                              "Outcome": "Fail", "Message": "System.DmlException",
                              "StackTrace": "Class.CaseRouter.route: line 3, column 1"})
        report = self.run_check()
        self.assertEqual(("FAIL", []), (report["status"], report["blockers"]))
        details = " ".join(self.status(report, "SC2")["details"])
        self.assertIn("fix them in this delivery: AccountTest.regression, CaseRouterTest.routesHighToTier2", details)
        self.assertNotIn("BLOCKER", details)

    def test_sc3_low_or_missing_coverage_fails_and_test_classes_are_exempt(self):
        self.sf.coverage = [{"name": "CaseRouter", "coveredPercent": 74}]
        sc3 = self.status(self.run_check(), "SC3")
        self.assertEqual((sc3["status"], sc3["details"]), ("FAIL", ["CaseRouter: 74%"]))
        self.sf.coverage = []
        self.assertEqual(self.status(self.run_check(), "SC3")["details"], ["CaseRouter: no coverage reported"])

    def test_sc4_missing_component_stale_or_check_only_deploy_fails(self):
        self.sf.deploy["files"] = [f for f in self.sf.deploy["files"] if "routingBadge" not in f["filePath"]]
        sc4 = self.status(self.run_check(), "SC4")
        self.assertEqual(sc4["status"], "FAIL")
        self.assertIn("lwc/routingBadge/routingBadge.js", sc4["details"][0])

        self.sf = FakeSalesforce()
        self.sf.deploy.update(completedDate="2000-01-01T00:00:00.000Z", checkOnly=True)
        details = " ".join(self.status(self.run_check(), "SC4")["details"])
        self.assertIn("before the last source commit", details)
        self.assertIn("check-only", details)

    def test_sc4_compares_with_the_last_source_commit_not_later_records(self):
        import os
        def commit_at(message, date):
            env = {**os.environ, "GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date}
            subprocess.run(["git", "commit", "-qam", message], cwd=self.root, env=env, check=True, capture_output=True)
        (self.root / "force-app/main/default/classes/CaseRouter.cls").write_text(HANDLER + "// v2\n")
        commit_at("source v2", "2030-01-01T10:00:00Z")
        (self.wi / "deploy-job-id").write_text(JOB + "\n")
        (self.wi / "acceptance-trace.md").write_text(TRACE + "\n")
        commit_at("record deploy job", "2030-01-03T10:00:00Z")
        self.sf.deploy["completedDate"] = "2030-01-02T10:00:00.000Z"
        self.assertEqual("PASS", self.status(self.run_check(), "SC4")["status"])
        self.sf.deploy["completedDate"] = "2029-12-31T10:00:00.000Z"
        self.assertIn("before the last source commit", self.status(self.run_check(), "SC4")["details"][0])

    def test_sc4_meta_and_bundle_files_match_their_component(self):
        self.sf.deploy["files"] = [
            {"state": "Changed", "filePath": str(self.root / "force-app/main/default/classes/CaseRouter.cls")},
            {"state": "Changed", "filePath": "force-app/main/default/classes/CaseRouterTest.cls-meta.xml"},
            {"state": "Changed", "filePath": "force-app/main/default/lwc/routingBadge/routingBadge.js-meta.xml"},
            {"state": "Created", "filePath": "force-app/main/default/objects/Case/fields/Routing__c.field-meta.xml"},
        ]
        self.assertEqual(self.status(self.run_check(), "SC4")["status"], "PASS")

    def test_sc4_falls_back_to_component_names(self):
        del self.sf.deploy["files"]
        self.sf.deploy["details"] = {"componentSuccesses": [
            {"fullName": "CaseRouter"}, {"fullName": "CaseRouterTest"}, {"fullName": "routingBadge"},
            {"fullName": "Case.Routing__c"}]}
        sc4 = self.status(self.run_check(), "SC4")
        self.assertEqual(sc4["status"], "PASS", sc4["details"])
        self.assertIn("by component name", sc4["details"][0])

    def test_sc4_needs_a_real_job_id(self):
        (self.wi / "deploy-job-id").unlink()
        sh(self.root, "git", "commit", "-qam", "no job")
        self.assertIn("no deploy job ID", self.status(self.run_check(), "SC4")["details"][0])
        self.assertIn("is not a deploy job ID", self.status(self.run_check(deploy_job_id="latest"), "SC4")["details"][0])

    def test_sc5_dirty_tree_or_wrong_branch_fails(self):
        (self.root / "README.md").write_text("changed\n")
        (self.wi / "delivery-check.json").write_text("{}")  # the check's own report never counts
        sc5 = self.status(self.run_check(), "SC5")
        self.assertEqual(sc5["status"], "FAIL")
        self.assertEqual(sc5["details"], ["working tree has 1 uncommitted change(s): README.md"])
        sh(self.root, "git", "checkout", "-q", "README.md")
        sh(self.root, "git", "switch", "-qc", "spike")
        self.assertIn("is not a feat/* branch", self.status(self.run_check(), "SC5")["details"][0])

    def test_configuration_errors_exit_2(self):
        (self.root / "config/harness.local.json").write_text("{}")
        with self.assertRaisesRegex(cd.CheckError, "agentOrg is not set"):
            self.run_check()
        with self.assertRaisesRegex(cd.CheckError, "under work-items"):
            cd.check(Path("force-app"), root=self.root, runner=self.sf)
        self.sf.__class__ = type("Broken", (FakeSalesforce,), {"__call__": lambda s, c, w: (1, "not json", "boom") if c[0] == "sf" else cd.run_command(c, w)})
        with self.assertRaisesRegex(cd.CheckError, "returned no JSON"):
            self.run_check(org="agent-dev")

    def test_is_test_class(self):
        self.assertTrue(cd.is_test_class(HANDLER_TEST))
        self.assertTrue(cd.is_test_class("/* note */ @IsTest(SeeAllData=false) public class X {}"))
        self.assertFalse(cd.is_test_class(HANDLER))
        self.assertFalse(cd.is_test_class("public class Y { @isTest static void t() {} }"))



class CrossPlatformWrapperTest(unittest.TestCase):
    def test_node_wrapper_finds_python_and_passes_arguments(self):
        import shutil
        if shutil.which("node") is None:
            self.skipTest("node is not installed")
        root = Path(__file__).resolve().parents[1]
        done = subprocess.run(["node", str(root / "scripts" / "check-delivery.mjs"), "--help"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("--work-item", done.stdout)


if __name__ == "__main__":
    unittest.main()
