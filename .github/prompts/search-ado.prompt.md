---
name: search-ado
description: Text-search Azure DevOps wikis and work items in the configured project; fetched wiki pages are sanitized, cached, and quoted with provenance.
argument-hint: "query=<text> [target=wiki|workitems|both] [top=<N>]"
agent: designer
tools: ['read', 'search', 'edit', 'execute', 'vscode/askQuestions', 'ado-readonly/*']
---

Thin VS Code alias with no logic of its own. As the `designer` agent, follow the
[search-ado skill](../skills/search-ado/SKILL.md) for the supplied input, starting with its
`Invocation contract`.
