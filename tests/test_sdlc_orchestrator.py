"""SDK orchestrator: station chain, return limits, tripwires, checkpoints and host permissions.

Contract: docs/orchestrator.md. The Copilot SDK is not needed: a fake runner returns tickets,
so these tests pin the host decisions, not model behaviour.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import copilot_safety_hook as safety
from scripts import sdlc_orchestrator as orch


class FakeRunner:
    def __init__(self, script: dict[str, list[dict]]):
        self.script = {key: list(value) for key, value in script.items()}
        self.calls: list[tuple[str, str]] = []

    def run_station(self, station, prompt):
        self.calls.append((station.id, prompt))
        payload = self.script[station.id].pop(0)
        return orch.Ticket.from_payload(station.id, {"station": station.id, "summary": station.id,
                                                     "open_questions": [], "next_action": "",
                                                     **payload})


class FakeGate:
    def __init__(self, decisions=None, confirm=False):
        self.decisions = {"H1": "approve", "H2": "approve", "H3": "approve"} if decisions is None else decisions
        self.confirm_answer = confirm
        self.asked: list[str] = []

    def checkpoint(self, checkpoint, question, packet):
        self.asked.append(checkpoint)
        return self.decisions.get(checkpoint, "pending"), ""

    def confirm(self, station, reason):
        return self.confirm_answer

    def answer(self, station, question):
        return "no"


class OrchestratorFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "output" / "orchestrator"
        (self.root / "work-items/42-x").mkdir(parents=True)
        (self.root / "work-items/42-x/design.md").write_text("# design\n", encoding="utf-8")
        self.evidence = ["work-items/42-x/design.md"]

    def state(self, kind="item"):
        return orch.RunState("run-1", kind, "42" if kind == "item" else "Add a field", "dev_sbx", True,
                             work_item_id="42" if kind == "item" else None)

    def run_chain(self, script, gate=None, kind="item"):
        runner = FakeRunner(script)
        gate = gate or FakeGate()
        final = orch.Orchestrator(runner, gate, self.state(kind), root=self.root, runs_dir=self.runs,
                                  log=lambda _: None).run()
        return final, runner, gate

    def passing(self, **extra):
        return {"status": "PASS", "evidence": self.evidence, **extra}


class TestStationChain(OrchestratorFixture):
    def test_happy_path_runs_every_station_and_checkpoint_in_order(self):
        script = {sid: [self.passing(work_item_id="42", work_item_folder="work-items/42-x")]
                  for sid in ("S1", "S2", "S3", "S4", "S5", "S6")}
        final, runner, gate = self.run_chain(script)
        self.assertEqual("DONE", final.status)
        self.assertEqual(["S1", "S2", "S3", "S4", "S5", "S6"], [c[0] for c in runner.calls])
        self.assertEqual(["H1", "H2", "H3"], gate.asked)
        packet = (self.runs / "run-1/delivery-packet.md").read_text(encoding="utf-8")
        self.assertIn("| S6 | PASS |", packet)
        self.assertTrue((self.runs / "run-1/state.json").is_file())

    def test_written_requirement_skips_ado_intake(self):
        script = {sid: [self.passing(work_item_id="42")] for sid in ("S2", "S3", "S4", "S5", "S6")}
        final, runner, _ = self.run_chain(script, kind="text")
        self.assertEqual("DONE", final.status)
        self.assertEqual("S2", runner.calls[0][0])
        self.assertIn("<requirement>\nAdd a field\n</requirement>", runner.calls[0][1])

    def test_checker_fail_returns_twice_then_escalates(self):
        fail = {"status": "FAIL", "evidence": []}
        script = {"S1": [self.passing()], "S2": [self.passing()] * 3, "S3": [fail] * 3}
        final, runner, gate = self.run_chain(script)
        self.assertEqual("ESCALATED", final.status)
        self.assertEqual({"S2": 2}, final.returns)
        self.assertEqual(["S1", "S2", "S3", "S2", "S3", "S2", "S3"], [c[0] for c in runner.calls])
        self.assertEqual([], gate.asked)

    def test_builder_blocked_stops_for_a_person(self):
        script = {"S1": [self.passing()], "S2": [{"status": "BLOCKED", "evidence": []}]}
        final, _, _ = self.run_chain(script)
        self.assertEqual("NEEDS_HUMAN", final.status)

    def test_checkpoint_without_a_person_pauses_and_resume_continues(self):
        script = {sid: [self.passing()] for sid in ("S1", "S2", "S3")}
        final, _, _ = self.run_chain(script, gate=FakeGate(decisions={}))
        self.assertEqual("WAITING_FOR_HUMAN", final.status)
        self.assertEqual(orch.SEQUENCE.index("H1"), final.position)
        resumed = orch.RunState.load("run-1", self.runs)
        resumed.status = "RUNNING"
        rest = {sid: [self.passing()] for sid in ("S4", "S5", "S6")}
        done = orch.Orchestrator(FakeRunner(rest), FakeGate(), resumed, root=self.root,
                                 runs_dir=self.runs, log=lambda _: None).run()
        self.assertEqual("DONE", done.status)

    def test_rejected_checkpoint_stops_the_run(self):
        script = {sid: [self.passing()] for sid in ("S1", "S2", "S3")}
        final, _, _ = self.run_chain(script, gate=FakeGate(decisions={"H1": "reject"}))
        self.assertEqual("REJECTED", final.status)


class TestTripwires(OrchestratorFixture):
    def test_pass_without_evidence_is_blocked(self):
        ticket = orch.apply_tripwires(orch.Ticket("S2", "PASS", "x"), self.root)
        self.assertEqual("BLOCKED", ticket.status)
        self.assertIn("L3: PASS without evidence", ticket.tripwires)

    def test_missing_or_escaping_evidence_is_blocked(self):
        for raw in ("work-items/42-x/missing.md", "../outside.md"):
            ticket = orch.apply_tripwires(orch.Ticket("S2", "PASS", "x", evidence=[raw]), self.root)
            self.assertEqual("BLOCKED", ticket.status, raw)

    def test_existing_evidence_keeps_pass(self):
        ticket = orch.apply_tripwires(orch.Ticket("S2", "PASS", "x", evidence=self.evidence), self.root)
        self.assertEqual("PASS", ticket.status)

    def test_ticket_parsing_rejects_unknown_status_and_reads_fenced_json(self):
        with self.assertRaises(ValueError):
            orch.Ticket.from_payload("S2", {"status": "DONE"})
        text = 'Done.\n```json\n{"status": "pass", "summary": "ok", "evidence": ["a"]}\n```'
        self.assertEqual("PASS", orch.Ticket.from_payload("S2", text).status)


class TestPrompts(OrchestratorFixture):
    def test_build_prompt_carries_the_autonomy_grant_only_with_an_agent_org(self):
        state = self.state()
        build = orch.STATION_BY_ID["S4"]
        self.assertIn("--target-org dev_sbx", orch.build_prompt(build, state))
        state.autonomy = False
        self.assertIn("No autonomy grant", orch.build_prompt(build, state))

    def test_checker_prompt_forbids_edits_and_names_the_contract(self):
        prompt = orch.build_prompt(orch.STATION_BY_ID["S3"], self.state())
        self.assertIn("checker for this hand-over", prompt)
        self.assertIn("starting with its `Invocation contract`", prompt)
        self.assertIn("itemId=42 scope=design", prompt)

    def test_implementation_review_names_the_build_commits(self):
        state = self.state()
        state.tickets.append({"station": "S4", "status": "PASS", "summary": "built", "commits": ["abc", "def"]})
        prompt = orch.build_prompt(orch.STATION_BY_ID["S6"], state)
        self.assertIn("scope=implementation commits=abc,def", prompt)


class TestHostPermissions(unittest.TestCase):
    BUILD = orch.STATION_BY_ID["S4"]
    REVIEW = orch.STATION_BY_ID["S3"]

    def decide(self, kind, details, station=None, org="dev_sbx"):
        return orch.decide_permission(kind, details, station or self.BUILD, org)

    def test_publication_is_always_rejected(self):
        for command in ("git push origin feat", "gh pr create --fill", "gh pr merge 3", "git merge main",
                        "git reset --hard HEAD~1", "gh api repos/x -X POST"):
            self.assertFalse(self.decide("shell", {"command": command}).allow, command)

    def test_deploy_must_name_exactly_the_agent_org(self):
        self.assertTrue(self.decide("shell", {"command": "sf project deploy start -o dev_sbx -d force-app"}).allow)
        for command in ("sf project deploy start -d force-app",
                        "sf project deploy start -o prod_org -d force-app",
                        "sf project deploy start -o dev_sbx -o other -d force-app"):
            self.assertFalse(self.decide("shell", {"command": command}).allow, command)
        self.assertFalse(self.decide("shell", {"command": "sf project deploy start -o dev_sbx"}, org=None).allow)

    def test_checker_cannot_write_but_builder_can(self):
        self.assertFalse(self.decide("write", {"path": "x"}, station=self.REVIEW).allow)
        self.assertTrue(self.decide("write", {"path": "x"}).allow)

    def test_hook_ask_and_managed_approval_go_to_a_person(self):
        decision = self.decide("hook", {"message": "This will be a real deployment"})
        self.assertFalse(decision.allow)
        self.assertTrue(decision.ask_human)
        self.assertTrue(self.decide("read", {"managed_approval_required": True}).ask_human)

    def test_unknown_kinds_and_foreign_mcp_writes_are_rejected(self):
        self.assertFalse(self.decide("url", {"url": "https://example.com"}).allow)
        self.assertFalse(self.decide("mcp", {"server": "other", "read_only": False}).allow)
        self.assertTrue(self.decide("mcp", {"server": "salesforce", "read_only": True}).allow)


class TestAutonomyGrantInSafetyHook(unittest.TestCase):
    """SAFE-DEPLOY-AUTONOMY-001: only the host environment plus the exact agent org skips the ask."""

    CONFIG = {"salesforce": {"agentOrg": "dev_sbx", "orgs": [], "review": {}}}

    def grant(self, command, environment="dev", env_value="dev_sbx", config=None):
        parts = command.split()
        env = {safety.AUTONOMY_ENV: env_value} if env_value is not None else {}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(safety, "load_config", return_value=config or self.CONFIG):
            if env_value is None:
                os.environ.pop(safety.AUTONOMY_ENV, None)
            return safety.autonomous_deploy_grant(parts, environment, Path("."))

    def test_grant_covers_an_explicit_deploy_to_the_agent_org(self):
        self.assertEqual("dev_sbx", self.grant("sf project deploy start -o dev_sbx -d force-app"))
        self.assertEqual("dev_sbx", self.grant("sf project deploy start --target-org=dev_sbx -d force-app"))

    def test_no_host_grant_no_autonomy(self):
        self.assertIsNone(self.grant("sf project deploy start -o dev_sbx", env_value=None))
        self.assertIsNone(self.grant("sf project deploy start -o dev_sbx", env_value="other"))

    def test_grant_never_covers_other_targets_defaults_or_non_developer_orgs(self):
        self.assertIsNone(self.grant("sf project deploy start -d force-app"))
        self.assertIsNone(self.grant("sf project deploy start -o other -d force-app"))
        self.assertIsNone(self.grant("sf project deploy start -o dev_sbx -o other"))
        # Plan 05, D-A2: the agent org is always a developer org; uat, stage and prod never qualify.
        for environment in ("prod", "uat", "stage", None):
            self.assertIsNone(self.grant("sf project deploy start -o dev_sbx", environment=environment))
            self.assertIsNone(self.grant("sf project delete source -o dev_sbx -m ApexClass:X", environment=environment))

    def test_grant_covers_quick_deploy_and_source_delete_in_the_developer_org(self):
        # Plan 05, P-A3.
        self.assertEqual("dev_sbx", self.grant("sf project deploy quick -o dev_sbx --job-id 0Af"))
        self.assertEqual("dev_sbx", self.grant("sf project delete source -o dev_sbx -m ApexClass:X"))
        self.assertIsNone(self.grant("sf project deploy quick --job-id 0Af"))

    def test_grant_requires_the_configured_agent_org(self):
        config = {"salesforce": {"orgs": [], "review": {}}}
        self.assertIsNone(self.grant("sf project deploy start -o dev_sbx", config=config))


class TestConfiguredAgentOrg(unittest.TestCase):
    def test_reads_alias_and_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "harness.local.json"
            path.write_text(json.dumps({"salesforce": {"agentOrg": "dev_sbx", "orgs": [
                {"alias": "dev_sbx", "environment": "dev"}]}}), encoding="utf-8")
            self.assertEqual(("dev_sbx", "dev"), orch.configured_agent_org(path))
            self.assertEqual((None, None), orch.configured_agent_org(Path(directory) / "missing.json"))

    def test_plan_needs_no_sdk(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, orch.main(["--plan"]))
        self.assertIn("S4  developer", output.getvalue())


if __name__ == "__main__":
    unittest.main()
