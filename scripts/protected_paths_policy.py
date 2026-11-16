"""Protected control files, shared by both PreToolUse hooks (plan 05, D-R2).

Copilot CLI ignores the `hooks` field in agent frontmatter, so the per-agent role guard does not
run there; only `.github/hooks/safety.json` does. The protected-file rule therefore lives here and
is enforced by the global safety hook for every agent, and by the role guard where it runs.
"""
from __future__ import annotations

import fnmatch
import re

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
# Written only by scripts/check_delivery.py; an agent-written report would fake success.
NEVER_EDITED_PATTERNS = ("work-items/*/delivery-check.json",)


def protected_path(relative_path: str) -> bool:
    lowered = relative_path.casefold()
    return (
        lowered in PROTECTED_EXACT
        or any(lowered.startswith(prefix) for prefix in PROTECTED_PREFIXES)
        or any(fnmatch.fnmatchcase(lowered, pattern) for pattern in PROTECTED_PATTERNS)
    )




REDIRECT_TARGET = re.compile(r"""(?<![0-9&])>>?\s*(?:"([^"]+)"|'([^']+)'|([^\s;&|<>()]+))""")
CODE_TARGET = re.compile(r"""(?:Path|open|write_text|write_bytes)\(\s*(?:"([^"]+)"|'([^']+)')""")
WRITE_COMMANDS = frozenset({
    "tee", "cp", "mv", "rm", "rmdir", "chmod", "chown", "truncate", "ln", "install", "rsync",
    "dd", "touch", "unlink", "shred", "set-content", "out-file", "add-content", "remove-item",
    "move-item", "copy-item", "new-item",
})
IN_PLACE_COMMANDS = frozenset({"sed", "perl"})
GIT_WRITE_SUBCOMMANDS = frozenset({"checkout", "restore", "apply", "am", "rm", "mv"})


def _is_protected_target(raw: str) -> bool:
    path = raw.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("-"):
        return False
    lowered = path.casefold()
    candidates = {lowered, lowered.rstrip("/") + "/"}
    for marker in ("/scripts/", "/.github/", "/config/", "/schemas/", "/.vscode/", "/.githooks/", "/extensions/", "/work-items/"):
        if marker in lowered:  # an absolute or nested path into the repository
            candidates.add(lowered[lowered.index(marker) + 1:])
    return any(
        candidate in NEVER_EDITED_EXACT
        or any(fnmatch.fnmatchcase(candidate, pattern) for pattern in NEVER_EDITED_PATTERNS)
        or protected_path(candidate)
        for candidate in candidates
    )


def shell_write_to_protected(command: str) -> str | None:
    """Best-effort: the write target of a terminal command is a protected file.

    Only real write targets count: redirect targets, the path literal of Python file writes, and
    the arguments of write commands (`cp`, `mv`, `rm`, `tee`, `sed -i`, `git checkout --` …). A
    protected name inside written text (for example a document that mentions
    `scripts/check_delivery.py`) is not a target. This catches obvious writes, not every program.
    """
    import shlex

    normalized = command.replace("\\", "/")
    targets: list[str] = []
    targets += [next(g for g in match if g) for match in REDIRECT_TARGET.findall(normalized)]
    if re.search(r"write_text|write_bytes|\.write\(|open\([^)]*['\"][wax+]", normalized):
        targets += [next(g for g in match if g) for match in CODE_TARGET.findall(normalized)]
    for segment in re.split(r"[;&|\n\r]+", normalized):
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in {"sudo", "command", "env", "exec"}):
            words = words[1:]
        if not words:
            continue
        executable = words[0].rsplit("/", 1)[-1].casefold()
        if executable in WRITE_COMMANDS:
            targets += words[1:]
        elif executable in IN_PLACE_COMMANDS and any(w == "-i" or w.startswith("-i") or w.startswith("-pi") for w in words[1:]):
            targets += words[1:]
        elif executable == "git" and len(words) > 1 and words[1] in GIT_WRITE_SUBCOMMANDS:
            targets += words[2:]
    for target in targets:
        if _is_protected_target(target):
            return target
    return None


def edit_decision(relative_path: str, role: str | None) -> str:
    """allow | ask | deny for one normalized repository-relative path (plan 05, D-R2)."""
    if relative_path.startswith("OUTSIDE::"):
        return "deny"
    if relative_path.casefold() in NEVER_EDITED_EXACT or any(
        fnmatch.fnmatchcase(relative_path.casefold(), pattern) for pattern in NEVER_EDITED_PATTERNS
    ):
        return "deny"
    if protected_path(relative_path):
        # The maintainer (role guard) and the global hook (role unknown on Copilot CLI) ask a
        # person; every other known role is denied.
        return "ask" if role in (MAINTAINER_ROLE, None) else "deny"
    return "allow"




PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.MULTILINE)


def patch_paths(tool_input: object) -> list[str]:
    """File paths named in an apply_patch-style input (Copilot CLI sends the patch as text)."""
    texts = []
    if isinstance(tool_input, str):
        texts.append(tool_input)
    elif isinstance(tool_input, dict):
        texts.extend(value for value in tool_input.values() if isinstance(value, str))
    return [first or second for text in texts for first, second in PATCH_FILE.findall(text)]


LEADING_CD = re.compile(r"""^\s*cd\s+(?:"([^"]+)"|'([^']+)'|(\S+))\s*&&\s*(.+)$""", re.DOTALL)


def strip_root_cd(command: str, root: "object") -> str:
    """`cd <repository root> && <command>` -> `<command>` (agents prefix commands this way).

    Only an exact repository-root target is removed, so the remaining command is judged in the
    working directory the hooks already assume. Any other `cd` keeps the command compound.
    """
    from pathlib import Path

    match = LEADING_CD.match(command or "")
    if not match:
        return command
    target = next(group for group in match.groups()[:3] if group)
    try:
        if Path(target).expanduser().resolve() == Path(str(root)).resolve():
            return match.group(4).strip()
    except (OSError, RuntimeError):
        return command
    return command



def split_sf_pipeline(command: str, sf_token: "re.Pattern[str]") -> str | None:
    """Return the head of `sf … [2>&1] | <filter …>` when the head is a plain command and the
    filter part names no sf command; otherwise None. Quote-aware for the first pipe only."""
    quote = ""
    for index, char in enumerate(command):
        if char in "\"'" and (not quote or quote == char):
            quote = "" if quote else char
        elif char == "|" and not quote:
            head, tail = command[:index], command[index + 1:]
            if tail.startswith("|"):
                return None  # `||` is chaining, not a pipe
            head = re.sub(r"\s2>&1\s*$", "", head).strip()
            if re.search(r"[;&|`$<>\n\r]", head) or sf_token.search(tail):
                return None
            return head
    return None
