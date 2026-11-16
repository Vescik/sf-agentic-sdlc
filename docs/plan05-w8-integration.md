# Plan 05: W8 SDLC chain as instructions, judged by a few success criteria

Status: plan, 2026-11-16. Phases 1 (delivery check), 2 (boundaries) and 3 (conductor) are implemented;
Phase 0 (live spike) is blocked, see [Implementation notes](#implementation-notes). Owner
decisions recorded in [Decisions](#decisions-2026-11-16) are binding for the work below.

## Goal

One requirement goes in (an ADO work item ID or a written requirement). Copilot CLI runs the
station chain over the harness agents and ends with a draft PR that meets a short list of
success criteria. The agent works on its own. The target is always a developer org, so a wrong
delivery costs one more iteration, not damage. A person is asked during the run only when the
requirement cannot be understood. The final go/no-go on the draft PR (H3) always stays human.

## Lesson from W8: few gates, all checked by code

The full W8 design stopped a run at almost every hand-over. At each one the model judged
whether evidence was "complete", a requirement "clear" or a ticket "valid". Every such judgment
was a point where two runs of the same input went different ways, and the agents kept stopping
on some problem. The runs were not deterministic.

This plan keeps the W8 _work order_ (stations, roles, checker ≠ builder) and drops the W8
_mid-chain gates_:

1. **Stations are instructions.** A conductor agent runs them in order. Tickets between stations
   are a run log, not a gate: nothing stops on a ticket.
2. **Success is judged once, at the end, by a script.** `scripts/check_delivery.py` runs or reads
   the Salesforce results itself and answers PASS or FAIL per criterion. An agent's statement
   that something is done counts for nothing.
3. **Boundaries are hooks.** What an agent must never do (production, merge, force push) is
   denied by code, the same way every time. Boundaries never depend on the model's judgment.
4. **Only two things stop a run early:** a requirement the agent cannot understand (it asks one
   question and waits), and an exhausted attempt budget (6 loops; the person can start the next
   iteration with feedback). Everything else the agent works around or fixes itself
   ([Self-repair](#self-repair-instead-of-stops)).

W8 patterns are rewritten in this repository's words. No `W8_*` file is copied here, and all
golden-case data is synthetic.

## Starting point (main `cba1002`, 2026-11-16)

- Merged: PR #2 (Knowledge removed), PR #3 (release handover removed), PR #4 (Copilot CLI port and
  SDK orchestrator `scripts/sdlc_orchestrator.py`).
- Local gates green: validator 2546 assertions, 80 deterministic evals, 697 unit tests.
- CI on `main` has been red since the first commit: `npm audit --omit=dev --audit-level=high`
  fails on dependencies of `@azure-devops/mcp` (`qs` critical among them). Later CI steps do not
  run.
- Not live-verified: no `config/harness.local.json` (`salesforce.agentOrg` unset), Copilot SDK not
  installed, Dev Hub `devmp` needs re-auth. Copilot CLI 1.0.112 is installed.
- The station chain already exists as a Python host (`docs/orchestrator.md`) with mid-chain
  tripwires. This plan moves the chain into instructions and replaces the tripwires with the end
  check. The host stays only as an optional headless runner (Phase 6).

## Success criteria

A run succeeds when every criterion passes for the **same commit** (the HEAD of the `feat/*`
branch). `check_delivery.py` writes the result to `work-items/<id>-<slug>/delivery-check.json`
with the commit SHA. The file is a report for people, not a gate input: the hook that allows the
draft PR runs the script itself (B2, D-R3).

| #   | Criterion                                          | How the script checks it                                                                                                                                                                                                                                                                                                       |
| --- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| SC1 | Every acceptance criterion is covered              | Each `AC-n` ID in `requirements.md` appears in the trace table with at least one Apex test method (`Class.method`). That method exists in `force-app/` and has outcome `Pass` in the SC2 run. An AC that cannot be tested in Apex names a written manual test step instead, and the report lists it as "manual" so H3 sees it. |
| SC2 | All Salesforce tests are green                     | The script itself runs `sf apex run test --test-level RunLocalTests --result-format json --wait …` against `agentOrg`: 0 failed. If the repository has LWC Jest tests, `npm run test:unit` exits 0. Apex tests run in the org; "local" means the org's local (non-managed) tests.                                              |
| SC3 | Coverage ≥ 75% for every changed class and trigger | From the SC2 result. "Changed" means Apex classes and triggers changed on the branch against its base (`git diff --name-only <base>...HEAD`). Without it, a later production deploy fails the platform's 75% rule.                                                                                                             |
| SC4 | Metadata deployed without missing components       | The script reads the deploy result from the org (`sf project deploy report --job-id <id> --json`, read-only), not from a file an agent wrote: status `Succeeded`, and every source file changed on the branch under `force-app/` is in the deployed file list. A changed file that was not deployed is a FAIL.                 |
| SC5 | Clean result                                       | The working tree is clean, all work is committed on a `feat/*` branch, and the deploy and test runs belong to the HEAD commit.                                                                                                                                                                                                 |

Reported, not blocking:

- **Static scan:** `sf code-analyzer run` on the changed files. High and critical findings are
  listed in the report for H3. This starts as a warning because the scanner can raise false
  positives. Make it a criterion once a few runs show the noise level.
- **Assumptions:** the numbered assumptions are repeated in the report and the draft PR, so
  H3 sees every one.

## Decisions 2026-11-16

| ID   | Decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Replaces                                                                           |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| D-A2 | The `agentOrg` is always a **developer** org (environment class `dev`, a Developer Edition or a scratch org). The launcher refuses an `agentOrg` of any other class, and the autonomy grant in the safety hook applies only to `dev`. Real deploys to that org need no chat question in any CLI session started through the repository launcher. `uat`, `stage` and `prod` are never targets of a run.                                                                                                                             | SAFE-DEPLOY-AUTONOMY-001: grant for `dev`, `uat` or `stage`, orchestrated run only |
| D-B1 | When `delivery-check.json` is PASS for HEAD, the `git-agent` may push the `feat/*` branch and open a **draft** PR. Merge, ready-for-review, approve and production stay human.                                                                                                                                                                                                                                                                                                                                                     | "agents never push or open PRs" in orchestrated runs                               |
| D-D2 | No human checkpoint during the run (H1 and H2 removed). On a developer org a wrong delivery has no lasting cost: the person sends feedback and starts the next iteration. H3 on the draft PR always stays.                                                                                                                                                                                                                                                                                                                         | three checkpoints H1–H3                                                            |
| D-D4 | An unclear requirement does not stop the run: the agent writes a numbered assumption and continues; the assumptions go to the draft PR for H3. Only a requirement the agent **cannot understand at all**, a contradiction (two requirements that cannot both hold) or a missing input makes it ask the person one exact question and wait. The answer is recorded in `requirements.md`.                                                                                                                                            | W8 "the run stops and returns to S1" for every ambiguity                           |
| D-SC | Success is the five criteria SC1–SC5, checked by `check_delivery.py` at the end. Mid-chain tickets are a log, not a gate.                                                                                                                                                                                                                                                                                                                                                                                                          | W8 L3 evidence checks at every hand-over (L09 § A7)                                |
| D-R1 | Removed as hard stops: commit subject format; the "run from the repository root" rule; the checker write ban; the question for an unknown MCP tool; ADO blocks for a missing config and for scope outside the configured project; org and project enumeration.                                                                                                                                                                                                                                                                     | safety hook and role guard rules of the same name                                  |
| D-R2 | Per-role path limits are removed. One shared list of protected control files stays, which no agent writes: `.github/hooks/`, `.github/agents/`, `.github/instructions/`, `.github/mcp.json`, `.vscode/`, `scripts/copilot_*.py`, `scripts/*_policy.py`, `scripts/start_*_mcp.mjs`, `config/`, `schemas/`. The Salesforce development MCP stays denied (it would deploy around the `sf` policy). An unresolved Dev Hub stays denied only for `package delete` and `package uninstall`, because a Dev Hub is often a production org. | per-role edit allowlists; full Dev Hub and enumeration denies                      |
| D-R3 | No file guard for `delivery-check.json`. The draft-PR rule in the safety hook runs `check_delivery.py` itself for HEAD instead of reading a file. ADO writes stay limited to the two existing tools (wiki page, work-item artifact link).                                                                                                                                                                                                                                                                                          | planned role-guard rule for `approvals/` and `delivery-check.json`                 |
| D-AB | Attempt budget: the build-and-fix loop (S5 → check → fix) runs at most **6** times per iteration. Each loop must change the cause named in the failing log, not repeat the same attempt. After the sixth FAIL the iteration ends with the failing criteria and no PR. The person can start the next iteration on the same branch with a feedback file (`deliver-requirement itemId=… feedback=<file>`); the budget starts again.                                                                                                   | proposed budget of 3                                                               |
| D-SR | Expired org auth, missing local config, an untrusted folder and the missing VS Code native tool are not stops. The agent or the launcher works around them ([Self-repair](#self-repair-instead-of-stops)).                                                                                                                                                                                                                                                                                                                         | stops 36–39 of the 2026-11-16 list                                                 |

Proposed defaults, not yet confirmed by the owner (apply unless changed):

| ID   | Proposal                                                                                                                                                        |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P-A3 | Quick deploy and `project delete source` are allowed without a question against the developer `agentOrg` (D-A2); against any other org they stay "ask".         |
| P-A5 | Add `sf code-analyzer run` (read-only) to the Salesforce command allowlist.                                                                                     |
| P-A7 | Data-writing commands (`data delete/update/upsert bulk`, `apex run`) are allowed only against the `agentOrg`. Today they are allowed on any non-production org. |
| P-B2 | Push becomes a hook rule, not a sentence: only `feat/*` branches, never `main`, never `--force`, only by `git-agent`.                                           |
| P-C5 | Hook timeout fails open in the CLI. Keep hooks well under 10 s and add a test that measures the role guard and the safety hook on a cold start.                 |

## When a run stops

| Stop                                                               | What happens                                                                                                                                       | Enforced by                                 |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Requirement not understandable, contradictory, or an input missing | the agent asks one exact question and waits; the answer goes to `requirements.md` and the run continues                                            | conductor instruction (D-D4)                |
| Attempt budget exhausted (6 loops)                                 | the iteration ends FAIL with `delivery-check.json` and the failing criteria; no push, no PR; the person may start the next iteration with feedback | conductor instruction, attempt count in log |
| Boundary hit                                                       | the tool call is denied; the agent reports it and continues within limits, or ends the run                                                         | hooks (table below)                         |

Nothing else stops a run. A station that finds a problem fixes it within the budget or records
it for H3.

## Self-repair instead of stops

| Situation                                         | What the agent or launcher does                                                                                                                                                                                                                | Still needs a person                                                 |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Org or Dev Hub auth expired                       | checks with `sf org display`; the CLI refreshes the access token itself. If the refresh token is dead, the run pauses with one command for the person (`! sf org login web -a <alias>`) and resumes from the work-item folder after the login. | the login itself: agents never handle credentials (SAFE-CRED-001)    |
| `config/harness.local.json` or `agentOrg` missing | the launcher runs `scripts/first_launch.py`, which sets `agentOrg` when exactly one non-production org is configured                                                                                                                           | the choice, once, when there are zero or several non-production orgs |
| Untrusted folder, CLI started from a subdirectory | the launcher always changes to the repository root and starts the CLI with `--trust-folder`, so hooks and MCP servers load                                                                                                                     | —                                                                    |
| VS Code native Salesforce tool missing in the CLI | the agent uses the direct `sf` CLI under the same `sf` policy: the org class comes from the config instead of the VS Code dialog, and `latest` selectors are resolved and named explicitly                                                     | — (replaces the SAFE-HOST-NATIVE-001 stop on the CLI)                |
| A build or test failure                           | fixes inside the attempt budget (D-AB)                                                                                                                                                                                                         | after 6 loops, the run report goes to the person                     |

## Boundaries (hooks, unchanged by the model)

`ask` becomes `deny` in CLI autopilot mode, so every "ask" is a hard stop when nobody is at the
terminal.

| #   | Boundary                                                                                                                            | Kind                    | Where                                              |
| --- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | -------------------------------------------------- |
| A1  | Production: CLI allows only metadata retrieve; confirmation cannot override                                                         | deny                    | `salesforce_operation_policy.py` (SAFE-PROD-001)   |
| A2  | Real deploy to any org other than the developer `agentOrg`, or without the launcher grant                                           | ask                     | safety hook (SAFE-DEPLOY-CONFIRM-001, D-A2)        |
| A3  | Quick deploy, destructive source delete                                                                                             | ask (P-A3)              | safety hook                                        |
| A4  | Missing `--target-org`, unclassified org, CLI defaults                                                                              | deny                    | Salesforce policy                                  |
| A5  | `sf` command not on the allowlist; flag files; wrappers                                                                             | deny                    | Salesforce policy, safety hook                     |
| A6  | Salesforce development MCP; `package delete` and `package uninstall` with an unresolved Dev Hub                                     | deny                    | safety hook, Salesforce policy (D-R2)              |
| B1  | Merge, rebase, `reset --hard`, `branch -D`, `gh pr merge/review/ready`, `gh api`                                                    | deny                    | safety hook (new rule; today only in the SDK host) |
| B2  | Push other than `feat/*` by `git-agent`; non-draft PR; draft PR when the hook's own run of `check_delivery.py` for HEAD is not PASS | deny (P-B2, D-B1, D-R3) | safety hook (new rule)                             |
| C1  | Protected control files (list in D-R2) written by any agent                                                                         | deny                    | role guard (one shared list, D-R2)                 |
| C2  | Destructive patterns (`rm -rf`, `DROP TABLE`, `DELETE FROM`)                                                                        | deny                    | safety hook                                        |
| C3  | Interactive shell input, browser tools                                                                                              | deny                    | safety hook                                        |
| C4  | ADO writes other than the wiki page and the work-item artifact link                                                                 | deny                    | safety hook, `ado_tool_policy.py` (D-R3)           |

Removed as hard stops (D-R1, D-R2): commit subject format, the repository-root rule for
terminal commands, per-role path limits, the checker write ban, the question for an unknown MCP
tool, ADO blocks for missing config and project scope, org and project enumeration, and the Dev
Hub block for every command except `package delete` and `package uninstall`. Checker roles stay
separate agents with their own instructions; separation is now by role, not by permission.

## Station map (work order, not gates)

| Station          | Agent                | Skill                                                              | Output in `work-items/<id>-<slug>/`                                                  | Work            |
| ---------------- | -------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------ | --------------- |
| S1 requirements  | `designer`           | `fetch-ado-item`; new mode "requirement from text"                 | `requirements.md`: numbered requirements, `AC-n` acceptance criteria, assumptions    | add text intake |
| S2 design        | `designer`           | `solution-design`                                                  | `design.md` with requirement → design traceability                                   | exists          |
| S3 design review | `reviewer` (checker) | `check-against-principles scope=design`                            | review notes in the log; problems go back to S2 inside the budget                    | exists          |
| S4 build         | `developer`          | `development` (plan section first, open item O-1)                  | commits on `feat/*`; deploy and Apex tests in `agentOrg`; AC → test trace table      | extend          |
| S5 check and fix | `developer`          | new `check-delivery` skill                                         | `delivery-check.json` from the script; fix and re-run, at most 6 times (D-AB)        | new             |
| S6 review        | `reviewer` (checker) | `check-against-principles scope=implementation` plus security list | findings for H3; a finding that breaks a criterion goes back to S4 inside the budget | extend          |
| S7 draft PR      | `git-agent`          | new `delivery-packet` skill                                        | pushed `feat/*`, draft PR with the check result, assumptions, findings and rollback  | new             |
| H3               | person               | —                                                                  | the person reviews the draft PR and merges or closes it                              | —               |

The S6 security list covers CRUD/FLS enforcement, `with sharing` and `inherited sharing`,
dynamic SOQL injection, hard-coded IDs, secrets and endpoints (Named Credentials), personal data
in logs and test data, and managed-package boundaries. Its findings are reported, not a gate,
unless they break SC1–SC5.

The W8 stations S5 quality and S6 security are folded into the end check (SC1–SC3) and the S6
review here. The W8 planning station is a plan section at the start of the build (O-1).

## What gets written

Instructions:

- `.github/agents/sdlc-conductor.agent.md`: runs the stations as sub-agents with a fresh context
  each, passes state through files in the work item, stops only as listed in
  [When a run stops](#when-a-run-stops), and resumes from the work-item folder.
- `.github/skills/deliver-requirement/SKILL.md`: the station table, the stop list, the attempt
  budget, and the invocation contract (`copilot --agent sdlc-conductor`, then
  `deliver-requirement itemId=…` or `requirementFile=…`).
- `.ai/contracts/delivery-success.md`: SC1–SC5, the warning list, and the trace-table format
  (`AC-n` → `Class.method` or manual step).
- New or extended skills: requirement from text (S1), plan section in `development` (S4),
  `check-delivery` (S5), security list (S6), `delivery-packet` (S7).
- `.ai/templates/`: `requirements.md`, `feedback.md` (input for the next iteration),
  `delivery-packet.md` (the draft PR body).
- `evals/agent-scenarios.yaml`: golden cases with synthetic Salesforce requirements (Phase 5).

Runtime:

- `scripts/check_delivery.py`: SC1–SC5 as above, JSON output with the commit SHA, unit tests with
  recorded `sf` JSON fixtures. The SDK orchestrator calls the same script.
- Role guard: per-role path limits replaced by one shared protected-file list (D-R2).
- Launcher: changes to the repository root, starts the CLI with `--trust-folder`, runs
  `first_launch.py` when `agentOrg` is missing, and refuses an `agentOrg` that is not class `dev`
  (D-A2, D-SR).
- Safety hook: B1 and B2 Git rules, including "draft PR only when its own run of
  `check_delivery.py` passes for HEAD"; the launcher grant (D-A2); removal of the D-R1 rules.
- `scripts/sdlc` launcher (a few lines): checks `agentOrg`, sets `SF_AGENTIC_AUTONOMOUS_ORG`, and
  starts `copilot --agent sdlc-conductor` from the repository root. The model cannot set this
  variable.

## Phases (one PR each)

0. **Live spike (blocks the rest).** Needs `config/harness.local.json` with `agentOrg` and the
   `devmp` re-auth. Record the CLI version and the answers:
   1. Can a custom agent start another custom agent as a sub-agent?
   2. Do the sub-agent's frontmatter hooks (role guard) run?
   3. Does `model:` in agent frontmatter work (model per station)?
   4. The six checks in `docs/copilot-cli-port.md` § Live verification.

   If question 1 is "no", the conductor cannot exist as instructions. The SDK host then runs the
   stations, and Phases 1, 2, 4 and 5 still apply unchanged.

1. **Success check:** `.ai/contracts/delivery-success.md`, `scripts/check_delivery.py`, tests
   with recorded `sf` JSON. This comes first because every later phase is judged by it.
2. **Boundaries:** remove the D-R1 rules and the per-role limits; add the shared protected-file
   list (D-R2); B1/B2 Git rules; launcher grant for `dev` only (D-A2); P-A5 and P-A7 if
   confirmed; update tests and safety evals for every removed or added rule.
3. **Conductor:** `sdlc-conductor` agent and `deliver-requirement` skill; validator checks for the
   new files.
4. **Missing stations:** S1 text intake, plan section in S4, `check-delivery` skill, S6 security
   list, `delivery-packet` and draft PR.
5. **Golden cases and live runs:** N (normal: a field, a validation rule and an Apex handler with
   tests), E (edge: contradictory requirements, where the agent must ask before design; and a
   requirement that touches a managed-package field), T (trap: the requirement asks to merge and
   deploy to production, which the hooks must deny). One full live run of N and one of T,
   recorded in the work item. Success for this phase: N ends with a PASS check and a draft PR;
   two runs of N end with the same criteria results; a failed iteration of N followed by a
   feedback iteration ends PASS.
6. **SDK host decision:** if the conductor passes Phase 5, the SDK orchestrator stays as a thin
   headless runner over the same check, or is removed. No new work on it before then.

## Open items

- O-1: the planning step as a section at the start of `development` (proposed), or its own
  skill?
- O-2: CI red on `npm audit`: fix before Phase 1 (upgrade, or a documented exception for
  `@azure-devops/mcp`), so CI runs the validator and the tests again.
- O-3: dependabot PR #1 is still open.
- O-4: confirm or change P-A3, P-A5, P-A7, P-B2 and P-C5.
- O-6: SAFE-HOST-NATIVE-001 in `.github/instructions/managed-package.instructions.md` must be
  rewritten for the CLI fallback (D-SR) in Phase 2.

## Out of scope

Wiki publication, release handover, Knowledge, production deploys, merges by an agent, mid-chain
evidence gates, and real client data.

## Implementation notes

- **Phase 0 (2026-11-16):** Copilot CLI 1.0.112 authenticates through `gh` but every session
  fails with "Access denied by policy settings": the account has no Copilot CLI access. The
  only result: the CLI ignores the agent frontmatter fields `argument-hint` and `handoffs` with
  a warning.
- **Phase 1:** `scripts/check_delivery.py` and `.ai/contracts/delivery-success.md`. The trace
  table is the file `acceptance-trace.md`; the deploy job ID is the file `deploy-job-id`.
- **Phase 2, deviation from D-R3:** the draft-PR hook reads `delivery-check.json` and requires
  PASS for the current HEAD commit. It does not run `check_delivery.py` itself, because the
  check runs the Apex tests (minutes) and a CLI hook that exceeds its 10 s timeout fails open.
  An agent could therefore write a false report; H3 sees the report in the draft PR and can run
  the check again.
- **Phase 2, launcher:** `scripts/sdlc.py` (D-A2, D-SR). The SDK orchestrator keeps its own
  push and PR ban (Phase 6 decides its future); its autonomy grant is now `dev` only.
- **Phase 3:** `.github/agents/sdlc-conductor.agent.md` delegates to `designer`, `reviewer`,
  `developer` and `git-agent`; `.github/skills/deliver-requirement/SKILL.md` holds the station
  table, the stop list, `requirements.md`, the S6 security list, the draft-PR packet and the
  feedback iteration. Most of Phase 4 (S1 text intake, planning, check step, security list,
  packet) is written into this skill; Phase 4 now means testing and refining each station on a
  live run. The validator check `check_delivery_conductor` pins delegation and the budget.
- **Phase 5 (written, not run):** golden cases N1, E1, E2 and T1 with evaluator oracles in
  `evals/fixtures/delivery-golden/`, and four `conductor-` scenarios in
  `evals/agent-scenarios.yaml`. The live runs wait for Copilot CLI access and a developer org.
- **Found, not decided:**
  - The role guard keeps a per-role terminal allowlist (read-only commands, the harness scripts,
    `sf` for the developer). It was not on the hard-stop list. `check_delivery.py` was added
    for every role; other commands (for example `npm`, `sf` for roles other than the developer)
    stay denied.
  - A Dev Hub classified `prod` blocks `sf org create scratch` (production allows only
    metadata retrieve). A scratch org as the agent org needs a decision on this rule.

