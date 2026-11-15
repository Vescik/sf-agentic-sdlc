#!/usr/bin/env python3
"""One requirement in, a reviewable Salesforce delivery packet out (Copilot SDK host).

The orchestrator runs the W8 station chain over the harness agents. Each station is one Copilot
session as one custom agent (its role guard and the global safety hook stay active), and it ends
with a structured hand-over ticket. The host, not the model, decides what happens next:

    S1 intake      designer             fetch-ado-item            (ADO input only)
    S2 design      designer             solution-design
    S3 design rev. reviewer (checker)   check-against-principles  scope=design
    H1             human checkpoint     approve the design
    S4 build       developer            development               validate, deploy, test in agentOrg
    S5 quality     test-strategist      prepare-qa-test-plan
    S6 impl. rev.  reviewer (checker)   check-against-principles  scope=implementation
    H2             human checkpoint     approve after the security/implementation review
    S7 readiness   host                 writes the delivery packet from the tickets
    H3             human checkpoint     final go/no-go; agents never push, merge, or deploy to prod

Controls the host adds (docs/orchestrator.md):
- tripwire L3: a PASS ticket without existing evidence files becomes BLOCKED;
- tripwire L5: the permission policy rejects push, PR writes, merge and other publication;
- checker stations cannot write files; a checker FAIL returns to the builder at most
  ``MAX_RETURNS`` times, then the run escalates to a human;
- SAFE-DEPLOY-AUTONOMY-001: the CLI process gets ``SF_AGENTIC_AUTONOMOUS_ORG=<agentOrg>``, so
  the safety hook lets real deploys that name exactly that org run without a chat question;
- a hook ``ask`` reaches the human gate with the hook's own reason (the CLI has no native modal).

Usage:
    python scripts/sdlc_orchestrator.py --item 1234
    python scripts/sdlc_orchestrator.py --requirement-file requirement.md
    python scripts/sdlc_orchestrator.py --resume <run-id> [--decision H1=approve]
    python scripts/sdlc_orchestrator.py --plan          # print the station chain, no SDK needed

The Copilot SDK (``requirements-orchestrator.txt``) is imported only when a station runs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "output" / "orchestrator"
CONFIG_PATH = ROOT / "config" / "harness.local.json"
AUTONOMY_ENV = "SF_AGENTIC_AUTONOMOUS_ORG"  # read by scripts/copilot_safety_hook.py
MAX_RETURNS = 2  # W8 return limit: two returns per hand-over, the third failure escalates
STATION_TIMEOUT_SECONDS = 3600.0
TICKET_STATUSES = ("PASS", "FAIL", "BLOCKED", "INCOMPLETE")


@dataclass(frozen=True)
class Station:
    id: str
    title: str
    agent: str
    skill: str
    command: str
    arguments: str
    checker: bool = False
    returns_to: str | None = None
    ado_only: bool = False


STATIONS: tuple[Station, ...] = (
    Station("S1", "Requirement intake", "designer", "fetch-ado-item", "fetch-ado-item",
            "itemId={item}", ado_only=True),
    Station("S2", "Solution design", "designer", "solution-design", "solution-design",
            "{requirement}"),
    Station("S3", "Design review", "reviewer", "check-against-principles", "check-against-principles",
            "itemId={item} scope=design", checker=True, returns_to="S2"),
    Station("S4", "Build and org validation", "developer", "development", "development",
            "itemId={item}"),
    Station("S5", "QA test plan", "test-strategist", "prepare-qa-test-plan", "prepare-qa-test-plan",
            "itemId={item}"),
    Station("S6", "Implementation and security review", "reviewer", "check-against-principles",
            "check-against-principles", "itemId={item} scope=implementation {subject}",
            checker=True, returns_to="S4"),
)
STATION_BY_ID = {station.id: station for station in STATIONS}
CHECKPOINTS = {
    "H1": "Approve the design and its review before any code is written.",
    "H2": "Approve the build after the implementation and security review.",
    "H3": "Final go/no-go on the delivery packet. Push, PR, merge and production stay human.",
}
SEQUENCE = ("S1", "S2", "S3", "H1", "S4", "S5", "S6", "H2", "S7", "H3")

TICKET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["station", "status", "summary", "evidence", "open_questions", "next_action"],
    "properties": {
        "station": {"type": "string"},
        "status": {"type": "string", "enum": list(TICKET_STATUSES)},
        "summary": {"type": "string"},
        "work_item_id": {"type": ["string", "null"]},
        "work_item_folder": {"type": ["string", "null"]},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "commits": {"type": "array", "items": {"type": "string"}},
        "findings": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
    },
}


@dataclass
class Ticket:
    """The W8 hand-over ticket (L09 § A7): status, evidence and receipt for one station."""

    station: str
    status: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_action: str = ""
    work_item_id: str | None = None
    work_item_folder: str | None = None
    commits: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    tripwires: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, station: str, payload: Any) -> "Ticket":
        if isinstance(payload, str):
            payload = json.loads(extract_json(payload))
        if not isinstance(payload, dict):
            raise ValueError("ticket must be a JSON object")
        status = str(payload.get("status", "")).upper()
        if status not in TICKET_STATUSES:
            raise ValueError(f"ticket status {status!r} is not one of {TICKET_STATUSES}")

        def strings(key: str) -> list[str]:
            value = payload.get(key) or []
            return [str(item) for item in value] if isinstance(value, list) else [str(value)]

        def optional(key: str) -> str | None:
            value = payload.get(key)
            return str(value) if value not in (None, "") else None

        return cls(
            station=station,
            status=status,
            summary=str(payload.get("summary", "")),
            evidence=strings("evidence"),
            open_questions=strings("open_questions"),
            next_action=str(payload.get("next_action", "")),
            work_item_id=optional("work_item_id"),
            work_item_folder=optional("work_item_folder"),
            commits=strings("commits"),
            findings=strings("findings"),
        )


def extract_json(text: str) -> str:
    """Return the last JSON object in a reply (a fenced block or the bare object)."""
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        return fenced[-1]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("reply carries no JSON ticket")
    return text[start:end + 1]


def apply_tripwires(ticket: Ticket, root: Path = ROOT) -> Ticket:
    """L3: a PASS needs evidence, and every evidence path must exist inside the repository."""
    if ticket.status != "PASS":
        return ticket
    if not ticket.evidence:
        ticket.tripwires.append("L3: PASS without evidence")
    for raw in ticket.evidence:
        path = (root / raw).resolve()
        if root.resolve() not in path.parents and path != root.resolve():
            ticket.tripwires.append(f"L3: evidence outside the repository: {raw}")
        elif not path.exists():
            ticket.tripwires.append(f"L3: evidence file does not exist: {raw}")
    if ticket.tripwires:
        ticket.status = "BLOCKED"
    return ticket


# ── Permission policy (pure, testable without the SDK) ─────────────────────────────────────

PUBLICATION_PATTERNS = (
    (re.compile(r"\bgit\s+push\b"), "L5: push is a human action"),
    (re.compile(r"\bgit\s+merge\b"), "L5: merge is a human action"),
    (re.compile(r"\bgit\s+rebase\b"), "L5: history rewrites are a human action"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "destructive Git action"),
    (re.compile(r"\bgit\s+branch\s+-D\b"), "destructive Git action"),
    (re.compile(r"\bgh\s+pr\s+(?:create|merge|review|ready|edit|close|reopen|comment)\b"),
     "L5: PR writes, review and merge are human actions"),
    (re.compile(r"\bgh\s+(?:api|release|repo|workflow|secret)\b"), "L5: GitHub writes are human actions"),
)
SF_TARGET = re.compile(r"(?:--target-org|-o|--targetusername|-u)(?:=|\s+)([A-Za-z0-9._-]+)")
SF_DEPLOY = re.compile(r"\b(?:sf|sfdx)\s+(?:project\s+deploy|deploy\s+metadata|force:source:deploy|force:mdapi:deploy)\b")
ALLOWED_MCP_SERVERS = frozenset({"salesforce", "ado-readonly"})


@dataclass(frozen=True)
class PermissionDecision:
    allow: bool
    reason: str = ""
    ask_human: bool = False


def decide_permission(kind: str, details: dict[str, Any], station: Station, agent_org: str | None) -> PermissionDecision:
    """Host-side permission policy for one station. Hooks still run; this is a second layer."""
    if details.get("managed_approval_required"):
        return PermissionDecision(False, "managed policy requires a person", ask_human=True)
    if kind == "read":
        return PermissionDecision(True)
    if kind == "write":
        if station.checker:
            return PermissionDecision(False, f"{station.id} is a checker station and cannot write files")
        return PermissionDecision(True)
    if kind == "shell":
        command = str(details.get("command", ""))
        for pattern, reason in PUBLICATION_PATTERNS:
            if pattern.search(command):
                return PermissionDecision(False, reason)
        if SF_DEPLOY.search(command):
            targets = set(SF_TARGET.findall(command))
            if not agent_org or targets != {agent_org}:
                return PermissionDecision(
                    False, "deploys in an orchestrated run must name exactly the configured agent org"
                )
        return PermissionDecision(True)
    if kind == "mcp":
        server = str(details.get("server", ""))
        if server in ALLOWED_MCP_SERVERS or details.get("read_only") is True:
            return PermissionDecision(True)
        return PermissionDecision(False, f"MCP server {server!r} is not an allowed write channel")
    if kind == "hook":
        # A repository hook answered "ask": this is the CLI equivalent of the native modal.
        return PermissionDecision(False, str(details.get("message") or "hook asks for a person"), ask_human=True)
    return PermissionDecision(False, f"{kind} permission is not part of an orchestrated run")


# ── Human checkpoints ──────────────────────────────────────────────────────────────────────

class HumanGate(Protocol):
    def checkpoint(self, checkpoint: str, question: str, packet: str) -> tuple[str, str]: ...

    def confirm(self, station: str, reason: str) -> bool: ...

    def answer(self, station: str, question: str) -> str: ...


class ConsoleGate:
    """Ask the person at the terminal. Without a terminal, checkpoints pause the run."""

    def __init__(self, decisions: dict[str, str] | None = None, interactive: bool | None = None):
        self.decisions = dict(decisions or {})
        self.interactive = sys.stdin.isatty() if interactive is None else interactive

    def checkpoint(self, checkpoint: str, question: str, packet: str) -> tuple[str, str]:
        if checkpoint in self.decisions:
            return self.decisions[checkpoint], "decided on the command line"
        if not self.interactive:
            return "pending", "no interactive person; resume with --decision"
        print(f"\n=== {checkpoint}: {question}\n{packet}\n")
        answer = input(f"{checkpoint} approve/reject? ").strip().lower()
        note = input("Note for the record (optional): ").strip()
        return ("approve" if answer in {"a", "approve", "y", "yes"} else "reject"), note

    def confirm(self, station: str, reason: str) -> bool:
        if not self.interactive:
            return False
        print(f"\n[{station}] The harness asks for a person:\n{reason}")
        return input("Allow this exact operation once? [y/N] ").strip().lower() in {"y", "yes"}

    def answer(self, station: str, question: str) -> str:
        if not self.interactive:
            return ("No person is available inside this station. Record the question in "
                    "open_questions and return INCOMPLETE if it blocks the step.")
        print(f"\n[{station}] Agent question: {question}")
        return input("Answer: ").strip()


# ── Run state ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RunState:
    run_id: str
    requirement_kind: str  # "item" or "text"
    requirement: str
    agent_org: str | None
    autonomy: bool
    position: int = 0
    work_item_id: str | None = None
    work_item_folder: str | None = None
    returns: dict[str, int] = field(default_factory=dict)
    tickets: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: dict[str, dict[str, str]] = field(default_factory=dict)
    status: str = "RUNNING"
    started_at: str = field(default_factory=lambda: now())

    def save(self, runs_dir: Path = RUNS_DIR) -> Path:
        target = runs_dir / self.run_id / "state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return target

    @classmethod
    def load(cls, run_id: str, runs_dir: Path = RUNS_DIR) -> "RunState":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
            raise ValueError("invalid run id")
        return cls(**json.loads((runs_dir / run_id / "state.json").read_text(encoding="utf-8")))

    def last_ticket(self, station: str) -> dict[str, Any] | None:
        return next((t for t in reversed(self.tickets) if t["station"] == station), None)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── Station runner protocol and the Copilot SDK implementation ─────────────────────────────

class StationRunner(Protocol):
    def run_station(self, station: Station, prompt: str) -> Ticket: ...


def has_invocation_contract(skill: str, root: Path = ROOT) -> bool:
    path = root / ".github" / "skills" / skill / "SKILL.md"
    return path.is_file() and "## Invocation contract" in path.read_text(encoding="utf-8")


def build_prompt(station: Station, state: RunState, root: Path = ROOT) -> str:
    item = state.work_item_id or "<the work item ID from the design ticket>"
    requirement = (f"itemId={state.work_item_id}" if state.requirement_kind == "item"
                   else f"the written requirement below\n\n<requirement>\n{state.requirement}\n</requirement>")
    subject = ""
    if station.id == "S6":
        build = state.last_ticket("S4")
        commits = ",".join((build or {}).get("commits") or [])
        subject = f"commits={commits}" if commits else ""
    arguments = station.arguments.format(item=item, requirement=requirement, subject=subject).strip()
    upstream = state.tickets[-4:]
    contract = ", starting with its `Invocation contract`," if has_invocation_contract(station.skill, root) else ""
    lines = [
        f"Orchestrated run {state.run_id}, station {station.id} ({station.title}).",
        f"You are the `{station.agent}` agent. Run the `{station.command}` command: follow the "
        f"`{station.skill}` skill{contract} with: {arguments}",
        "No person is in this turn. Do not ask questions you can answer from the repository; record "
        "blocking questions in `open_questions` and return INCOMPLETE.",
        "Never push, open or merge a PR, or deploy to any org other than the configured agent org. "
        "Commit locally through the Git Workflow skill when the skill says so.",
    ]
    if station.id == "S4":
        if state.autonomy and state.agent_org:
            lines.append(
                f"Host autonomy grant (SAFE-DEPLOY-AUTONOMY-001) for agent org `{state.agent_org}`: "
                f"retrieve, validate (`sf project deploy validate` or `--dry-run`) and deploy with "
                f"`--target-org {state.agent_org}` without a chat question, then run the Apex tests "
                "and report the job IDs. Any other org or a quick deploy still needs a person."
            )
        else:
            lines.append("No autonomy grant in this run: stop before any real deploy and report it.")
    if station.checker:
        lines.append("You are the checker for this hand-over, not the builder: review only, never edit.")
    if upstream:
        lines.append("Previous hand-over tickets (most recent last):")
        lines.extend(f"- {t['station']} {t['status']}: {t['summary']}" for t in upstream)
    lines.append(
        "End your reply with the hand-over ticket as one JSON object: station, status "
        "(PASS|FAIL|BLOCKED|INCOMPLETE), summary, work_item_id, work_item_folder, evidence "
        "(repository-relative paths that exist), commits, findings, open_questions, next_action."
    )
    return "\n\n".join(lines)


class CopilotStationRunner:
    """One Copilot SDK client per run; one session per station, as that station's agent."""

    def __init__(self, gate: HumanGate, *, agent_org: str | None, autonomy: bool,
                 model: str | None = None, root: Path = ROOT):
        try:
            import copilot  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on the optional dependency
            raise SystemExit(
                "The Copilot SDK is not installed. Run: .venv/bin/pip install -r requirements-orchestrator.txt"
            ) from exc
        self.gate, self.agent_org, self.autonomy, self.model, self.root = gate, agent_org, autonomy, model, root
        self._loop = asyncio.Runner()
        self._client = None

    def close(self) -> None:
        if self._client is not None:
            self._loop.run(self._client.stop())
        self._loop.close()

    async def _ensure_client(self):
        from copilot import CopilotClient

        if self._client is None:
            env = dict(os.environ)
            env.pop(AUTONOMY_ENV, None)
            if self.autonomy and self.agent_org:
                env[AUTONOMY_ENV] = self.agent_org
            self._client = CopilotClient(env=env, working_directory=str(self.root))
            await self._client.start()
        return self._client

    def run_station(self, station: Station, prompt: str) -> Ticket:
        return self._loop.run(self._run(station, prompt))

    async def _run(self, station: Station, prompt: str) -> Ticket:
        client = await self._ensure_client()
        session = await client.create_session(
            agent=station.agent,
            model=self.model,
            working_directory=str(self.root),
            trust_working_directory="session",
            enable_config_discovery=True,
            enable_file_hooks=True,
            on_permission_request=self._permission_handler(station),
            on_user_input_request=self._user_input_handler(station),
            name=f"{station.id} {station.title}",
        )
        try:
            event = await session.send_and_wait(prompt, response_schema=TICKET_SCHEMA,
                                                timeout=STATION_TIMEOUT_SECONDS)
            content = getattr(getattr(event, "data", None), "content", None)
            if not content:
                return Ticket(station.id, "INCOMPLETE", "The station ended without a hand-over ticket.")
            try:
                return Ticket.from_payload(station.id, content)
            except (ValueError, json.JSONDecodeError) as exc:
                return Ticket(station.id, "INCOMPLETE", f"Unreadable hand-over ticket: {exc}")
        finally:
            await session.disconnect()

    def _permission_handler(self, station: Station) -> Callable[..., Any]:
        from copilot.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject

        def handler(request: Any, invocation: Any) -> Any:
            kind, details = describe_permission_request(request)
            decision = decide_permission(kind, details, station, self.agent_org)
            if decision.allow:
                return PermissionDecisionApproveOnce()
            if decision.ask_human and self.gate.confirm(station.id, decision.reason):
                return PermissionDecisionApproveOnce()
            return PermissionDecisionReject(feedback=decision.reason or "Not allowed in this station.")

        return handler

    def _user_input_handler(self, station: Station) -> Callable[..., Any]:
        async def handler(request: dict[str, Any], invocation: Any) -> dict[str, Any]:
            return {"answer": self.gate.answer(station.id, str(request.get("question", ""))),
                    "wasFreeform": True}

        return handler


