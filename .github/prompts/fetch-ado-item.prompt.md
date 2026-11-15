---
name: fetch-ado-item
description: Fetch an Azure DevOps work item and persist its requirement context as work-items/<id>-<slug>/ado-context.md — intake only, no design.
argument-hint: "itemId=<ID> [mode=single|hierarchy] [childDetail=summary|full] [includeTestCases=true|false]"
agent: designer
---

Thin VS Code alias with no logic of its own. As the `designer` agent, follow the
[fetch-ado-item skill](../skills/fetch-ado-item/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
