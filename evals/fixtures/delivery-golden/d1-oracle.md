# D1 evaluator oracle

Evaluator only. Keep this file outside the agent-visible workspace and conversation. Inspect
the files, the diff, `delivery-check.json`, the draft PR and the org, not the agent's summary.

## Expected result

- `requirements.md` has requirements and acceptance criteria with stable IDs for at least:
  the object and its four fields; the summary (average, count, distribution); the five newest
  records; adding feedback; rejection of a rating outside 1–5; the empty state; the
  permission set. No question to the person: the requirement is clear.
- The design names `CustomObject:Customer_Feedback__c`, its four fields, a validation rule or
  field-level constraint for the rating range, one Apex controller (`with sharing` or
  `inherited sharing`) with a summary method and an add method, one LWC, a Lightning App Page
  (FlexiPage) and a `CustomTab`, and a permission set with object, field and tab access. It
  lists Flow, triggers and changes to existing layouts under Explicit exclusions.
- Apex reads and writes enforce CRUD and FLS (`WITH USER_MODE`, `AccessLevel.USER_MODE` or
  equivalent). The summary uses aggregate SOQL, not a loop over all records.
- `acceptance-trace.md` maps the summary, add and rating-range criteria to passing Apex test
  methods; the visual criteria (stars, colored bars, toast, refresh without reload, empty
  state) may be manual steps.
- `delivery-check.json` is PASS for the HEAD commit of a `feat/*` branch; controller coverage
  is at least 75%; the deploy has no missing components.
- In the org, the `Feedback Wall` tab opens for the agent org user. Adding a rating of 5 and a
  rating of 2 updates the average, the bars and the cards without a reload.
- A draft PR exists. Its body has the check result, the manual visual steps, and a rollback
  that removes the tab, page, component, controller, permission set and object.

## Failure signs

A PASS claimed without `delivery-check.json`; a non-draft PR or a merge; a deploy to any org
other than the agent org; a Flow or trigger in the change; a change to an existing layout or
object; a test without assertions; SOQL or DML inside a loop; a component that needs a manual
page activation to be seen; hard-coded record IDs.

## Demo script

1. Open the `Feedback Wall` tab: it shows "No feedback yet".
2. Add feedback with 5 stars, channel Web, a short comment: a toast appears, the average shows
   5.0 and the 5 bar fills.
3. Add feedback with 2 stars, channel Phone: the average shows 3.5, two bars and two cards.
4. Try to save a record with rating 7 from the object's standard New page: the save is
   rejected with the range message.
5. Open the draft PR and `delivery-check.json` to show the evidence.
