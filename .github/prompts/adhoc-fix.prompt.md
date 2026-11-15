---
name: adhoc-fix
description: Bounded defect fix express lane — edit, optionally deploy after confirmation, verify, and write a fix note.
argument-hint: "component=<Type:Name> [org=<alias>] plus the diagnosis or a pointer to it"
agent: developer
tools: ['read', 'search', 'edit', 'execute', 'vscode/askQuestions', 'salesforce/review_org_identity', 'salesforce/review_object_contract', 'salesforce/review_soql_query']
---

Thin VS Code alias with no logic of its own. As the `developer` agent, follow the
[adhoc-fix skill](../skills/adhoc-fix/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
