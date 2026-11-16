# Salesforce org changes

Append-only agent-reported operational history. This is not deployment consent, release approval, QA evidence, or independent proof. Re-establish current scope, target, and required confirmation before reusing a command. Never store secrets or sensitive business payloads.

## 2026-11-16T11:44:10Z — Metadata deployment

- Delivery scope: Work Item 1 — Route Cases by Priority
- Target: devmp (explicit)
- Operation: real deploy
- Source: commit 2c72fb34c8387d5f9f2632fd1b256f38acab354e; working tree dirty with participating routing metadata, Apex classes, trigger, layout, and profile
- Command: Salesforce CLI metadata deployment start; explicit target; scoped source paths; selected test class only
- Scope: `Case.Routing_Tier__c`, `CaseRoutingHandler`, `CaseRoutingHandlerTest`, `CaseRoutingTrigger`, existing Support Case layout, and Support profile field permission
- Result: PARTIAL — Salesforce reported all 6 metadata components successful, but the overall deployment failed its tests
- Job ID: 0AfgL00000e8jNVSAY
- Test policy / outcome: RunSpecifiedTests / `CaseRoutingHandlerTest`; 0 passed and 3 failed because test queries did not recognize `Routing_Tier__c`
- Verification: Deployment report showed 6 component successes, 0 component errors, and 3 test errors. Current field and metadata state still need verification.
- Rollback / cleanup: No rollback or cleanup performed. Revert and redeploy remain available after diagnosing the partial result.
- Unverified / next action: Confirm the field and other component state in `devmp`; diagnose why the test runtime did not resolve the newly deployed field; rerun only after a material correction or confirmed corrected deployment scope.


### Status update — 2026-11-16T11:44:58Z

- Observed state: the live Case object contract still does not list `Routing_Tier__c` after the failed deployment. The CLI describe also returned no matching field.
- Verification: the selected org identity remained verified as environment `dev`; the field is not currently confirmed in org metadata.
- Next action: remove test SOQL references to the new field, rerun validation, and deploy only after the focused test outcome is available.


## 2026-11-16T11:47:18Z — Metadata deployment

- Delivery scope: Work Item 1 — Route Cases by Priority
- Target: devmp (explicit)
- Operation: real deploy
- Source: commit 2c72fb34c8387d5f9f2632fd1b256f38acab354e; working tree dirty; participating path: `Routing_Tier__c.field-meta.xml`; other pending paths were excluded from this stage
- Command: Salesforce CLI metadata deploy; explicit target; one CustomField source
- Scope: `CustomField:Case.Routing_Tier__c`
- Result: SUCCEEDED
- Job ID: 0AfgL00000e8cXLSAY
- Test policy / outcome: NoTestRun; no Apex tests ran in this field-only stage
- Verification: CLI reported the field component deployment succeeded. Live field metadata verification is pending.
- Rollback / cleanup: None performed. A scoped field removal remains available if recovery is needed.
- Unverified / next action: Confirm the live field values and presence, then deploy the remaining planned components and run `CaseRoutingHandlerTest`.


### Status update — 2026-11-16T11:48:18Z

- Observed state: the live Case object contract now lists `Routing_Tier__c` as a picklist. Retrieved field metadata contains only `Tier1` and `Tier2`, both with default=false, and marks the value set restricted.
- Verification: REST object contract completed and the deployed field metadata was retrieved from `devmp` and inspected.
- Next action: deploy the remaining planned metadata with the focused test.


## 2026-11-16T11:52:29Z — Metadata deployment

