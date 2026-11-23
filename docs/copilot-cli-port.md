# Copilot port: CLI, Copilot harness and Copilot SDK

The harness agents, skills and hooks were written for the VS Code **Local** harness. This
document covers the port to every GitHub Copilot host that runs the same files:

| Host | What it is | How this repository uses it |
|---|---|---|
| **Copilot CLI** | the `copilot` terminal agent | `scripts/sdlc.py` launcher, delivery runs (plan 05) |
| **Copilot harness in VS Code** | the default for new sessions in the editor Chat view and the **Agents window** since 28 Oct 2026; built on the Copilot SDK; sessions run in a separate Agent Host process | interactive work in VS Code |
| **Copilot SDK** | the same runtime embedded in a program (Python, Node, Go, .NET, Java, Rust); generally available | `scripts/sdlc_orchestrator.py` |
| Local harness (VS Code) | the old editor-only runtime | **deprecated, removed in February 2027**; not available in the Agents window |

The file keeps its old name because other files link to it.

Status:
- **Copilot CLI 1.0.112:** ported and verified live (2026-11-16/17), on macOS and Windows.
- **Copilot harness and SDK:** the facts below come from the VS Code and GitHub documentation
  (read 2026-11-23). They are **not yet verified live** in this repository. Run
  [Live verification](#live-verification) per host before you rely on a host.

## One runtime, three front ends

The Copilot CLI, the VS Code Copilot harness and the Copilot SDK share one agent runtime.
Agent files, skills, instructions and file hooks therefore mostly behave the
same way. The differences come from:
- which files each front end discovers;
- whether an editor is connected (extension tools);
- how a person can answer `ask`.

Treat a fact verified live on the CLI as the default for the other two hosts until a probe
shows a difference. Where the documentation disagrees with the CLI live result (agent-scoped
hooks, below), the live result wins until a probe on the newer host passes.

## What changed (all hosts)

| Area | Before (Local only) | Now | Why |
|---|---|---|---|
| Agent `target` | `target: vscode` on all agents | unset | The CLI skips agents with `target: vscode`. `target` changes how the editor reads the file, not the harness. |
| Agent and prompt `tools` | `edit/editFiles`, `execute/runInTerminal`, `web/fetch` | `edit`, `execute`, `web` (also `read`, `search`, `agent`, `todo`) | Copilot built-in aliases. Unknown names are ignored without an error, so an agent loaded without its editor or shell. The validator rejects the qualified names. |
| Sub-agent delegation | Local `agent/runSubagent`, `handoffs`, `agents` | the native `task` tool; the conductor's chain is an instruction plus the global sub-agent gate | Copilot does not accept `handoffs`, `agents`, `argument-hint` or `advancedOptions`. `agent/runSubagent` is not portable. |
| Role guard timeout | 5 s | 10 s | See [Hooks](#hooks-on-every-host): a hook timeout does not deny. |
| `.github/hooks/safety.json` | no `version`, `command` and `windows` only | `"version": 1`, plus `powershell` | Copilot hook file format. The key stays PascalCase `PreToolUse`, so the payload is snake_case (`tool_name`, `tool_input`). |
| Hook output | `hookSpecificOutput.permissionDecision` | the same, plus top-level `permissionDecision` and `permissionDecisionReason` | VS Code reads the first, the CLI documents the second. |
| Hook input | snake_case only | also camelCase `toolName` and `toolArgs` (`toolArgs` may be a JSON string) | The camelCase `preToolUse` event sends this payload on every Copilot host. |
| Hook failure | non-zero exit | every error path prints a `deny` JSON and exits 0 | Local and the Copilot harness treat a generic non-zero exit as a non-blocking warning. |
| Protection that must hold for every agent | agent frontmatter hooks (role guard) | the global safety hook, with the shared list in `scripts/protected_paths_policy.py` | Agent-scoped hooks did not run on CLI 1.0.112, and the hook payload has no agent name. |
| `write_bash`, `write_powershell` | not recognized | denied for every role | They send keystrokes to a running shell, which is not a reviewable command. |
| CLI `create` tool, `apply_patch` | not recognized as editors | treated as edits; `apply_patch` paths come from its `*** Add/Update/Delete File:` lines | Path limits apply to new files and patches too. |
| Prompt files | 13 prompts with routing, arguments, stops, next actions | thin VS Code aliases; logic in each skill's `## Invocation contract` | The CLI does not read `.github/prompts`. VS Code's migration guide says to turn prompts into skills. |
| Validator `.git` check | `.git` must be a directory | `.git` may be a file | Linked git worktrees. |

## Customization support by host

Sources: Copilot CLI live probes, the VS Code custom agent and hooks references, the
Copilot SDK docs. "Docs" means documented, not yet probed here.

| Feature | Copilot CLI 1.0.112 (live) | VS Code Copilot harness (docs) | Copilot SDK (docs) |
|---|---|---|---|
| Agents in `.github/agents` | yes | yes (also `.claude/agents`, `~/.copilot/agents`, organization agents) | via `agents.directories`, repository settings `agentDirectories`, or code in `agents.definitions` |
| Agent `tools` list | yes; unknown names ignored | yes; tool names differ by harness | `tools` on each agent definition; omitted = all session tools |
| `handoffs`, `agents`, `argument-hint` | ignored with a warning | not accepted | no such fields |
| Agent-scoped `hooks` | **did not run** | documented as running "while that agent is active" | no `hooks` field on agent definitions; use session hooks |
| File hooks `.github/hooks/*.json` | yes | yes (also `.github/copilot/settings*.json`, `.claude/settings*.json`, `~/.copilot/hooks`) | repository hooks controlled by `hooks.enableRepositoryHooks`; explicit `hooks.directories` |
| Code hooks | — | — | `hooks.handlers`: `onPreToolUse` returns allow, deny or ask, with `modifiedArgs` and `additionalContext` |
| Agent name in the tool hook payload | no | no (`preToolUse` has `toolName`, `toolArgs`); `subagentStart` has `agent_type` | not in `onPreToolUse` input; streaming events `subagent.started` carry `agentName` |
| Prompt files `.github/prompts` | not read | migration guide says to convert them to skills | not read |
| Skills `.github/skills` | yes | yes | `skills.directories` |
| Extension tools (for example `sf-harness.salesforce-operations/salesforceOperation`) | not available | only while an editor window with the extension is connected | not available |
| `vscode/askQuestions` | not available | client tool; needs the editor connected | `interaction.onUserInputRequest` handles `ask_user` |
| `ask` decision | a question in interactive mode; **deny** in `-p` and autopilot | needs an interactive approval flow; "do not assume it will pause an unattended session" | the program's permission handler decides; the SDK is deny by default |
| Agent selection | `--agent <name>` | the agent picker | `agents.selected` or `session.rpc.agent.select()` |
| Sandbox | none by default | `chat.agent.sandbox.enabled`, managed sandbox policy | in-process hosting gives neither crash isolation nor a sandbox; use the child process or `copilot-runtime --server` |

## Hooks on every host

- **Format.** Keep `.github/hooks/safety.json` with `"version": 1`, PascalCase `PreToolUse`,
  `command`, `windows` and `powershell`, timeout 10 s. The PascalCase alias sends snake_case
  `tool_name`/`tool_input` and may report Claude-style tool names. The camelCase `preToolUse`
  sends `toolName`/`toolArgs`. The hook parses both.
- **Decisions.** `allow`, `deny` or `ask`. When several hooks answer, the most restrictive
  decision wins. Print both output shapes.
- **Failure.**
  - Copilot documents a `preToolUse` command error as a deny.
  - A **timeout falls through to the normal permission flow**, not to a deny.
  - Exit code 2 is a blocking error. Any other non-zero code is a warning, and the tool runs.

  So every error path in our hooks prints a `deny` JSON and exits 0, and the hooks stay
  fast.
- **No agent name.** The tool hook payload has no agent. Role rules that must hold therefore
  live in the global hook. On the CLI the payload had `cwd`, `hook_event_name`, `session_id`,
  `timestamp`, `tool_input`, `tool_name`, `tool_use_id`. The Copilot harness documents
  `subagentStart`/`subagentStop` with `agent_id` and `agent_type`. A later version can record
  the active sub-agent per session from those events and apply role rules in the global hook.
  This is not built yet.
- **Tool names seen live on the CLI:** `Bash` (also PowerShell on Windows), `Edit`, `create`,
  `apply_patch`, `Agent` (the model calls it `task`), `write_bash` and `write_powershell`. Match them case-insensitively. Tool names and input schemas differ between
  harnesses, so record the names on each new host (probe 2 below).
- **SDK.** The orchestrator can call the policy modules (`protected_paths_policy`,
  `git_workflow_policy`, `salesforce_operation_policy` and the safety hook's
  `evaluate_event`) in process from `onPreToolUse`. This is enforcement in code, not through a
  file hook. Keep repository hooks on (`hooks.enableRepositoryHooks`) as a second layer.

## Setup

### Every host

1. In the ignored `config/harness.local.json`, set `salesforce.agentOrg` to a configured
   developer alias. `scripts/first_launch.py` fills it when exactly one non-production org is
   recorded.
2. Trust the repository root. Repository hooks load only for a trusted folder;
   SDK repository locations need trust that covers the checkout root.
3. Start from the repository root. From a subdirectory, the root hooks may not load (CLI 1.0.111
   warns).
4. Run the delivery check with `node scripts/check-delivery.mjs …` on every OS. Windows has no
   `python3`, and `sf` is the npm shim `sf.cmd` there; the checker starts it through
   `node …/@salesforce/cli/bin/run.js`.

### Copilot CLI

- `brew upgrade --cask copilot-cli` or `copilot update`. Check with `copilot --version`.
- Start delivery runs through `python scripts/sdlc.py` (on Windows `python scripts\sdlc.py`).
  The launcher sets the deploy grant, checks for a clean tree on `main`, puts `sf` on PATH,
  adds `--trust-folder` in `-p` mode and finishes S3, S6 and S7.

### VS Code Copilot harness (editor and Agents window)

- Choose **Copilot** as the session target. The Local harness disappears in February 2027;
  `vscode.temporaryDefaultToLocalHarness` is going away too.
- Enable tools under **Chat: Open Customizations > Tools**. The choice is stored per user
  profile, not per request.
- Extension tools (the Salesforce operation tool) work only in a session with a connected
  editor window that runs the extension. In the Agents window without an editor, agents use
  the `sf` CLI under the same policy (SAFE-HOST-NATIVE-001).
- The VS Code **Migrate** action moves prompts to skills and converts files once. Our prompts
  are already thin aliases; do not let Migrate duplicate skill logic.
- Sandbox: `chat.agent.sandbox.enabled`. Check that agents can still reach `sf` and the org
  inside the sandbox.

### Copilot SDK (orchestrator)

- `requirements-orchestrator.txt` pins `github-copilot-sdk==1.0.34`, the pre-GA package that
  bundles CLI 1.0.112. The generally available SDK (`microsoft/copilot-sdk`, v2) hosts the
  runtime in process by default. Plan the upgrade:
  - define agents with `agents.definitions` (or load `.github/agents` with `agents.directories`);
  - enforce policy in `hooks.handlers.onPreToolUse` and keep `hooks.enableRepositoryHooks` on;
  - answer questions with `interaction.onUserInputRequest`;
  - set a deny-by-default permission handler;
  - select the station agent with `agents.selected`.
- Use the child-process or `copilot-runtime --server` mode for crash isolation. In-process mode
  gives neither isolation nor a sandbox.

## Known gaps

### Copilot CLI (live, 1.0.112)

- **Agent frontmatter `hooks` do not run.** A developer session wrote `config/spike-probe.txt`
  with no role-guard decision. Protected files are enforced by the global hook. Role-only
  rules apply in VS Code Local only: only the git-agent pushes and opens PRs, and the
  maintainer may make confirmed edits.
- **`ask` is a deny in prompt mode,** even with `--allow-all-tools`: "Denied by preToolUse hook
  (unable to ask user for confirmation)". The deploy autonomy grant
  (SAFE-DEPLOY-AUTONOMY-001) replaces `ask` for developer-org deploys in launcher runs.
- **Sub-agents:** the `task` tool with `agent_type`; the hook sees `Agent`. The gate allows
  only the custom agents. Built-in sub-agents asked for models the plan did not have.
- **Models:** on some plans only `--model auto` works. Do not set `model` in agents or
  sub-agent calls.
- **Windows:**
  - `sf` and `copilot` may be `.cmd` shims, so the launcher spawns full paths.
  - The agents' shell may not see `sf`, so the launcher puts it on PATH.
  - Agents use PowerShell. `Set-Location '<root>';` counts like `cd <root> &&`.
  - A here-string with `\` triggered "Allow path access: `\`". Refuse it; agents write files
    with the editor only.
- **Organization policy** can disable `--yolo` and `--allow-all`.

### VS Code Copilot harness (docs, to verify)

- **Agent-scoped hooks** are documented as supported, unlike the live CLI result. Until a
  probe passes, keep everything that must hold in the global hook.
- **No `handoffs`.** The designer → reviewer → developer chain runs as instructions plus `task`
  sub-agents, or through the orchestrator.
- **Prompt tool narrowing** (for example `publish-wiki` dropping Salesforce tools) does not
  apply. The agent's full tool list applies; the contract records the intended list.
- **`ask` in unattended sessions** (Agents window background work, cloud sessions) cannot be
  relied on to pause.
- **Hooks are in preview** in VS Code and may change.

### Copilot SDK (docs, to verify)

- **Deny-by-default permissions.** The orchestrator must answer every permission request
  explicitly.
- **No CLI flags and no TUI** (`-p`, `--agent`, `/skills`). Use config and the `rpc`
  APIs instead.
- **No agent name in `onPreToolUse`.** Correlate tool calls with `subagent.started` events
  (`agentName`, `toolCallId`) if a role rule is needed.
- **The SDK is a moving target.** Pin the version and record it in each run.

## Commands on every host

Every public command is a pair of a role (custom agent) and a skill. The skill's
`## Invocation contract` states both:

```text
Role: `designer`. ...
Arguments: `itemId=<ID> ...`.
Entry points: VS Code `/solution-design <arguments>`; Copilot CLI `copilot --agent designer`
with `solution-design <arguments>`.
```

- **CLI:** `copilot --agent designer`, then `solution-design itemId=1234`.
- **VS Code Copilot harness:** pick the `designer` agent and type `solution-design itemId=1234`.
  The thin prompt alias works only while VS Code still reads prompt files.
- **SDK:** select the agent (`agents.selected`) and send the same text as the prompt.

Skills stay `user-invocable: false`, so they never become slash commands that run in the
default agent, which has no role guard. The validator keeps prompts thin (at most 45 words and
one skill link) and checks that each contract's role, arguments and entry point match the
prompt frontmatter.

## Live verification

Run in the repository root with a trusted folder. Record the host, its version and each
result in the decisions log.

### Common checks (each host)

1. All eight agents are listed and start.
2. In the designer, `echo ok` runs. `sf project deploy start -o prod` is denied with the
   hook's reason.
3. Ask an agent to edit a file under `.github/hooks/`: the global hook asks a person or
   denies it.
4. A `task` sub-agent with a custom `agent_type` works. `general-purpose` is denied.
5. `solution-design` without arguments: the agent asks once for the item or the requirement and does not guess.

### Probes for a new host or version

- **P1, agent-scoped hooks.** Give an agent a frontmatter hook that denies everything, then ask
  it for `echo ok`. If the command runs, agent hooks are ignored on this host.
- **P2, payload.** Use a global hook that appends its stdin to `.cache/hook-probe.jsonl`. Make
  one shell call, one edit and one sub-agent call. Record the keys and tool names.
- **P3, ask.** A hook returns `ask`. Run it interactively and once unattended (CLI `-p`,
  Agents window background, SDK).
- **P4, timeout.** A hook sleeps past its timeout. Does the tool run?
- **P5, Windows.** Repeat checks 1–3 on Windows and run `node scripts/check-delivery.mjs`.

If check 2 or 3 runs the command, the host does not honor the hook. Stop using that host
for this repository and record it.

## Sources

- VS Code: [Choose an agent harness](https://code.visualstudio.com/docs/agents/run/agent-harnesses),
  [Move from Local to Copilot](https://code.visualstudio.com/docs/agents/run/move-to-copilot),
  [Custom agent file reference](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference),
  [Agent hooks](https://code.visualstudio.com/docs/agent-customization/hooks),
  [Hooks reference](https://code.visualstudio.com/docs/agents/reference/hooks-reference)
- GitHub: [Copilot in VS Code, Universe releases (2026-10-28)](https://github.blog/changelog/2026-10-28-github-copilot-in-vs-code-universe-releases/),
  [SDK pre-tool-use hook](https://docs.github.com/en/copilot/how-tos/copilot-sdk/use-hooks/pre-tool-use)
- Copilot SDK: [repository](https://github.com/microsoft/copilot-sdk),
  [custom agents](https://github.com/microsoft/copilot-sdk/blob/main/docs/features/custom-agents.md),
  [customization locations](https://github.com/microsoft/copilot-sdk/blob/main/docs/features/customization-locations.md),
  [SDK vs CLI compatibility](https://github.com/microsoft/copilot-sdk/blob/main/docs/troubleshooting/compatibility.md)
