#!/usr/bin/env node
// Run scripts/check_delivery.py with whatever Python this machine has (plan 05).
//
//   node scripts/check-delivery.mjs --work-item work-items/<id>-<slug> [check_delivery.py options]
//
// The same command works on macOS, Linux and Windows: `python3` does not exist on a standard
// Windows install, and `python` may be missing on macOS. The check needs only the standard
// library, so any Python 3.9+ works. Exit codes are those of check_delivery.py
// (0 PASS, 1 FAIL, 2 cannot run, 3 BLOCKED); 2 also when no Python is found.
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const script = join(root, "scripts", "check_delivery.py");
const candidates =
  process.platform === "win32"
    ? [["py", "-3"], ["python"], ["python3"]]
    : [["python3"], ["python"]];

for (const [command, ...prefix] of candidates) {
  const result = spawnSync(command, [...prefix, script, ...process.argv.slice(2)], {
    cwd: root,
    stdio: "inherit",
  });
  if (result.error && result.error.code === "ENOENT") {
    continue;
  }
  if (result.error) {
    console.error(`check-delivery: ${command} failed: ${result.error.message}`);
    process.exit(2);
  }
  process.exit(result.status ?? 2);
}
console.error("check-delivery: no Python 3 interpreter found (tried py -3, python, python3)");
process.exit(2);
