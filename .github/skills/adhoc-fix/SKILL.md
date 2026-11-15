---
name: adhoc-fix
description: Express lane for a small bounded defect fix, including optional confirmed deployment and org verification.
user-invocable: false
---

# Ad-hoc defect fix (express lane)

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
[Managed Package Boundaries](../../instructions/managed-package.instructions.md).

This lane is the owner-approved exception (decision of 2026-07-23) to the developer
accepted-design entry gate. It exists so a diagnosed defect — a broken Flow decision, a wrong
validation formula, a mislabeled field — can be fixed in the repository the moment the diagnosis
is in hand. Everything else about the role's boundaries is unchanged: edits stay inside
`force-app/`, `manifest/`, and `tests/e2e/`; a real deploy follows the Developer's single-use chat
confirmation rule.

## Invocation contract

Role: `developer`. Run this contract only as the `developer` custom agent, whose role guard applies.
Arguments: `component=<Type:Name> [org=<alias>] plus the diagnosis or a pointer to it`.
Entry points: VS Code `/adhoc-fix <arguments>` (thin alias `.github/prompts/adhoc-fix.prompt.md`);
Copilot CLI `copilot --agent developer` with `adhoc-fix <arguments>`. A `/<command> <arguments>`
next action in this repository means the same pair on Copilot CLI.
VS Code narrows the tools for this entry point to: `read`, `search`, `edit`, `execute`, `vscode/askQuestions`, `salesforce/review_org_identity`, `salesforce/review_object_contract`, `salesforce/review_soql_query`. Copilot CLI applies the agent's own list.

Require a named target component and a written diagnosis (ask once
(VS Code: `vscode/askQuestions`; Copilot CLI: in the reply) if either is missing). This lane replaces the accepted-design entry
gate only for a small bounded defect fix; retrieve the current org state first, make the smallest
coherent edit in `force-app/`, and write the fix note under
`output/documentation/adhoc-fixes/`.

Report the fix note path, the before → after of the defective element, local verification, and the
proposed deployment scope. If a real deploy is needed, ask with the target, scope, and explicit
org-change warning, then run only the exact confirmed command and verify the result. If the fix
stops being small and bounded, route through the normal design lane.

## Entry conditions

- A written diagnosis exists: what is broken, in which component, expected vs. actual behavior,
  and the evidence trail (investigation output, error message, or the user's own description).
  Restate it at the top of the fix note; do not start editing from a vague "something is wrong".
- The fix is small and bounded: one defect, the smallest coherent set of components (typically
  one), no new automation, no object/field schema changes, no permission changes. When the fix
  grows beyond that, stop and route through the normal design lane instead of stretching this one.
- Package ownership and namespace are recorded as impact context, not used as a harness-level deny.

## Procedure

1. Retrieve the current org state of the target component before editing, so the fix is based on
   what is deployed, not on a stale local copy:
   `sf project retrieve start --target-org <configured-alias> --metadata <Type:Name>`
   (the target may be explicit or use the normal project/default CLI context).
2. Read the retrieved source and confirm the diagnosis against it — the exact element, formula,
   or connector that is wrong. When the defect plausibly depends on real record shape (field
   fill, picklist values in use, lookup population), probe it through the governed
   `review_soql_query` facade tool — verbatim SOQL over the facade's REST transport — rather
   than assuming — preferred practice per the 2026-07-30/2026-08-04 owner decisions; probed numbers quoted
   in the fix note cite the org alias and observation time. If the retrieved state
   contradicts the diagnosis, stop and report instead of guessing.
3. Find dependents before touching the component: search the repository-root `force-app/`
   source for references to it (who reads, writes and grants access to it). An empty result
   is a recorded gap and is NEVER proof that nothing depends on this component; name any
   unchecked metadata type as an unknown in the fix note.
4. Make the smallest coherent edit in `force-app/`. Match the existing metadata style; change the
   defective element, not the surrounding structure.
5. Verify what can be verified locally: the XML parses, the changed element is the only
   difference against the retrieved copy, and any referenced fields/labels/subflows exist in the
   local source.
6. Write the fix note to `output/documentation/adhoc-fixes/<yyyy-mm-dd>-<component>.md`:
   diagnosis (verbatim), files changed, the exact before → after of the defective element,
   verification performed, the proposed deploy command and component list, and the rollback path.
7. If a real deploy is in scope, state the target and scope, warn that changes will be deployed to
   the org, and ask `Should I run this deployment?` Run the exact command only after an
   unambiguous answer. Record the job and verify org state. After the result, append the
   operation once to the canonical durable log using the
   [Development skill](../development/SKILL.md) — the applicable Work Item/Feature log when one
   exists, otherwise `docs/org-changes/<yyyy-mm-dd>-<slug>.md`. Link that path from the ignored
   fix note; never duplicate the entry or leave the fix note as the sole durable record. Recommend an
   after-the-fact guardrail review — the human opens the reviewer role on the fix note
   and changed files; record the verdict by appending a `Review outcome` section to the note.

## Prohibitions

- Never run a real deploy without fresh confirmation for that exact target, scope, and command.
- Never fix more than the diagnosed defect in one pass — no drive-by refactors, no "while I'm
  here" cleanups, no scope growth past the bounded-fix entry condition.
- Never edit outside `force-app/`, `manifest/`, `tests/e2e/`, the fix note, and the single
  canonical org-change log; approvals,
  Principles, and records remain out of reach.
- Never present the repository edit as deployed, fixed-in-org, or verified-in-org without a
  successful deploy receipt and explicit verification.

## Return

Return the fix note path; the diagnosis summary; files changed with the before → after of the
defective element; local verification performed; the proposed or executed deploy command and
component list; deployment receipt and org verification when run; the rollback path; and the
canonical org-change-log path (or `none — no qualifying org mutation executed`); and the
recommendation to run the after-the-fact guardrail review.