def describe_permission_request(request: Any) -> tuple[str, dict[str, Any]]:
    """Map an SDK PermissionRequest variant onto (kind, details) for decide_permission."""
    kind = str(getattr(request, "kind", "unknown"))
    details: dict[str, Any] = {"managed_approval_required": bool(getattr(request, "managed_approval_required", False))}
    if kind == "shell":
        details["command"] = getattr(request, "full_command_text", "")
    elif kind == "write":
        details["path"] = getattr(request, "resolved_path", None) or getattr(request, "file_name", "")
    elif kind == "mcp":
        details["server"] = getattr(request, "server_name", "")
        details["tool"] = getattr(request, "tool_name", "")
        details["read_only"] = getattr(request, "read_only", False)
    elif kind == "hook":
        details["message"] = getattr(request, "hook_message", None) or getattr(request, "tool_name", "")
    elif kind == "url":
        details["url"] = getattr(request, "url", "")
    return kind, details


# ── Orchestrator ───────────────────────────────────────────────────────────────────────────

class Orchestrator:
    def __init__(self, runner: StationRunner, gate: HumanGate, state: RunState, *,
                 root: Path = ROOT, runs_dir: Path = RUNS_DIR, log: Callable[[str], None] = print):
        self.runner, self.gate, self.state = runner, gate, state
        self.root, self.runs_dir, self.log = root, runs_dir, log

    def run(self) -> RunState:
        while self.state.status == "RUNNING" and self.state.position < len(SEQUENCE):
            step = SEQUENCE[self.state.position]
            if step in CHECKPOINTS:
                self._checkpoint(step)
            elif step == "S7":
                self._write_packet()
                self.state.position += 1
            else:
                self._station(STATION_BY_ID[step])
            self.state.save(self.runs_dir)
        if self.state.status == "RUNNING":
            self.state.status = "DONE"
            self.state.save(self.runs_dir)
        return self.state

    def _station(self, station: Station) -> None:
        if station.ado_only and self.state.requirement_kind != "item":
            self.log(f"{station.id} skipped: written requirement, no ADO intake")
            self.state.position += 1
            return
        self.log(f"{station.id} {station.title} → {station.agent}")
        ticket = apply_tripwires(self.runner.run_station(station, build_prompt(station, self.state, self.root)), self.root)
        self.state.tickets.append(asdict(ticket))
        self.state.work_item_id = ticket.work_item_id or self.state.work_item_id
        self.state.work_item_folder = ticket.work_item_folder or self.state.work_item_folder
        self.log(f"{station.id} {ticket.status}: {ticket.summary}")
        if ticket.status == "PASS":
            self.state.position += 1
        elif ticket.status == "FAIL" and station.returns_to:
            used = self.state.returns.get(station.returns_to, 0)
            if used >= MAX_RETURNS:
                self.state.status = "ESCALATED"
                self.log(f"{station.id}: third failure of this hand-over; a person decides next")
            else:
                self.state.returns[station.returns_to] = used + 1
                self.state.position = SEQUENCE.index(station.returns_to)
                self.log(f"{station.id}: return {used + 1}/{MAX_RETURNS} to {station.returns_to}")
        else:
            self.state.status = "NEEDS_HUMAN"
            self.log(f"{station.id} stopped the run ({ticket.status}); see {self.state.run_id}/state.json")

    def _checkpoint(self, checkpoint: str) -> None:
        packet = self.packet_markdown()
        decision, note = self.gate.checkpoint(checkpoint, CHECKPOINTS[checkpoint], packet)
        if decision == "pending":
            self.state.status = "WAITING_FOR_HUMAN"
            self.log(f"{checkpoint} waits for a person: python scripts/sdlc_orchestrator.py "
                     f"--resume {self.state.run_id} --decision {checkpoint}=approve")
            return
        self.state.checkpoints[checkpoint] = {"decision": decision, "note": note, "at": now()}
        if decision == "approve":
            self.state.position += 1
        else:
            self.state.status = "REJECTED"
            self.log(f"{checkpoint} rejected by a person: {note}")

    def packet_markdown(self) -> str:
        lines = [
            f"# Delivery packet — run {self.state.run_id}",
            "",
            f"- Requirement: {self.state.requirement_kind} `{self.state.requirement[:120]}`",
            f"- Work item: {self.state.work_item_id or 'not yet known'} "
            f"({self.state.work_item_folder or 'folder not yet known'})",
            f"- Agent org: {self.state.agent_org or 'not configured'}; autonomy grant: "
            f"{'yes' if self.state.autonomy and self.state.agent_org else 'no'}",
            f"- Returns used: {self.state.returns or 'none'}",
            "",
            "| Station | Status | Summary | Evidence | Tripwires |",
            "|---|---|---|---|---|",
        ]
        for ticket in self.state.tickets:
            lines.append(
                f"| {ticket['station']} | {ticket['status']} | {ticket['summary'].replace('|', '/')} | "
                f"{', '.join(ticket['evidence']) or '—'} | {', '.join(ticket['tripwires']) or '—'} |"
            )
        questions = [q for t in self.state.tickets for q in t["open_questions"]]
        if questions:
            lines += ["", "## Open questions", *[f"- {q}" for q in questions]]
        if self.state.checkpoints:
            lines += ["", "## Human checkpoints",
                      *[f"- {key}: {value['decision']} ({value['at']}) {value['note']}"
                        for key, value in self.state.checkpoints.items()]]
        lines += ["", "Agents did not push, open or merge a PR, or deploy outside the agent org."]
        return "\n".join(lines) + "\n"

    def _write_packet(self) -> None:
        target = self.runs_dir / self.state.run_id / "delivery-packet.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.packet_markdown(), encoding="utf-8")
        self.log(f"S7 delivery packet: {target.relative_to(self.root) if self.root in target.parents else target}")


