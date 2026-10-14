#!/usr/bin/env node
// Thin launcher: runs the FixMySlop Python CLI of the same version via uvx or pipx,
// or an existing local install. No Python packaging knowledge required.
"use strict";
const { spawnSync } = require("node:child_process");
const { version } = require("../package.json");

const args = process.argv.slice(2);

function has(cmd, probe = ["--version"]) {
  const r = spawnSync(cmd, probe, { stdio: "ignore" });
  return r.status === 0;
}

function run(cmd, cmdArgs) {
  const r = spawnSync(cmd, cmdArgs, { stdio: "inherit" });
  if (r.error) return null;
  process.exit(r.status ?? 1);
}

const python = ["python3", "python", "py"].find((p) => has(p, ["-c", "import fixmyslop"]));

if (python) run(python, ["-m", "fixmyslop", ...args]);
if (has("uvx")) run("uvx", [`fixmyslop@${version}`, ...args]);
if (has("pipx")) run("pipx", ["run", "--spec", `fixmyslop==${version}`, "fixmyslop", ...args]);

console.error(
  "FixMySlop needs Python 3.10+ and one of these:\n" +
  "  uv     https://docs.astral.sh/uv/   (then `npx fixmyslop` just works)\n" +
  "  pipx   https://pipx.pypa.io/\n" +
  "  or:    pip install fixmyslop"
);
process.exit(127);
