#!/usr/bin/env node
// Thin launcher for the Python REST review facade (salesforce_review_server.py).
//
// Kept (plan-2026-08-09 F-3 deviation, reviewed): .vscode/mcp.json cannot express a
// cross-platform Python interpreter path, and a bare "python" command would run
// whatever interpreter is first on PATH - typically one without the admitted
// `requests` dependency. This launcher resolves the interpreter with a fixed ladder
// (env override -> repo .venv -> py -3 -> python3 -> python,
// probed for the real dependency) and keeps the pre-contact walls that must hold
// before ANY process talks to an org. The old vendor-MCP child and the .mjs review
// server are gone from this launch path; F-4 deletes them from the tree.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, "..");
const CONFIG_PATH = resolve(REPO_ROOT, "config", "harness.local.json");
const REVIEW_SERVER = resolve(SCRIPT_DIR, "salesforce_review_server.py");
const PROBE_TIMEOUT_MS = 15_000;

function fail(message) {
  process.stderr.write(`Salesforce MCP startup blocked: ${message}\n`);
  process.exit(2);
}

const ALIAS_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; ) {
    const key = argv[index];
    // Both MCP entries (.vscode/mcp.json, .github/mcp.json) read the one agent org from the
    // ignored local policy (salesforce.agentOrg); Copilot CLI has no input prompts.
    if (key === "--org-from-config") {
      parsed.orgFromConfig = true;
      index += 1;
      continue;
    }
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      fail("expected --mode review (--org <alias> | --org-from-config)");
    }
    parsed[key.slice(2)] = value;
    index += 2;
  }
  return parsed;
}

const { mode, org: argumentOrg, orgFromConfig } = parseArgs(process.argv.slice(2));
// This launcher exposes the structured review facade only. Developer writes deliberately use
// direct sf/sfdx commands, so no write-mode MCP process is launched from here.
if (mode !== "review") {
  fail(`unsupported mode '${mode ?? ""}'; this MCP launcher supports review mode only`);
}
// The bounded read-only server proves the live host, Org ID and IsSandbox before tools.
// Alias naming does not classify the environment or grant permissions.
if (argumentOrg && orgFromConfig) {
  fail("pass either --org <alias> or --org-from-config, not both");
}
if (!argumentOrg && !orgFromConfig) {
  fail("the org alias is missing");
}

let config;
if (!existsSync(CONFIG_PATH)) {
  fail(
    "config/harness.local.json is missing; create the ignored local policy from " +
      "config/harness.example.json before starting Salesforce MCP",
  );
}
try {
  config = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
} catch (error) {
  fail(`cannot read valid ${CONFIG_PATH}: ${error.message}`);
}

const org = argumentOrg ?? config?.salesforce?.agentOrg;
if (!org) {
  fail("salesforce.agentOrg is not set in config/harness.local.json; name the configured org the agents work against");
}
if (typeof org !== "string" || !ALIAS_PATTERN.test(org)) {
  fail("the org alias is not a valid Salesforce CLI alias");
}

const matches = config?.salesforce?.orgs?.filter((candidate) => candidate?.alias === org) ?? [];
if (matches.length > 1) fail("duplicate configured alias");
const entry = matches[0];
if (orgFromConfig && !entry) {
  fail("salesforce.agentOrg must name a salesforce.orgs entry so its environment is classified");
}
const environment = entry ? String(entry.environment) : null;
if (entry && !new Set(["dev", "uat", "stage", "prod", "development", "production"]).has(environment)) {
  fail(`alias '${org}' requires an explicit dev/uat/stage/prod environment (legacy qa has no automatic mapping)`);
}
if (config?.salesforce?.review?.enabled !== true) {
  fail("Salesforce org review is disabled in local configuration");
}

process.stderr.write("Salesforce MCP startup: resolving the Python runtime\n");

// Interpreter ladder: the probe imports the
// facade's real third-party dependency, so a missing `requests` surfaces here as one
// actionable message instead of a dead server.
function interpreterCandidates() {
  const candidates = [];
  if (process.env.SALESFORCE_MCP_PYTHON) candidates.push([process.env.SALESFORCE_MCP_PYTHON]);
  candidates.push(
    [join(REPO_ROOT, ".venv", "bin", "python")],
    [join(REPO_ROOT, ".venv", "Scripts", "python.exe")],
    ["py", "-3"],
    ["python3"],
    ["python"],
  );
  return candidates;
}

let python = null;
for (const candidate of interpreterCandidates()) {
  const probe = spawnSync(candidate[0], [...candidate.slice(1), "-c", "import requests"], {
    timeout: PROBE_TIMEOUT_MS,
    stdio: "ignore",
  });
  if (!probe.error && probe.status === 0) {
    python = candidate;
    break;
  }
}
if (!python) {
  fail(
    "no Python interpreter with the 'requests' dependency was found (tried " +
      "SALESFORCE_MCP_PYTHON, the repo .venv, py -3, python3, python); run: " +
      "python -m pip install --require-hashes -r requirements-dev.lock",
  );
}

process.stderr.write(
  "Salesforce MCP startup: launching the review facade; CLI authorization and live org validation run before tool discovery\n",
);

const child = spawn(python[0], [...python.slice(1), REVIEW_SERVER, "--org", org], {
  cwd: REPO_ROOT,
  // PYTHONUTF8 forces UTF-8 std streams on Windows, where the default encoding is a
  // legacy code page and the MCP spec mandates UTF-8 frames.
  env: { ...process.env, PYTHONUTF8: "1" },
  stdio: "inherit",
  shell: false,
});

child.on("error", (error) => fail(`failed to start the Python review facade: ${error.message}`));
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
