---
name: publish-wiki
description: Publish a solution's three files or a delivery document to the existing Azure DevOps Wiki.
argument-hint: "<solution directory, delivery document, or topic> [itemId=<ID>] [wiki=<name>] [path=<existing wiki path>]"
agent: developer
tools: ['read', 'search', 'edit', 'execute', 'vscode/askQuestions', 'ado-readonly/*']
---

Thin VS Code alias with no logic of its own. As the `developer` agent, follow the
[publish-wiki skill](../skills/publish-wiki/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
