"""Vercel function: GET /r/<owner>/<repo> (rewritten to /api/report?repo=owner/repo)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from fms_site import make_handler, report_response  # noqa: E402

handler = make_handler(report_response)   # Vercel looks for a class named `handler`
