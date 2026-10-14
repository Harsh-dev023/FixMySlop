#!/usr/bin/env node
// Thin launcher: runs the FixMySlop Python CLI of the SAME version as this npm package —
// a matching local install if there is one, otherwise via uvx or pipx.
"use strict";
const { spawnSync } = require("node:child_process");
const { version } = require("../package.json");

const args = process.argv.slice(2);
const VERSION_PROBE =
  "import importlib.metadata as m, sys; print(m.version('fixmyslop'))";

function ok(cmd, probe) {
  const r = spawnSync(cmd, probe, { encoding: "utf8" });
  return r.status === 0 ? (r.stdout || "").trim() || "ok" : null;
}

function run(cmd, cmdArgs) {
  const r = spawnSync(cmd, cmdArgs, { stdio: "inherit" });
  if (r.error) return;
  process.exit(r.status ?? 1);
}

let outdated = null;
for (const python of ["python3", "python", "py"]) {
  const installed = ok(python, ["-c", VERSION_PROBE]);
  if (installed === version) run(python, ["-m", "fixmyslop", ...args]);
  if (installed && !outdated) outdated = { python, installed };
}
if (ok("uvx", ["--version"])) run("uvx", [`fixmyslop@${version}`, ...args]);
if (ok("pipx", ["--version"])) run("pipx", ["run", "--spec", `fixmyslop==${version}`, "fixmyslop", ...args]);

if (outdated) {
  console.error(
    `Found fixmyslop ${outdated.installed}, but this launcher runs ${version}. Upgrade with:\n` +
    `  ${outdated.python} -m pip install -U "fixmyslop==${version}"\n` +
    "or install uv (https://docs.astral.sh/uv/) so npx can fetch the right version automatically."
  );
} else {
  console.error(
    "FixMySlop needs Python 3.10+ and one of these:\n" +
    "  uv     https://docs.astral.sh/uv/   (then `npx fixmyslop` just works)\n" +
    "  pipx   https://pipx.pypa.io/\n" +
    `  or:    pip install "fixmyslop==${version}"`
  );
}
process.exit(127);