- Delivery scope: Work Item 1 — Route Cases by Priority
- Target: devmp (explicit)
- Operation: real deploy
- Source: commit 2c72fb34c8387d5f9f2632fd1b256f38acab354e; working tree dirty; participating path: `Custom%3A Support Profile.profile-meta.xml`; other pending paths were excluded from this stage
- Command: Salesforce CLI metadata deploy; explicit target; one Support Profile source
- Scope: `Profile:Custom: Support Profile` field permission for `Case.Routing_Tier__c`
- Result: SUCCEEDED
- Job ID: 0AfgL00000e8p4jSAA
- Test policy / outcome: NoTestRun; no Apex tests ran in this profile-only stage
- Verification: CLI reported the profile component deployment succeeded. Live profile permission verification is pending.
- Rollback / cleanup: None performed. A scoped profile rollback remains available if recovery is needed.
- Unverified / next action: Confirm the live Support profile grants read and not edit access, then rerun the focused test as a Support-profile user.


## 2026-11-16T11:54:20Z — Metadata deployment

- Delivery scope: Work Item 1 — Route Cases by Priority
- Target: devmp (explicit)
- Operation: real deploy
- Source: commit 2c72fb34c8387d5f9f2632fd1b256f38acab354e; working tree dirty; participating paths: `CaseRoutingHandler.cls`, `CaseRoutingHandlerTest.cls`, `CaseRoutingTrigger.trigger`, Support Case layout, and Support profile; other pending paths were excluded from this stage
- Command: Salesforce CLI metadata deploy; explicit target; scoped Apex, trigger, layout, and profile sources
- Scope: `CaseRoutingHandler`, `CaseRoutingHandlerTest`, `CaseRoutingTrigger`, existing Support Case layout, and Support profile field permission
- Result: SUCCEEDED
- Job ID: 0AfgL00000e8rZZSAY
- Test policy / outcome: RunSpecifiedTests / `CaseRoutingHandlerTest`; 3 passed and 0 failed
- Verification: CLI reported 5/5 metadata components successful and all 3 named test methods passed. Live layout and profile state still require final inspection.
- Rollback / cleanup: None performed. Reverting the scoped metadata and using an authorized rollback deployment remains available.
- Unverified / next action: Retrieve the Support layout with the field and verify the profile read-only permission remains present; verify the live object contract and report production deployment status as unverified.


### Status update — 2026-11-16T11:55:03Z — Profile stage 0AfgL00000e8p4jSAA

- Observed state: retrieved `Custom: Support Profile` metadata confirms `Case.Routing_Tier__c` is readable and not editable. The profile retains its Support Case layout assignment.
- Verification: profile and field metadata were retrieved together from `devmp` and inspected.
- Next action: none for profile access.

### Status update — 2026-11-16T11:55:03Z — Routing deployment 0AfgL00000e8rZZSAY

- Observed state: the live Case object contract lists `Routing_Tier__c` as a picklist. Retrieved field metadata shows only `Tier1` and `Tier2`, both with default=false, and a restricted value set. The Support Case layout shows the field as read-only.
- Verification: object contract was verified through REST; field, layout, and profile metadata were retrieved from `devmp`; the focused deployment reported 3 passing tests and 0 failures.
- Next action: complete local acceptance trace, tasks, source review, and commit. Production deployment remains unverified.


### Status update — 2026-11-16T11:55:03Z — Initial combined job 0AfgL00000e8jNVSAY

- Superseded next action: test SOQL was retained. The field was deployed first, then the Support read-only field permission, and the final focused tests passed as a Support-profile test user.
- Verification: the final routing job `0AfgL00000e8rZZSAY` succeeded with 3 passing tests. The sequence and reasons are recorded in `decisions.md`.
- Next action: none for the initial failed operation; its `PARTIAL` result remains unchanged.


### Status update — 2026-11-16T11:59:21Z — Support access verification

- Observed state: an aggregate user query found zero active users assigned to `Custom: Support Profile` in `devmp`. The profile and layout metadata still confirm read-only field configuration.
- Verification: the query returned only an aggregate count and profile name; no user identities were retrieved.
- Rollback / cleanup: no user assignment or data mutation was performed.
- Unverified / next action: access for actual support users is not confirmed. An org owner must identify the intended profile or permission-set assignment if needed. No production assignment state was checked.
