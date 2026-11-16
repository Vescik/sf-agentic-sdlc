# Requirements

## Source

This is a written, non-ADO work item. The user request names the Case Routing Tier feature but does not state its routing rules. This work item uses the matching normal-case fixture at `evals/fixtures/delivery-golden/n1-input.md` as its detailed baseline. That fixture is synthetic, not a customer request or ADO record. Confirm if a different routing policy was intended.

## Requirements

- **R-1 — Routing field:** Add `Case.Routing_Tier__c` as a picklist with `Tier1` and `Tier2` values.
- **R-2 — Routing rule:** On Case creation and whenever `Priority` changes, set `High` to `Tier2` and every other priority value to `Tier1`.
- **R-3 — Bulk processing:** Process 200 Cases in one transaction.
- **R-4 — Agent visibility:** Show the routing field on the existing Case layout and provide support agents read access to the field.
- **R-5 — Existing records:** Do not backfill existing Cases.

## Acceptance criteria

- **AC-1:** The Case routing field is a picklist with exactly the values `Tier1` and `Tier2`.
- **AC-2:** A new Case with `Priority = High` receives `Tier2`; a new Case with any other priority receives `Tier1`.
- **AC-3:** Changing a Case priority recalculates its routing tier using the same rule.
- **AC-4:** Creating 200 Cases in one transaction routes every Case correctly.
- **AC-5:** The existing Case layout displays the routing field, and a support agent granted the new read-only field permission can read it.
- **AC-6:** Existing Cases are not backfilled by this change.

## Assumptions

- **A-1 — Detailed behavior:** The synthetic N1 fixture is the intended elaboration of the user feature name. This assumption affects R-1 through R-5 and AC-1 through AC-6.
- **A-2 — Permission assignment:** The repository change provides a read-only permission set for the new field. An administrator must assign it to support agents. The user did not identify a support-agent profile, permission set, or group, so this repository task will not change assignments.
- **A-3 — Layout target:** The existing `Case-Case Layout` is the intended page layout. The selected org returned this layout during read-only metadata retrieval.

## Questions and answers

None.
