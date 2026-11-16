# Delivery Success Contract

Status: normative
Schema version: 1

A delivery run succeeds only when `scripts/check_delivery.py` reports PASS for the HEAD commit of
the feature branch. An agent's own statement that work is done, tested, or deployed is never
success. Plan and decisions: [plan 05](../../docs/plan05-w8-integration.md).

```bash
.venv/bin/python scripts/check_delivery.py --work-item work-items/<id>-<slug>
```

The script runs the Apex tests itself and reads the deploy result from the org. It writes
`work-items/<id>-<slug>/delivery-check.json` (ignored by Git) and exits 0 for PASS, 1 for FAIL,
and 2 when it cannot run (configuration or tool error). A run that exits 2 has no result: fix the
cause and run the check again; never report it as PASS or FAIL.

## Criteria

All five must pass for the same commit.

| ID  | Criterion                                          | Checked by the script                                                                                                                                                                                               |
| --- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SC1 | Every acceptance criterion is covered              | Every `AC-n` in `requirements.md` has a row in `acceptance-trace.md`. Each `Class.method` in the row exists in the package source and has outcome `Pass` in the SC2 run. A `manual: <step>` entry is listed for H3. |
| SC2 | All Salesforce tests are green                     | `sf apex run test --test-level RunLocalTests --code-coverage` against the agent org: outcome Passed, no failing test. When `package.json` has a `test:unit` script, `npm run test:unit` must exit 0.                |
| SC3 | Coverage ≥ 75% for every changed class and trigger | Every non-test Apex class and trigger added or changed against the base branch has at least 75% coverage in the SC2 run. A class with no reported coverage fails.                                                   |
| SC4 | Metadata deployed without missing components       | `sf project deploy report --job-id <id>` in the agent org: status Succeeded, not check-only, completed after the last commit that changed package source, and every source file changed on the branch is in the deployed file list.             |
| SC5 | Clean result                                       | The branch is `feat/*`, and the working tree has no uncommitted change except the check's own report.                                                                                                               |

## Files the agent writes

- `requirements.md`: numbered requirements and acceptance criteria with stable IDs `AC-1`,
  `AC-2`, … The IDs never change after the first commit; a dropped criterion is marked dropped,
  not renumbered.
- `acceptance-trace.md`: one table row per acceptance criterion. Separate several entries with
  commas.

  ```markdown
  | AC   | Covered by                                      |
  | ---- | ----------------------------------------------- |
  | AC-1 | CaseRouterTest.routesHighToTier2                |
  | AC-2 | CaseRouterTest.routesOtherToTier1               |
  | AC-3 | manual: open a case and check the Routing field |
  ```

  Use a manual step only when an Apex test cannot observe the behavior (for example layout or
  UI-only behavior). A manual step is not checked by the script; H3 sees each one in the draft
  PR.

- `deploy-job-id`: the ID of the real deploy job (`0Af…`) of the HEAD commit to the agent org,
  one line. Commit it with the work.

## Repair

On FAIL, read the failing details, change the cause, commit, deploy, and run the check again.
The attempt budget is 6 checks per iteration (plan 05, D-AB). Each attempt must change something
named in the failing details; repeating the same attempt does not count as repair.

## Limits

- SC4 compares file paths when the deploy result lists files, and component names otherwise.
  A component that the name fallback cannot map is reported as missing, never as deployed.
- The completion time in SC4 proves that the deploy happened after the last source commit, not
  that it deployed exactly that commit. Deploy from a clean tree after committing the source;
  commit `deploy-job-id` afterwards.
- The script does not run a static scan. `sf code-analyzer` findings are a warning in the
  report (plan 05) once the command is on the Salesforce allowlist.
