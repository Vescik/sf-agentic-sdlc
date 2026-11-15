---
name: feature-health
description: Run the Feature/BRD-to-Story coverage gate before Solution Design.
argument-hint: "itemId=<Feature ID>"
agent: test-strategist
---

Thin VS Code alias with no logic of its own. As the `test-strategist` agent, follow the
[check-feature-coverage skill](../skills/check-feature-coverage/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
