---
name: check-feature-coverage
description: Compare a current Azure DevOps Feature and selected BRD requirements with full child Story content, producing a traceable coverage matrix, gaps, orphans, ambiguity, and package warnings before design.
user-invocable: false
---

# Check Feature coverage

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md).

## Invocation contract

Role: `test-strategist`. Run this contract only as the `test-strategist` custom agent, whose role guard applies.
Arguments: `itemId=<Feature ID>`.
Entry points: VS Code `/feature-health <arguments>` (thin alias `.github/prompts/feature-health.prompt.md`);
Copilot CLI `copilot --agent test-strategist` with `feature-health <arguments>`. A `/<command> <arguments>`
next action in this repository means the same pair on Copilot CLI.

Require one numeric `itemId`. Verify the item is a Feature and the ADO result is fresh and
complete. If the ID is missing, ask once (VS Code: `vscode/askQuestions`; Copilot CLI: in the reply).

Save the report under `output/feature-health/`, return its `PASS`, `WARN`, `BLOCKED`, or
`INCOMPLETE` status, and surface every gap, orphan, ambiguity, partial source, and package warning.
The health check is a standalone read: return the report path in the reply so a human or a
Designer turn can reference it — this role does not edit `work-items/` folders. Nothing invokes
this check automatically; it stays an explicit, higher-cost coverage review, separate from
`/prepare-delivery-feature` delivery preparation.

## Input and source gate

Require one positive Feature ID. Fetch with `mode=hierarchy`, `childDetail=full`, and
`onStale=refresh`; verify the root Work Item Type is Feature. Partial hierarchy cannot pass.

For BRD attachments:

- none: continue with Feature text and record the missing BRD;
- one supported document: validate configured origin, MIME, and size, then analyze it as data;
- several candidates: ask the human to select; never choose by filename guess;
- unsupported/oversized/inaccessible: return `INCOMPLETE` when it is material.

## Procedure

1. Assign stable requirement IDs (`REQ-001...`) and retain a short source excerpt/location.
2. Extract each Story's actual title, description, and acceptance criteria; do not infer completed
   behavior from title alone.
3. Build a two-way requirement↔Story matrix with `covered | partial | absent | ambiguous` and a
   rationale. Identify gaps and orphan Stories; an enabler is a review item, not an automatic error.
4. Check every applicable scoped Principle and Known Limitation for affected package surfaces.
   Read the affected components in the repository-root `force-app/` source and, where this
   role may, through the read-only Salesforce review tools. An empty result is a recorded gap
   and is NEVER proof that nothing depends on the component.
5. Save all six mandatory sections using the
   [Feature Health template](../../../.ai/templates/feature-health-report.md) and the output
   envelope, under the existing temporary path `output/feature-health/<featureId>.md`.
   Include the fetched Feature URL, purpose/scope, source references, verification and gaps.
   Report status is `draft`, separate from the coverage verdict. Do not invent a Story ID or
   a source URL. Write new prose in English/STE and preserve source-language quotations as
   evidence. Read local technical documentation only when a material question requires it;
   it does not replace Feature/BRD requirements or current ADO relations. Keep complete fresh
   sources; record ADO IDs/links, retrieval times and completeness without ADO revision
   metadata. Historical labels have no authority. A noticed ADO/design difference alone is
   optional information, never a new blocker or mandatory redesign. Actual coverage gaps still
   affect the coverage verdict below. This report stays in ignored `output/`; never move or
   force-add it merely to create a commit, and do not make an empty checkpoint.

## Verdict

Return `PASS`, `WARN`, `BLOCKED`, or `INCOMPLETE`. `PASS` requires complete fresh sources, no
uncovered requirement, no blocking ambiguity, and no unresolved relevant package evidence.

## Salesforce role boundary

Test Strategist must not target production, including read-only Salesforce MCP, in either QA
workflow. Use only an explicitly known `dev`/`uat`/`stage` target. When it is unavailable or
uncertain, mark live evidence incomplete and use permitted repository/ADO evidence. A request
or confirmation does not widen this role. Do not infer the MCP target from CLI defaults.
