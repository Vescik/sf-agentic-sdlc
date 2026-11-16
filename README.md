# Salesforce Managed-Package Copilot Brain-Core

A private, team-versioned GitHub Copilot harness for Salesforce development around any configured
managed-package environment. It combines a minimal always-on safety/grounding kernel, eight SDLC agents,
fourteen public prompt commands, eighteen internal skills, governed but initially unseeded
Memory/QA layers, reconciled read-only org review, durable per-work-item design files,
and repeatable validation. No object, namespace, package behavior, or business meaning is built in.

## Current authority

1. [.github/copilot-instructions.md](.github/copilot-instructions.md) — always-on safety kernel.
2. [docs/workspace-topology.md](docs/workspace-topology.md) — supported single-repository workspace.
3. [docs/compatibility.md](docs/compatibility.md) — runtime/version contract.
4. [.ai/contracts/execution-contract.md](.ai/contracts/execution-contract.md) — common skill
   execution, cache, output, and failure behavior.
5. [docs/grounding-architecture.md](docs/grounding-architecture.md) — Principles,
   repository/org reconciliation, and the work-item boundary.

The original design history (`HARNESS_BLUEPRINT.md`, `BUILD_REPORT.md`, `HARNESS_DIAGRAMS.md`,
and both `HANDOFF_FOR_FABLE*.md` reviews) was removed from the working tree on 2026-07-16; it
remains in git history under the tag `design-history` (`git show design-history:docs/archive/README.md`
for the index). It was historical input only, never the normative runtime specification.
The 2026-07/08 planning, discovery, audit, and completion documents were likewise removed from
the working tree on 2026-08-11; they remain in git history under the tag `docs-history-2026-08-11`.

## Architecture

| Layer | Location | Purpose |
|---|---|---|
| Safety and Principles | `.github/copilot-instructions.md`, `.github/instructions/` | Minimal always-on kernel plus path-scoped rules loaded through `applyTo` |
| Orchestration | `.github/agents/` | Design, investigation, development, QA strategy, independent review |
| Public commands | `.github/prompts/` | Deterministic slash-command entry points (count pinned by `validate_harness.py`) |
| Internal capabilities | `.github/skills/` | Progressively loaded procedures hidden from the slash menu |
| Contracts | `.ai/contracts/` | Execution, writing, workflow and source-authority contracts |
| Work state and QA | `work-items/`, `.ai/memory/` | Per-item ADO context/design/tasks/decisions/QA test plan, optional Feature delivery map, and durable decisions |
| Salesforce project | `sfdx-project.json`, `force-app/`, `manifest/`, `tests/e2e/` | Root SFDX project, source, manifests, and Salesforce tests |
| Runtime | `.vscode/mcp.json`, `.github/hooks/`, `scripts/` | Reconciled MCP/hidden-CLI review, guarded Salesforce channels, deterministic checks |
| Local/generated data | `.cache/`, `output/` | Ignored raw cache and human-review drafts |


## Start here

Follow [SETUP.md](SETUP.md) — or, if you are setting up a machine from scratch, the
zero-assumptions walkthrough in
[docs/setup-zero-to-first-prompt.md](docs/setup-zero-to-first-prompt.md). Clone this repository
once, then open `sf-harness.code-workspace`.
The same agents, skills, hooks and MCP servers also load in GitHub Copilot CLI
([Copilot CLI port](docs/copilot-cli-port.md)). For one-prompt delivery from a requirement to a
draft PR in the developer agent org, run `python scripts/sdlc.py` and give the `sdlc-conductor`
agent `deliver-requirement itemId=<ID>` or `requirementFile=<path>`
([plan 05](docs/plan05-w8-integration.md)). In prompt mode the launcher starts the review and
draft-PR stations itself when the conductor leaves them out after a PASS delivery check. The [SDK orchestrator](docs/orchestrator.md) is the
headless alternative.
Once the workspace is installed, use the [Ways of Working guide](docs/ways-of-working.md) to
choose the right path for a feature, defect, managed-package dependency, or configuration-only
change.
The repository root is both the harness root and the only Salesforce DX project root. The
workspace exposes it once as `brain-core`; `sfdx-project.json`, `force-app/`, `manifest/`, and
`tests/e2e/` share the same branch, pull request, and commit history as the governance artifacts.
Opening the repository root directly is also supported; MCP and tasks use the unqualified
`${workspaceFolder}` variable so they do not depend on a display-name alias.

From the repository root, create/activate the virtual environment as described in SETUP, install
the pinned Node runtime, then run:

```bash
python -m pip install -r requirements-dev.lock
npm ci --ignore-scripts
python scripts/validate_harness.py
python -m unittest discover -s tests -v
npm run prettier:verify
npm run lint
```

`validate_harness.py` validates static repository integrity; `first_launch.py` validates
installation and local-config shape. External capabilities are proven at the point of use: the
Both Salesforce review MCP entries start with `salesforce.agentOrg` from
`config/harness.local.json`. The review MCP proves that org's live identity at startup, and ADO
scope is checked on every tool call. `python scripts/verify_salesforce_org.py --org <alias>` is
an optional human diagnostic for one org.

ADO uses one organization and project from `config/harness.local.json`. The launcher validates
that scope before starting the pinned vendor MCP. Complete the connector's interactive OAuth
sign-in in VS Code Local. Restart `ado-readonly` after changing the organization or project.
See [the setup guide](SETUP.md#3-local-configuration) for configuration and migration details.

Use `/publish-wiki` with the Developer to publish the three solution files or a delivery document.
It preserves stable pages, reads live content before conditional updates, and confirms the delivery
Story link. See [Wiki publication](docs/wiki-publication.md) for production scope and migration.

The workflows that need `config/harness.local.json` intentionally fail closed until it contains
real, human-owned environment/process values and the package/component review scope.
Missing evidence produces explicit unknowns, not fabricated package facts.

`manifest/package.xml` is a generic starter manifest, not automatic deployment scope. Before an
org-facing retrieve, validation, or deployment, bind the scope to the components named by the
approved design (`work-items/<id>-<slug>/design.md`); wildcard presence is never task scope.


For Developer operations requiring a one-use environment answer or supported latest-job selection,
install the [native Salesforce operation tool](docs/native-salesforce-operations.md). Existing MCP
contracts stay unchanged; host/live acceptance is recorded separately.
