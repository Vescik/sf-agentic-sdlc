"""Git admission: publication boundaries for agents (plan 05, boundaries B1 and B2).

Agents commit freely on their branch; commit messages are not checked (plan 05, D-R1).
Denied for every agent: merge, rebase, `reset --hard`, force branch deletion, `gh api`,
and the gh subcommands that merge, review, release or change repository settings.
Push and `gh pr create` are for the git-agent only: pushes go to `feat/*` branches without
force or deletion, and a pull request must be a draft with a PASS delivery check for HEAD.
Shell command separation keeps unrelated commands on their normal policy path.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

PR_BODY = ".cache/github/pr-body.md"
SOLUTION_DOCUMENTATION_PATTERN = re.compile(
    r"docs/solutions/[a-z0-9]+(?:-[a-z0-9]+)*/(?:overview|flows|components)\.md"
)


class Rejected(ValueError):
    pass


@dataclass(frozen=True)
class GitAdmission:
    has_git: bool = False
    decision: str = "allow"
    reason: str = ""
    remaining_commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Word:
    text: str
    dynamic: bool = False


@dataclass(frozen=True)
class _Command:
    raw: str
    words: tuple[_Word, ...]


def executable(parts: list[str]) -> str:
    return parts[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe") if parts else ""


def _scan(command: str, windows: bool) -> tuple[list[_Command], list[str]]:
    """Read shell words and executable segments without evaluating any shell text."""
    commands: list[_Command] = []
    substitutions: list[str] = []
    words: list[_Word] = []
    word: list[str] = []
    quote = ""
    started = dynamic = False
    segment = index = 0

    def finish_word() -> None:
        nonlocal word, started, dynamic
        if started:
            words.append(_Word("".join(word), dynamic))
        word, started, dynamic = [], False, False

    def finish_command(end: int) -> None:
        nonlocal words
        finish_word()
        if words:
            commands.append(_Command(command[segment:end].strip(), tuple(words)))
        words = []

    while index < len(command):
        char = command[index]
        if char == "\\" and not windows and quote != "'" and index + 1 < len(command):
            following = command[index + 1]
            if following in "\\\"' $`;&|<>\n":
                if following != "\n":
                    word.append(following)
                    started = True
                index += 2
                continue
        if char in "\"'" and (not quote or quote == char):
            quote = "" if quote else char
            started = True
            index += 1
            continue
        if quote != "'" and command.startswith("$(", index):
            begin = index + 2
            depth, nested_quote = 1, ""
            index = begin
            while index < len(command) and depth:
                nested = command[index]
                if nested == "\\" and index + 1 < len(command):
                    index += 2
                    continue
                if nested in "\"'" and (not nested_quote or nested_quote == nested):
                    nested_quote = "" if nested_quote else nested
                elif not nested_quote:
                    depth += (nested == "(") - (nested == ")")
                index += 1
            if depth:
                raise Rejected("Unterminated shell command substitution.")
            inner = command[begin:index - 1]
            if inner.startswith("(") and inner.endswith(")"):
                # Arithmetic expansion is data, while substitutions embedded in
                # that expression still execute commands and must stay visible.
                _, arithmetic_substitutions = _scan(inner[1:-1], windows)
                substitutions.extend(arithmetic_substitutions)
            else:
                substitutions.append(inner)
            word.append(command[begin - 2:index])
            started = dynamic = True
            continue
        if quote != "'" and char == "`" and not windows:
            end = index + 1
            while end < len(command):
                if command[end] == "\\":
                    end += 2
                elif command[end] == "`":
                    break
                else:
                    end += 1
            if end == len(command):
                raise Rejected("Unterminated shell command substitution.")
            substitutions.append(command[index + 1:end])
            word.append(command[index:end + 1])
            started = dynamic = True
            index = end + 1
            continue
        if quote != "'" and (char == "$" or (windows and char in "%!")):
            dynamic = True
        if not quote and char == "#" and not started:
            finish_command(index)
            newline = command.find("\n", index)
            if newline < 0:
                return commands, substitutions
            index = newline + 1
            segment = index
            continue
        if not quote and (char in ";&|\n\r()" or (char in "{}" and not started)):
            # Descriptor duplication (2>&1) is a redirect, not a new command.
            if char == "&" and ((index and command[index - 1] in "<>") or command[index:index + 2] == "&>"):
                word.append(char)
                started = True
            else:
                finish_command(index)
                segment = index + 1
        elif not quote and char.isspace():
            finish_word()
        else:
            word.append(char)
            started = True
        index += 1
    if quote:
        raise Rejected("Unterminated shell quoted argument.")
    finish_command(len(command))
    return commands, substitutions


def parse_command(command: str, *, windows: bool | None = None) -> list[str]:
    commands, _ = _scan(command, os.name == "nt" if windows is None else windows)
    if len(commands) != 1:
        raise Rejected("Expected one command.")
    return [word.text for word in commands[0].words]


def _directory(cwd: Path | None, word: _Word) -> Path | None:
    if word.dynamic or word.text in {"-", "~"} or word.text.startswith("~/"):
        return None
    path = Path(word.text)
    return path if path.is_absolute() else cwd / path if cwd is not None else None


def _unwrap(words: tuple[_Word, ...], cwd: Path | None) -> tuple[tuple[_Word, ...], Path | None]:
    index = 0
    while index < len(words):
        token = words[index].text
        if token in {"if", "then", "elif", "else", "while", "until", "do", "!"}:
            index += 1
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            index += 1
        elif token in {"command", "exec", "env"}:
            wrapper = token
            index += 1
            while index < len(words) and words[index].text.startswith("-"):
                option = words[index].text
                index += 1
                if option == "--":
                    break
                value_options = {"exec": {"-a"}, "env": {"-u", "--unset", "-C", "--chdir", "-a", "--argv0"}, "command": set()}[wrapper]
                flag_options = {"exec": {"-c", "-l"}, "env": {"-i", "--ignore-environment", "-0", "--null", "-v", "--debug"}, "command": {"-p", "-v", "-V"}}[wrapper]
                if option in value_options and index < len(words):
                    if option in {"-C", "--chdir"}:
                        cwd = _directory(cwd, words[index])
                    index += 1
                elif wrapper == "env" and option.startswith("--chdir="):
                    cwd = _directory(cwd, _Word(option.split("=", 1)[1], words[index - 1].dynamic))
                elif wrapper == "env" and option.startswith(("--unset=", "--argv0=")):
                    pass
                elif option not in flag_options:
                    # An unknown wrapper option may consume the apparent `git`
                    # token as data (for example exec -a git rm). Keep the wrapper
                    # on normal policy unless its executable position is known.
                    return words, cwd
        else:
            break
    return words[index:], cwd


GIT_GLOBAL_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path"})
PUSH_FORBIDDEN = frozenset({"--force", "--force-with-lease", "--force-if-includes", "--mirror", "--all",
                            "--branches", "--delete", "--tags", "--prune", "--follow-tags"})
PUSH_VALUE_OPTIONS = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})
FEATURE_BRANCH = re.compile(r"feat/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
PUBLISHER_ROLE = "git-agent"
DELIVERY_CHECK_GLOB = "work-items/*/delivery-check.json"
# gh command groups: subcommands an agent may never run (plan 05, boundary B1).
GH_DENIED = {
    "pr": frozenset({"merge", "review", "ready", "close", "reopen", "lock", "unlock"}),
    "release": None,  # all but the read subcommands below
    "repo": frozenset({"create", "delete", "edit", "rename", "archive", "unarchive", "fork", "sync", "set-default"}),
    "secret": None,
    "variable": None,
    "workflow": frozenset({"run", "enable", "disable"}),
    "run": frozenset({"cancel", "rerun", "delete"}),
    "auth": None,
    "ruleset": None,
}
GH_READ = frozenset({"list", "view", "status", "download", "diff", "checks"})


def _run_git(cwd: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _skip_git_options(words: tuple[_Word, ...], cwd: Path | None) -> tuple[int | None, Path | None]:
    index = 1
    while index < len(words) and words[index].text.startswith("-"):
        token = words[index].text
        if token in GIT_GLOBAL_VALUE_OPTIONS:
            if index + 1 >= len(words):
                return None, cwd
            if token == "-C":
                cwd = _directory(cwd, words[index + 1])
            index += 2
        else:
            if token.startswith("-C") and len(token) > 2:
                cwd = _directory(cwd, _Word(token[2:], words[index].dynamic))
            index += 1
    return (index if index < len(words) else None), cwd


def _push_error(args: tuple[_Word, ...], cwd: Path | None, role: str | None) -> str | None:
    if role is not None and role != PUBLISHER_ROLE:
        return f"Only the {PUBLISHER_ROLE} pushes; {role} hands the branch to it (plan 05, B2)."
    if any(word.dynamic for word in args):
        return "git push needs literal arguments so the target branch can be checked."
    positional: list[str] = []
    index = 0
    while index < len(args):
        token = args[index].text
        if token == "--":
            positional.extend(word.text for word in args[index + 1:])
            break
        if token in PUSH_VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("--"):
            if token.split("=", 1)[0] in PUSH_FORBIDDEN:
                return f"git push {token} is not allowed: no force, delete, mirror or tag pushes (plan 05, B2)."
        elif token.startswith("-"):
            if any(flag in token[1:] for flag in "fd"):
                return f"git push {token} is not allowed: no force or delete pushes (plan 05, B2)."
        else:
            positional.append(token)
        index += 1
    refspecs = positional[1:]
    if not refspecs:
        if cwd is None:
            return "git push without a refspec needs a known working directory."
        branch = _run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
        refspecs = [branch or ""]
    for refspec in refspecs:
        if refspec.startswith("+") or refspec.startswith(":"):
            return f"git push {refspec} forces or deletes a branch (plan 05, B2)."
        destination = refspec.split(":", 1)[-1].removeprefix("refs/heads/")
        if destination == "HEAD" and cwd is not None:
            destination = _run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or ""
        if not FEATURE_BRANCH.fullmatch(destination):
            return f"Agents push only feat/* branches, never {destination or 'an unknown branch'!r} (plan 05, B2)."
    return None


def _git_error(words: tuple[_Word, ...], cwd: Path | None, role: str | None) -> str | None:
    index, cwd = _skip_git_options(words, cwd)
    if index is None:
        return None
    sub = words[index].text
    args = words[index + 1:]
    texts = [word.text for word in args]
    if sub in {"merge", "rebase"} and texts not in (["--abort"], ["--quit"]):
        return f"git {sub} is reserved for a person; agents commit on their feature branch (plan 05, B1)."
    if sub == "reset" and any(text == "--hard" for text in texts):
        return "git reset --hard discards work; agents never run it (plan 05, B1)."
    if sub == "branch" and ("-D" in texts or ({"-d", "--delete"} & set(texts) and {"-f", "--force"} & set(texts))):
        return "Force-deleting a branch is reserved for a person (plan 05, B1)."
    if sub == "push":
        return _push_error(args, cwd, role)
    return None


def delivery_check_passed(cwd: Path | None) -> bool:
    """A delivery-check.json in some work item reports PASS for the current HEAD commit."""
    if cwd is None:
        return False
    top = _run_git(cwd, "rev-parse", "--show-toplevel")
    head = _run_git(cwd, "rev-parse", "HEAD")
    if not top or not head:
        return False
    for path in Path(top).glob(DELIVERY_CHECK_GLOB):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(report, dict) and report.get("status") == "PASS" and report.get("commit") == head:
            return True
    return False


def _gh_error(words: tuple[_Word, ...], cwd: Path | None, role: str | None) -> str | None:
    texts = [word.text for word in words[1:]]
    if not texts:
        return None
    group = texts[0]
    sub = texts[1] if len(texts) > 1 else ""
    if group == "api":
        return "gh api can change anything on GitHub; agents never call it (plan 05, B1)."
    if group == "pr" and sub == "create":
        if role is not None and role != PUBLISHER_ROLE:
            return f"Only the {PUBLISHER_ROLE} opens pull requests (plan 05, B2)."
        if "--draft" not in texts and "-d" not in texts:
            return "Agents open draft pull requests only: add --draft (plan 05, B2)."
        if not delivery_check_passed(cwd):
            return ("No PASS delivery check for HEAD: run scripts/check_delivery.py and fix every "
                    "failing criterion before the draft PR (plan 05, D-B1).")
        return None
    if group in GH_DENIED:
        denied = GH_DENIED[group]
        if (denied is None and sub not in GH_READ) or (denied is not None and sub in denied):
            return f"gh {group} {sub} is reserved for a person (plan 05, B1)."
    return None


def inspect_command(command: str, cwd: Path | None, *, windows: bool | None = None,
                    role: str | None = None) -> GitAdmission:
    """Admit Git segments and return other shell commands for their existing policy."""
    windows = os.name == "nt" if windows is None else windows
    try:
        commands, substitutions = _scan(command, windows)
    except Rejected:
        return GitAdmission(remaining_commands=(command,))
    has_git = False
    error = None
    remaining: list[str] = []
    navigation: list[str] = []
    current = Path(cwd) if cwd is not None else None
    for item in commands:
        words, command_cwd = _unwrap(item.words, current)
        if not words:
            continue
        exe = executable([words[0].text])
        if exe in {"fi", "done"} and len(words) == 1:
            continue
        if exe in {"cd", "pushd", "set-location"}:
            navigation.append(item.raw)
            targets = [word for word in words[1:] if word.text.lower() not in {"/d", "--", "-literalpath", "-path"}]
            current = _directory(command_cwd, targets[0]) if len(targets) == 1 else None
            continue
        if exe in {"git", "gh"} and not words[0].dynamic:
            has_git = True
            check = _git_error if exe == "git" else _gh_error
            error = error or check(words, command_cwd, role)
        else:
            shell_options = {"sh": "-c", "bash": "-c", "zsh": "-c", "dash": "-c",
                             "cmd": "/c", "powershell": "-command", "pwsh": "-command"}
            shell_option = shell_options.get(exe)
            body = next((words[index + 1] for index in range(1, len(words) - 1)
                         if words[index].text.lower() == shell_option), None) if shell_option else None
            if body is not None and not body.dynamic:
                nested = inspect_command(body.text, command_cwd, windows=exe in {"cmd", "powershell", "pwsh"}, role=role)
                has_git = has_git or nested.has_git
                error = error or (nested.reason if nested.decision == "deny" else None)
                remaining.extend(" && ".join([*navigation, residual]) for residual in nested.remaining_commands)
            else:
                remaining.append(" && ".join([*navigation, item.raw]))
    for substitution in substitutions:
        nested = inspect_command(substitution, current, windows=windows, role=role)
        has_git = has_git or nested.has_git
        error = error or (nested.reason if nested.decision == "deny" else None)
        remaining.extend(" && ".join([*navigation, residual]) for residual in nested.remaining_commands)
    if not has_git:
        remaining = [command] if command.strip() else []
    return GitAdmission(has_git, "deny" if error else "allow", error or "", tuple(remaining))


def is_git_gh_command(command: str) -> bool:
    return inspect_command(command, Path.cwd()).has_git


def exact_path(root: Path, raw: str) -> str:
    """Exact-file check for editor grants; never a Git path restriction."""
    if not raw or raw.startswith(("-", "/", "\\")) or any(char in raw for char in "*?[:\\\0\r\n"):
        raise Rejected("Use an exact repository-relative editor file path.")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise Rejected("Editor paths cannot contain traversal.")
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise Rejected("Editor grants do not follow symlinks.")
    if candidate.is_dir() or not candidate.resolve().is_relative_to(root.resolve()):
        raise Rejected("The editor target must be a repository-contained file.")
    return raw


def pr_body_path(root: Path, raw: str, *, must_exist: bool = False) -> bool:
    try:
        if os.name == "nt":
            raw = raw.replace("\\", "/")
        candidate = Path(raw)
        if candidate.is_absolute():
            raw = candidate.relative_to(root).as_posix()
        if exact_path(root, raw) != PR_BODY:
            return False
        path = root / raw
        if not path.exists():
            return not must_exist
        metadata = path.stat()
        return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
    except (ValueError, OSError):
        return False
