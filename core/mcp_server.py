"""
Minimal MCP (Model Context Protocol) server over stdio — no extra dependencies.

Lets Claude Code, Cursor, Codex, Windsurf, etc. call FixMySlop as a native tool:

    claude mcp add fixmyslop -- fixmyslop mcp

Tools:
    check_slop    scan files/folders, return compact findings + fix hints
    explain_rule  why a rule exists and how to fix it
    fix_safe      apply deterministic, behavior-preserving fixes
    slop_guide    the anti-slop rules to follow while writing code
"""
import json
import sys
from pathlib import Path
from typing import Any, Optional

from macros import APP_NAME, APP_VERSION, SEVERITY_RANK

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "check_slop",
        "description": (
            "Deterministically scan code for AI slop in well under a second: UI tells (purple gradients, gradient "
            "text, emoji icons, generic marketing copy, fake stats), accessibility bugs, elided code "
            "('... existing code ...'), placeholder implementations, swallowed exceptions, hallucinated or "
            "undeclared packages, leaked secrets, SQL injection. Call it on files you just wrote or edited, "
            "and before telling the user a task is done. Returns one line per issue plus how to fix each rule."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"},
                          "description": "Files or folders to scan. Default: the whole project."},
                "changed_only": {"type": "boolean",
                                 "description": "Only files changed vs the base branch plus uncommitted work."},
                "min_severity": {"type": "string", "enum": ["critical", "high", "medium", "low"],
                                 "description": "Hide issues below this severity (default low)."},
                "only": {"type": "array", "items": {"type": "string"},
                         "description": "Rule groups/ids to run: ui, a11y, slop, sec, deps, or ids like ui/ai-gradient."},
            },
        },
    },
    {
        "name": "explain_rule",
        "description": "Explain a FixMySlop rule: what it catches, why it matters, and exactly how to fix it.",
        "inputSchema": {
            "type": "object",
            "properties": {"rule_id": {"type": "string", "description": "e.g. ui/ai-gradient"}},
            "required": ["rule_id"],
        },
    },
    {
        "name": "fix_safe",
        "description": (
            "Apply FixMySlop's deterministic, behavior-preserving fixes (delete narrating comments, "
            "`except:` → `except Exception:`, remove debugger statements / console.log in UI code). "
            "Returns what changed and what still needs a manual fix."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
        },
    },
    {
        "name": "slop_guide",
        "description": (
            "Return the anti-slop rules for writing UI and code (design, copy, accessibility, error handling, "
            "dependencies, security). Read before generating a UI or a large feature."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _text(text: str, is_error: bool = False) -> dict:
    """MCP tool result wrapper."""
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _scan(paths: Optional[list[str]], changed: bool = False, min_severity: str = "low",
          only: Optional[list[str]] = None):
    """Run the shared CLI pipeline (rules + static tools)."""
    from cli.cli_app import run_scan
    return run_scan(paths or None, changed=changed, only=only, min_severity=min_severity or "low")


def call_tool(name: str, args: dict) -> dict:
    """Dispatch one tool call."""
    from core.report_builder import relative_path
    from core.slop.brief import compact_findings, ANTI_SLOP_GUIDE
    from core.slop import RULES

    if name == "check_slop":
        severity = str(args.get("min_severity") or "low").upper()
        if severity not in SEVERITY_RANK:
            return _text(f"Invalid min_severity '{severity}'.", True)
        report, _ = _scan(args.get("paths"), bool(args.get("changed_only")), severity, args.get("only"))
        header = (f"{len(report.issues)} issue(s), slop score {report.slop_score:g}/100 (grade {report.grade}), "
                  f"{report.scanned_files} file(s), {report.scan_time_s:.2f}s.")
        if not report.issues:
            return _text(header + " Clean.")
        footer = ("\n\nFix these, then call check_slop again. For a genuine false positive add a "
                  "`fixmyslop-ignore[<rule-id>]` comment with a reason.")
        design = (f"\n\nThis project's design system (use it when fixing UI items):\n{report.design_context}"
                  if report.design_context else "")
        return _text(header + "\n" + compact_findings(report.issues, lambda p: relative_path(report, p))
                     + design + footer)

    if name == "explain_rule":
        rule = RULES.get(str(args.get("rule_id", "")))
        if not rule:
            return _text(f"Unknown rule. Known: {', '.join(sorted(RULES))}", True)
        return _text(f"{rule.id} — {rule.title} ({rule.severity}, {rule.category})\n\n"
                     f"Why: {rule.why}\n\nFix: {rule.fix}\n\n"
                     f"Suppress one occurrence: fixmyslop-ignore[{rule.id}] comment with a reason.")

    if name == "fix_safe":
        from core.slop.fixers import apply_safe_fixes
        report, _ = _scan(args.get("paths"))
        applied = apply_safe_fixes(report.issues)
        remaining = [i for i in report.issues if not i.applied]
        lines = [f"Applied {sum(applied.values())} safe fix(es) in {len(applied)} file(s)."]
        lines += [f"- {relative_path(report, path)}: {count}" for path, count in sorted(applied.items())]
        lines.append(f"{len(remaining)} issue(s) need manual fixes — call check_slop to see them.")
        return _text("\n".join(lines))

    if name == "slop_guide":
        return _text(ANTI_SLOP_GUIDE)

    return _text(f"Unknown tool '{name}'", True)


def handle(message: dict) -> Optional[dict]:
    """Handle one JSON-RPC message; returns a response or None for notifications."""
    method = message.get("method")
    msg_id = message.get("id")
    if msg_id is None:
        return None  # notification (e.g. notifications/initialized)

    def ok(result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        return ok({
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": APP_NAME.lower(), "version": APP_VERSION},
            "instructions": (
                "FixMySlop is a fast, deterministic linter for AI-generated slop. Call check_slop on files "
                "you create or edit (especially UI code) and before reporting a task as complete; fix what it "
                "reports. Call slop_guide before building a UI from scratch."
            ),
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            return ok(call_tool(params.get("name", ""), params.get("arguments") or {}))
        except FileNotFoundError as e:
            return ok(_text(str(e), True))
        except Exception as e:  # report tool failures to the model instead of killing the server
            return ok(_text(f"FixMySlop failed: {type(e).__name__}: {e}", True))
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(stdin=None, stdout=None):
    """Run the stdio server loop (newline-delimited JSON-RPC)."""
    if stdin is None:
        for stream, options in ((sys.stdin, {"encoding": "utf-8"}),
                                (sys.stdout, {"encoding": "utf-8", "newline": "\n"})):
            try:  # JSON-RPC is UTF-8 with LF framing; Windows defaults to cp1252 + CRLF
                stream.reconfigure(**options)
            except (AttributeError, ValueError):
                pass
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            response = handle(message) if isinstance(message, dict) else None
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def project_mcp_config() -> dict:
    """The entry agents put in .mcp.json / .cursor/mcp.json."""
    return {"command": "fixmyslop", "args": ["mcp"]}


def write_mcp_json(path: Path) -> str:
    """Add the fixmyslop server to an MCP config file (idempotent)."""
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except ValueError:
            return f"skipped: {path.name} is not valid JSON"
    servers = data.setdefault("mcpServers", {})
    if "fixmyslop" in servers:
        return f"MCP server already in {path.as_posix()}"
    servers["fixmyslop"] = project_mcp_config()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"registered MCP server in {path.as_posix()}"
