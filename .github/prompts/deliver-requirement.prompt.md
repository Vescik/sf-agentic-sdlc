---
name: deliver-requirement
description: Deliver one requirement to a draft PR with the sdlc-conductor agent — thin alias, no logic of its own.
argument-hint: "itemId=<ID> | requirementFile=<path> [feedback=<path>]"
agent: sdlc-conductor
---

Thin VS Code alias with no logic of its own. As the `sdlc-conductor` agent, follow the
[deliver-requirement skill](../skills/deliver-requirement/SKILL.md) for the supplied input,
starting with its `Invocation contract`.
