# Route Cases by Priority — Acceptance Trace

Source: `requirements.md`, acceptance criteria AC-1–AC-6. This trace records implementation verification separately from design coverage. These are Developer validation results, not QA execution records.

| Criterion | Planned implementation | Observed verification evidence | Result |
| --- | --- | --- | --- |
| AC-1 | `Case.Routing_Tier__c` restricted picklist | Retrieved metadata from `devmp` shows exactly `Tier1` and `Tier2`, both with default=false, and a restricted value set. The live Case object contract lists the field as a picklist. | Verified |
| AC-2 | Before-insert mapping in `CaseRoutingTrigger` and `CaseRoutingHandler` | `CaseRoutingHandlerTest.routesHighAndOtherPrioritiesOnInsert` passed: High mapped to Tier2; Medium, Low, and null mapped to Tier1. | Verified |
| AC-3 | Handler recalculates on Priority change | `CaseRoutingHandlerTest.recalculatesWhenPriorityChanges` passed for High-to-Low and Medium-to-High updates. | Verified |
| AC-4 | Collection-based handler | `CaseRoutingHandlerTest.routesTwoHundredCasesInOneTransaction` passed with 200 Cases inserted in one DML operation and every tier asserted. | Verified |
| AC-5 | Existing Support layout plus read-only Support profile field permission | Retrieved Support layout shows `Routing_Tier__c` as Readonly. Retrieved Support profile shows readable=true and editable=false, and retains its Support Case layout assignment. | Verified |
| AC-6 | No backfill, Flow, integration, or permission change beyond read-only field access | Changed implementation paths contain no data migration, Flow, or integration. No data CRUD ran. The only field-level permission change is read-only access on `Custom: Support Profile`. | Verified |

The focused deployment job `0AfgL00000e8rZZSAY` reported 3 passing tests and 0 failures. The field, profile, and remaining components were deployed in scoped stages recorded in `org-changes.md`. The initial combined deployment failure and implementation adaptations are recorded in `decisions.md` and `org-changes.md`.
