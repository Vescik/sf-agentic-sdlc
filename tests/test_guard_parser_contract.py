from __future__ import annotations

import argparse
import unittest
import unittest.mock
from pathlib import Path

from scripts import copilot_role_guard as guard
from scripts import validate_salesforce_deploy


# Subcommands that exist in the CLI parsers but are deliberately NOT reachable through the
# role guard. Adding a parser subcommand that appears in neither the guard allowlists nor
# this map fails the contract tests below: every new command needs an explicit decision.
INTENTIONALLY_UNGUARDED = {
    "validate_salesforce_deploy": {},
}

# Parser flags the guard deliberately does not accept for a guarded subcommand.
# Empty today: the guard mirrors every parser flag. Add entries only with a rationale.
INTENTIONALLY_EXCLUDED_FLAGS: dict[str, dict[str, set[str]]] = {
    "validate_salesforce_deploy": {},
}


def subcommand_parsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("parser has no subcommands")


def option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in {"-h", "--help"}
    }


class GuardParserContractTests(unittest.TestCase):
    """Pin the role-guard allowlists to the argparse surface of the guarded CLIs.

    The guard re-implements flag validation instead of importing the parsers (it must stay
    dependency-free and fail closed), which historically drifted when a parser grew a flag
    the guard did not know about. These tests make that drift a CI failure in both
    directions.
    """

    def contract(self, script_name: str, parser: argparse.ArgumentParser, guarded: dict[str, frozenset]) -> None:
        parsers = subcommand_parsers(parser)
        unguarded = INTENTIONALLY_UNGUARDED[script_name]
        excluded = INTENTIONALLY_EXCLUDED_FLAGS[script_name]

        self.assertEqual(
            set(),
            set(guarded) & set(unguarded),
            f"{script_name}: a subcommand cannot be both guarded and intentionally unguarded",
        )
        self.assertEqual(
            set(parsers),
            set(guarded) | set(unguarded),
            f"{script_name}: every parser subcommand needs a guard allowlist entry or an "
            "INTENTIONALLY_UNGUARDED declaration (and stale entries must be removed)",
        )
        for command, guard_flags in guarded.items():
            parser_flags = option_strings(parsers[command])
            self.assertEqual(
                set(),
                set(guard_flags) - parser_flags,
                f"{script_name} {command}: guard allows flags the parser does not define",
            )
            self.assertEqual(
                set(),
                parser_flags - set(guard_flags) - excluded.get(command, set()),
                f"{script_name} {command}: parser defines flags the guard would silently "
                "deny; allow them or declare them in INTENTIONALLY_EXCLUDED_FLAGS",
            )

    def test_validate_deploy_guard_mirrors_parser(self) -> None:
        self.contract(
            "validate_salesforce_deploy",
            validate_salesforce_deploy.build_parser(),
            guard.VALIDATE_DEPLOY_COMMAND_FLAGS,
        )

    def test_salesforce_read_lane_stays_retired(self) -> None:
        # Owner decision 2026-08-04: the CLI record-read lane was retired in favor of
        # review_soql_query on the facade. A reappearing script or guard surface means an
        # accidental resurrection, not a merge artifact to keep.
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "scripts" / "salesforce_read.py").exists())
        self.assertFalse(hasattr(guard, "salesforce_read_command_allowed"))
        self.assertFalse(hasattr(guard, "SALESFORCE_READ_FLAGS"))

    def test_knowledge_lanes_stay_removed(self) -> None:
        # sf-agentic-sdlc removed the Knowledge subsystem on 2026-11-15. A reappearing
        # guard surface or role means an accidental resurrection, not a merge artifact.
        root = Path(__file__).resolve().parents[1]
        for script in ("knowledge_store.py", "knowledge_search.py", "force_app_knowledge.py"):
            self.assertFalse((root / "scripts" / script).exists(), script)
        for name in (
            "KNOWLEDGE_STORE_COMMAND_FLAGS",
            "KNOWLEDGE_SEARCH_COMMAND_FLAGS",
            "FORCE_APP_COMMAND_FLAGS",
            "knowledge_store_command_allowed",
            "is_governed_record_path",
        ):
            self.assertFalse(hasattr(guard, name), name)
        self.assertNotIn("knowledge-curator", guard.ALLOWED_PREFIXES)


if __name__ == "__main__":
    unittest.main()
