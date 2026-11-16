# Agent Compatibility Contract

Follow `.github/copilot-instructions.md`. `docs/` explains the package;
`work-items/` holds plans. `brain-core` (`.`) is the only SFDX root.
Load role contracts/skills and `.ai/repo-map.md`; never search another root for metadata.

Developer uses reviewed CLI on `dev`/`uat`/`stage`. Production CLI permits only verified metadata
retrieve; other reads use Salesforce MCP within role limits. Test Strategist cannot target prod.
Unknown targets/latest require the native Developer tool with arguments only; its dialogs own
one-use environment selection and exact deployment confirmation. Never launch private helpers or
supply approval/environment fields. See `docs/native-salesforce-operations.md`.
Before a real deploy, identify target/scope and warn that changes reach the org; confirm that exact
invocation. Native execution requires its modal confirmation.

Governed Salesforce/ADO and protected non-Git edits need a custom agent's role guard
(VS Code or Copilot CLI); default Agent mode lacks it. Merge and force push stay human; only
the git-agent pushes `feat/*` and opens draft PRs (plan 05).
