"""Tests for the agent-facing workflow: safe fixes, brief, SARIF, hook, MCP server, init."""
import io
import json
from pathlib import Path

from typer.testing import CliRunner

from cli.cli_app import app, run_scan
from core.mcp_server import serve
from core.report_builder import ReportBuilder
from core.slop.brief import build_fix_brief, upsert_guide, GUIDE_START
from core.slop.engine import SlopEngine, slop_score, grade
from core.slop.fixers import apply_safe_fixes

runner = CliRunner()

SLOPPY_TSX = (
    'export default function Hero() {\n'
    '  // Initialize the count\n'
    '  const count = 0;\n'
    '  return (\n'
    '    <div className="bg-gradient-to-r from-purple-600 to-pink-500">\n'
    '      <h1>Revolutionize your workflow</h1>\n'
    '      <a href="#">Learn more</a>\n'
    '    </div>\n'
    '  );\n'
    '}\n'
)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "18"}}', encoding="utf-8")
    (tmp_path / "Hero.tsx").write_text(SLOPPY_TSX, encoding="utf-8")
    (tmp_path / "util.py").write_text("try:\n    x = 1\nexcept:\n    raise\n", encoding="utf-8")
    return tmp_path


def test_run_scan_reports_and_scores(tmp_path):
    report, _ = run_scan([str(_project(tmp_path))], use_static=False)
    rules = {i.rule_id for i in report.issues}
    assert {"ui/ai-gradient", "ui/marketing-slop", "a11y/dead-link", "slop/bare-except"} <= rules
    assert report.grade in "ABCDF" and report.slop_score > 0


def test_safe_fixes_preserve_behavior_and_line_endings(tmp_path):
    project = _project(tmp_path)
    crlf = project / "crlf.py"
    crlf.write_bytes(b"try:\r\n    x = 1\r\nexcept:\r\n    raise\r\n")
    report, _ = run_scan([str(project)], use_static=False)
    applied = apply_safe_fixes(report.issues)
    assert applied
    assert "except Exception:" in (project / "util.py").read_text(encoding="utf-8")
    assert b"except Exception:\r\n" in crlf.read_bytes()
    assert "Initialize the count" not in (project / "Hero.tsx").read_text(encoding="utf-8")


def test_brief_lists_issues_with_fix_hints(tmp_path):
    report, _ = run_scan([str(_project(tmp_path))], use_static=False)
    brief = build_fix_brief(report.issues, lambda p: Path(p).name)
    assert "## UI direction" in brief
    assert "Hero.tsx" in brief and "ui/ai-gradient" in brief
    assert "How to fix each rule" in brief


def test_sarif_export(tmp_path):
    report, _ = run_scan([str(_project(tmp_path))], use_static=False)
    sarif = json.loads(ReportBuilder().export(report, "sarif"))
    run = sarif["runs"][0]
    assert sarif["version"] == "2.1.0"
    assert run["results"] and run["tool"]["driver"]["rules"]
    assert all(not r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"].startswith("/")
               for r in run["results"])


def test_score_and_grade():
    assert slop_score([], 1000) == 0.0
    assert grade(0) == "A" and grade(90) == "F"


def test_scan_cli_formats_and_fail_on(tmp_path):
    project = _project(tmp_path)
    result = runner.invoke(app, ["scan", str(project), "-f", "compact", "--no-static", "--fail-on", "medium"])
    assert result.exit_code == 1
    assert "ui/ai-gradient" in result.stdout
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert runner.invoke(app, ["scan", str(clean), "--no-static", "--fail-on", "low"]).exit_code == 0


def test_hook_blocks_only_on_edited_lines(tmp_path):
    project = _project(tmp_path)
    payload = {"tool_name": "Edit", "cwd": str(project),
               "tool_input": {"file_path": str(project / "Hero.tsx"),
                              "new_string": "      <h1>Revolutionize your workflow</h1>"}}
    result = runner.invoke(app, ["hook"], input=json.dumps(payload))
    assert result.exit_code == 2
    assert "ui/marketing-slop" in result.output
    assert "ui/ai-gradient" not in result.output  # not part of this edit

    payload["tool_input"]["new_string"] = "  const count = 0;"
    assert runner.invoke(app, ["hook"], input=json.dumps(payload)).exit_code == 0


def test_mcp_server_roundtrip(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "check_slop", "arguments": {"paths": ["Hero.tsx"]}}},
        {"jsonrpc": "2.0", "id": 4, "method": "nope"},
    ]
    out = io.StringIO()
    serve(io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n"), out)
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["id"] for r in responses] == [1, 2, 3, 4]
    assert {t["name"] for t in responses[1]["result"]["tools"]} >= {"check_slop", "fix_safe"}
    assert "ui/ai-gradient" in responses[2]["result"]["content"][0]["text"]
    assert responses[3]["error"]["code"] == -32601


def test_init_is_idempotent(tmp_path):
    for _ in range(2):
        result = runner.invoke(app, ["init", str(tmp_path), "--claude", "--cursor", "--agents"])
        assert result.exit_code == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert len(settings["hooks"]["PostToolUse"]) == 1
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8").count(GUIDE_START) == 1
    assert (tmp_path / ".claude" / "skills" / "fixmyslop" / "SKILL.md").exists()
    assert "fixmyslop" in json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert (tmp_path / ".fixmyslop.yml").exists()


def test_upsert_guide_preserves_existing_content(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text("# My rules\n\nBe nice.\n", encoding="utf-8")
    upsert_guide(path)
    upsert_guide(path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# My rules") and text.count(GUIDE_START) == 1


def test_rules_command():
    result = runner.invoke(app, ["rules", "ui/ai-gradient"])
    assert result.exit_code == 0 and "Fix:" in result.stdout


def test_engine_is_fast(tmp_path):
    """Hundreds of files should scan in well under a few seconds."""
    import time
    for n in range(200):
        (tmp_path / f"C{n}.tsx").write_text(SLOPPY_TSX, encoding="utf-8")
    engine = SlopEngine(tmp_path)
    start = time.time()
    for path in tmp_path.glob("*.tsx"):
        engine.check_file(path, SLOPPY_TSX)
    assert time.time() - start < 5
