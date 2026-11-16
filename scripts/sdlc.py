#!/usr/bin/env python3
"""Start a delivery session on Copilot CLI (plan 05, decisions D-A2 and D-SR).

    python scripts/sdlc.py [--agent <name>] [copilot options …]

The launcher
- always runs Copilot CLI from the repository root, so repository hooks and MCP servers load;
- runs scripts/first_launch.py when config/harness.local.json or salesforce.agentOrg is missing;
- refuses an agent org that is not a configured developer org (environment `dev`);
- sets SF_AGENTIC_AUTONOMOUS_ORG=<agentOrg> for the CLI process. The safety hook inherits it and
  lets real deploys, quick deploys and source deletes to exactly that org run without a
  question. A model command cannot set this variable for the hook;
- adds --trust-folder for a prompt-mode session (-p/--prompt), which has no trust prompt;
- finishes a delivery run in prompt mode (plan 05, live runs 8-9: the conductor reached a PASS
  delivery check but skipped the reviewer and git-agent stations). When the current `feat/*`
  branch has a PASS `delivery-check.json` for HEAD, the launcher starts the missing stations
  itself: S6 `reviewer` (its answer is saved under `.cache/delivery/`) and S7 `git-agent`, which
  pushes the branch and opens the draft PR. The hooks still judge every action. `--no-finish`
  turns this off.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "harness.local.json"
AUTONOMY_ENV = "SF_AGENTIC_AUTONOMOUS_ORG"  # read by scripts/copilot_safety_hook.py
DEFAULT_AGENT = "sdlc-conductor"
DELIVERY_CACHE = ROOT / ".cache" / "delivery"
PR_BODY = ROOT / ".cache" / "github" / "pr-body.md"
S6_PROMPT = (
    "Station S6 of deliver-requirement (implementation and security review) for {work_item} on "
    "branch {branch}. Follow check-against-principles with scope=implementation for the commits "
    "since main, and the S6 security list of the deliver-requirement skill (CRUD/FLS, sharing, "
    "SOQL injection, hard-coded IDs, secrets, personal data, managed-package boundaries). Do not "
    "edit files. Answer with the verdict, then the findings ordered by severity."
)
S7_PROMPT = (
    "Station S7 of deliver-requirement for {work_item}. delivery-check.json is PASS for HEAD "
    "{head}. Push the branch {branch} to origin and open a DRAFT pull request against main with "
    "the body file .cache/github/pr-body.md: gh pr create --draft --base main --head {branch} "
    "--title {title!r} --body-file .cache/github/pr-body.md. Report the PR URL."
)
Runner = Callable[..., "subprocess.CompletedProcess[str]"]
FALLBACK_AGENT = "designer"


class LaunchError(Exception):
    pass


def developer_agent_org(config_path: Path = CONFIG) -> str:
    """Return salesforce.agentOrg when it is a configured org of environment `dev`."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaunchError(f"{config_path.relative_to(ROOT) if config_path.is_relative_to(ROOT) else config_path} is missing or invalid") from exc
    salesforce = config.get("salesforce") if isinstance(config, dict) else None
    alias = salesforce.get("agentOrg") if isinstance(salesforce, dict) else None
    if not isinstance(alias, str) or not alias.strip():
        raise LaunchError("salesforce.agentOrg is not set")
    orgs = salesforce.get("orgs") if isinstance(salesforce.get("orgs"), list) else []
    entry = next((org for org in orgs if isinstance(org, dict) and org.get("alias") == alias), None)
    if entry is None:
        raise LaunchError(f"salesforce.agentOrg {alias!r} is not a salesforce.orgs entry")
    environment = {"development": "dev"}.get(entry.get("environment"), entry.get("environment"))
    if environment != "dev":
        raise LaunchError(
            f"salesforce.agentOrg {alias!r} is environment {entry.get('environment')!r}; a delivery run "
            "works only against a developer org (environment \"dev\", plan 05 D-A2)"
        )
    return alias


def copilot_command(args: list[str], agents_dir: Path = ROOT / ".github" / "agents") -> list[str]:
    args = list(args)
    if "--agent" not in args and not any(arg.startswith("--agent=") for arg in args):
        agent = DEFAULT_AGENT if (agents_dir / f"{DEFAULT_AGENT}.agent.md").is_file() else FALLBACK_AGENT
        args = ["--agent", agent, *args]
    prompt_mode = any(arg in ("-p", "--prompt") or arg.startswith("--prompt=") for arg in args)
    if prompt_mode and "--trust-folder" not in args:
        args.append("--trust-folder")
    return ["copilot", *args]


def strip_session_args(args: list[str]) -> list[str]:
    """The user's Copilot options without --agent, -p/--prompt and --output-format (and values)."""
    rest: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in ("--agent", "-p", "--prompt", "--output-format"):
            skip = True
            continue
        if arg.startswith(("--agent=", "--prompt=", "--output-format=")) or arg in ("--trust-folder", "--no-finish"):
            continue
        rest.append(arg)
    return rest


def _run(runner: Runner, command: list[str], env: dict[str, str] | None = None) -> "subprocess.CompletedProcess[str]":
    return runner(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)


