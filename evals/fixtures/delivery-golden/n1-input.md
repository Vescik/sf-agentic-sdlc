# N1 input: route cases by priority (normal)

Synthetic requirement for a delivery trial with the `sdlc-conductor` agent. It is not an ADO
item or a real client request. Give this file as `requirementFile=` to
`deliver-requirement` in a disposable copy of the repository, against a developer org.

## Requirement

Support wants every Case to show which support tier owns it.

- Add a picklist field `Case.Routing_Tier__c` with the values `Tier1` and `Tier2`.
- When a Case is created or its Priority changes, set the tier: Priority `High` gives
  `Tier2`, every other Priority gives `Tier1`.
- The rule must work when 200 Cases are created in one transaction.
- Support agents see the field on the Case page layout.

No data backfill for existing Cases is needed. No integration, Flow or permission change is
requested beyond read access for the field on the existing layout.
