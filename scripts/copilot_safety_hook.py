#!/usr/bin/env python3
"""Workspace PreToolUse hook for destructive actions and real Salesforce deploy consent."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

# Git and local tools do not depend on a working Salesforce/ADO installation.
# Record a safe diagnostic and reject only the operation that needs a failed policy.
import importlib

_POLICY_ERRORS: dict[str, str] = {}


def _optional_policy(name: str):
    try:
        try:
            return importlib.import_module("scripts." + name)
        except ModuleNotFoundError as exc:
            if exc.name not in {"scripts", "scripts." + name}:
                raise
            return importlib.import_module(name)
    except Exception as exc:
        _POLICY_ERRORS[name] = type(exc).__name__
        return None


sf_policy = _optional_policy("salesforce_operation_policy")
git_policy = _optional_policy("git_workflow_policy")
ado_policy = _optional_policy("ado_tool_policy")
_ado_config = _optional_policy("ado_config")
protected_policy = _optional_policy("protected_paths_policy")
github_policy = _optional_policy("github_mcp_policy")
ado_config_error = _ado_config.ado_config_error if _ado_config is not None else None

from typing import Any
from urllib.parse import unquote, urlparse

# Recursive+force `rm` is handled by has_recursive_force_rm() (tokenized, any flag order,
# quote/backslash-splice resistant) rather than a regex, to avoid catastrophic backtracking
# on large inputs and to scope flag detection to each command segment.
DESTRUCTIVE_PATTERNS = (
    re.compile(r"\bDROP\s+(TABLE|DATABASE)\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    # cmd.exe / PowerShell spellings of the recursive deletions above (W-1,
    # audit-2026-08-09-windows-readiness): cmd.exe is available on team Windows
    # machines even though PowerShell is policy-blocked there; Remove-Item is
    # covered anyway as defense in depth. Plain `del file` / `rd dir` without the
    # recursive switch stay allowed, mirroring the non-recursive `rm` carve-out.
    re.compile(r"\b(?:rd|rmdir)\b[^\n]*\s/s\b", re.IGNORECASE),
    re.compile(r"\bdel\b[^\n]*\s/s\b", re.IGNORECASE),
    re.compile(r"\bremove-item\b[^\n]*\s-recurse\b", re.IGNORECASE),
)

SANDBOX_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\."
    r"(?:my\.salesforce\.com|lightning\.force\.com|my\.site\.com)$",
    re.IGNORECASE,
)
SCRATCH_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*\.scratch\.my\.salesforce\.com$",
    re.IGNORECASE,
)
DEV_EDITION_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*\.develop\.my\.salesforce\.com$",
    re.IGNORECASE,
)

FILESYSTEM_KEYS = {
    "directory",
    "dir",
    "path",
    "filepath",
    "file_path",
    "manifest",
    "manifestpath",
    "manifest_path",
    "sourcepath",
    "source_path",
    "targetpath",
    "target_path",
    "sourcedir",
    "targetdir",
    "projectdir",
    "source_dir",
    "target_dir",
    "project_dir",
    "target",
    "configpath",
    "config_path",
    "resultsfile",
    "results_file",
}

HARNESS_ROOT = Path(__file__).resolve().parents[1]
# Kept explicit in both independent hook processes; neither grants arbitrary extension tools.
NATIVE_OPERATION_TOOLS = frozenset({
    "sf_harness_run_operation",
    "sf-harness.salesforce-operations/salesforceOperation",
    "salesforceOperation",
})


def native_operation_input_error(tool_input: Any) -> str | None:
    if not isinstance(tool_input, dict) or set(tool_input) != {"arguments"}:
        return "Native Salesforce input must contain only arguments; role, environment and approval are host-owned."
    arguments = tool_input["arguments"]
    if not isinstance(arguments, list) or not 1 <= len(arguments) <= 128:
        return "Native Salesforce arguments must be a nonempty bounded list."
    if any(not isinstance(arg, str) or not arg or len(arg) > 8192 or
           any(char in arg for char in "\x00\r\n") for arg in arguments):
        return "Native Salesforce arguments must be bounded strings without control separators."
    try:
        if sum(len(arg.encode("utf-8")) for arg in arguments) > 32768:
            return "Native Salesforce arguments exceed the input limit."
    except UnicodeEncodeError:
        return "Native Salesforce arguments must be valid UTF-8."
    return None


def private_native_invocation(command: str) -> bool:
    """The installed native tool owns this protocol; terminal callers cannot feed replies."""
    helper = re.compile(r"\b(?:salesforce_operation_session|salesforce_job_selection|salesforce_job_executor)\b")
    try:
        parts = shlex.split(command.replace("\\", "/"))
    except ValueError:
        # Unbalanced quotes (for example a heredoc with prose): judge the raw text instead of
        # treating every unparseable command as a private-helper call (live run 6).
        return bool(helper.search(command))
    if not parts:
        return False
    executable = Path(parts[0]).name.lower().removesuffix(".exe").removesuffix(".cmd")
    if executable in {"cat", "type", "get-content", "rg", "grep", "ls"}:
        return False
    if executable in {"python", "python3", "py"} and parts[1:3] == ["-m", "py_compile"]:
        return False
    if executable == "node" and parts[1:2] == ["--check"]:
        return False
    return bool(re.search(
        r"\b(?:salesforce_operation_session|salesforce_job_selection|salesforce_job_executor)\b",
        command,
    ))
SALESFORCE_REVIEW_TOOLS = {
    "review_org_identity",
    "review_installed_packages",
    "review_object_contract",
    "review_configured_orgs",
    "review_soql_query",
    # REST facade additions (plan-2026-08-09 F-2): diagnostics, read-only by construction.
    "org_limits",
    "explain_query",
}

# The browser automation lane was removed (2026-08-05): no guard script, no origin allowlist,
# no session receipts. Browser-automation-shaped tools and commands are denied outright so the
# old hard deny can never degrade into the fail-closed "ask" backstop (MCP names) or into
# terminal passthrough (commands).
BROWSER_TOOL_NAME_TOKENS = (
    "playwright",
    "puppeteer",
    "chromium",
    "chromedriver",
    "selenium",
    "webdriver",
    "browser",
)
# VS Code's built-in render-only preview pane. It carries "browser" in its name but has no
# automation back-channel, and its URL payload is still screened by the production and
# non-sandbox Salesforce URL checks. Exact-name carve-out, not substring.
SIMPLE_BROWSER_PREVIEW_NAMES = frozenset({"opensimplebrowser", "open_simple_browser"})
BROWSER_COMMAND_PATTERN = re.compile(
    r"playwright|puppeteer|chromedriver|headless[-_]?shell|--headless\b|chromium",
    re.IGNORECASE,
)
def safety_toggle(config: dict[str, Any] | None, name: str) -> bool:
    if not isinstance(config, dict):
        return False
    return config.get("safety", {}).get(name) is True


# MCP tool classification. VS Code may hand the hook either a "server/tool" name or a BARE "tool"
# name (observed live: `core_list_orgs`). Server-prefix matching alone therefore leaks — classify by
# the unqualified tool token too.
# This fallback only identifies calls that must fail when the ADO module is broken.
ADO_TOOL_PREFIXES = (
    "core_", "wit_", "wiki", "testplan", "build_", "repo_", "release_",
    "pipelines_", "search_", "advsec_", "work_item",
)
SALESFORCE_DEV_TOOL_TOKENS = frozenset({
    "run_soql_query", "list_all_orgs", "deploy_metadata", "retrieve_metadata",
    "run_apex_test", "run_apex_tests", "run_agent_test", "resume_tool_operation",
    "create_scratch_org", "delete_org", "assign_permission_set", "run_code_analyzer",
    "get_username", "deploy", "quick_deploy", "quick_deploy_metadata", "retrieve",
})
# Shell tools named after the binary they run. Matched EXACTLY (see is_terminal_tool):
# Copilot CLI sends `Bash`, and short names like "sh" cannot be substring-matched safely.
SHELL_BINARY_TOOL_NAMES = frozenset({
    "bash", "sh", "zsh", "fish", "dash", "ksh", "pwsh", "powershell", "cmd",
})
SALESFORCE_OBJECT_API_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
# A standalone `sf` invocation token. `\b` alone treats hyphens/dots as word boundaries, so the
# workspace's own path (`sf-harness-brain-core`) or a file like `sf.py` matched and every command
# or path mentioning the repository directory was denied as a "wrapped Salesforce command"
# (observed live on the Windows pilot). Exclude word/`.`/`-` neighbours on both sides while still
# matching `sf`, `sf.cmd`, `sf.exe`, `./sf`, `/usr/local/bin/sf`, and de-spliced `s''f`.
SF_TOKEN = re.compile(r"(?<![\w.-])(?:sf|sfdx)(?:\.cmd|\.exe)?(?![\w.-])", re.IGNORECASE)
COMMAND_SEPARATORS = re.compile(r"[;&|\n\r]")


def dequote(command: str) -> str:
    """Collapse shell quote and backslash splices the way the shell does before exec.

    `s''f`, `s""f`, and `s\\f` all execute as `sf`; stripping these characters lets the
    static prefilters see the real token instead of the obfuscated spelling.
    """

    return command.replace("'", "").replace('"', "").replace("\\", "")


def has_recursive_force_rm(text: str) -> bool:
    """Detect `rm` with both a recursive and a force flag in any order.

    Tokenized per command segment (split on shell separators) so a force flag belonging to a
    later command cannot combine with an earlier `rm -r`. De-quoted first so `r''m`/`r\\m`
    splices are caught. Linear in input length — no regex backtracking on the hook hot path.
    """

    for segment in COMMAND_SEPARATORS.split(dequote(text)):
        tokens = segment.split()
        rm_seen = False
        recursive = False
        force = False
        for token in tokens:
            base = token.rsplit("/", 1)[-1]
            if base == "rm":
                rm_seen = True
                continue
            if not rm_seen or not token.startswith("-"):
                continue
            if token.startswith("--"):
                recursive = recursive or token == "--recursive"
                force = force or token == "--force"
            else:
                recursive = recursive or "r" in token[1:].lower()
                force = force or "f" in token[1:].lower()
        if rm_seen and recursive and force:
            return True
    return False


# Set by main() so denial logging can name the tool without threading it through every call.
_EVENT_TOOL_NAME = ""


def _log_decision(decision: str, reason: str | None) -> None:
    """Append deny/ask decisions to an ignored local log so blocked agents are diagnosable.

    VS Code shows the reason only transiently (if at all); without a durable trail the user
    cannot tell which hook denied what. Never raises — observability must not break enforcement.
    """

    try:
        log_dir = HARNESS_ROOT / ".cache"
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hook": "copilot_safety_hook",
            "tool": _EVENT_TOOL_NAME,
            "decision": decision,
            "reason": reason or "",
        }
        with (log_dir / "denials.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def hook_response(decision: str | None = None, reason: str | None = None) -> dict[str, Any]:
    if decision is None:
        return {"continue": True}
    _log_decision(decision, reason)
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
    }
    if reason:
        output["permissionDecisionReason"] = reason
    # VS Code reads hookSpecificOutput; Copilot CLI documents top-level permissionDecision.
    # Emitting both keeps one decision valid on both hosts (docs/copilot-cli-port.md).
    return {"hookSpecificOutput": output, **{key: value for key, value in output.items() if key != "hookEventName"}}


# Copilot CLI: write_bash/write_powershell send raw keystrokes to a running shell session.
# The input is not a reviewable command (it can answer a confirmation prompt or start a
# command no rule has seen), so interactive shell input is denied for every role.
SUBAGENT_TYPES = frozenset({"designer", "reviewer", "developer", "git-agent", "config-investigator", "test-strategist"})
INTERACTIVE_SHELL_INPUT_TOOLS = frozenset({"write_bash", "write_powershell"})


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Map the Copilot CLI camelCase payload (toolName/toolArgs) onto tool_name/tool_input.

    The repository registers PascalCase PreToolUse hooks, for which VS Code and Copilot CLI
    both send tool_name/tool_input. A camelCase registration sends toolName and toolArgs
    (toolArgs may be a JSON string); this keeps both shapes on one evaluation path.
    """
    if "tool_name" in event or "toolName" not in event:
        return event
    arguments: Any = event.get("toolArgs", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            pass
    return {**event, "tool_name": event.get("toolName"), "tool_input": arguments}


def flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten(child)}" for key, child in value.items())
    if isinstance(value, list):
        return " ".join(flatten(child) for child in value)
    return str(value)


