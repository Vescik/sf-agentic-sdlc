---
name: document-solution
description: Create or update three linked Markdown files for an implemented Salesforce solution.
argument-hint: "<solution topic and scope> [itemId=<ID>] [documentationPath=docs/solutions/<slug>/]"
agent: developer
tools: ['read', 'search', 'edit', 'execute', 'vscode/askQuestions', 'ado-readonly/*', 'salesforce/review_org_identity', 'salesforce/review_installed_packages', 'salesforce/review_object_contract', 'salesforce/review_soql_query']
---

Thin VS Code alias with no logic of its own. As the `developer` agent, follow the
[document-solution skill](../skills/document-solution/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
