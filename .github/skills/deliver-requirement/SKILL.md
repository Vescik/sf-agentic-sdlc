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

1. Start the station as a sub-agent of the named custom agent. Give it a written request with
   the work-item folder, the station's skill, its inputs and its expected outputs. Never pass
   results only in the request text: the station reads its inputs from files.
2. Ask the station to append one line to `run-log.md` when it ends: station, agent, UTC time,
   status (`DONE`, `RETURNED`, `BLOCKED`), output paths, and the next step. After the station,
   read its outputs and the log line from the work-item folder. The log is a record, not a gate.
3. Only `scripts/check_delivery.py` writes `delivery-check.json`; the hooks deny every agent
   edit of that file. Never ask a station to write or repair it by hand.
4. A station that finds a problem fixes it inside the attempt budget, or records it for H3. It
   does not stop the run.
5. Stop early only for these reasons:
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
| S1 requirements | `designer` | ADO input: follow `fetch-ado-item itemId=<ID>`. Then, for every input, write `requirements.md` (see below). | `requirements.md` is committed |
| S2 design | `designer` | Follow `solution-design` for the work item. The design lists the planned metadata components and traces each `AC-n` to the design. | `design.md` is committed |
| S3 design review | `reviewer` | Follow `check-against-principles itemId=<ID> scope=design`. | a review result exists; findings that block the design go back to S2 once, then to H3 as findings |
| S4 build | `developer` | Follow `development` on branch `feat/<id>-<slug>`: plan tasks, write source and Apex tests; for a new field, add a permission set with field access and assign it in the agent org; commit the source, deploy to the agent org, then commit `acceptance-trace.md` and `deploy-job-id`. | the work is committed and deployed |
| S5 check | `developer` | Run `python scripts/check_delivery.py --work-item <folder>`. On FAIL, fix the cause named in the failing details, commit, deploy, and run the check again. | `delivery-check.json` is PASS for HEAD, or the budget is spent |
| S6 implementation review | `reviewer` | Follow `check-against-principles itemId=<ID> scope=implementation` with the security list below. | review findings are written; a finding that breaks SC1–SC5 goes back to S4 inside the budget, every other finding goes to H3 |
| S7 draft PR | `git-agent` | Push `feat/<id>-<slug>` and open a draft PR with the delivery packet as its body. | the draft PR URL is known |
| H3 | person | Reviews the draft PR; merges or closes it. | — |

After S6, run the delivery check again when S6 caused a change. S7 starts only on a PASS for
the HEAD commit.

## S1: `requirements.md`

Write it for an ADO item and for a written requirement alike:

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
