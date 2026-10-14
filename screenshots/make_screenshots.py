"""Regenerate README screenshots: python screenshots/make_screenshots.py

- screenshots/cli.svg      terminal output of `fixmyslop scan examples/slop-app`
- <tmp>/fixmyslop-report.html  interactive report (render it with a headless browser for report.png)
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402

from fixmyslop.cli import cli_output  # noqa: E402
from fixmyslop.cli.cli_app import run_scan  # noqa: E402
from fixmyslop.core.report_builder import ReportBuilder, relative_path  # noqa: E402
from fixmyslop.macros import APP_NAME, APP_VERSION  # noqa: E402

OUT = Path(__file__).resolve().parent


def main():
    report, _ = run_scan([str(ROOT / "examples" / "slop-app")], use_static=False)
    console = Console(record=True, width=92, force_terminal=True, color_system="truecolor")
    cli_output.console = console
    console.print("[dim]$[/dim] fixmyslop scan examples/slop-app\n")
    cli_output.print_banner(APP_NAME, APP_VERSION)
    cli_output.print_slop_report(report, lambda p: relative_path(report, p), limit=14,
                                 fixable_count=3, agent_hint="Claude Code", target="examples/slop-app")
    console.save_svg(str(OUT / "cli.svg"), title="fixmyslop scan")
    html_path = Path(tempfile.gettempdir()) / "fixmyslop-report.html"
    html_path.write_text(ReportBuilder().export(report, "html"), encoding="utf-8")
    print("wrote", OUT / "cli.svg", "and", html_path)


if __name__ == "__main__":
    main()
