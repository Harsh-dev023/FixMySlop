# FixMySlop — User Guide

FixMySlop finds AI slop deterministically and hands the fixes to your coding agent.
The [README](README.md) has the full reference; this is the short tour.

## 1. Scan

```bash
fixmyslop scan                         # whole project
fixmyslop scan src/components          # a folder
fixmyslop scan --changed               # files changed vs main + uncommitted work
fixmyslop scan --only ui --only a11y   # just UI and accessibility rules
fixmyslop scan -s report.html          # shareable HTML report
```

Each finding has a severity, a stable rule id (e.g. `ui/ai-gradient`) and a concrete fix.
`fixmyslop rules <id>` explains any rule.

## 2. Fix

```bash
fixmyslop fix --safe-only     # deterministic fixes that can't change behavior
fixmyslop fix                 # safe fixes, then Claude Code / Codex / Gemini fixes the rest, then re-scan
fixmyslop fix --dry-run       # print the fix brief instead of running an agent
```

No agent CLI installed? `fixmyslop fix --agent llm` uses any OpenAI-compatible endpoint
(Ollama by default; set `--base-url`, `--api-key`, `--model` for a cloud model). Every
LLM rewrite is validated (no truncation, no elided code, must parse) and shown as a diff
before it's applied.

## 3. Keep it clean

```bash
fixmyslop init --claude      # skill + MCP tool + live hook + CLAUDE.md rules
fixmyslop init --cursor      # Cursor rules + MCP
fixmyslop init --agents      # AGENTS.md for Codex, Gemini, Jules, Copilot agents
fixmyslop init --github      # PR annotations, fail on HIGH
fixmyslop init --pre-commit  # block slop at commit time
```

## 4. Tune

Edit `.fixmyslop.yml`:

```yaml
exclude: ["legacy/**"]
disable: ["ui/default-font"]
severity: {"slop/console-log": "INFO"}
fail_on: high
```

False positive? Add `fixmyslop-ignore[<rule-id>] <reason>` in a comment on the line (or the line above).

## Desktop app

`fixmyslop gui` (install with `pip install "fixmyslop[gui]"`). Rules always run; tick
"LLM review" for an optional model pass if you have Ollama or another backend running.
