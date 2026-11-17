# D1 input: customer feedback wall (demo)

Synthetic requirement for a delivery demo with the `sdlc-conductor` agent. It is not an ADO
item or a real client request. Give this file as `requirementFile=` to
`deliver-requirement` against a developer org.

## Requirement

The service team wants to collect short customer feedback in Salesforce and see the overall
picture on one screen.

- Add a custom object `Customer_Feedback__c` with these fields:
  - `Rating__c`: a whole number from 1 to 5, required;
  - `Comment__c`: long text, up to 1,000 characters, optional;
  - `Channel__c`: a picklist with the values `Email`, `Phone` and `Web`, required;
  - `Account__c`: an optional lookup to Account.
- Add a Lightning Web Component on its own Lightning tab named `Feedback Wall`. It shows:
  - the average rating with one decimal and as stars, and the number of feedback records;
  - a bar for each rating from 1 to 5 with its count, colored from red (1) to green (5);
  - the five newest feedback records as cards with rating, channel, comment and date;
  - a form to add feedback: clickable stars for the rating, the channel, an optional comment
    and a Submit button. After Submit, a success toast appears and the average, the bars and
    the cards update without a page reload;
  - the text "No feedback yet" when there are no records.
- A rating outside 1–5 is rejected with a clear error message, both in the form and when the
  record is saved by any other way.
- Users who work with the screen get access to the object, its fields and the tab through a
  permission set. Assign it to the agent org user.

No Flow, no trigger, and no change to existing objects, fields or page layouts. No data
migration or sample data is needed.
