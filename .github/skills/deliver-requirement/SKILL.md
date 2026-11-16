---
name: deliver-requirement
description: Run one requirement through intake, design, review, build, the end-of-run delivery check and a draft PR, with each station as a sub-agent in the developer agent org.
user-invocable: false
---

# Deliver Requirement

One requirement goes in; a draft PR with a PASS delivery check comes out, or a run report that
names the failing criteria. Decisions: [plan 05](../../../docs/plan05-w8-integration.md).
Success: [delivery success contract](../../../.ai/contracts/delivery-success.md).

## Invocation contract

Role: `sdlc-conductor`. Run this contract only as the `sdlc-conductor` custom agent, whose role guard applies.
Arguments: `itemId=<ID> | requirementFile=<path> [feedback=<path>]`.
Entry points: VS Code `/deliver-requirement <arguments>` (thin alias `.github/prompts/deliver-requirement.prompt.md`);
Copilot CLI `python scripts/sdlc.py` (starts `copilot --agent sdlc-conductor` with the agent-org
grant) with `deliver-requirement <arguments>`.

Exactly one of `itemId` and `requirementFile` is required. `feedback` starts the next iteration
of an earlier run: the same work item and branch, the person's feedback file as new input, and
a new attempt budget. When an argument is missing or both are given, ask once and wait.

## Rules for every station

1. Start the station as a sub-agent of the named custom agent: the `task` tool with
   `agent_type` set to the agent name (`designer`, `reviewer`, `developer`, `git-agent`). The
   hooks deny every other sub-agent, including the built-in `task` and `general-purpose`
   agents. Do not set a `model`; the station inherits the session model. Give it a written request with
   the work-item folder, the station's skill, its inputs and its expected outputs. Never pass
   results only in the request text: the station reads its inputs from files.
2. Ask the station to append one line to `run-log.md` when it ends: station, agent, UTC time,
   status (`DONE`, `RETURNED`, `BLOCKED`), output paths, and the next step. After the station,
   read its outputs and the log line from the work-item folder. The log is a record, not a gate.
3. Ask every station to write and change files with its editor tools, not with shell commands
   such as `python3 -c`, heredocs or PowerShell here-strings, and to run `git` and `sf` directly,
   one command at a time, never through a Python `subprocess` or a script. A shell command that
   mentions `sf` inside its text is denied as a chained Salesforce command.
4. Only `scripts/check_delivery.py` writes `delivery-check.json`; the hooks deny every agent
   edit of that file. Never ask a station to write or repair it by hand.
5. A station that finds a problem fixes it inside the attempt budget, or records it for H3. It
   does not stop the run.
6. Tell every station that this is a delivery run (SAFE-DELIVERY-RUN-001): gaps become recorded
   assumptions and PR findings, never a stop.
7. Stop early only for these reasons:
   - the requirement cannot be understood, two requirements contradict each other, or an input
     is missing: ask the person one exact question, wait, record the answer in
     `requirements.md`, and continue;
   - the attempt budget is spent (6 delivery checks in one iteration): end the run with the
     last `delivery-check.json` and the failing criteria, without push or PR;
   - `delivery-check.json` is BLOCKED: tests outside the delivery fail in the org. Do not fix
     them. End the run, list the `blockers`, and ask the person to fix the org and start the
     next iteration;
   - a hook denies an action that the run needs and no permitted way exists: report the
     denial and its reason, and end the run.

## Stations

