---
name: investigate-object
description: Collect bounded, sanitized, reconciled evidence for one Salesforce object or component and report it read-only.
argument-hint: "objectApiName=<API name>"
agent: config-investigator
tools: ['read', 'search', 'edit', 'execute', 'vscode/askQuestions', 'salesforce/review_org_identity', 'salesforce/review_installed_packages', 'salesforce/review_object_contract', 'salesforce/review_configured_orgs', 'salesforce/review_soql_query']
---

Thin VS Code alias with no logic of its own. As the `config-investigator` agent, follow the
[investigate-object skill](../skills/investigate-object/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
