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


def protected_path(relative_path: str) -> bool:
    lowered = relative_path.casefold()
    return (
        lowered in PROTECTED_EXACT
        or any(lowered.startswith(prefix) for prefix in PROTECTED_PREFIXES)
        or any(fnmatch.fnmatchcase(lowered, pattern) for pattern in PROTECTED_PATTERNS)
    )


SHELL_WRITE = re.compile(
    r"(?:>|\btee\b|\bsed\b[^|;&]*\s-i|\bperl\b[^|;&]*\s-i|\b(?:cp|mv|rm|rmdir|chmod|chown|truncate|ln|"
    r"install|rsync|dd|touch|unlink|shred)\b|\bopen\(|write_text|write_bytes|\.write\(|"
    r"\bgit\s+(?:checkout|restore|apply|am|stash\s+pop)\b|Set-Content|Out-File|Add-Content|Remove-Item|"
    r"Move-Item|Copy-Item|New-Item)",
    re.IGNORECASE,
)
PROTECTED_TEXT = re.compile(
    r"(?:\.github/(?:hooks|agents|instructions)\b|\.githooks\b|\.vscode\b|(?<![\w/.-])config/|(?<![\w/.-])schemas/|"
    r"extensions/salesforce-operations\b|\.github/mcp\.json|copilot_[a-z_]+\.py|[a-z_]+_policy\.py|"
    r"start_[a-z_]+_mcp\.mjs|check_delivery\.py|scripts/sdlc\.py|sf-harness\.code-workspace|"
    r"harness\.local\.json)",
    re.IGNORECASE,
)


def shell_write_to_protected(command: str) -> str | None:
    """Best-effort: a terminal command that names a protected file and a write primitive.

    Read commands (cat, grep, git diff) on protected files stay allowed. This catches obvious
    writes, not every possible program; the editor rule in edit_decision is the main boundary.
    """
    normalized = command.replace("\\", "/")
    for segment in re.split(r"[;&|\n\r]", normalized):
        write = SHELL_WRITE.search(segment)
        if not write:
            continue
        # The protected path must come after the write primitive: `python check_delivery.py
        # > out.txt` writes out.txt, while `echo x > scripts/copilot_safety_hook.py` does not.
        target = PROTECTED_TEXT.search(segment, write.start())
        if target:
            return target.group(0)
    return None


def edit_decision(relative_path: str, role: str | None) -> str:
    """allow | ask | deny for one normalized repository-relative path (plan 05, D-R2)."""
    if relative_path.startswith("OUTSIDE::"):
        return "deny"
    if relative_path.casefold() in NEVER_EDITED_EXACT:
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