def agent_answer(stdout: str) -> str:
    """The last top-level assistant message of a `--output-format json` Copilot session."""
    answer = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = event.get("data") or {}
        if event.get("type") == "assistant.message" and data.get("content") and not data.get("parentToolCallId"):
            answer = data["content"]
    return answer


def run_station(agent: str, prompt: str, extra: list[str], env: dict[str, str], runner: Runner) -> str:
    command = ["copilot", "--agent", agent, "-p", prompt, *extra, "--trust-folder", "--output-format", "json"]
    print(f"sdlc: finishing the run with {agent}", file=sys.stderr)
    return agent_answer(_run(runner, command, env).stdout)


def finish_delivery(extra: list[str], env: dict[str, str], runner: Runner = subprocess.run) -> list[str]:
    """Start S6 and S7 when the conductor left them out of a PASS delivery (see the module doc)."""
    branch = _run(runner, ["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if not branch.startswith("feat/"):
        return [f"not finishing: branch {branch or '?'} is not a feat/* branch"]
    work_item = ROOT / "work-items" / branch.removeprefix("feat/")
    head = _run(runner, ["git", "rev-parse", "HEAD"]).stdout.strip()
    try:
        report = json.loads((work_item / "delivery-check.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"not finishing: no delivery-check.json in {work_item.relative_to(ROOT)}"]
    if report.get("status") != "PASS" or report.get("commit") != head:
        return [f"not finishing: delivery check is {report.get('status')} for {str(report.get('commit'))[:12]}, HEAD is {head[:12]}"]
    notes = []
    relative = work_item.relative_to(ROOT).as_posix()
    review = DELIVERY_CACHE / f"{work_item.name}-implementation-review.md"
    if not review.is_file():
        answer = run_station("reviewer", S6_PROMPT.format(work_item=relative, branch=branch), extra, env, runner)
        DELIVERY_CACHE.mkdir(parents=True, exist_ok=True)
        review.write_text(f"# S6 implementation review ({head[:12]})\n\n{answer or '(no answer)'}\n", encoding="utf-8")
        notes.append(f"S6 review saved to {review.relative_to(ROOT)}")
    listing = _run(runner, ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url"])
    try:
        open_prs = json.loads(listing.stdout or "[]") if listing.returncode == 0 else None
    except json.JSONDecodeError:
        open_prs = None
    if open_prs is None:
        return notes + ["not finishing S7: gh pr list failed"]
    if open_prs:
        return notes + [f"S7 already done: {open_prs[0].get('url')}"]
    body = PR_BODY.read_text(encoding="utf-8") if PR_BODY.is_file() else ""
    if not body.strip():
        body = (f"## Summary\n\nDelivery run for `{relative}`.\n\n## Delivery check\n\n"
                + "\n".join(f"- {c.get('id')} {c.get('status')}: {c.get('title')}" for c in report.get("criteria", []))
                + "\n\nManual steps: " + ("; ".join(report.get("manualSteps") or []) or "none") + "\n")
    if "## S6 implementation review" not in body:
        body += "\n## S6 implementation review\n\n" + re.sub(r"^# .*\n+", "", review.read_text(encoding="utf-8")) + "\n"
    PR_BODY.parent.mkdir(parents=True, exist_ok=True)
    PR_BODY.write_text(body, encoding="utf-8")
    title = f"[{work_item.name.split('-', 1)[0]}] {work_item.name.split('-', 1)[-1].replace('-', ' ')}"
    answer = run_station("git-agent", S7_PROMPT.format(work_item=relative, head=head[:12], branch=branch, title=title),
                         extra, env, runner)
    return notes + [f"S7: {answer[:300] or '(no answer)'}"]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    try:
        agent_org = developer_agent_org()
    except LaunchError as first:
        print(f"sdlc: {first}; running scripts/first_launch.py", file=sys.stderr)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "first_launch.py")], cwd=ROOT, check=False)
        try:
            agent_org = developer_agent_org()
        except LaunchError as exc:
            print(f"sdlc: {exc}. Set salesforce.agentOrg in config/harness.local.json to a configured "
                  "developer org and start again.", file=sys.stderr)
            return 2
    if shutil.which("copilot") is None:
        print("sdlc: Copilot CLI is not installed (brew install --cask copilot-cli)", file=sys.stderr)
        return 2
    finish = "--no-finish" not in args
    args = [arg for arg in args if arg != "--no-finish"]
    command = copilot_command(args)
    env = {**os.environ, AUTONOMY_ENV: agent_org}
    print(f"sdlc: agent org {agent_org} (dev); {' '.join(command)}", file=sys.stderr)
    code = subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
    prompt_mode = any(arg in ("-p", "--prompt") or arg.startswith("--prompt=") for arg in args)
    agent = next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "--agent"), None) or next(
        (a.split("=", 1)[1] for a in args if a.startswith("--agent=")), DEFAULT_AGENT)
    if finish and prompt_mode and agent == DEFAULT_AGENT:
        for note in finish_delivery(strip_session_args(args), env):
            print(f"sdlc: {note}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
