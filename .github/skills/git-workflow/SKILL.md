---
name: git-workflow
description: Shared Git and GitHub CLI workflow for all roles; hooks reserve merge and destructive actions for a person, and only the git-agent pushes feature branches and opens draft PRs.
user-invocable: false
---

# Git Workflow

Apply the [writing standard](../../../.ai/contracts/writing-standard.md).
Every role can use local Git: branches, staging, commits, stash, fetch and pull. The hooks
enforce the publication boundaries of [plan 05](../../../docs/plan05-w8-integration.md)
(B1, B2) for every agent:

- Denied always: `git merge`, `git rebase` (except `--abort`/`--quit`), `git reset --hard`,
  force branch deletion, `gh api`, `gh pr merge|review|ready|close`, and the `gh release`,
  `repo`, `secret`, `variable`, `workflow`, `run` and `auth` subcommands that change state.
- Only the `git-agent` pushes, and only to `feat/*` branches: no force, delete, mirror or tag
  pushes, never `main`.
- Only the `git-agent` opens a pull request, always with `--draft`, and only when
  `scripts/check_delivery.py` reported PASS for the current HEAD commit.

Run `git` and `gh` directly, one command at a time; do not wrap them in a Python `subprocess`
call, a PowerShell script block or a here-string, which neither a reviewer nor the hooks can
judge. Commit messages are not checked by a hook. Salesforce/ADO configuration does not gate Git.

## Scope and authorization

Preserve unrelated staged, unstaged, and untracked work. Inspect the actual diff before
committing; include only the requested result or changes the human explicitly asks to commit.
Choose the staging method that fits that scope, including partial staging or `git add -A`.
Active authors can commit coherent milestones after proportional verification without a
separate commit request. A review request stays a review; available Git commands do not
instruct Reviewer to change source.
Editor permissions and Salesforce/ADO access controls are unchanged.

In a delivery run, a PASS delivery check is the instruction to push the feature branch and
open the draft PR (plan 05, D-B1). Outside a delivery run, push and PR creation need an
explicit human instruction. Merge, ready-for-review, approval and release always stay with a
person. `clean -fd` and shared-history rewriting need an explicit human instruction. Ordinary
local conflict resolution follows the requested scope; report conflicts that need a human
decision. Native host approval may still appear independently of the repository hooks.

## Branches and local commits

Inspect repository state and choose or reuse a branch suitable for the requested work.
These names are conventions, not requirements:

- `feat/<work-item-id>-<slug>` for one delivery item. Only `feat/*` branches can be pushed by
  an agent.
- `feat/<feature-id>-<slug>` for combined Feature delivery selected by the human.
- `chore/<short-description>` for local maintenance or documentation without a Work Item.

Local work on other branches is permitted. No branch name, ADO fetch, context file,
delivery map, synchronized base, or index/working-tree equality is a Git prerequisite.
Use actual requirement context when the delivery task needs it; never invent an ADO ID.
A parent relation alone does not select combined Feature delivery. Feature membership is a
planning decision, not a Git gate. `start work item <ID>` and `start feature <Feature ID>`
remain optional Git Agent entry points. Intake returns `/solution-design itemId=<ID>` when
appropriate; a Git action does not start a new lifecycle phase.

Review the staged result, commit it, and verify the resulting SHA and remaining changes.
Report actual verification and whether the result is local or published. Inspect a failed or
unknown outcome before retrying. Do not reset or stash unrelated work to make a commit pass.

## Commit message

Use a nonempty descriptive subject. This convention is recommended, not checked by a hook:

```text
[chore] Update workspace configuration
[docs] Describe deployment procedure
[WI-123] Add account validation — AB#123
[FEATURE-456] Integrate billing changes — AB#456
```

Write the actual result in English/STE; an optional body explains why and actual
verification. Use configured identity and truthful dates. Preserve useful history unless
rewriting it is part of the explicit request. Do not use `Fixes`, `Resolves`, or `Closes` as
ADO state-transition instructions. A commit neither approves a design nor proves a deployment
or test result.

## GitHub work

Use the user's configured CLI authentication without printing tokens. Resolve the intended
repository and PR from the request and actual state. Inspect its diff, head/base, current
checks, and reviews before acting. Search for an existing matching PR before creating one;
read remote state before retrying a timeout or uncertain result. Queued or auto-merge enabled
is not merged. Report the actual PR URL, head, status, and checks.

Use `.github/pull_request_template.md` for truthful descriptions. Write the body through the
editor to the ignored `.cache/github/pr-body.md` and pass `--body-file`; this transport file
is a transport file, not a source edit.
Preserve human edits. Prefer explicit `--repo`, `--head`, `--base`, and `--title` when creating
a PR. The hook requires `--draft`; a person marks the PR ready and merges it. Respect
repository requirements and the authorized scope.

Link the canonical `org-changes.md` when Salesforce mutations occurred. The log is
traceability, not approval or independent proof. Do not copy its content into the PR or invent results.
For Work Item PRs, use raw `Azure Boards: AB#<id>` references. For combined delivery, use
`Azure Boards Feature: AB#<feature-id>` and `Included Work Items: AB#<id>, …` from the agreed
scope. For maintenance without ADO, state that the reference is not applicable. These links
do not authorize ADO updates. Publication, merge, release, and deployment are separate actions.
