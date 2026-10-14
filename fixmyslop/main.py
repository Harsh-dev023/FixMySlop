"""
FixMySlop entry point.
- No args → launch GUI (falls back to CLI help when PyQt5 isn't installed)
- Any args → CLI (`fixmyslop gui` also launches the GUI)
"""
import sys


def main():
    """Launch GUI if no args given, otherwise run CLI."""
    from fixmyslop.cli.cli_app import app

    if len(sys.argv) > 1:
        app()
        return
    try:
        from fixmyslop.ui.app import launch
    except ImportError:
        sys.argv.append("--help")
        app()
        return
    launch()


if __name__ == "__main__":
    main()
