# SDLC orchestrator (Copilot SDK)

Status: implemented 2026-11-15 on branch `feat/copilot-sdk-harness`. Host logic is covered by
`tests/test_sdlc_orchestrator.py` with a fake runner. **Not yet run against a live Copilot
session or org.**

One requirement goes in: an ADO work item ID or a written requirement. The orchestrator runs
the W8 station chain over the harness agents and writes a reviewable delivery packet. People
keep the decisions that must stay human.

```bash
.venv/bin/pip install -r requirements-orchestrator.txt     # Copilot SDK, bundles CLI 1.0.112
.venv/bin/python scripts/sdlc_orchestrator.py --plan         # print the chain, no SDK needed
.venv/bin/python scripts/sdlc_orchestrator.py --item 1234
.venv/bin/python scripts/sdlc_orchestrator.py --requirement-file requirement.md
.venv/bin/python scripts/sdlc_orchestrator.py --resume <run-id> --decision H1=approve
```

Run state, tickets and the packet go to `output/orchestrator/<run-id>/` (ignored by Git).

## Station chain

| Step | Who | Skill (command) | Done when |
|---|---|---|---|
| S1 intake | `designer` | `fetch-ado-item` | ADO input only; `ado-context.md` persisted and committed |
| S2 design | `designer` | `solution-design` | `design.md` committed |
| S3 design review | `reviewer`, checker | `check-against-principles` `scope=design` | PASS; FAIL returns to S2 |
| H1 | person | — | design approved before code is written |
| S4 build | `developer` | `development` | code committed locally; validate, deploy and tests in the agent org |
| S5 quality | `test-strategist` | `prepare-qa-test-plan` | `qa-test-plan.md` committed |
| S6 implementation and security review | `reviewer`, checker | `check-against-principles` `scope=implementation commits=…` | PASS; FAIL returns to S4 |
| H2 | person | — | build approved after the review |
| S7 readiness | host | — | `delivery-packet.md` written from the tickets |
| H3 | person | — | final go/no-go; push, PR, merge and production stay human |

Each station is one Copilot session as one custom agent, so the agent's role guard and the
global safety hook apply. The session loads the repository's agents, skills, instructions,
hooks and MCP servers (`enable_config_discovery`, `enable_file_hooks`, session-scoped trust).

## Hand-over ticket

Every station ends with one JSON ticket (W8 L09 § A7), requested through the SDK
`response_schema`: `station`, `status` (`PASS`, `FAIL`, `BLOCKED`, `INCOMPLETE`), `summary`,
`work_item_id`, `work_item_folder`, `evidence`, `commits`, `findings`, `open_questions`,
`next_action`. The host, not the model, decides the next step from it.

## Host controls

| Control | Where | Effect |
|---|---|---|
| L3 missing evidence | `apply_tripwires` | A PASS without evidence, or with a path that does not exist or leaves the repository, becomes BLOCKED. |
| L5 self-approval, merge, publication | `decide_permission` | `git push`, `git merge`, `git rebase`, `git reset --hard`, `git branch -D`, `gh pr create/merge/review/…`, `gh api/release/repo/…` are rejected in every station. |
| Checker ≠ builder | `decide_permission` | S3 and S6 cannot write files (the reviewer role guard also denies edits). |
| Return limit | `Orchestrator._station` | A checker FAIL returns to its builder at most 2 times; the third failure stops the run as ESCALATED. |
| Agent org only | `decide_permission` | A deploy command must name exactly `salesforce.agentOrg` with `--target-org`. |
| Hook asks | permission handler | A hook `ask` (for example a deploy outside the grant) goes to the person at the terminal with the hook's reason. Without a terminal it is rejected. |
| Questions | user-input handler | An agent question goes to the person at the terminal; without one, the agent records it in `open_questions`. |
| Checkpoints | `ConsoleGate` | H1–H3 ask at the terminal. Without a terminal the run pauses as WAITING_FOR_HUMAN; resume with `--decision`. |

## Agent org and autonomy

`salesforce.agentOrg` in `config/harness.local.json` names the one org the agents work against.
It must be a `salesforce.orgs` entry. Both Salesforce review MCP entries (`.vscode/mcp.json`,
`.github/mcp.json`) start with it (`--org-from-config`); no host prompts for an alias. The review
facade still proves host, Org ID and IsSandbox before tools.

Owner decision 2026-11-15: in an orchestrated run, retrieve, validate and deploy to the agent org
need no fresh confirmation (SAFE-DEPLOY-AUTONOMY-001 in
`.github/instructions/managed-package.instructions.md`):

- the orchestrator starts the Copilot CLI process with `SF_AGENTIC_AUTONOMOUS_ORG=<agentOrg>`;
  the hook process inherits it from the host, and no model command can set it;
- `scripts/copilot_safety_hook.py` then allows a real `sf project deploy start` or
  `sf deploy metadata` only when every `--target-org` is exactly the agent org and the org is
  classified `dev`, `uat` or `stage`;
- quick deploys, destructive source deletes, CLI defaults, other orgs and `prod` keep the
  existing question or denial. Validate (`--dry-run`) and retrieve never needed one.

`--no-autonomy` turns the grant off for a run. An agent org classified `prod` never gets it.

## Limits

- **Not live-verified.** The SDK calls follow `github-copilot-sdk` 1.0.34. Run one short
  requirement end to end and record the result before relying on it.
- **Native Salesforce operation tool.** It exists only in VS Code (SAFE-HOST-NATIVE-001). Steps
  that need it (unconfigured targets, latest selectors, environment answers) stop and report.
- **Tool narrowing per station.** The host rejects publication and checker writes, but uses the
  agent's own tool list otherwise. Narrower per-station lists (`available_tools`) are a next step
  once the CLI tool names are confirmed on a live run.
- **Model tier per station.** One `--model` for the whole run for now (W8 L01 is open).
- **Supply chain.** `requirements-orchestrator.txt` pins the SDK version but not hashes; it is
  outside the hash-locked `requirements-dev.lock` and outside CI.
