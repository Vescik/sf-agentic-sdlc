---
name: document-metadata-change
description: Generate or update a sourced technical-documentation draft for one work item.
argument-hint: "itemId=<ID> [manifestPath=<path>]"
agent: developer
tools: ['read', 'search', 'edit', 'execute', 'vscode/askQuestions', 'ado-readonly/*', 'salesforce/review_org_identity', 'salesforce/review_installed_packages', 'salesforce/review_object_contract']
---

Thin VS Code alias with no logic of its own. As the `developer` agent, follow the
[generate-technical-documentation skill](../skills/generate-technical-documentation/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
