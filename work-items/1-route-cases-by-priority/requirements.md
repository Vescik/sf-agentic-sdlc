# Route Cases by Priority — Requirements

## Requirements

- **R-1.** Add a `Case.Routing_Tier__c` picklist with the values `Tier1` and `Tier2`.
- **R-2.** When a Case is created, set its routing tier to `Tier2` when Priority is `High`; set it to `Tier1` for every other Priority value.
- **R-3.** When a Case Priority changes, recalculate its routing tier using the same mapping.
- **R-4.** Support agents can see and read the routing tier on the existing Case page layout.
- **R-5.** The routing rule supports 200 Cases created in one transaction.
- **R-6.** Do not backfill existing Cases. Do not add integration or Flow changes. Do not request permission changes beyond read access for the field.

## Acceptance criteria

- **AC-1.** `Case.Routing_Tier__c` is a picklist whose available values are `Tier1` and `Tier2`.
- **AC-2.** A newly created Case with Priority `High` has routing tier `Tier2`; a newly created Case with any other Priority has routing tier `Tier1`.
- **AC-3.** When an existing Case Priority changes to `High`, its routing tier becomes `Tier2`; when it changes to any other value, its routing tier becomes `Tier1`.
- **AC-4.** Creating 200 Cases in one transaction applies the expected routing tier to every Case without failing because of the batch size.
- **AC-5.** Support agents can see and read the routing tier on the existing Case page layout.
- **AC-6.** Existing Cases are not backfilled, and the change adds no integration or Flow behavior or permission changes beyond read access for the field.

## Assumptions

- None. The source defines the field, values, routing rule, transaction size, layout visibility, and exclusions.

## Questions and answers

- None. No clarification was needed to record the stated requirement.

## Source

- `evals/fixtures/delivery-golden/n1-input.md` — human-provided requirement file. The source identifies the requirement as synthetic and not an ADO item or a real client request.