| Step | Agent | Request | Done when |
| --- | --- | --- | --- |
| S1 requirements | `designer` | Before S1, fix the run's identity and say it in every station request: the work-item folder `work-items/<id>-<slug>` and the branch `feat/<id>-<slug>`. For an ADO item, `<id>` is its ID; for a `requirementFile`, `<id>` is the next free number in `work-items/` and the requirement is a written, human-provided requirement with no ADO item. Pass the exact input (the file path, which the station reads itself, or the ADO item ID). ADO input: follow `fetch-ado-item itemId=<ID>`. Then, for every input, create the branch and write `requirements.md` (see below). | `requirements.md` is committed on `feat/<id>-<slug>` |
| S2 design | `designer` | Follow `solution-design` with the written requirement in `work-items/<id>-<slug>/requirements.md` (or `itemId=<ID>` for ADO input). Say that no `ado-context.md` exists for a written requirement. The design lists the planned metadata components and traces each `AC-n` to the design. Everything the requirement excludes (for example "no Flow", "no backfill") is listed under Explicit exclusions and never appears in the planned change surface. | `design.md` is committed |
| S3 design review | `reviewer` | Follow `check-against-principles itemId=<ID> scope=design`. | a review result exists; findings that block the design go back to S2 once, then to H3 as findings |
| S4 build | `developer` | Follow `development` on branch `feat/<id>-<slug>`. The launcher granted deploy autonomy (`SF_AGENTIC_AUTONOMOUS_ORG`): deploy with `--target-org <agent org>` and do not ask for confirmation; the hooks enforce the limits. Plan tasks, write source and Apex tests; for a new field, add a permission set with field access and assign it in the agent org; commit the source, deploy to the agent org, then commit `acceptance-trace.md` and `deploy-job-id`. | the work is committed and deployed |
| S5 check | `developer` | Run `node scripts/check-delivery.mjs --work-item <folder>` (the same command on macOS and Windows; never `python3`, which Windows lacks). On FAIL, fix the cause named in the failing details, commit, deploy, and run the check again. | `delivery-check.json` is PASS for HEAD, or the budget is spent |
| S6 implementation review | `reviewer` | Follow `check-against-principles itemId=<ID> scope=implementation` with the security list below. | review findings are written; a finding that breaks SC1–SC5 goes back to S4 inside the budget, every other finding goes to H3 |
| S7 draft PR | `git-agent` | Push `feat/<id>-<slug>` and open a draft PR with the delivery packet as its body. | the draft PR URL is known |
| H3 | person | Reviews the draft PR; merges or closes it. | — |

Every station runs as its own sub-agent, in this order. S3 and S6 are `reviewer` sub-agents
and S7 is a `git-agent` sub-agent; never mark a station DONE or RETURNED without starting its
sub-agent (live run 8 skipped all three). After S6, run the delivery check again when S6 caused
a change. S7 starts only on a PASS for the HEAD commit and is not optional: a PASS without a draft
PR is an unfinished run.

## S1: `requirements.md`

The designer writes it with its editor tool (a shell `printf` or heredoc write is blocked by the
CLI's own shell safety). Write it for an ADO item and for a written requirement alike:

- `## Requirements`: numbered `R-1`, `R-2`, … in plain sentences.
- `## Acceptance criteria`: `AC-1`, `AC-2`, … each one observable and testable. Keep the IDs
  stable; mark a dropped criterion as dropped instead of renumbering.
- `## Assumptions`: numbered `A-1`, … for every gap that the agent closed without asking. Each
  assumption names the requirement it touches.
- `## Questions and answers`: the exact question asked and the person's answer, when the run
  had to ask.
- `## Source`: the ADO item (`ado-context.md`) or the requirement file; for a feedback
  iteration, also the feedback file.

## S6: security list

The review covers CRUD and FLS enforcement, `with sharing` or `inherited sharing` on every new
class, dynamic SOQL injection, hard-coded IDs, secrets and endpoints (Named Credentials only),
personal data in logs and test data, and managed-package boundaries. Findings are reported, not
a gate, unless they break a success criterion.

## S7: delivery packet (draft PR body)

Write it to `.cache/github/pr-body.md` with these sections: requirement summary and source; the
`delivery-check.json` result with each criterion; manual steps from SC1; assumptions; open
findings from S3 and S6; changed components; rollback (how to remove or revert the deployed
components in the developer org); and the run log path.

## Feedback iteration

With `feedback=<path>`: read the earlier `run-log.md`, `requirements.md` and the feedback file.
Update `requirements.md` (new answers, changed or added criteria, with stable IDs), then start at
the earliest station the feedback affects: S1 or S2 for a changed requirement, S4 for a defect.
The attempt budget starts again. The draft PR, when one exists, is updated by the git-agent.

## Run report

End with the line per station from `run-log.md`, the number of delivery checks used, the final
`delivery-check.json` status, and the draft PR URL or the failing criteria.
