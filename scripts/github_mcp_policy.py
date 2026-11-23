"""GitHub MCP tools: reads are allowed, one narrow write (a draft PR), everything else denied.

The global safety hook used to allow every MCP tool it did not recognize (plan 05, D-R1). The
VS Code extension Git DevOps Assistant (MS-DAW-TCA.ado-productivity-copilot) registers the
GitHub MCP server (api.githubcopilot.com/mcp) with write tools, so a merge or a non-draft pull
request would bypass the git rules that apply to `git` and `gh` (plan 05, B1/B2). This module
applies the same rules to GitHub MCP calls:

- read tools (`get_*`, `list_*`, `search_*`, `*_read`) are allowed;
- `create_pull_request` is allowed only as a draft from a `feat/*` head that is the current
  local branch with a PASS `delivery-check.json` for HEAD;
- every other GitHub MCP tool (merge, review, update, push, delete, issues, settings,
  workflows) is denied.

Tool names differ by host and are recognized in every observed or documented form:
`<server>/<tool>` (VS Code), `<server>-<tool>` (Copilot CLI joins server and tool with `-`),
`mcp_<server>_<tool>`, and a bare known tool name.
"""
from __future__ import annotations

import re
from typing import Any, Callable

FEATURE_BRANCH = re.compile(r"feat/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")

# github-mcp-server write tools named explicitly, so a bare name is recognized as GitHub too.
WRITE_TOOLS = frozenset({
    "create_pull_request", "merge_pull_request", "update_pull_request",
    "update_pull_request_branch", "create_pull_request_review",
    "submit_pending_pull_request_review", "create_pending_pull_request_review",
    "add_pull_request_review_comment_to_pending_review", "delete_pending_pull_request_review",
    "pull_request_review_write", "add_comment_to_pending_review", "request_copilot_review",
    "create_or_update_file", "push_files", "delete_file", "create_branch", "create_repository",
    "fork_repository", "create_issue", "update_issue", "add_issue_comment", "issue_write",
    "sub_issue_write", "assign_copilot_to_issue", "create_and_submit_pull_request_review",
    "run_workflow", "rerun_workflow_run", "rerun_failed_jobs", "cancel_workflow_run",
    "delete_workflow_run_logs", "dismiss_notification", "mark_all_notifications_read",
    "manage_notification_subscription", "manage_repository_notification_subscription",
    "create_gist", "update_gist", "label_write", "star_repository", "unstar_repository",
})
READ_PREFIXES = ("get_", "list_", "search_")
DRAFT_PR_TOOL = "create_pull_request"
_KNOWN_SUFFIX = re.compile(
    r"(?:^|[-_:/ ])((?:get|list|search)_[a-z0-9_]+|[a-z0-9_]+_read|"
    + "|".join(sorted((re.escape(name) for name in WRITE_TOOLS), key=len, reverse=True))
    + r")$"
)


def github_tool(tool_name: str) -> str | None:
    """The bare GitHub MCP tool name, or None when the tool is not a GitHub MCP tool."""
    lowered = tool_name.strip().lower()
    if not lowered:
        return None
    if "/" in lowered:
        server, tool = lowered.rsplit("/", 1)
        # A known GitHub write is treated as GitHub under any server name (VS Code may shorten
        # the server label); reads only count under a GitHub-named server.
        return tool if "github" in server or tool in WRITE_TOOLS else None
    match = _KNOWN_SUFFIX.search(lowered)
    if match and match.group(1) in WRITE_TOOLS:
        return match.group(1)
    if "github" not in lowered:
        return None
    if match:
        return match.group(1)
    # A GitHub-named tool whose action is unknown: keep the whole name so it is denied.
    return lowered


def is_read_tool(tool: str) -> bool:
    return tool not in WRITE_TOOLS and (tool.startswith(READ_PREFIXES) or tool.endswith("_read"))


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def tool_error(
    tool_name: str,
    tool_input: Any,
    current_branch: Callable[[], str | None],
    delivery_passed: Callable[[], bool],
) -> str | None:
    """None when the call is allowed, otherwise the reason to deny it."""
    tool = github_tool(tool_name)
    if tool is None or is_read_tool(tool):
        return None
    if tool != DRAFT_PR_TOOL:
        return (f"GitHub MCP {tool!r} changes GitHub; agents only read GitHub and open draft pull "
                "requests (plan 05, B1/B2). A person merges, reviews and changes settings.")
    args = tool_input if isinstance(tool_input, dict) else {}
    if not _truthy(args.get("draft")):
        return "Agents open draft pull requests only: set draft to true (plan 05, B2)."
    head = str(args.get("head") or "").split(":")[-1]
    if not FEATURE_BRANCH.fullmatch(head):
        return f"Pull requests come only from feat/* branches, never {head or 'an unknown head'!r} (plan 05, B2)."
    if head == str(args.get("base") or ""):
        return "The pull request base must differ from its head."
    branch = current_branch()
    if branch != head:
        return (f"Open the pull request for the current branch {branch or '(unknown)'!r}, not {head!r}: "
                "the delivery check covers only the checked-out HEAD.")
    if not delivery_passed():
        return ("A draft pull request needs a PASS delivery-check.json for HEAD; run "
                "node scripts/check-delivery.mjs first (plan 05, D-B1).")
    return None
