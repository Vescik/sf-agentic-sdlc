# Route Cases by Priority — Acceptance Trace

Source: requirements.md, acceptance criteria AC-1–AC-6. This trace was created before implementation validation. It tracks implementation and validation evidence separately from design coverage.

| Criterion | Planned implementation | Planned evidence | Result |
| --- | --- | --- | --- |
| AC-1 | Case.Routing_Tier__c restricted picklist | Field metadata and deployed object contract show exactly Tier1 and Tier2 | Pending |
| AC-2 | CaseRoutingTrigger and CaseRoutingHandler before insert | CaseRoutingHandlerTest asserts High → Tier2 and every other priority, including null, → Tier1 | Pending |
| AC-3 | Handler recalculates on Priority change | Test updates to High and non-High and asserts resulting values | Pending |
| AC-4 | Collection-based handler | Test inserts 200 Cases in one transaction and asserts every result | Pending |
| AC-5 | Existing Support layout plus read-only Support profile field permission | Deployed layout includes the field; profile metadata shows readable=true and editable=false | Pending |
| AC-6 | No backfill, Flow, integration, or permission change beyond read-only field access | Review changed paths and confirm no data operation; inspect exact field permission | Pending |

No validation result is recorded yet. Update each result only after observing the corresponding evidence. Do not record QA execution results here.
