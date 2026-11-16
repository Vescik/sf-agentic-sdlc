# Tasks

- [ ] **T-01 — Add the routing field and access metadata.** Design: [Behavior](design.md#behavior), [Planned change surface](design.md#planned-change-surface). Coverage: AC-1, AC-5. Create the restricted picklist, add it read-only to the existing Case layout, and add the read-only permission set. Done when all three metadata components are present and pass scoped metadata validation.
- [ ] **T-02 — Implement Apex routing.** Design: [Behavior](design.md#behavior), [Acceptance criteria coverage](design.md#acceptance-criteria-coverage). Coverage: AC-2, AC-3, AC-4, AC-6. Create the before trigger, handler, and isolated tests. Done when tests assert insert, priority change, unchanged-priority, and 200-record outcomes.
- [ ] **T-03 — Validate the complete change in the configured development org.** Design: [Verification and rollback](design.md#verification-and-rollback). Coverage: AC-1 through AC-6. Run a scoped validation with Apex tests. Done when the command reports successful validation and passing tests; validation is not deployment.
- [ ] **T-04 — Record actual verification and work-item progress.** Support reason: preserve the requested acceptance trace and run history. Done when the trace and run log match observed results and completed task checkboxes.

Deployment, permission-set assignment, and post-deployment agent access checks are not part of this repository setup request.