def load_config(root: Path) -> dict[str, Any] | None:
    path = root / "config" / "harness.local.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def is_non_production_salesforce_origin(origin: str) -> bool:
    """Sandbox, scratch org, or Developer Edition — every shape that is provably not production.

    Deliberately wider than is_salesforce_sandbox_origin(), which stays strict for
    config-declared origins. This one guards mentions of an org URL in a tool call, where a
    Developer Edition is a legitimate target under the read-anywhere convention
    (owner 2026-08-04); denying it there blocked org reads the read facade itself permits.
    """
    return _origin_matches(origin, (SANDBOX_HOST, SCRATCH_HOST, DEV_EDITION_HOST))


def _origin_matches(origin: str, host_patterns: tuple) -> bool:
    try:
        parsed = urlparse(origin)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port is None
        and bool(parsed.hostname)
        and any(pattern.fullmatch(parsed.hostname or "") for pattern in host_patterns)
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
    )


def is_salesforce_sandbox_origin(origin: str) -> bool:
    return _origin_matches(origin, (SANDBOX_HOST, SCRATCH_HOST))


def salesforce_review_tool_error(
    config: dict[str, Any] | None,
    tool_name: str,
    tool_input: Any,
) -> str | None:
    if config is None:
        return "local harness configuration is missing"
    review = config.get("salesforce", {}).get("review", {})
    # requireDualSource retired with the REST facade rewrite (plan 2026-08-09): the flag
    # gated a second transport that no longer exists; review.enabled is the whole switch.
    if review.get("enabled") is not True:
        return "Salesforce org review is disabled"
    # Owner decision 2026-08-04: the facade owns live non-production identity proof
    # (per call, with review.deniedOrganizationIds as the org-level brake), so the hook
    # holds no per-alias grant gate — only tool-shape checks below.
    lowered = tool_name.lower()
    matched = next((name for name in SALESFORCE_REVIEW_TOOLS if lowered.endswith(name)), None)
    if matched is None:
        return "raw or unknown Salesforce read tool is forbidden"
    if not isinstance(tool_input, dict):
        return "Salesforce review input must be an object"
    keys = set(tool_input)
    if matched == "review_configured_orgs" and not safety_toggle(
        config, "allowScopedEnumeration"
    ):
        return "scoped org enumeration is disabled (safety.allowScopedEnumeration)"
    if matched in {"review_org_identity", "review_installed_packages", "review_configured_orgs", "org_limits"}:
        if keys:
            return "this Salesforce review tool accepts no model-controlled arguments"
        return None
    if matched in {"review_soql_query", "explain_query"}:
        # Shape/type validation only; the statement-level SOQL validation (grammar, FROM-object
        # gates, LIMIT bounds) lives in the facade server so exactly one validator exists.
        # explain_query shares the SOQL input shape; it never executes the statement.
        if "query" not in keys or not keys <= {"query", "useToolingApi"}:
            return "composed SOQL review accepts only query and useToolingApi"
        query = tool_input.get("query")
        if not isinstance(query, str) or not 8 <= len(query) <= 4000:
            return "query must be a string of 8-4000 characters"
        if "useToolingApi" in keys and not isinstance(tool_input.get("useToolingApi"), bool):
            return "useToolingApi must be a boolean"
        return None
    if keys != {"objectApiName"}:
        return "object review accepts only objectApiName"
    object_name = tool_input.get("objectApiName")
    if not isinstance(object_name, str) or not SALESFORCE_OBJECT_API_NAME.fullmatch(object_name):
        return "objectApiName is malformed"
    # Absent allowedObjectApiNames means all objects (owner decision 2026-07-30); "*" opts into
    # all objects; the name is still regex-validated above, so this only widens which objects are
    # readable, never how they are named.
    allowlist = review.get("allowedObjectApiNames", ["*"])
    if "*" not in allowlist and object_name not in allowlist:
        return "objectApiName is outside the configured review allowlist"
    return None


