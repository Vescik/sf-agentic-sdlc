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
- adds --trust-folder for a prompt-mode session (-p/--prompt), which has no trust prompt.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "harness.local.json"
AUTONOMY_ENV = "SF_AGENTIC_AUTONOMOUS_ORG"  # read by scripts/copilot_safety_hook.py
DEFAULT_AGENT = "sdlc-conductor"
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
    command = copilot_command(args)
    env = {**os.environ, AUTONOMY_ENV: agent_org}
    print(f"sdlc: agent org {agent_org} (dev); {' '.join(command)}", file=sys.stderr)
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
