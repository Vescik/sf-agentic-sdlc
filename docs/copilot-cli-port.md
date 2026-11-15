# Copilot CLI port

Status: implemented 2026-11-15 on branch `feat/copilot-sdk-harness`. Local tests pass.
**Not yet verified on a live Copilot CLI session**: run the checks in
[Live verification](#live-verification) before relying on the CLI path.

The harness agents, hooks and MCP servers were written for VS Code Local. This port makes the
same files load in GitHub Copilot CLI (checked against CLI 1.0.112, 2026-11-13) without
breaking VS Code. The Copilot SDK starts the same CLI runtime, so the port is also the
base for an SDK orchestrator.

## What changed

| Area | Before (VS Code only) | Now (VS Code and Copilot CLI) | Why |
|---|---|---|---|
| Agent `target` | `target: vscode` on all agents | unset | The CLI skips agents with `target: vscode`. Unset means both hosts. |
| Agent and prompt `tools` | `edit/editFiles`, `execute/runInTerminal`, `web/fetch` | `edit`, `execute`, `web` | The CLI ignores unknown tool names without an error, so an agent loaded without its editor or shell. The aliases exist on both hosts. The validator now rejects the VS Code-qualified names. |
| Role guard timeout | 5 s | 10 s | A hook timeout **fails open** in the CLI. A crash or non-zero exit fails closed. |
| `.github/hooks/safety.json` | no `version`, `command` and `windows` only | `"version": 1`, plus `powershell` for CLI on Windows | CLI hook file format. The key stays PascalCase `PreToolUse`, so both hosts send the snake_case payload (`tool_name`, `tool_input`) the hooks already parse. |
| Hook output | `hookSpecificOutput.permissionDecision` | the same, plus top-level `permissionDecision` and `permissionDecisionReason` | VS Code reads the first shape; the CLI hooks reference documents the second. |
| Hook input | snake_case only | also camelCase `toolName` and `toolArgs` (`toolArgs` may be a JSON string) | Defensive: a camelCase registration sends this payload. |
| `write_bash`, `write_powershell` | not recognized; reached only text checks | denied for every role | These CLI tools send keystrokes to a running shell. The input is not a reviewable command and could answer a confirmation prompt. |
| CLI `create` tool | not recognized as an editor | treated as an edit (exact name match) | Role path limits would not apply to new files. |
| `.github/mcp.json` | empty | `ado-readonly` and `salesforce` with the same read-only launchers as `.vscode/mcp.json` | The CLI reads `.github/mcp.json` (and `.mcp.json`), not `.vscode/mcp.json`. |
| Salesforce MCP alias | `${input:sf_review_org}` prompt in VS Code | both hosts start with `--org-from-config`, which reads `salesforce.agentOrg` | The CLI has no input prompts, and one org for MCP, `sf` and the orchestrator is the owner decision. The facade still proves host, Org ID and IsSandbox before tools; the alias grants nothing. |
| Prompt files | 13 `.github/prompts/*.prompt.md` with routing, arguments, stops and next actions | thin VS Code aliases; the logic moved to the linked skill's `## Invocation contract` | Copilot CLI does not read `.github/prompts` (it reads instructions, `.github/skills`, `.github/agents`, `.claude/commands`). The text would not exist on the CLI. |
| Validator `.git` check | `.git` must be a directory | `.git` may be a file | Linked git worktrees have a `.git` file. |

## Setup for the CLI

1. Install or update the CLI: `brew upgrade --cask copilot-cli` (or `copilot update`).
   Check with `copilot --version`.
2. In the ignored local policy `config/harness.local.json`, set `salesforce.agentOrg` to a
   configured `salesforce.orgs` alias (review must be `enabled`). `scripts/first_launch.py`
   fills it when exactly one non-production org is recorded:

   ```json
   "salesforce": { "agentOrg": "<a configured non-production alias>", "orgs": [ … ], "review": { … } }
   ```

3. Trust the repository root. Repository hooks and MCP servers load only for a trusted
   folder. Use the interactive trust prompt, or `--trust-folder` for one `-p` session.
4. Always start the CLI **from the repository root**. With `-p --trust-folder` from a
   subdirectory, the root hooks do not load (CLI 1.0.111 prints a warning).
5. Check that the servers load: `copilot mcp list`.

## Known gaps on the CLI

- **Native Salesforce operation tool.** `sf-harness.salesforce-operations/salesforceOperation`
  is a VS Code extension tool and does not exist in the CLI. Operations that need it
  (unknown targets, `latest`, its one-use environment and deployment dialogs) stop and report
  (SAFE-HOST-NATIVE-001). Deploys to the configured agent org go through direct `sf`; in an
  orchestrated run they need no question (SAFE-DEPLOY-AUTONOMY-001, `docs/orchestrator.md`).
- **`ask` decisions.** The CLI turns `ask` into `deny` in autopilot mode and in the cloud
  agent. A "person says yes" gate is then a hard stop, not a question.
- **Handoffs.** `handoffs` is a VS Code feature. On the CLI, the designer → reviewer →
  developer chain runs through the SDK orchestrator: `docs/orchestrator.md`.
- **Prompt tool narrowing.** Seven prompts narrow the agent's tools in VS Code (for example
  `publish-wiki` drops the Salesforce tools). The CLI applies the agent's full list. Each
  Invocation contract records the VS Code list; an SDK orchestrator station can enforce it.
- **Question form.** `vscode/askQuestions` has no CLI equivalent in the agent `tools` list.
  Whether the CLI `ask_user` tool stays available under an explicit `tools` list is not
  verified.
- **Policy limits.** An organization policy can disable `--yolo` and `--allow-all`
  (CLI 1.0.110 warns when it ignores them).
- **Fail-open timeouts.** Hooks have 10 s. A hook that times out lets the tool run.

## Commands on the CLI

Every public command is a pair: a role (custom agent) and a skill. The skill's
`## Invocation contract` states both:

```text
Role: `designer`. ...
Arguments: `itemId=<ID> ...`.
Entry points: VS Code `/fetch-ado-item <arguments>`; Copilot CLI `copilot --agent designer`
with `fetch-ado-item <arguments>`.
```

On the CLI, start the named agent and give the command name with its arguments, for
example `copilot --agent designer` and then `fetch-ado-item itemId=1234`. A next action
printed as `/solution-design itemId=<ID>` means the same pair.

Skills stay `user-invocable: false`, so they do not become CLI slash commands. A slash
command would run the skill in whatever agent is active, including the default agent, which
has no role guard. The validator keeps prompts thin (at most 45 words, one skill link) and
checks that the contract's role, arguments and entry point match the prompt frontmatter.

## Live verification

Run in the repository root with a trusted folder. Record the CLI version and the result of
each check in the work item or the decisions log.

1. `/agent` lists all seven agents; `copilot --agent designer` starts.
2. In the designer, ask for `echo ok`: it runs. Ask for `sf project deploy start -o prod`:
   the safety hook denies it, with the hook's reason in the output.
3. In the reviewer, ask it to create a file under `.github/hooks/`: the role guard denies it.
4. `copilot mcp list` shows `ado-readonly` and `salesforce`; the designer can call
   `salesforce/review_org_identity` against the configured non-production alias.
5. Which tools does each agent actually get? Compare with its `tools` list.
6. `copilot --agent designer`, then `fetch-ado-item` without arguments: the agent asks once
   for `itemId` in its reply and does not guess.

If check 2 or 3 runs the command, the CLI is not honoring the hook output: stop using the
CLI path and record it.
