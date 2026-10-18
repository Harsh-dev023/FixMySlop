"""Vercel function: GET /badge/<owner>/<repo> (rewritten to /api/badge?repo=owner/repo)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from fms_site import badge_response, make_handler  # noqa: E402

handler = make_handler(badge_response)   # Vercel looks for a class named `handler`
