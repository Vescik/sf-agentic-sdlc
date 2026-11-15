---
name: prepare-delivery-feature
description: Prepare one ADO Feature as explicit delivery context for its direct child Work Items — persists the Feature's ado-context.md and a delivery-map.md membership manifest; never touches child folders.
argument-hint: "itemId=<Feature ID> [include=all|<ID,ID,...>]"
agent: designer
---

Thin VS Code alias with no logic of its own. As the `designer` agent, follow the
[prepare-delivery-feature skill](../skills/prepare-delivery-feature/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
