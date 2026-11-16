# E2 input: urgent cases (edge, unclear but not contradictory)

Synthetic requirement for a delivery trial. Not an ADO item or a real client request.

## Requirement

Add `Case.Routing_Tier__c` (picklist: `Tier1`, `Tier2`). Urgent cases go to `Tier2`; all other
cases go to `Tier1`. The tier is set when the Case is created.
