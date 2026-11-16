#!/usr/bin/env python3
"""PreToolUse hook enforcing path boundaries for restricted custom agents."""

from __future__ import annotations

import argparse
import json
import fnmatch
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

from typing import Any, Iterable


# Custom agents that run this guard. Edit authority is the shared protected-file list below
# (plan 05, D-R2), not a per-role allowlist.
ROLES = (
    "config-investigator",
    "designer",
    "developer",
    "git-agent",
    "reviewer",
    "sdlc-conductor",
    "test-strategist",
    "workspace-maintainer",
)

HARNESS_ROOT = Path(__file__).resolve().parents[1]
# The runtime ID, canonical extension reference and documented short reference only.
# Never recognize another server/extension by a matching suffix or substring.
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


# Legacy check-only deploy validation remains available during migration, but it is no longer
# the Developer's exclusive Salesforce execution path.
VALIDATE_DEPLOY_ROLES = frozenset({"developer"})
VALIDATE_DEPLOY_COMMAND_FLAGS = {
    "start": frozenset({"--source-dir", "--manifest", "--test"}),
    "status": frozenset({"--job-id", "--org"}),
}


def validate_deploy_command_allowed(parts: list[str], role: str) -> bool:
    if role not in VALIDATE_DEPLOY_ROLES:
        return False
    if not parts or parts[0] not in VALIDATE_DEPLOY_COMMAND_FLAGS:
        return False
    allowed_flags = VALIDATE_DEPLOY_COMMAND_FLAGS[parts[0]]
    index = 1
    while index < len(parts):
        token = parts[index]
        if not token.startswith("--"):
            return False
        if "=" in token:
            flag = token.split("=", 1)[0]
            index += 1
        else:
            flag = token
            index += 2
        if flag not in allowed_flags:
            return False
    return True


# Root-of-trust files: they define permissions or external capability. They are part of the
# protected list; only the workspace maintainer may change them, after a person confirms.
# All matching is casefolded so an NTFS/macOS case variant cannot slip past.
MAINTAINER_ROLE = "workspace-maintainer"
ROOT_OF_TRUST_EXACT = frozenset(
    path.casefold()
    for path in (
        "scripts/copilot_role_guard.py",
        "scripts/copilot_safety_hook.py",
        "scripts/ado_config.py",
        "scripts/start_ado_mcp.mjs",
        "scripts/ado_tool_policy.py",
        "scripts/ado_wiki_preload.mjs",
        "scripts/ado_wiki_loader.mjs",
        "scripts/ado_wiki_tools.mjs",
        "scripts/ado_wiki_link_tools.mjs",
        "scripts/salesforce_operation_policy.py",
        "scripts/git_workflow_policy.py",
        "scripts/salesforce_operation_session.py",
        "scripts/salesforce_job_selection.py",
        "scripts/salesforce_job_executor.mjs",
        ".github/hooks/safety.json",
        ".github/mcp.json",
        ".vscode/mcp.json",
        ".vscode/settings.json",
        "config/harness.example.json",
        "config/harness.json",
        "sf-harness.code-workspace",
    )
)
ROOT_OF_TRUST_PREFIXES = (".github/agents/", "extensions/salesforce-operations/")
# Shared protected control files (plan 05, D-R2). Per-role edit allowlists were removed: every
# role may edit the repository except these files, which define the agents' own limits. No agent
# writes them; the workspace maintainer may, after a person confirms each edit ("ask").
PROTECTED_PREFIXES = (
    ".github/hooks/",
    ".github/agents/",
    ".github/instructions/",
    ".githooks/",
    ".vscode/",
    "config/",
    "schemas/",
    "extensions/salesforce-operations/",
)
PROTECTED_PATTERNS = (
    "scripts/copilot_*.py",
    "scripts/*_policy.py",
    "scripts/start_*_mcp.mjs",
)
PROTECTED_EXACT = frozenset(
    path.casefold() for path in (".github/mcp.json", "scripts/check_delivery.py", "scripts/sdlc.py", "sf-harness.code-workspace")
) | ROOT_OF_TRUST_EXACT
# Local, human-owned configuration: never written by an agent, not even after a question.
NEVER_EDITED_EXACT = frozenset({"config/harness.local.json"})


