---
name: investigate-config-records
description: Snapshot the configuration records held in one allowlisted reference-data object (statuses, settings) and report it read-only with a recorded digest.
argument-hint: "objectApiName=<API name> [org=<alias>] [fields=<A,B,C>]"
agent: config-investigator
tools: ['read', 'search', 'edit', 'execute', 'vscode/askQuestions', 'salesforce/review_org_identity', 'salesforce/review_object_contract', 'salesforce/review_configured_orgs', 'salesforce/review_soql_query']
---

Thin VS Code alias with no logic of its own. As the `config-investigator` agent, follow the
[investigate-config-records skill](../skills/investigate-config-records/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
