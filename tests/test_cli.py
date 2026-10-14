"""Tests for cli/cli_app.py."""
from typer.testing import CliRunner
from fixmyslop.cli.cli_app import app
from fixmyslop.macros import APP_VERSION

runner = CliRunner()


class TestCLI:
    """Tests for the FixMySlop CLI commands."""

    def test_version_command(self):
        """'version' command should print the app version."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert APP_VERSION in result.stdout

    def test_scan_nonexistent_path(self):
        """'scan' should fail gracefully for a non-existent path."""
        result = runner.invoke(app, ["scan", "/nonexistent/path/xyz"])
        assert result.exit_code != 0


def test_npm_launcher_version_matches():
    """The npx launcher pins the Python package version, so they must stay in sync."""
    import json
    from pathlib import Path
    package = json.loads((Path(__file__).parent.parent / "npm" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == APP_VERSION