def is_real_deploy_tool(tool_name: str) -> bool:
    """Return whether an MCP tool starts a real deploy rather than inspecting one."""

    bare = tool_name.rsplit("/", 1)[-1].lower()
    return bare in {"deploy", "deploy_metadata", "quick_deploy", "quick_deploy_metadata"}


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s'\"<>]+", text, re.IGNORECASE)


def terminal_command(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "text"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
    return flatten(tool_input)


def is_terminal_tool(tool_name: str) -> bool:
    """Return whether a Copilot tool name represents terminal/shell execution.

    Two kinds of matching, deliberately — do not merge them into one list:

    * SUBSTRING for the long, unambiguous host tokens. "terminal" covers run_in_terminal /
      execute/runInTerminal / get_terminal_output; runtask/runcommands are VS Code runners
      that can spawn a shell. A bare "run" substring once matched the MCP tools
      run_soql_query / run_tests, which is why only these specific tokens are listed.
    * EXACT for shell binary names. Copilot CLI names its shell tool `Bash` (the hook payload
      carries the capitalised form), which matched none of the substring tokens — so in the
      CLI every command-scoped human-approval gate below was unreachable while the hook
      itself looked healthy, because the name-independent text checks still fired.
      These must NOT be substrings: "sh" would match publish, push, refresh and any MCP tool
      containing those letters, and would send non-command tool inputs through the command
      rules.
    """
    lowered = tool_name.lower()
    if lowered in SHELL_BINARY_TOOL_NAMES:
        return True
    return any(
        token in lowered
        for token in ("terminal", "execute", "shell", "runtask", "run_task", "runcommands", "run_commands")
    )


def target_orgs(parts: list[str]) -> list[str]:
    targets: list[str] = []
    for index, part in enumerate(parts):
        if part in ("--target-org", "-o", "--targetusername", "-u") and index + 1 < len(parts):
            targets.append(parts[index + 1])
        if part.startswith(("--target-org=", "--targetusername=")):
            targets.append(part.split("=", 1)[1])
    return targets


def sf_pipeline_head(command: str) -> str:
    """`sf … --json | python3 …` -> `sf … --json` (plan 05, live trial: agents filter sf output).

    A pipe after the Salesforce command cannot change its target org, so only the first segment
    is judged by the Salesforce policy. Substitution, chaining and redirects in the sf segment,
    and any sf command after the pipe, keep the whole command compound (denied).
    """
    if protected_policy is None:
        return command
    head = protected_policy.split_sf_pipeline(command, SF_TOKEN)
    return head if head and SF_TOKEN.search(head) and not SF_TOKEN.search(dequote(command[len(head):])) else command


def direct_sf_command(command: str) -> list[str] | None:
    # The shell collapses quote/backslash splices (`s''f`, `s""f`, `s\f`) back to `sf` before
    # execution, so a prefilter over the raw string alone misses them. Test a de-spliced copy
    # too; the metacharacter gate below still runs against the original command.
    # `command -v sf`, `which sf`, `type sf` only look the CLI up (live run 6).
    lookup = re.sub(r"(?<![\w.-])(?:command\s+-v|which|type|where)\s+(?:sf|sfdx)(?:\.cmd|\.exe)?(?![\w.-])", "cli-lookup", command)
    if not SF_TOKEN.search(lookup) and not SF_TOKEN.search(dequote(lookup)):
        return None
    command = lookup if SF_TOKEN.search(lookup) else command
    # A Python or Node one-liner that writes text mentioning `sf` is not a Salesforce command
    # unless it can start a process (live runs 8-9: org-changes.md entries written this way).
    try:
        first = shlex.split(command.replace("\\", "/"))[0]
    except (ValueError, IndexError):
        first = command.split(maxsplit=1)[0] if command.split() else ""
    if Path(first).name.lower() in {"python", "python3", "py", "node"} and not re.search(
            r"subprocess|os\.system|os\.exec|os\.spawn|popen|pty\.|child_process|execSync|spawnSync|\bexec\(|\bspawn\(",
            command, re.IGNORECASE):
        return None
    command = sf_pipeline_head(command)
    if re.search(r"[;&|`$<>\n\r]", command):
        raise ValueError("compound, redirected, or substituted Salesforce commands are forbidden")
    try:
        parts = shlex.split(command.replace("\\", "/"))
    except ValueError as exc:
        raise ValueError(f"Salesforce command could not be parsed: {exc}") from exc
    if not parts or Path(parts[0]).name.lower() not in {
        "sf", "sf.cmd", "sf.exe", "sfdx", "sfdx.cmd", "sfdx.exe"
    }:
        raise ValueError("Salesforce CLI must be invoked directly, without a shell or environment wrapper")
    return parts


def _flag_enabled(parts: list[str], *flags: str) -> bool:
    lowered = [part.lower() for part in parts]
    for part in lowered:
        if part in flags:
            return True
        for flag in flags:
            if part.startswith(f"{flag}="):
                return part.split("=", 1)[1] not in {"false", "0", "no"}
    return False


# SAFE-DEPLOY-AUTONOMY-001 (owner decisions 2026-11-15 and 2026-11-16, plan 05 D-A2 and P-A3).
# The launcher (scripts/sdlc) or the SDK orchestrator sets this variable to the configured
# salesforce.agentOrg; the hook process inherits it from the host, and no model command can
# change the hook's environment. Only then does a real deploy, quick deploy or source delete to
# that exact developer org skip the per-deploy question. Validate and retrieve never needed one.
AUTONOMY_ENV = "SF_AGENTIC_AUTONOMOUS_ORG"
AUTONOMOUS_DEPLOY_WORDS = frozenset({
    ("project", "deploy", "start"), ("deploy", "metadata"),
    ("project", "deploy", "quick"), ("project", "delete", "source"),
})
AUTONOMOUS_ENVIRONMENTS = frozenset({"dev"})


def autonomous_deploy_grant(parts: list[str], environment: str | None, root: Path) -> str | None:
    """Return the agent org when this real deploy is covered by the host's autonomy grant."""
    granted = os.environ.get(AUTONOMY_ENV, "")
    if not granted:
        return None
    config = load_config(root) or {}
    salesforce = config.get("salesforce") if isinstance(config, dict) else None
    agent_org = salesforce.get("agentOrg") if isinstance(salesforce, dict) else None
    if not isinstance(agent_org, str) or granted != agent_org:
        return None
    words = tuple(word.lower() for word in sf_policy.command_words(sf_policy.canonical_command(parts)))
    if words not in AUTONOMOUS_DEPLOY_WORDS:
        return None
    # The target must be spelled out and be exactly the agent org: no CLI default, no second org.
    targets = target_orgs(parts)
    if not targets or any(target != agent_org for target in targets):
        return None
    if environment not in AUTONOMOUS_ENVIRONMENTS:
        return None
    return agent_org


def is_real_deploy_command(parts: list[str]) -> bool:
    """Classify current `sf` and legacy `sfdx` commands that initiate an org deployment."""

    lowered = sf_policy.canonical_command([part.lower() for part in parts])
    executable = Path(lowered[0]).name.removesuffix(".exe").removesuffix(".cmd")
    args = lowered[1:]
    if executable in {"sf", "sfdx"}:
        words = sf_policy.command_words(lowered)
        if words in {("project", "deploy", "start"), ("deploy", "metadata")}:
            return not _flag_enabled(args, "--dry-run")
        if words == ("project", "delete", "source"):
            return not _flag_enabled(args, "--check-only", "--checkonly", "-c")
        if words == ("project", "deploy", "quick"):
            return True
    if executable in {"sf", "sfdx"} and args and args[0] in {"force:source:deploy", "force:mdapi:deploy"}:
        return not _flag_enabled(args, "--checkonly", "-c")
    return False


def deploy_target(parts: list[str], tool_input: Any | None = None) -> str:
    targets = target_orgs(parts)
    if targets:
        return targets[-1]
    if isinstance(tool_input, dict):
        values = collect_named_values(
            tool_input,
            {"target_org", "targetorg", "org", "username", "alias"},
        )
        if values:
            return values[-1]
    return "the project/default target-org context"


def deploy_scope(parts: list[str], tool_input: Any | None = None) -> str:
    scope_flags = {
        "--source-dir", "-d", "--manifest", "-x", "--metadata", "-m",
        "--metadata-dir", "--pre-destructive-changes", "--post-destructive-changes",
        "--job-id", "--validated-deploy-request-id", "--sourcepath", "-p", "--deploydir",
    }
    values: list[str] = []
    for index, part in enumerate(parts):
        lowered = part.lower()
        if lowered in scope_flags and index + 1 < len(parts):
            values.append(f"{part} {parts[index + 1]}")
        elif any(lowered.startswith(f"{flag}=") for flag in scope_flags):
            values.append(part)
    if not values and isinstance(tool_input, dict):
        values = collect_filesystem_paths(tool_input)
    summary = ", ".join(values[:6]) if values else "the command-selected deployment scope"
    return summary[:800]


def real_deploy_confirmation_reason(
    parts: list[str], tool_input: Any | None = None
) -> str:
    return (
        "This will be a real deployment of changes to Salesforce org "
        f"{deploy_target(parts, tool_input)}. Scope: {deploy_scope(parts, tool_input)}. "
        "Should I run this deployment? Confirmation applies only to this exact invocation; "
        "a new deploy, quick deploy, or redeploy requires fresh confirmation."
    )


def collect_filesystem_paths(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in FILESYSTEM_KEYS:
                if isinstance(child, str):
                    found.append(child)
                elif isinstance(child, list):
                    found.extend(item for item in child if isinstance(item, str))
                    for item in child:
                        if not isinstance(item, str):
                            found.extend(collect_filesystem_paths(item))
                else:
                    found.extend(collect_filesystem_paths(child))
            else:
                found.extend(collect_filesystem_paths(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_filesystem_paths(child))
    return found


def collect_named_values(value: Any, names: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in names:
                if isinstance(child, (str, int)):
                    found.append(str(child))
                elif isinstance(child, list):
                    found.extend(str(item) for item in child if isinstance(item, (str, int)))
            found.extend(collect_named_values(child, names))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_named_values(child, names))
    return found


def within_root(raw: str, root: Path) -> bool:
    if not raw or raw.startswith(("http://", "https://")):
        return True
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
        return True
    except ValueError:
        return False


def within_salesforce_source(raw: str, root: Path) -> bool:
    """Restrict MCP filesystem arguments to Salesforce project artifacts at repo root."""

    if not raw or raw.startswith(("http://", "https://")):
        return True
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    return relative == "sfdx-project.json" or any(
        relative == prefix or relative.startswith(f"{prefix}/")
        for prefix in ("force-app", "manifest", "tests/e2e")
    )


def evaluate_event(event: dict[str, Any], *, inspect_git: bool = True) -> dict[str, Any]:
    tool_name = str(event.get("tool_name", ""))
    global _EVENT_TOOL_NAME
    _EVENT_TOOL_NAME = tool_name
    lowered_name = tool_name.lower()
    # Unqualified tool token, so a bare `core_list_orgs` is classified the same as `ado-readonly/core_list_orgs`.
    bare_tool = tool_name.rsplit("/", 1)[-1].lower()
    is_ado = (ado_policy.is_ado_tool(tool_name) if ado_policy is not None else
              "ado-readonly" in lowered_name or bare_tool.startswith(ADO_TOOL_PREFIXES))
    is_sf_review = (
        lowered_name == "salesforce"
        or lowered_name.startswith("salesforce/")
        or bare_tool in SALESFORCE_REVIEW_TOOLS
    )
    is_sf_dev = "salesforce-development" in lowered_name or bare_tool in SALESFORCE_DEV_TOOL_TOKENS
    tool_input = event.get("tool_input", {})
    # Sub-agents (plan 05, live trial 2026-11-16): on Copilot CLI a conductor started the built-in
    # `task`/`general-purpose` agents, which have every tool, instead of the station agents. Only
    # the repository's station agents may be started as sub-agents.
    # The model calls it `task`; the CLI hook payload names it `Agent` (live run 7).
    if bare_tool in ("task", "agent") and isinstance(tool_input, dict) and ("agent_type" in tool_input or "agentType" in tool_input or "prompt" in tool_input):
        agent_type = str(tool_input.get("agent_type") or tool_input.get("agentType") or "")
        if agent_type not in SUBAGENT_TYPES:
            return hook_response(
                "deny",
                f"Sub-agent {agent_type or '(none)'!r} is not a station agent. Start one of "
                f"{', '.join(sorted(SUBAGENT_TYPES))} with agent_type (plan 05).",
            )
    if bare_tool in INTERACTIVE_SHELL_INPUT_TOOLS:
        return hook_response(
            "deny",
            "Interactive shell input is not reviewable; run one complete non-interactive command instead.",
        )
    # GitHub MCP (Git DevOps Assistant extension): the git rules for `git`/`gh` apply to MCP calls
    # too. Only a denial returns here; an allowed call still meets every later check (ADO, text).
    if github_policy is None:
        if "github" in lowered_name:
            return hook_response("deny", f"GitHub MCP policy unavailable: github_mcp_policy ({_POLICY_ERRORS.get('github_mcp_policy', 'load error')}).")
    else:
        github_cwd = Path(event.get("cwd") or os.getcwd())
        github_error = github_policy.tool_error(
            tool_name,
            tool_input,
            lambda: git_policy._run_git(github_cwd, "rev-parse", "--abbrev-ref", "HEAD") if git_policy else None,
            lambda: bool(git_policy and git_policy.delivery_check_passed(github_cwd)),
        )
        if github_error:
            return hook_response("deny", github_error)
    if tool_name in NATIVE_OPERATION_TOOLS:
        # Environment questions, drift checks and deployment dialogs happen in one native
        # invocation. Do not deny an unknown classification before the host can ask.
        error = native_operation_input_error(tool_input)
        return hook_response("deny", error) if error else hook_response()
    if is_ado and (ado_policy is None or ado_config_error is None):
        failed = "ado_tool_policy" if ado_policy is None else "ado_config"
        return hook_response("deny", f"ADO policy unavailable: {failed} ({_POLICY_ERRORS.get(failed, 'load error')}).")
    # Wiki Markdown may contain quoted commands or source URLs. Only the known
    # adapter's top-level text fields are data; all selectors remain guarded.
    checked_input = ado_policy.selector_input(tool_name, tool_input) if is_ado else tool_input
    text = flatten(checked_input)
    root = HARNESS_ROOT
    # Shell-command semantics apply only to terminal-shaped tools. For read/list/search tools the
    # flatten() fallback returned file PATHS here, and any path inside this repository contains an
    # `sf` token via the directory name — so plain read_file calls were denied as wrapped
    # Salesforce commands (observed live on the Windows pilot). Non-command surfaces are still
    # covered by the `text` checks (destructive/production patterns) and tool classification.
    command = terminal_command(tool_input) if is_terminal_tool(tool_name) else ""
    if command and protected_policy is not None:
        command = protected_policy.strip_root_cd(command, root)
    if command and protected_policy is not None:
        protected_write = protected_policy.shell_write_to_protected(command)
        if protected_write:
            return hook_response("deny", f"Agents do not change protected control files from the terminal (plan 05, D-R2): {protected_write}")
    if command and inspect_git and git_policy is not None:
        admission = git_policy.inspect_command(command, Path(event.get("cwd") or os.getcwd()))
        if admission.has_git:
            if admission.decision == "deny":
                return hook_response("deny", admission.reason)
            # A Git command cannot exempt a second, non-Git command from its policy.
            results = [evaluate_event({**event, "tool_input": {"command": remaining}}, inspect_git=False)
                       for remaining in admission.remaining_commands]
            for decision in ("deny", "ask"):
                for result in results:
                    if result.get("hookSpecificOutput", {}).get("permissionDecision") == decision:
                        return result
            return hook_response()
    if command and git_policy is None and re.search(r"\b(?:git|gh)(?:\.exe)?\b", command):
        return hook_response("deny", "Git message validator could not load; restore scripts/git_workflow_policy.py.")
    if not command and git_policy is not None:
        paths = collect_filesystem_paths(tool_input) if isinstance(tool_input, (dict, list)) else []
        if protected_policy is not None:
            paths += [path for path in protected_policy.patch_paths(tool_input) if path not in paths]
        # Bare "create" is the Copilot CLI new-file tool; exact match only (a substring would hit MCP tools).
        is_editor = bare_tool == "create" or any(token in lowered_name for token in ("edit", "createfile", "create_file", "replace", "insert", "patch", "write"))
        correct_cwd = Path(event.get("cwd") or os.getcwd()).resolve() == root
        if is_editor and paths and (correct_cwd or all(Path(path).is_absolute() for path in paths)) and all(git_policy.pr_body_path(root, path) for path in paths):
            # A PR description can quote a forbidden command without executing it.
            # The independent role guard still governs this exact transport path.
            text = " ".join(paths)
        # Protected control files (plan 05, D-R2), enforced here for every agent because Copilot
        # CLI does not run the per-agent role guard. The role is unknown here, so a protected
        # file needs a person ("ask"); local config and paths outside the repository are denied.
        if is_editor and paths:
            if protected_policy is None:
                return hook_response("deny", f"Protected-file policy unavailable: protected_paths_policy ({_POLICY_ERRORS.get('protected_paths_policy', 'load error')}).")
            event_root = Path(event.get("cwd") or os.getcwd()).resolve()
            decisions = {}
            for raw in paths:
                candidate = Path(os.path.expanduser(raw))
                candidate = (candidate if candidate.is_absolute() else event_root / candidate).resolve(strict=False)
                try:
                    relative = candidate.relative_to(root.resolve()).as_posix()
                except ValueError:
                    relative = f"OUTSIDE::{candidate}"
                decisions[relative] = protected_policy.edit_decision(relative, None)
            denied = sorted(path for path, decision in decisions.items() if decision == "deny")
            if denied:
                return hook_response("deny", "Local configuration and paths outside the repository are never edited by an agent (plan 05, D-R2): " + ", ".join(denied))
            asked = sorted(path for path, decision in decisions.items() if decision == "ask")
            if asked:
                return hook_response("ask", "Protected control file — it defines the agents' own limits: " + ", ".join(asked) + ". A person must confirm this exact edit (plan 05, D-R2).")
    if command and private_native_invocation(command):
        return hook_response("deny", "Private Salesforce session/executor cannot be invoked from a terminal; use the native Developer tool.")

    if has_recursive_force_rm(text) or any(pattern.search(text) for pattern in DESTRUCTIVE_PATTERNS):
        return hook_response("deny", "Destructive operation blocked by the global safety policy.")

    config = load_config(root) if is_sf_review else None
    # Org/project enumeration and the ADO config/scope blocks were removed (plan 05, D-R1). ADO
    # stays limited to its read tools and the two narrow writes (D-R3).
    if is_ado:
        operation = "publication" if ado_policy.bare_tool_name(tool_name) in ado_policy.WRITE_TOOLS else "read"
        capability_error = ado_policy.tool_error(tool_name, tool_input)
        if capability_error:
            return hook_response("deny", f"ADO {operation} blocked: {capability_error}.")
    if is_sf_review:
        scope_error = salesforce_review_tool_error(config, tool_name, tool_input)
        if scope_error:
            return hook_response(
                        "deny",
                        f"Salesforce org review blocked: {scope_error}.",
                    )
    if is_sf_dev:
        return hook_response("deny", "Salesforce development MCP is not an available channel. Use the governed direct CLI or existing read-only review tools.")
    try:
        sf_parts = direct_sf_command(command)
    except ValueError as exc:
        return hook_response("deny", f"Salesforce command blocked: {exc}.")
    if sf_parts is not None:
        if sf_policy is None:
            return hook_response("deny", f"Salesforce policy unavailable: salesforce_operation_policy ({_POLICY_ERRORS.get('salesforce_operation_policy', 'load error')}).")
        decision = sf_policy.evaluate(sf_parts, root)
        if not decision.allowed:
            return hook_response("deny", decision.reason)
        if is_real_deploy_command(sf_parts) and not any(part in ("--help", "-h") for part in sf_parts):
            granted_org = autonomous_deploy_grant(sf_parts, decision.environment, root)
            if granted_org is not None:
                return hook_response(
                    "allow",
                    f"SAFE-DEPLOY-AUTONOMY-001: host autonomy grant for agent org {granted_org} "
                    f"(Org ID {decision.organization_id}; environment {decision.environment}).",
                )
            granted = os.environ.get(AUTONOMY_ENV, "")
            if granted and not target_orgs(sf_parts):
                return hook_response(
                    "deny",
                    f"Add --target-org {granted}: the deploy grant covers only an explicit target "
                    "(SAFE-DEPLOY-AUTONOMY-001). Run the same command again with it.",
                )
            reason = real_deploy_confirmation_reason(sf_parts)
            reason += f" Resolved Org ID: {decision.organization_id}; environment: {decision.environment}."
            return hook_response("ask", reason)
        return hook_response()

    if re.search(r"(?:@salesforce/mcp|ALLOW_ALL_ORGS|DEFAULT_TARGET_ORG)", command, re.IGNORECASE):
        return hook_response("deny", "An unguarded Salesforce runtime wrapper is forbidden; invoke sf or sfdx directly.")

    is_browser_named = (
        any(token in lowered_name for token in BROWSER_TOOL_NAME_TOKENS)
        and bare_tool not in SIMPLE_BROWSER_PREVIEW_NAMES
        and lowered_name not in SIMPLE_BROWSER_PREVIEW_NAMES
    )
    if is_browser_named or BROWSER_COMMAND_PATTERN.search(dequote(command)):
        return hook_response(
                    "deny",
                    "Direct browser tooling is disabled; the browser automation lane was removed from this harness.",
                )

    # An unrecognized MCP tool is no longer a question (plan 05, D-R1): MCP servers come only from
    # the repository and user configuration, and every recognized server keeps its rules above.
    return hook_response()


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps(hook_response("deny", "Hook could not parse input.")))
        return 0
    if not isinstance(event, dict):
        print(json.dumps(hook_response("deny", "Hook input must be an object.")))
        return 0
    print(json.dumps(evaluate_event(normalize_event(event))))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Local treats generic nonzero exits as non-blocking. Emit a valid deny instead.
        print(json.dumps(hook_response("deny", "Guard failed; operation was not authorized.")))
        raise SystemExit(0)
