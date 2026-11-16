# Case Routing Tier

## Requirement baseline

This is a written, non-ADO requirement in [requirements.md](requirements.md). The detailed routing behavior comes from the matching synthetic fixture `evals/fixtures/delivery-golden/n1-input.md`, as recorded in assumption A-1. No `ado-context.md` exists.

## Design evidence

- The selected `devmp` org was identity-verified as a non-production development org at `2026-11-16T12:26:39Z`. This is an observation of that org, not a production claim.
- The installed-package review for `devmp` reported no installed packages at `2026-11-16T12:26:39Z`.
- The Case object contract for `devmp` reported that `Case` exists and `Priority` is a picklist. It did not report `Routing_Tier__c` among the 63 fields returned. The contract was observed at `2026-11-16T12:26:40Z`.
- The existing `Case-Case Layout` was retrieved read-only from `devmp` and is now represented at `force-app/main/default/layouts/Case-Case Layout.layout-meta.xml`.
- Before this work, the repository had no Case Apex, field, layout, or permission-set source. The Apex, trigger, and metadata below are subscriber-owned. No `VendorNS__` component is part of the design.
- `docs/package-concept.md` and `docs/package-constraints.md` are absent. The design has no package dependency, so this gap does not block the proposed implementation.

## Behavior

`CaseRoutingTier` runs before insert and before update. `CaseRoutingTierHandler.apply` assigns `Tier2` when `Priority` is exactly `High`; it assigns `Tier1` for every other value, including null. On update, it recalculates only when `Priority` changes. It does not backfill existing Cases or overwrite a routing tier when another field changes.

The handler uses the trigger in-memory records and `Trigger.oldMap`. It performs no queries, DML, asynchronous work, or external calls. The before-save context writes the field in the Case transaction. A platform validation or another automation failure follows the normal Case transaction failure behavior; this change adds no catch or partial-save behavior.

The trigger handles the complete trigger collection. Tests cover a 200-record insert. The handler declares inherited sharing, although the implementation reads and writes only the trigger records and does not query related data.

The field is a restricted picklist with the two required values. The Case layout displays it as read-only because the trigger owns the value. `Case_Routing_Tier_Read` grants field-level read access and no edit access. An administrator must assign this permission set to support agents; assignment is not part of the repository change because no support-agent principal was identified.

No migration or backfill is included. Existing Cases keep their current value, including null. A Case receives a routing tier on creation or when its priority changes.

## Package impact

No package-owned component is read or changed. The `devmp` installed-package review reported no installed packages at `2026-11-16T12:26:39Z`. All planned components are subscriber-owned Salesforce metadata.

## Decisions and alternatives

- **Use a before trigger and handler.** This matches the requested Apex implementation and centralizes logic for create and priority-change paths. A record-triggered Flow was considered, but it does not meet the request for Apex source.
- **Recalculate only on insert or priority change.** Recalculating on every update would overwrite unrelated edits and exceed the stated trigger conditions.
- **Provide a dedicated read-only permission set.** Modifying an unidentified profile or existing permission set would risk granting access to the wrong users. Assignment remains an administrator action under assumption A-2.
- **Update the retrieved `Case-Case Layout`.** This preserves the existing layout rather than creating a second layout. The target is an assumption under A-3.

## Acceptance criteria coverage

| Criterion | Solution / planned surfaces | Planned verification | Status |
| --- | --- | --- | --- |
| AC-1 | Restricted picklist `CustomField:Case.Routing_Tier__c`; `CaseRoutingTierHandlerTest.picklistHasTierValues` | Describe the field and assert its values are exactly `Tier1` and `Tier2`. | Covered |
| AC-2 | Before-insert routing in `ApexTrigger:CaseRoutingTier` and `ApexClass:CaseRoutingTierHandler`; `CaseRoutingTierHandlerTest.routesNewCasesByPriority` | Insert high, other, and null-priority Cases and assert their stored tiers. | Covered |
| AC-3 | Before-update priority-change routing in `ApexTrigger:CaseRoutingTier` and `ApexClass:CaseRoutingTierHandler`; `CaseRoutingTierHandlerTest.recalculatesWhenPriorityChanges` | Change priority across both tiers and assert the stored result after each update. | Covered |
| AC-4 | Collection processing in `ApexClass:CaseRoutingTierHandler`; `CaseRoutingTierHandlerTest.routesTwoHundredCases` | Insert 200 Cases in one transaction and assert all stored tiers. | Covered |
| AC-5 | `Layout:Case-Case Layout`; read-only `PermissionSet:Case_Routing_Tier_Read` | Inspect layout and permission metadata; after assignment, verify an agent can read but cannot edit the field. | Covered |
| AC-6 | No migration surface; create/update trigger entry conditions | Confirm the scoped change contains no backfill job or update of existing Case records. | Covered |

`Covered` describes the planned solution and verification. It does not claim implementation, test, or deployment success.

## Planned change surface

| Surface | Ownership | Planned action | Purpose / source |
| --- | --- | --- | --- |
| `ApexTrigger:CaseRoutingTier` | Subscriber | Create | Invoke the handler before Case insert and update. |
| `ApexClass:CaseRoutingTierHandler` | Subscriber | Create | Apply the routing rule to trigger records. |
| `ApexClass:CaseRoutingTierHandlerTest` | Subscriber | Create | Verify field values, routing behavior, and bulk processing. |
| `CustomField:Case.Routing_Tier__c` | Subscriber | Create | Store the routing tier. |
| `Layout:Case-Case Layout` | Subscriber | Modify | Display the read-only routing tier on the existing layout. |
| `PermissionSet:Case_Routing_Tier_Read` | Subscriber | Create | Grant read-only access to the new field when assigned. |

## Verification and rollback

Run the Apex tests and a scoped Salesforce validation against the configured development org. Do not treat validation as deployment. No deployment or permission-set assignment is authorized by this repository setup request. Before deployment, assign the permission set to the intended support agents and confirm that the target layout and profile assignment are correct.

Rollback by removing the new trigger, handler, test, field, and permission set, then restoring the Case layout from the pre-change version. Rollback must account for any Cases that acquired a routing tier after deployment; this work does not delete or rewrite their business data.