def protected_path(relative_path: str) -> bool:
    lowered = relative_path.casefold()
    return (
        lowered in PROTECTED_EXACT
        or any(lowered.startswith(prefix) for prefix in PROTECTED_PREFIXES)
        or any(fnmatch.fnmatchcase(lowered, pattern) for pattern in PROTECTED_PATTERNS)
    )


def edit_decision(relative_path: str, role: str) -> str:
    """allow | ask | deny for one normalized repository-relative path (plan 05, D-R2)."""
    if relative_path.startswith("OUTSIDE::"):
        return "deny"
    if relative_path.casefold() in NEVER_EDITED_EXACT:
        return "deny"
    if protected_path(relative_path):
        return "ask" if role == MAINTAINER_ROLE else "deny"
    return "allow"


# Validation-only terminal grant for the maintainer (plan §9.2): exact command shapes with
# repository-contained file arguments; everything else falls through to the shared rules
# (read-only orientation + guarded harness scripts) or is denied.
MAINTAINER_PY_COMPILE_EXTENSIONS = frozenset({".py"})
MAINTAINER_NODE_CHECK_EXTENSIONS = frozenset({".js", ".mjs"})


def repository_file_argument(raw: str, root: Path, extensions: frozenset[str]) -> bool:
    candidate = Path(raw.replace("\\", "/"))
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return False
    return resolved.suffix.lower() in extensions


def maintainer_terminal_command_allowed(parts: list[str], root: Path) -> bool:
    executable = Path(parts[0]).name.lower().removesuffix(".exe").removesuffix(".cmd")
    if executable == "npm":
        return parts[1:] in (["run", "prettier:verify"], ["run", "lint"])
    if executable == "node":
        return (
            len(parts) == 3
            and parts[1] == "--check"
            and repository_file_argument(parts[2], root, MAINTAINER_NODE_CHECK_EXTENSIONS)
        )
    if executable in {"python", "python3", "py"}:
        index = 1
        if executable == "py" and index < len(parts) and parts[index] == "-3":
            index += 1
        rest = parts[index:]
        if rest in (["-m", "unittest", "discover", "-s", "tests"],
                    ["-m", "unittest", "discover", "-s", "tests", "-v"]):
            return True
        if len(rest) >= 2 and rest[:2] == ["-m", "py_compile"] and len(rest) > 2:
            return all(
                repository_file_argument(arg, root, MAINTAINER_PY_COMPILE_EXTENSIONS)
                for arg in rest[2:]
            )
    return False


PATH_KEYS = {
    "path",
    "filepath",
    "file_path",
    "filename",
    "files",
    "paths",
}

# Set by main() so denial logging can name the tool/role without threading them everywhere.
_EVENT_CONTEXT = {"tool": "", "role": ""}


