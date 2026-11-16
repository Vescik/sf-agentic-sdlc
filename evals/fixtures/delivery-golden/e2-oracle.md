# E2 evaluator oracle

Evaluator only. Keep this file outside the agent-visible workspace and conversation.

## Expected result

"Urgent" is not defined, but a reasonable reading exists. This is not a contradiction, so the
run does not stop (plan 05, D-D4).

- `requirements.md` has a numbered assumption, for example `A-1: "urgent" means Priority
  High`, linked to the requirement it affects.
- No question to the person.
- The run ends as in N1: PASS delivery check and a draft PR whose body repeats `A-1`.
- The tier is set on create; the solution does not invent an update rule that was not asked.

## Failure signs

The run stops to ask; the assumption is missing from `requirements.md` or from the draft PR;
the agent invents more behavior than the requirement states.
