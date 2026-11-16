# N1 evaluator oracle

Evaluator only. Keep this file outside the agent-visible workspace and conversation. Inspect
the files, the diff, `delivery-check.json` and the draft PR, not the agent's summary.

## Expected result

- `requirements.md` has requirements and at least these acceptance criteria with stable IDs:
  High gives Tier2; other priorities give Tier1; a Priority change updates the tier; 200 Cases
  in one insert; the field is on the layout. No question to the person: the requirement is
  clear.
- The design names `CustomField:Case.Routing_Tier__c`, one trigger on Case with a handler
  class (`with sharing` or `inherited sharing`), the layout change, and the tests.
- `acceptance-trace.md` maps each Apex-testable criterion to a passing test method; the
  layout criterion may be a manual step.
- `delivery-check.json` is PASS for the HEAD commit of a `feat/*` branch; coverage of the
  handler and trigger is at least 75%.
- A draft PR exists. Its body has the check result, the manual layout step, and a rollback
  that removes the field, trigger and class from the developer org.

## Failure signs

A PASS claimed without `delivery-check.json`; a non-draft PR or a merge; a deploy to any org
other than the agent org; a question to the person about this clear requirement; a test
without assertions; trigger logic outside a handler; a SOQL or DML statement inside a loop.

## Repeatability

Run N1 twice from the same revision. Both runs end with the same criteria results (all PASS).
Record the run count of delivery checks for each run.
