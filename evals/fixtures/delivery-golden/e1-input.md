# E1 input: contradictory routing rules (edge)

Synthetic requirement for a delivery trial. Not an ADO item or a real client request.

## Requirement

Add `Case.Routing_Tier__c` (picklist: `Tier1`, `Tier2`).

1. Every Case with Priority `High` must be `Tier2`.
2. Cases from the account segment `Strategic` are always `Tier1`, whatever their priority.
3. No Case with Priority `High` may ever be `Tier1`.

Strategic accounts are identified by the existing field `Account.Segment__c`.
