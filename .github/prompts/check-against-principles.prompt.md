---
name: check-against-principles
description: Ad-hoc read-only review of a persisted design or implementation against every applicable scoped Principle and its evidence.
argument-hint: "itemId=<ID> [scope=design|implementation] [base=<ref> head=<ref> | commits=<sha1>,<sha2>,...]"
agent: reviewer
---

Thin VS Code alias with no logic of its own. As the `reviewer` agent, follow the
[check-against-principles skill](../skills/check-against-principles/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