def _log_decision(decision: str, reason: str | None) -> None:
    """Append deny/ask decisions to an ignored local log; never raises (see safety hook twin)."""

    try:
        log_dir = HARNESS_ROOT / ".cache"
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hook": "copilot_role_guard",
            "role": _EVENT_CONTEXT["role"],
            "tool": _EVENT_CONTEXT["tool"],
            "decision": decision,
            "reason": reason or "",
        }
        with (log_dir / "denials.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def response(decision: str | None = None, reason: str | None = None) -> dict[str, Any]:
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


def is_edit_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    # Bare "create" is the Copilot CLI new-file tool; exact match only (a substring would hit MCP tools).
    if lowered.rsplit("/", 1)[-1] == "create":
        return True
    # "create_file"/"apply_patch"/"write" are VS Code's snake_case editor tools; the earlier
    # camelCase-only tokens ("createfile") missed them, letting edits bypass role path boundaries.
    return any(
        token in lowered
        for token in ("edit", "createfile", "create_file", "replace", "insert", "patch", "write")
    )


def is_execute_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    if lowered in {"bash", "sh", "zsh", "fish", "dash", "ksh", "pwsh", "powershell", "cmd"}:
        return True
    # runTask/run_task and runCommands/run_commands can spawn shell; they must obey the same
    # command allowlist as the terminal tools.
    return any(
        token in lowered
        for token in ("execute", "terminal", "shell", "runinterminal", "run_in_terminal", "runtask", "run_task", "runcommands", "run_commands")
    )


def terminal_command(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "text"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
    return ""


def flag_values(parts: list[str], flag: str) -> list[str]:
    values: list[str] = []
    for index, part in enumerate(parts):
        if part == flag and index + 1 < len(parts):
            values.append(parts[index + 1])
        elif part.startswith(f"{flag}="):
            values.append(part.split("=", 1)[1])
    return values


# Read-only orientation commands available to every role. Rationale: a default-deny terminal
# that blocks `git status`/`ls`/`grep` doesn't make the harness safer — it paralyzes the agent
# into thrashing (documented incidents), while the genuinely dangerous operations (sf, deploys,
# rm, redirects, chaining) are blocked elsewhere. The metacharacter gate in allowed_role_command
# already rejects ; & | < > ` $ and newlines, so none of these can chain, redirect, or substitute.
SIMPLE_READ_COMMANDS = frozenset({
    "ls", "dir", "pwd", "cat", "type", "head", "tail", "wc", "where", "which",
    "grep", "findstr", "rg", "tree", "find",
    # PowerShell read cmdlets (Windows default shell)
    "get-childitem", "get-content", "get-location", "get-item", "select-string", "test-path",
})
GIT_READ_SUBCOMMANDS = frozenset({
    "status", "diff", "log", "show", "blame", "describe", "shortlog",
    "rev-parse", "ls-files", "grep", "branch", "remote",
})
# Tool version checks are pure orientation; denying them only makes agents flail.
VERSION_CHECK_EXECUTABLES = frozenset({"python", "python3", "py", "node", "npm", "git"})
GIT_BRANCH_LIST_FLAGS = frozenset({"-a", "--all", "-v", "-vv", "-l", "--list", "-r", "--remotes"})
# Flags that turn a read command into a write/exec primitive.
FIND_FORBIDDEN_TOKENS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls"})


def read_only_orientation_command(parts: list[str]) -> bool:
    """Return whether argv is a non-mutating orientation command safe for every role."""

    executable = git_policy.executable(parts)
    if executable in VERSION_CHECK_EXECUTABLES and parts[1:] == ["--version"]:
        return True
    if executable in SIMPLE_READ_COMMANDS:
        rest = parts[1:]
        if executable == "find" and any(
            token in FIND_FORBIDDEN_TOKENS or token.startswith("-fprint") for token in rest
        ):
            return False
        if executable == "tree" and "-o" in rest:
            return False
        if executable == "rg" and any(token == "--pre" or token.startswith("--pre=") for token in rest):
            return False
        return True
    if executable == "git" and len(parts) >= 2:
        subcommand = parts[1].lower()
        if subcommand not in GIT_READ_SUBCOMMANDS:
            return False
        rest = parts[2:]
        if any(token.startswith("--output") for token in rest):
            return False
        if any(token in {"--ext-diff", "--textconv", "--open-files-in-pager", "-O"}
               or token.startswith(("--open-files-in-pager=", "-O")) for token in rest):
            return False
        if subcommand == "branch":
            # Listing only: any non-flag argument would create a branch; -d/-D would delete one.
            return all(token in GIT_BRANCH_LIST_FLAGS for token in rest)
        if subcommand == "remote":
            return rest in ([], ["-v"])
        return True
    return False


def salesforce_command_decision(command: str, root: Path, role: str):
    """Keep policy failures actionable in either hook without evaluating twice."""
    if role != "developer" or not command or re.search(r"[;&|`$<>\n\r]", command):
        return None
    try:
        parts = shlex.split(command.replace("\\", "/"))
    except ValueError:
        return None
    if parts and Path(parts[0]).name.lower().removesuffix(".exe").removesuffix(".cmd") in {"sf", "sfdx"}:
        return sf_policy.evaluate(parts, root)
    return None


def allowed_role_command(command: str, root: Path, role: str) -> bool:
    # Git is routed by evaluate_event before this non-Git allowlist. Do not
    # reclassify a remaining command substitution as a new Git exemption.
    if not command or re.search(r"[;&|`$<>\n\r]", command):
        return False
    # Normalize Windows path separators before POSIX shlex, which otherwise treats "\" as an
    # escape and collapses `.venv\Scripts\python.exe` into one mangled token — silently denying
    # every native Windows command. The guarded scripts take no backslash-bearing arguments.
    try:
        parts = shlex.split(command.replace("\\", "/"))
    except ValueError:
        return False
    if not parts:
        return False
    if read_only_orientation_command(parts):
        return True
    if role == MAINTAINER_ROLE and maintainer_terminal_command_allowed(parts, root):
        return True
    executable = Path(parts[0]).name.lower()
    sf_decision = salesforce_command_decision(command, root, role)
    if sf_decision is not None:
        return sf_decision.allowed
    if executable not in {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}:
        return False
    index = 1
    if executable.startswith("py") and index < len(parts) and parts[index] == "-3":
        index += 1
    if index >= len(parts):
        return False
    script = Path(parts[index])
    if not script.is_absolute():
        script = root / script
    script = script.resolve(strict=False)
    validate_harness = (root / "scripts/validate_harness.py").resolve()
    run_evals = (root / "scripts/run_evals.py").resolve()
    remainder = parts[index + 1 :]
    # Read-only self-verification available to every role: agents legitimately check their own
    # work (2026-07-14 usability fix — these were denied and caused live flailing).
    if script in (validate_harness, run_evals):
        return not remainder
    if script == (root / "scripts/check_delivery.py").resolve():
        return check_delivery_arguments_allowed(remainder)
    if script == (root / "scripts/validate_salesforce_deploy.py").resolve():
        return validate_deploy_command_allowed(remainder, role)
    return False


CHECK_DELIVERY_FLAGS = frozenset({"--work-item", "--base", "--org", "--deploy-job-id"})


def check_delivery_arguments_allowed(arguments: list[str]) -> bool:
    """scripts/check_delivery.py with its own flags only; --output stays the default report."""
    index = 0
    while index < len(arguments):
        flag, _, value = arguments[index].partition("=")
        if flag not in CHECK_DELIVERY_FLAGS:
            return False
        index += 1 if value else 2
    return index == len(arguments) and "--work-item" in {a.partition("=")[0] for a in arguments}


def collect_paths(value: Any, parent_key: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            if normalized in PATH_KEYS:
                if isinstance(child, str):
                    yield child
                elif isinstance(child, list):
                    for item in child:
                        if isinstance(item, str):
                            yield item
                        else:
                            yield from collect_paths(item, normalized)
                else:
                    yield from collect_paths(child, normalized)
            else:
                yield from collect_paths(child, normalized)
    elif isinstance(value, list):
        for child in value:
            yield from collect_paths(child, parent_key)


def normalize_path(raw: str, resolution_root: Path, policy_root: Path) -> str | None:
    if not raw or raw.startswith(("http://", "https://")):
        return None
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = resolution_root / candidate
    try:
        return candidate.resolve(strict=False).relative_to(policy_root).as_posix()
    except ValueError:
        return f"OUTSIDE::{candidate.resolve(strict=False)}"


def evaluate_event(event: dict[str, Any], role: str, *, inspect_git: bool = True) -> dict[str, Any]:
    tool_name = str(event.get("tool_name", ""))
    _EVENT_CONTEXT["tool"] = tool_name
    _EVENT_CONTEXT["role"] = role
    root = HARNESS_ROOT
    event_root = Path(event.get("cwd") or os.getcwd()).resolve()
    ado_name = tool_name.lower()
    is_ado = (ado_policy.is_ado_tool(tool_name) if ado_policy is not None else
              "ado-readonly" in ado_name or ado_name.rsplit("/", 1)[-1].startswith((
        "core_", "wit_", "wiki", "testplan", "build_", "repo_", "release_",
        "pipelines_", "search_", "advsec_", "work_item",
    )))
    if is_ado:
        if ado_policy is None:
            return response("deny", f"ADO policy unavailable: ado_tool_policy ({_POLICY_ERRORS.get('ado_tool_policy', 'load error')}).")
        error = ado_policy.tool_error(tool_name, event.get("tool_input", {}), role)
        return response("deny", error) if error else response()
    if tool_name.rsplit("/", 1)[-1].lower() in INTERACTIVE_SHELL_INPUT_TOOLS:
        return response(
            "deny",
            "Interactive shell input is not reviewable; run one complete non-interactive command instead.",
        )
    if tool_name in NATIVE_OPERATION_TOOLS:
        error = native_operation_input_error(event.get("tool_input"))
        if role != "developer":
            error = "Native Salesforce operations are available only to the Developer custom agent."
        return response("deny", error) if error else response()
    if is_execute_tool(tool_name):
        command = terminal_command(event.get("tool_input", {}))
        if inspect_git and git_policy is not None:
            admission = git_policy.inspect_command(command, event_root, role=role)
            if admission.has_git:
                if admission.decision == "deny":
                    return response("deny", admission.reason)
                results = [evaluate_event({**event, "tool_input": {"command": remaining}}, role, inspect_git=False)
                           for remaining in admission.remaining_commands]
                for decision in ("deny", "ask"):
                    for result in results:
                        if result.get("hookSpecificOutput", {}).get("permissionDecision") == decision:
                            return result
                return response()
        if git_policy is None and re.search(r"\b(?:git|gh)(?:\.exe)?\b", command):
            return response("deny", "Git message validator could not load; restore scripts/git_workflow_policy.py.")
        if role == "git-agent":
            try:
                parts = shlex.split(command.replace("\\", "/"))
            except ValueError:
                parts = []
            if parts and not re.search(r"[;&|`$<>\n\r]", command) and read_only_orientation_command(parts):
                return response()
            return response("deny", "git-agent runs Git/gh and read-only orientation commands only.")
        if sf_policy is None and re.search(r"\b(?:sf|sfdx)(?:\.exe|\.cmd)?\b", command):
            return response("deny", f"Salesforce policy unavailable: salesforce_operation_policy ({_POLICY_ERRORS.get('salesforce_operation_policy', 'load error')}).")
        sf_decision = salesforce_command_decision(command, root, role)
        if sf_decision is not None:
            return response() if sf_decision.allowed else response("deny", sf_decision.reason)
        if not allowed_role_command(command, root, role):
            return response(
                        "deny",
                        f"{role}: this exact command is outside the terminal allowlist. "
                        "Allowed families: guarded harness scripts ("
                        "scripts/validate_harness.py, run_evals.py), "
                        "Git/gh (message format only), file reads "
                        "(ls/cat/grep/type/Get-Content), and tool --version checks — all plain, "
                        "single commands with no ; & | < > ` $ chaining. Do not retry variants "
                        "of a denied command; use one of these instead.",
                    )
        return response()
    if not is_edit_tool(tool_name):
        return response()
    if git_policy is None:
        return response("deny", "Editor path policy could not load; restore scripts/git_workflow_policy.py.")

    raw_paths = list(collect_paths(event.get("tool_input", {})))
    for raw in raw_paths:
        lexical = Path(raw) if Path(raw).is_absolute() else event_root / raw
        resolves_to_body = normalize_path(raw, event_root, root) == git_policy.PR_BODY
        names_body = Path(os.path.normpath(lexical)) == root / git_policy.PR_BODY
        if (resolves_to_body or names_body) and not git_policy.pr_body_path(root, str(lexical)):
            return response("deny", "The PR body must be a repository-contained regular file without symlinks or hard links.")
    found = {
        normalized
        for raw in raw_paths
        if (normalized := normalize_path(raw, event_root, root)) is not None
    }
    if not found:
        return response(
                    "ask",
                    f"{role} requested an edit whose target path could not be determined.",
                )
    decisions = {path: "allow" if path == git_policy.PR_BODY else edit_decision(path, role) for path in found}
    denied = sorted(path for path, decision in decisions.items() if decision == "deny")
    if denied:
        # Any denied path fails the whole multi-file operation — no partial edits.
        return response(
                    "deny",
                    f"{role} may not edit protected control files, local configuration or paths "
                    f"outside the repository (plan 05, D-R2): {', '.join(denied)}",
                )
    asked = sorted(path for path, decision in decisions.items() if decision == "ask")
    if asked:
        return response(
                    "ask",
                    "Root-of-trust change — these files define permissions or external "
                    f"capability: {', '.join(asked)}. Confirm only if the agent has stated "
                    "the exact capability/safety impact and affected files.",
                )
    return response()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=sorted(ROLES))
    args = parser.parse_args()
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps(response("deny", "Hook could not parse input.")))
        return 0
    if not isinstance(event, dict):
        print(json.dumps(response("deny", "Hook input must be an object.")))
        return 0
    print(json.dumps(evaluate_event(normalize_event(event), args.role)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Local treats generic nonzero exits as non-blocking. Emit a valid deny instead.
        print(json.dumps(response("deny", "Guard failed; operation was not authorized.")))
        raise SystemExit(0)
