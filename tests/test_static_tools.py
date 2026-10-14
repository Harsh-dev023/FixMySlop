"""Tests for core/static_tools.py."""
from fixmyslop.core.static_tools import StaticToolRunner


class TestStaticToolRunner:
    """Tests for the StaticToolRunner class."""

    def test_init_detects_tools(self):
        """Should detect whether ruff/bandit/semgrep are installed."""
        runner = StaticToolRunner()
        assert isinstance(runner._available, dict)
        assert "ruff" in runner._available
        assert "bandit" in runner._available
        assert "semgrep" in runner._available

    def test_run_on_non_python_file(self, tmp_path):
        """Should return empty list for non-Python files with Python-only tools."""
        js_file = tmp_path / "app.js"
        js_file.write_text('console.log("hello");\n', encoding="utf-8")

        runner = StaticToolRunner()
        # Force semgrep to not available for this test
        runner._available["semgrep"] = False
        issues = runner.run(js_file, 'console.log("hello");\n', "javascript")
        assert isinstance(issues, list)

    def test_ruff_severity_mapping(self):
        """Should map ruff codes to appropriate severity levels."""
        assert StaticToolRunner._ruff_severity("S101") == "HIGH"  # Security
        assert StaticToolRunner._ruff_severity("F821") == "HIGH"  # Undefined name
        assert StaticToolRunner._ruff_severity("B006") == "MEDIUM"  # Bugbear
        assert StaticToolRunner._ruff_severity("E501") == "LOW"  # Style
        assert StaticToolRunner._ruff_severity("F401") == "LOW"  # Unused import
        assert StaticToolRunner._ruff_severity("D100") == "LOW"  # Default

    def test_get_tool_versions(self):
        """Should return version strings or None for each tool."""
        runner = StaticToolRunner()
        versions = runner.get_tool_versions()
        assert isinstance(versions, dict)
        assert "ruff" in versions


def test_ruff_severity_does_not_confuse_prefixes():
    """SIM (simplify) is not S (security); BLE is not B (bugbear)."""
    assert StaticToolRunner._ruff_severity("SIM103") == "LOW"
    assert StaticToolRunner._ruff_severity("BLE001") == "LOW"
    assert StaticToolRunner._ruff_severity("S608") == "HIGH"
    assert StaticToolRunner._ruff_severity("B904") == "MEDIUM"


def test_ruff_rules_pinned_unless_project_selects(tmp_path):
    """Results must not depend on ruff's ever-changing default rule set."""
    from fixmyslop.core.static_tools import project_selects_ruff_rules
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    assert not project_selects_ruff_rules(tmp_path)
    (tmp_path / "ruff.toml").write_text('[lint]\nselect = ["ALL"]\n', encoding="utf-8")
    assert project_selects_ruff_rules(tmp_path)