# ── CLI ────────────────────────────────────────────────────────────────────────────────────

def configured_agent_org(config_path: Path = CONFIG_PATH) -> tuple[str | None, str | None]:
    """Return (alias, environment) of salesforce.agentOrg from the ignored local policy."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    salesforce = config.get("salesforce") or {}
    alias = salesforce.get("agentOrg")
    entry = next((org for org in salesforce.get("orgs") or [] if org.get("alias") == alias), None)
    environment = str(entry.get("environment")) if entry else None
    return (alias if isinstance(alias, str) else None), environment


def parse_decisions(values: list[str]) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for value in values:
        key, _, decision = value.partition("=")
        if key not in CHECKPOINTS or decision not in {"approve", "reject"}:
            raise SystemExit(f"--decision expects H1|H2|H3=approve|reject, got {value!r}")
        decisions[key] = decision
    return decisions


def print_plan() -> None:
    for step in SEQUENCE:
        if step in CHECKPOINTS:
            print(f"{step}  human checkpoint      {CHECKPOINTS[step]}")
        elif step == "S7":
            print("S7  host                  write the delivery packet from the tickets")
        else:
            s = STATION_BY_ID[step]
            role = f"{s.agent}{' (checker)' if s.checker else ''}"
            print(f"{s.id}  {role:21} {s.command} {s.arguments}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--item", help="ADO work item ID (numeric)")
    source.add_argument("--requirement-file", type=Path, help="file with a written requirement")
    source.add_argument("--resume", help="continue a saved run")
    parser.add_argument("--decision", action="append", default=[], help="H1|H2|H3=approve|reject")
    parser.add_argument("--no-autonomy", action="store_true", help="never grant autonomous agent-org deploys")
    parser.add_argument("--model", help="model for every station (default: the CLI default)")
    parser.add_argument("--plan", action="store_true", help="print the station chain and exit")
    args = parser.parse_args(argv)

    if args.plan:
        print_plan()
        return 0
    agent_org, environment = configured_agent_org()
    if args.resume:
        state = RunState.load(args.resume)
        state.status = "RUNNING" if state.status in {"WAITING_FOR_HUMAN", "RUNNING"} else state.status
    else:
        if args.item:
            if not args.item.isdigit():
                raise SystemExit("--item must be a numeric ADO work item ID")
            kind, requirement = "item", args.item
        elif args.requirement_file:
            kind, requirement = "text", args.requirement_file.read_text(encoding="utf-8").strip()
        else:
            parser.error("give --item, --requirement-file, or --resume")
        autonomy = not args.no_autonomy and environment in {"dev", "uat", "stage"}
        if not args.no_autonomy and not autonomy:
            print(f"No autonomy grant: salesforce.agentOrg is {agent_org or 'unset'} "
                  f"(environment {environment or 'unclassified'}); deploys will stop for a person.")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        state = RunState(run_id, kind, requirement, agent_org, autonomy,
                         work_item_id=requirement if kind == "item" else None)
    gate = ConsoleGate(parse_decisions(args.decision))
    runner = CopilotStationRunner(gate, agent_org=state.agent_org, autonomy=state.autonomy, model=args.model)
    try:
        final = Orchestrator(runner, gate, state).run()
    finally:
        runner.close()
    print(f"Run {final.run_id}: {final.status} — output/orchestrator/{final.run_id}/")
    return 0 if final.status in {"DONE", "WAITING_FOR_HUMAN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
