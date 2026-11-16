---
name: org-discovery
description: The recipe for investigating the org through the read-only Salesforce MCP facade — what to call, in what order, and what to do when a tool fails.
user-invocable: false
---

# Org Discovery

Org facts come from tools, not memory. This is the standing recipe; scale it to the
question — a one-field question does not need the full sweep.

## The sequence

1. **`review_org_identity` — once per session.** Confirms which org you are reading and
   its live identity. Everything after is scoped to this identity and the active role.
   Test Strategist must never select production, including read-only MCP.
2. **`review_installed_packages` — once per session.** Establishes the installed VendorPkg
   version. Package-specific facts are version-scoped: note the version in whatever you
   write.
3. **`review_object_contract` — per object you touch.** The contract gives fields,
   relationships, and ownership: the namespace prefix is the ownership signal
   (`VendorNS__` = package-owned; no prefix or your own = subscriber; standard =
   platform).
4. **Repository source — before proposing a change to anything others may consume**
   (CustomMetadata, RecordType, Layout, shared objects): search `force-app/` for what
   already references it. An empty result is normal — continue discovery regardless.
5. **`review_soql_query` — when the design depends on data shape.** Structure, fill
   rates, real record shapes: prefer a bounded read over a guess or a blocking question.
   Never paste raw record rows into a design or an ADO artifact —
   derive the counts and shapes you need. When the question outgrows a bounded read — a
   persisted snapshot of configuration records or a deeper package investigation — prepare a manual request for `config-investigator` (its
   investigate-object / investigate-config-records lanes). Include the question, bounded scope,
   known sources, dependent decision and expected result under the
   [shared handoff contract](../../../.ai/contracts/execution-contract.md#handoff-and-continuation).
   Keep lasting findings in the calling role's existing artifact; this instruction does not
   dispatch an automatic subagent or widen discovery.

## When a tool fails

A failed or unavailable tool is a stated limitation, never permission to imagine the
result (SAFE-TOOL-001). Write the explicit assumption into the design ("assumed X because
review_object_contract was unavailable; verify before implementation") and continue.

A rejected query returns Salesforce's own reason after the envelope (for example
`INVALID_FIELD` or `INVALID_TYPE`): fix the query and retry instead of treating the fact as
unavailable. Metadata objects such as `Flow`, `FlowDefinition`, `Layout`, `ProfileLayout`
(which layout a profile sees) and `ApexTrigger` need `useToolingApi: true`;
`FlowDefinitionView`, `FieldPermissions`, `ObjectPermissions`, `PermissionSetAssignment` and
`Profile` use the normal API.

## Map versus terrain

`docs/` describes the package as the team last verified it; the org is the live truth.
On conflict the org wins — and the mismatch is worth money: report it as a proposed
correction to `docs/` (MP-MAP-001).
