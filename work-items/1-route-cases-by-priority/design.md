# Route Cases by Priority — Design

Design status: The user stated that this design was approved. No local design existed at the start. This file records the requested implementation scope before implementation edits.
Requirement baseline: requirements.md (human-provided synthetic requirement; no ADO item).

## Context and evidence

The requirement asks for a Case.Routing_Tier__c picklist, Apex routing on insert and Priority changes, 200-record support, and read access on the Support Case layout. Existing Cases must not be backfilled. No Flow or integration behavior is in scope.

The selected development org Case object contract was verified through REST on 2026-11-16T11:36:32Z. Case exists as a platform object, Priority is a picklist, and Routing_Tier__c was not present. The org identity was verified as environment dev at the same time. The installed-package review returned no installed packages at 2026-11-16T11:36:31Z. These are development-org observations, not production facts.

The Support profile and layout were retrieved from devmp. Custom: Support Profile assigns the existing Case-Case %28Support%29 Layout. The field will be visible and read-only for that profile. The profile receives only read access to the new field. docs/package-concept.md and docs/package-constraints.md are absent, so no VendorPkg-specific documentation was available. This design touches only the platform Case object and subscriber-owned metadata; it does not depend on VendorPkg behavior.

## Behavior

A single before insert, before update Case trigger delegates to a handler. On insert, the handler sets Routing_Tier__c to Tier2 only when Priority equals High; it sets Tier1 for every other value, including null. On update, it recalculates the tier only when Priority changes. Changes to other fields do not cause recalculation. The handler mutates Trigger.new records directly and performs no SOQL, DML, asynchronous work, or external calls. It processes the entire trigger collection without per-record queries or DML, supporting Salesforce 200-record trigger batches.

A restricted picklist defines only Tier1 and Tier2 and has no default, so the automation controls the value for new and reprioritized Cases. No migration or backfill is included. The trigger does not make Routing_Tier__c immutable when Priority is unchanged; enforcement of manual edits outside the specified routing events is not part of the requirement.

The existing Support Case layout displays Routing_Tier__c as read-only. Custom: Support Profile grants readable and not editable field-level access. No other profile, permission set, permission assignment, integration, or Flow is changed.

## Components and ownership

Case is platform-owned. All changed metadata components below are subscriber-owned extensions or configuration. The Apex handler uses inherited sharing; it performs no record reads or writes and assigns only fields on in-flight trigger records. The before-trigger transaction provides atomic behavior. Platform validation failures remain transaction failures; the handler does not catch or suppress them. No recursion guard is needed because the before-trigger performs no DML.

## Decisions and alternatives

- Use a before-trigger and mutate trigger records instead of performing post-trigger DML. This follows the requested trigger timing and avoids extra DML, recursion, and partial-update complexity.
- Recalculate only on insert or a Priority change, rather than every update. This follows the stated behavior and avoids overriding a tier during unrelated edits.
- Use one handler class and one Case trigger rather than duplicating mapping logic. The repository has no existing Case trigger to extend.
- Use the existing Support profile field-level read access rather than a new permission set. The retrieved profile assigns the Support Case layout and directly meets read-only access without unrelated permission changes.

## Acceptance criteria coverage

| Criterion | Solution / planned surfaces | Planned verification | Status |
| --- | --- | --- | --- |
| AC-1 | Restricted picklist on CustomField:Case.Routing_Tier__c | Inspect field metadata and deployed object contract for exactly Tier1 and Tier2 | Covered |
| AC-2 | Before-insert mapping in Trigger:CaseRoutingTrigger and ApexClass:CaseRoutingHandler | Apex test asserts High maps to Tier2 and non-High values, including null, map to Tier1 | Covered |
| AC-3 | Before-update mapping in Trigger:CaseRoutingTrigger and ApexClass:CaseRoutingHandler | Apex test changes Priority to High and to a non-High value and asserts each result | Covered |
| AC-4 | Collection-based handler in ApexClass:CaseRoutingHandler | Apex test inserts 200 Cases in one DML operation and asserts every tier | Covered |
| AC-5 | Layout:Case-Case %28Support%29 Layout and read-only field permission in Profile:Custom: Support Profile | Inspect deployed layout field placement and profile field permission (readable=true, editable=false) | Covered |
| AC-6.a — no backfill | No migration or data operation; field has no default | Confirm changed source contains no data migration and verify no backfill operation is run | Covered |
| AC-6.b — no integration or Flow changes | No integration or Flow surface is planned | Review the exact changed-path list | Covered |
| AC-6.c — read access only | Read-only permission on the Support profile; no edit permission or broader permission change | Inspect profile field permission and exact changed-path list | Covered |

Covered names a solution and planned verification; it does not mean implementation or test success.

## Planned change surface

| Surface | Ownership | Planned action | Purpose / source |
| --- | --- | --- | --- |
| CustomField:Case.Routing_Tier__c | Subscriber | Create | AC-1, AC-2, AC-3; restricted picklist values |
| Trigger:CaseRoutingTrigger | Subscriber | Create | AC-2, AC-3; before insert/update entry point |
| ApexClass:CaseRoutingHandler | Subscriber | Create | AC-2, AC-3, AC-4; bulk-safe priority mapping |
| ApexClass:CaseRoutingHandlerTest | Subscriber | Create | AC-2, AC-3, AC-4; outcome and bulk tests |
| Layout:Case-Case %28Support%29 Layout | Subscriber | Modify | AC-5; show the tier read-only |
| Profile:Custom: Support Profile | Subscriber | Modify | AC-5, AC-6.c; field read access only |

Explicit exclusions: existing-record backfill, integrations, Flows, permission changes outside field read access, unrelated Case automation, and package components.

## Verification and rollback

Local validation will inspect metadata XML and Apex source, run focused static checks, and run the Apex test class in the selected development org. A scoped deployment will include only the six planned logical components and run CaseRoutingHandlerTest. Post-deployment verification will retrieve or inspect the field, layout, and profile metadata and confirm test results. A real deployment is authorized by the configured autonomous development-org grant only for devmp; no other target is in scope.

Rollback consists of reverting the changed source components and deploying that rollback through the applicable deployment authorization. There is no data rollback because this change does not backfill or mutate existing records. No deployment or test result is claimed by this design.

## Assumptions and limits

- The existing Support profile and layout retrieved from devmp represent the support-agent UI requested by the requirement. Their assignment was observed in org metadata; this does not establish production deployment.
- The profile grants read-only access to the field. Users who do not receive that profile or an existing equivalent grant are outside the requirement audience.
- The repository does not include local package concept/constraint documents. No package-owned Case dependency was observed in the object contract or installed-package review; the design does not infer VendorPkg guarantees.
