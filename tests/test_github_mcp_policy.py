"""GitHub MCP tools through the global safety hook (Git DevOps Assistant extension)."""
from __future__ import annotations

import unittest

from scripts import github_mcp_policy as policy

PR = {"owner": "o", "repo": "r", "title": "t", "head": "feat/1-x", "base": "main", "draft": True}


def check(name, args=None, branch="feat/1-x", passed=True):
    return policy.tool_error(name, args if args is not None else {}, lambda: branch, lambda: passed)


class ToolNameTest(unittest.TestCase):
    def test_every_name_form_is_recognized(self):
        for name in ("Git DevOps Assistant: GitHub/merge_pull_request", "github/merge_pull_request",
                     "github-mcp-server-merge_pull_request", "mcp_github_merge_pull_request",
                     "merge_pull_request", "short-label/merge_pull_request"):
            self.assertEqual("merge_pull_request", policy.github_tool(name), name)

    def test_other_tools_are_not_github(self):
        for name in ("Bash", "Edit", "ado-readonly/wit_get_work_item", "salesforce/review_soql_query",
                     "other/get_thing"):
            self.assertIsNone(policy.github_tool(name), name)


class DecisionTest(unittest.TestCase):
    def test_reads_are_allowed(self):
        for name in ("github/get_me", "github/list_pull_requests", "github/search_code",
                     "github/pull_request_read", "adoProductivity_get_github_context"):
            self.assertIsNone(check(name), name)

    def test_writes_are_denied(self):
        for tool in ("merge_pull_request", "update_pull_request", "push_files", "delete_file",
                     "create_branch", "create_issue", "pull_request_review_write", "run_workflow"):
            self.assertIn("agents only read GitHub", check(f"github/{tool}"), tool)

    def test_unknown_github_action_is_denied(self):
        self.assertIsNotNone(check("github/some_new_mutation"))

    def test_draft_pr_from_current_feature_branch_with_pass_is_allowed(self):
        self.assertIsNone(check("github/create_pull_request", PR))
        self.assertIsNone(check("github/create_pull_request", {**PR, "draft": "true", "head": "me:feat/1-x"}))

    def test_draft_pr_rules(self):
        self.assertIn("draft pull requests only", check("github/create_pull_request", {**PR, "draft": False}))
        self.assertIn("draft pull requests only", check("github/create_pull_request", {k: v for k, v in PR.items() if k != "draft"}))
        self.assertIn("feat/*", check("github/create_pull_request", {**PR, "head": "main"}))
        self.assertIn("current branch", check("github/create_pull_request", PR, branch="feat/other"))
        self.assertIn("PASS delivery-check.json", check("github/create_pull_request", PR, passed=False))


class HookTest(unittest.TestCase):
    def test_global_hook_denies_github_merge_and_allows_reads(self):
        from scripts import copilot_safety_hook as hook

        def decision(name, args):
            out = hook.evaluate_event({"tool_name": name, "tool_input": args})
            return out.get("hookSpecificOutput", {}).get("permissionDecision", "continue")

        self.assertEqual("deny", decision("github-mcp-server-merge_pull_request", {"pullNumber": 1}))
        self.assertEqual("deny", decision("github/create_pull_request", {**PR, "draft": False}))
        self.assertNotEqual("deny", decision("github/pull_request_read", {"pullNumber": 1}))


if __name__ == "__main__":
    unittest.main()
