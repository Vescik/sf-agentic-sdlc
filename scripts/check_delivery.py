#!/usr/bin/env python3
"""End-of-run delivery check: five success criteria, judged by code, not by the agent.

Contract: .ai/contracts/delivery-success.md (plan: docs/plan05-w8-integration.md).

    node scripts/check-delivery.mjs --work-item work-items/<id>-<slug> \   (any OS; or python3 / py -3 directly)
        [--base main] [--org <agentOrg alias>] [--deploy-job-id <0Af...>] [--output <path>]

SC1  every acceptance criterion in requirements.md is traced to a passing Apex test method
     (or to a written manual step) in acceptance-trace.md
SC2  RunLocalTests in the agent org: 0 failed (plus `npm run test:unit` when it exists)
SC3  coverage >= 75% for every non-test Apex class and trigger changed on the branch
SC4  the deploy job in the agent org succeeded after the last source commit and contains every
     source file changed on the branch under the package directories
SC5  clean working tree, `feat/*` branch, all work committed

The script runs the Apex tests itself and reads the deploy result from the org; it never
trusts a result file an agent wrote. It writes <work-item>/delivery-check.json (ignored by
Git) and exits 0 for PASS, 1 for FAIL, 2 for a usage or configuration error, 3 for BLOCKED
(failing tests outside the delivery: a person fixes the org, the agent does not).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("config/harness.local.json")
COVERAGE_MIN = 75.0
TEST_WAIT_MINUTES = 60
COMMAND_TIMEOUT_SECONDS = (TEST_WAIT_MINUTES + 5) * 60
RESULT_FILE = "delivery-check.json"
REQUIREMENTS_FILE = "requirements.md"
TRACE_FILE = "acceptance-trace.md"
AC_ID = re.compile(r"\bAC-(\d+)\b")
TEST_REF = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z][A-Za-z0-9_]*)$")
APEX_SOURCE = re.compile(r"/(classes|triggers)/([^/]+)\.(cls|trigger)(-meta\.xml)?$")
BUNDLE_DIRS = ("lwc", "aura", "staticresources", "experiences", "waveTemplates")

# (command, cwd) -> (returncode, stdout, stderr)
Runner = Callable[[list[str], Path], tuple[int, str, str]]


class CheckError(Exception):
    """A usage or configuration problem: the check cannot run (exit 2)."""


@dataclass
class Criterion:
    id: str
    title: str
    status: str = "FAIL"  # PASS or FAIL
    details: list[str] = field(default_factory=list)

    def passed(self, *details: str) -> "Criterion":
        self.status = "PASS"
        self.details.extend(details)
        return self

    def failed(self, *details: str) -> "Criterion":
        self.status = "FAIL"
        self.details.extend(details)
        return self


def run_command(command: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                              timeout=COMMAND_TIMEOUT_SECONDS, check=False)
    except FileNotFoundError:
        return 127, "", f"{command[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {COMMAND_TIMEOUT_SECONDS} s"
    return done.returncode, done.stdout, done.stderr


def sf_json(runner: Runner, root: Path, command: list[str]) -> dict[str, Any]:
    """Run an sf command with --json and return its `result` object, or raise CheckError."""
    code, out, err = runner(command + ["--json"], root)
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise CheckError(f"`{' '.join(command)}` returned no JSON (exit {code}): {err.strip()[:300]}") from exc
    result = payload.get("result")
    if not isinstance(result, dict):
        message = payload.get("message") or payload.get("name") or "no result"
        raise CheckError(f"`{' '.join(command)}` failed: {message}")
    return result


def git(runner: Runner, root: Path, *args: str) -> str:
    code, out, err = runner(["git", *args], root)
    if code != 0:
        raise CheckError(f"git {' '.join(args)} failed: {err.strip()[:300]}")
    return out


# ── inputs ─────────────────────────────────────────────────────────────────────────────

def agent_org(root: Path, override: str | None) -> str:
    if override:
        return override
    try:
        config = json.loads((root / CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"{CONFIG_PATH} is missing or invalid; pass --org or run scripts/first_launch.py") from exc
    alias = (config.get("salesforce") or {}).get("agentOrg")
    if not isinstance(alias, str) or not alias.strip():
        raise CheckError("salesforce.agentOrg is not set in config/harness.local.json")
    return alias


def package_dirs(root: Path) -> list[str]:
    try:
        project = json.loads((root / "sfdx-project.json").read_text(encoding="utf-8"))
        dirs = [d["path"].strip("/") for d in project["packageDirectories"]]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CheckError("sfdx-project.json has no readable packageDirectories") from exc
    return dirs


def changed_source_files(runner: Runner, root: Path, base: str, dirs: list[str]) -> list[str]:
    """Files added or modified on the branch (deletions are not deployable source)."""
    out = git(runner, root, "diff", "--name-only", "--diff-filter=d", f"{base}...HEAD", "--", *dirs)
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def acceptance_ids(text: str) -> list[str]:
    return sorted({f"AC-{n}" for n in AC_ID.findall(text)}, key=lambda ac: int(ac[3:]))


def parse_trace(text: str) -> dict[str, list[str]]:
    """`| AC-n | Class.method, manual: step |` rows -> {AC-n: [entries]}."""
    trace: dict[str, list[str]] = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not re.fullmatch(r"AC-\d+", cells[0]):
            continue
        entries = [entry.strip().strip("`") for entry in cells[1].split(",") if entry.strip()]
        trace.setdefault(cells[0], []).extend(entries)
    return trace


def apex_methods(root: Path, dirs: list[str]) -> dict[str, str]:
    """Class name -> source text, for every Apex class under the package directories."""
    classes: dict[str, str] = {}
    for directory in dirs:
        for path in (root / directory).rglob("*.cls"):
            classes[path.stem] = path.read_text(encoding="utf-8", errors="replace")
    return classes


def is_test_class(source: str) -> bool:
    head = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.DOTALL)
    match = re.search(r"\bclass\b", head, re.IGNORECASE)
    return bool(match and re.search(r"@isTest\b", head[: match.start()], re.IGNORECASE))


# ── criteria ───────────────────────────────────────────────────────────────────────────

def check_clean(runner: Runner, root: Path, work_item: Path) -> tuple[Criterion, str, str]:
    criterion = Criterion("SC5", "Clean result")
    branch = git(runner, root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    head = git(runner, root, "rev-parse", "HEAD").strip()
    report = (work_item / RESULT_FILE).relative_to(root).as_posix()
    dirty = [line for line in git(runner, root, "status", "--porcelain").splitlines()
             if line.strip() and line[3:].strip() != report]
    problems = []
    if not branch.startswith("feat/"):
        problems.append(f"branch {branch!r} is not a feat/* branch")
    if dirty:
        problems.append(f"working tree has {len(dirty)} uncommitted change(s): " + ", ".join(d[3:] for d in dirty[:10]))
    if problems:
        criterion.failed(*problems)
    else:
        criterion.passed(f"branch {branch}, HEAD {head[:12]}, working tree clean")
    return criterion, branch, head


def check_trace(root: Path, work_item: Path, tests: dict[str, str], classes: dict[str, str]) -> tuple[Criterion, list[str]]:
    criterion = Criterion("SC1", "Every acceptance criterion is covered")
    manual: list[str] = []
    req_path, trace_path = work_item / REQUIREMENTS_FILE, work_item / TRACE_FILE
    if not req_path.is_file():
        return criterion.failed(f"{REQUIREMENTS_FILE} is missing in the work item"), manual
    required = acceptance_ids(req_path.read_text(encoding="utf-8"))
    if not required:
        return criterion.failed(f"{REQUIREMENTS_FILE} names no AC-n acceptance criteria"), manual
    if not trace_path.is_file():
        return criterion.failed(f"{TRACE_FILE} is missing in the work item"), manual
    trace = parse_trace(trace_path.read_text(encoding="utf-8"))
    problems = []
    for ac in required:
        entries = trace.get(ac, [])
        if not entries:
            problems.append(f"{ac}: no test or manual step in {TRACE_FILE}")
            continue
        for entry in entries:
            if entry.lower().startswith("manual:"):
                if not entry[7:].strip():
                    problems.append(f"{ac}: manual step has no text")
                else:
                    manual.append(f"{ac}: {entry[7:].strip()}")
                continue
            ref = TEST_REF.match(entry)
            if not ref:
                problems.append(f"{ac}: {entry!r} is neither Class.method nor 'manual: <step>'")
                continue
            cls, method = ref.groups()
            source = classes.get(cls)
            if source is None or not re.search(rf"\b{re.escape(method)}\s*\(", source):
                problems.append(f"{ac}: {entry} does not exist in the package source")
            elif tests.get(f"{cls}.{method}".lower()) != "Pass":
                outcome = tests.get(f"{cls}.{method}".lower(), "not run")
                problems.append(f"{ac}: {entry} outcome {outcome}")
    extra = sorted(set(trace) - set(required))
    if problems:
        criterion.failed(*problems)
    else:
        criterion.passed(f"{len(required)} acceptance criteria traced"
                         + (f", {len(manual)} by manual step" if manual else ""))
    if extra:
        criterion.details.append("traced but not in requirements: " + ", ".join(extra))
    return criterion, manual


def delivery_names(changed: list[str], work_item: Path) -> set[str]:
    """Lower-case names that tie a test failure to this delivery: changed components and the
    test classes named in the acceptance trace."""
    names: set[str] = set()
    for path in changed:
        name = full_name(path)
        names.add(name.lower())
        names.add(name.split(".")[-1].lower())
    trace = work_item / TRACE_FILE
    if trace.is_file():
        for entries in parse_trace(trace.read_text(encoding="utf-8")).values():
            for entry in entries:
                ref = TEST_REF.match(entry)
                if ref:
                    names.add(ref.group(1).lower())
    return {name for name in names if name}


def is_delivery_failure(test: dict[str, Any], names: set[str]) -> bool:
    """A failing test belongs to the delivery when its class is part of the delivery, or when
    its message or stack trace names a changed component (a regression the change caused)."""
    test_class = str((test.get("ApexClass") or {}).get("Name") or str(test.get("FullName", "")).split(".")[0]).lower()
    if test_class in names:
        return True
    text = f"{test.get('Message') or ''} {test.get('StackTrace') or ''}".lower()
    return any(re.search(rf"\b{re.escape(name)}\b", text) for name in names)


def run_tests(runner: Runner, root: Path, org: str, names: set[str] | None = None
              ) -> tuple[Criterion, dict[str, str], dict[str, float], list[str]]:
    """Returns the criterion, outcomes, coverage and the blockers: failing tests outside the
    delivery, which the agent does not fix (a person fixes the org first)."""
    criterion = Criterion("SC2", "All Salesforce tests are green")
    names = names or set()
    result = sf_json(runner, root, ["sf", "apex", "run", "test", "--test-level", "RunLocalTests",
                                    "--code-coverage", "--wait", str(TEST_WAIT_MINUTES), "--target-org", org])
    summary = result.get("summary") or {}
    outcomes: dict[str, str] = {}
    for test in result.get("tests") or []:
        name = test.get("FullName") or f"{(test.get('ApexClass') or {}).get('Name')}.{test.get('MethodName')}"
        outcomes[str(name).lower()] = str(test.get("Outcome"))
    coverage: dict[str, float] = {}
    for item in ((result.get("coverage") or {}).get("coverage") or []):
        try:
            coverage[str(item.get("name"))] = float(item.get("coveredPercent"))
        except (TypeError, ValueError):
            continue
    delivery_failed: list[str] = []
    blockers: list[str] = []
    for test in result.get("tests") or []:
        if str(test.get("Outcome")) in ("Pass", "Skip"):
            continue
        name = str(test.get("FullName") or f"{(test.get('ApexClass') or {}).get('Name')}.{test.get('MethodName')}")
        (delivery_failed if is_delivery_failure(test, names) else blockers).append(name)
    problems = []
    if str(summary.get("outcome", "")).lower() not in ("passed", "pass"):
        problems.append(f"Apex test outcome {summary.get('outcome')!r}")
    if delivery_failed:
        problems.append(f"{len(delivery_failed)} delivery test(s) not passing; fix them in this delivery: "
                        + ", ".join(sorted(delivery_failed)[:15]))
    if blockers:
        problems.append(f"BLOCKER: {len(blockers)} test(s) outside this delivery fail and do not name a "
                        "changed component; the agent does not fix them, a person fixes the org first: "
                        + ", ".join(sorted(blockers)[:15]))
    if not outcomes:
        problems.append("the Apex test run returned no test results")
    package = json.loads((root / "package.json").read_text(encoding="utf-8")) if (root / "package.json").is_file() else {}
    lwc_note = "no test:unit script, LWC Jest skipped"
    if "test:unit" in (package.get("scripts") or {}):
        code, _, err = runner(["npm", "run", "--silent", "test:unit"], root)
        if code != 0:
            problems.append(f"npm run test:unit exited {code}: {err.strip()[:200]}")
        lwc_note = "LWC Jest passed" if code == 0 else lwc_note
    if problems:
        criterion.failed(*problems)
    else:
        criterion.passed(f"{summary.get('testsRan', len(outcomes))} Apex tests passed in {org}", lwc_note)
    return criterion, outcomes, coverage, sorted(blockers)


def check_coverage(changed: list[str], classes: dict[str, str], coverage: dict[str, float]) -> Criterion:
    criterion = Criterion("SC3", f"Coverage >= {COVERAGE_MIN:g}% for every changed class and trigger")
    names = []
    for path in changed:
        match = APEX_SOURCE.search("/" + path)
        if not match:
            continue
        kind, name = match.group(1), match.group(2)
        if kind == "classes" and is_test_class(classes.get(name, "")):
            continue
        if name not in names:
            names.append(name)
    if not names:
        return criterion.passed("no non-test Apex class or trigger changed")
    low = []
    for name in names:
        percent = coverage.get(name)
        if percent is None:
            low.append(f"{name}: no coverage reported")
        elif percent < COVERAGE_MIN:
            low.append(f"{name}: {percent:g}%")
    if low:
        return criterion.failed(*low)
    return criterion.passed(", ".join(f"{name} {coverage[name]:g}%" for name in names))


def component_key(path: str) -> str:
    """Normalise a source path so a component and its -meta.xml compare equal."""
    path = path.replace("\\", "/")
    if path.endswith("-meta.xml"):
        path = path[: -len("-meta.xml")]
    parts = path.split("/")
    for bundle in BUNDLE_DIRS:
        if bundle in parts[:-1]:
            index = parts.index(bundle)
            if index + 1 < len(parts) - 1:
                return "/".join(parts[: index + 2])  # the whole bundle is one component
    return path


def full_name(path: str) -> str:
    """Best-effort metadata fullName for a source path (fallback when the job has no file list)."""
    parts = component_key(path).split("/")
    if "objects" in parts:
        rest = parts[parts.index("objects") + 1:]
        if len(rest) >= 3:
            return f"{rest[0]}.{rest[2].split('.')[0]}"
        if rest:
            return rest[0].split(".")[0]
    return parts[-1].split(".")[0]


def check_deploy(runner: Runner, root: Path, org: str, job_id: str | None, changed: list[str],
                 head_time: datetime) -> Criterion:
    criterion = Criterion("SC4", "Metadata deployed without missing components")
    if not job_id:
        return criterion.failed("no deploy job ID: pass --deploy-job-id or write it to deploy-job-id in the work item")
    if not re.fullmatch(r"0Af[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?", job_id):
        return criterion.failed(f"{job_id!r} is not a deploy job ID")
    result = sf_json(runner, root, ["sf", "project", "deploy", "report", "--job-id", job_id, "--target-org", org])
    problems = []
    if result.get("status") != "Succeeded" or result.get("success") is False:
        problems.append(f"deploy {job_id} status {result.get('status')!r}")
    if result.get("checkOnly") is True:
        problems.append(f"deploy {job_id} is a validation (check-only), not a deploy")
    completed = parse_time(result.get("completedDate"))
    if completed is None:
        problems.append(f"deploy {job_id} has no completedDate")
    elif completed < head_time:
        problems.append(f"deploy {job_id} completed {completed.isoformat()} before the last source commit {head_time.isoformat()}")
    files = result.get("files") or []
    if files:
        deployed = set()
        for item in files:
            file_path = str(item.get("filePath") or "")
            if not file_path or str(item.get("state", "")).lower() == "failed":
                continue
            path = Path(file_path)
            try:
                file_path = path.resolve().relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
            except ValueError:
                continue
            deployed.add(component_key(file_path))
        missing = [p for p in changed if component_key(p) not in deployed]
        how = "by file path"
    else:
        successes = ((result.get("details") or {}).get("componentSuccesses") or [])
        if isinstance(successes, dict):
            successes = [successes]
        names = {str(item.get("fullName")) for item in successes}
        missing = [p for p in changed if full_name(p) not in names]
        how = "by component name (the job has no file list)"
    if missing:
        problems.append(f"{len(missing)} changed file(s) not in deploy {job_id}: " + ", ".join(missing[:15]))
    if problems:
        return criterion.failed(*problems)
    return criterion.passed(f"deploy {job_id} Succeeded in {org}; {len(changed)} changed file(s) matched {how}")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── main ───────────────────────────────────────────────────────────────────────────────

def check(work_item: Path, *, root: Path = ROOT, base: str = "main", org: str | None = None,
          deploy_job_id: str | None = None, runner: Runner = run_command) -> dict[str, Any]:
    root = root.resolve()
    work_item = (root / work_item).resolve() if not work_item.is_absolute() else work_item.resolve()
    try:
        work_item.relative_to(root / "work-items")
    except ValueError as exc:
        raise CheckError("--work-item must be a folder under work-items/") from exc
    if not work_item.is_dir():
        raise CheckError(f"work item folder {work_item} does not exist")
    alias = agent_org(root, org)
    dirs = package_dirs(root)
    if deploy_job_id is None and (work_item / "deploy-job-id").is_file():
        deploy_job_id = (work_item / "deploy-job-id").read_text(encoding="utf-8").strip() or None

    sc5, branch, head = check_clean(runner, root, work_item)
    # The deploy must follow the last commit that changed package source. Later commits (for
    # example the one that records deploy-job-id) do not change what was deployed.
    source_time = git(runner, root, "log", "-1", "--format=%ct", f"{base}..HEAD", "--", *dirs).strip()
    head_time = datetime.fromtimestamp(int(source_time or git(runner, root, "show", "-s", "--format=%ct", "HEAD").strip()), timezone.utc)
    changed = changed_source_files(runner, root, base, dirs)
    classes = apex_methods(root, dirs)
    sc2, outcomes, coverage, blockers = run_tests(runner, root, alias, delivery_names(changed, work_item))
    sc1, manual = check_trace(root, work_item, outcomes, classes)
    sc3 = check_coverage(changed, classes, coverage)
    sc4 = check_deploy(runner, root, alias, deploy_job_id, changed, head_time)
    criteria = [sc1, sc2, sc3, sc4, sc5]
    return {
        "schemaVersion": 1,
        "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workItem": work_item.relative_to(root).as_posix(),
        "branch": branch,
        "base": base,
        "commit": head,
        "agentOrg": alias,
        "deployJobId": deploy_job_id,
        "changedSourceFiles": changed,
        # BLOCKED: failures outside the delivery; the run stops for a person (owner rule
        # 2026-11-16). FAIL: the agent repairs within its attempt budget.
        "status": "BLOCKED" if blockers else "PASS" if all(c.status == "PASS" for c in criteria) else "FAIL",
        "blockers": blockers,
        "criteria": [{"id": c.id, "title": c.title, "status": c.status, "details": c.details} for c in criteria],
        "manualSteps": manual,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work-item", required=True, type=Path, help="work-items/<id>-<slug>")
    parser.add_argument("--base", default="main", help="branch the feature branch is compared against")
    parser.add_argument("--org", help="agent org alias (default: salesforce.agentOrg)")
    parser.add_argument("--deploy-job-id", help="deploy job ID (default: <work-item>/deploy-job-id)")
    parser.add_argument("--output", type=Path, help=f"result file (default: <work-item>/{RESULT_FILE})")
    args = parser.parse_args(argv)
    try:
        report = check(args.work_item, base=args.base, org=args.org, deploy_job_id=args.deploy_job_id)
    except CheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    output = args.output or (ROOT / report["workItem"] / RESULT_FILE)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for item in report["criteria"]:
        print(f"{item['status']}: {item['id']} {item['title']}")
        for detail in item["details"]:
            print(f"    {detail}")
    print(f"{report['status']}: delivery check for {report['commit'][:12]} -> {output}")
    return {"PASS": 0, "BLOCKED": 3}.get(report["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
