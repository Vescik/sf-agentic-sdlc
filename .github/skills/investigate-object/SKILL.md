---
name: investigate-object
description: Collect bounded, sanitized evidence about a scoped Salesforce component or package question, and report it read-only.
user-invocable: false
---

# Investigate a Salesforce component question

This is a read-only investigation lane: the outcome is a sanitized report under
`output/investigations/`. Semantic org/vendor conclusions belong in the report.

## Invocation contract

Role: `config-investigator`. Run this contract only as the `config-investigator` custom agent, whose role guard applies.
Arguments: `objectApiName=<API name>`.
Entry points: VS Code `/investigate-object <arguments>` (thin alias `.github/prompts/investigate-object.prompt.md`);
Copilot CLI `copilot --agent config-investigator` with `investigate-object <arguments>`. A `/<command> <arguments>`
next action in this repository means the same pair on Copilot CLI.
VS Code narrows the tools for this entry point to: `read`, `search`, `edit`, `execute`, `vscode/askQuestions`, `salesforce/review_org_identity`, `salesforce/review_installed_packages`, `salesforce/review_object_contract`, `salesforce/review_configured_orgs`, `salesforce/review_soql_query`. Copilot CLI applies the agent's own list.

Require exactly one `objectApiName` (ask once (VS Code: `vscode/askQuestions`; Copilot CLI: in the reply) if missing). The
name must be on the configured review allowlist; evidence stays bounded, sanitized, and
grounded through the guarded review tools (record reads via `review_soql_query`); the facade proves the live org identity within the active role's limits before tool discovery, and object facts reconcile the describe and Tooling endpoints with contested traits nulled and listed in `contestedProperties`.

The outcome is a sanitized investigation report under `output/investigations/` — never a
verified fact. Report the report path,
reconciliation status, limitations, and any drift or contested findings. The investigation is a standalone read; when it was raised by delivery work, link the
report from the relevant `work-items/<id>-<slug>/` folder.

## Input

Require the exact question, normalized package/component subject, environment,
criticality, and why current repository evidence is insufficient. When delivery
work raised the investigation, note the work item (`work-items/<id>-<slug>/`) so the
report can be linked from it; a standalone read with no work item is a valid lane and not
a reason to stop.
Reject a generic “inspect the org,” unspecified target, record dump, or component outside
the configured review allowlist. Route record data-shape questions (structure, fill,
distributions) to the governed record reads instead of rejecting them (owner decision
2026-07-30): `review_soql_query` on the facade, or
[investigate-config-records](../investigate-config-records/SKILL.md).

## Procedure

1. Read the relevant metadata-repository state under `force-app/`.
2. Classify the source authority required. A package guarantee needs a vendor source;
   business meaning needs reviewed human evidence; live deployed configuration may use
   org observation.
3. Define the smallest factual proposition. For an absence question, report what you
   checked and how — enumeration scope, method, pagination bounds, and limitations — and
   state absence as an observation within those bounds, never as proof. Whether that
   coverage suffices is the reviewer's judgment, not a precondition for reporting.
4. Call `review_org_identity` first. Stop unless it is `VERIFIED` for the exact selected org within the active role's limits. Production MCP reads are allowed where the role permits them; `nonProduction: true` is not a general read prerequisite.
5. Call only the necessary guarded review tool:
   - `review_installed_packages` for package identity/version;
   - `review_object_contract` for an allowlisted object's accessible existence/field contract.
6. Treat MCP/CLI agreement as transport corroboration. On `MISMATCH`, `INCOMPLETE`, truncation,
   schema drift, sensitive-output detection, or scope mismatch, return unresolved.
7. Write the sanitized findings as a report under `output/investigations/`. Record limitations, repository
   drift, package version, and missing authority in the report itself.

## Prohibitions

- Never invoke or suggest direct `sf`/`sfdx`, SOSL, an alias, a directory, a Tooling flag, broad
  record retrieval, or an unguarded Salesforce MCP tool; composed read-only SOQL runs only
  through the governed facade's `review_soql_query` tool — never through raw CLI or raw vendor
  tools.
- Never infer inaccessible package internals or treat no returned row/component as proof of absence.
- Never return or persist credentials, usernames, raw org/package/record IDs, URLs, raw vendor
  payloads, labels/help text, picklist values, or unnecessary business data. For configuration
  values held as records in a reference-data table, use the governed exception
  [investigate-config-records](../investigate-config-records/SKILL.md) instead.
- Never call an observation `confirmed` or `verified`.

## Return

Return `EVIDENCE COLLECTED`, `INFERRED`, or `UNRESOLVED`; the report
path under `output/investigations/`; exact scope;
source/reconciliation status; repository drift; limitations; missing authority; and what a
human should verify next. No mutation of Salesforce is permitted.
