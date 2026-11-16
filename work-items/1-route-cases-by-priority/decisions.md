# Decisions

## D-1 — Stage field deployment before Apex behavior tests

- Planned action: deploy the routing field, Apex classes, trigger, Support layout, and Support profile in one scoped operation with `CaseRoutingHandlerTest`.
- Actual action: deploy and verify the field first without tests, then deploy the remaining planned components and run `CaseRoutingHandlerTest`.
- Reason: the combined validation and deployment both ran the test class while `Case.Routing_Tier__c` was not queryable. The real deployment failed its tests, and the live Case object contract still did not list the field. In-memory assertions also returned null because DML did not refresh the original test records.
- Impact: AC-1 is verified after the first stage. AC-2 through AC-4 remain unverified until the second stage passes. The designed behavior and planned component set do not change. The two-stage sequence leaves a temporary field-only state if the second stage fails.
- Verification and rollback: verify the deployed field before the second stage, then run the focused Apex test with the field already present. If the second stage fails, keep the failure visible and restore the prior metadata state through a separately authorized rollback deployment if needed.
- QA impact: no `qa-test-plan.md` exists. This adaptation does not change requirement outcomes or QA intent.

This records an implementation deviation from the planned single-operation deployment. It does not claim separate approval or change the design requirements.


## D-2 — Run outcome queries with Support field access

Supersedes D-1 only for the test execution sequence. D-1 remains the history of the first diagnosis and the field-only deployment.

- Planned action: after deploying the field, run the focused Apex tests with the deployment user context.
- Actual action: deploy the already-planned Support profile read permission before the tests, then create an isolated test user with that profile and run the test queries as that user.
- Reason: the field is now present in the live object contract and registered as metadata, but direct SOQL and the focused deployment test still report it as unavailable to their execution user. The Support profile is the only audience granted read access by the design.
- Impact: AC-2 through AC-4 verification will execute under the same field-read audience named by AC-5. The designed field access remains read-only and limited to the Support profile. No component or routing behavior changes.
- Verification and rollback: verify the Support profile read-only field permission after deployment, then run the test class as a Support-profile test user. If the test still cannot resolve the field, stop and investigate the org schema/permission mismatch rather than broaden access. The current field and profile can be reverted through scoped rollback metadata if required.
- QA impact: no `qa-test-plan.md` exists. Expected requirement outcomes remain unchanged.


## D-3 — Do not infer agent assignment from the Support profile name

- Planned action: deploy read-only field access to the existing Support profile and show the field on its assigned Support Case layout.
- Observed state: the profile permission and layout configuration are verified. An aggregate user query found zero active users assigned to `Custom: Support Profile` in `devmp` at 2026-11-16T11:59:21Z.
- Decision: do not assign users or broaden permissions. The requirement and design do not identify support-user records or authorize assignment changes.
- Impact: AC-5 is verified at the metadata configuration level. Visibility for active support agents is not confirmed in `devmp`; the production assignment state is also unknown. Other acceptance outcomes are unchanged.
- Verification and rollback: the profile and layout metadata remain the verified configuration. No user assignment or data mutation was performed. An org owner must identify the intended support-user access mapping if assignment is required.
- QA impact: no `qa-test-plan.md` exists. The expected outcome is unchanged; the unresolved user mapping remains visible.

This is a development finding, not approval to add assignments or broader field permissions.
