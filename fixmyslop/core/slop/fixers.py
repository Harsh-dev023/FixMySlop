"""
Safe, deterministic auto-fixes.

Only fixes that cannot change program behavior live here (deleting a narrating
comment, `except:` → `except Exception:`, removing debugger statements).
Everything else goes to an agent via the fix brief.
"""
import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from fixmyslop.core.issue import Issue
from fixmyslop.utils.logger import get_logger

logger = get_logger(__name__)

DELETE = None  # sentinel returned by a fixer to delete the line

_CONSOLE_LOG_LINE = re.compile(r"^\s*console\.log\((.*)\);?\s*$")
_DEBUGGER_LINE = re.compile(
    r"^\s*(?:debugger\s*;?|breakpoint\(\)|import i?pdb\s*(?:;\s*i?pdb\.set_trace\(\))?|i?pdb\.set_trace\(\))\s*$"
)


def _fix_bare_except(line: str) -> Optional[str]:
    """`except:` → `except Exception:`."""
    return re.sub(r"^(\s*)except\s*:", r"\1except Exception:", line, count=1)


def _fix_delete_comment(line: str) -> Optional[str]:
    """Delete a whole-line comment."""
    stripped = line.strip()
    if stripped.startswith(("#", "//", "/*", "{/*")):
        return DELETE
    return line


def _fix_debugger(line: str) -> Optional[str]:
    """Delete a standalone debugger/breakpoint line."""
    return DELETE if _DEBUGGER_LINE.match(line) else line


def _fix_console_log(line: str) -> Optional[str]:
    """Delete a single-line console.log(...) statement with balanced parentheses."""
    match = _CONSOLE_LOG_LINE.match(line)
    if not match:
        return line
    args = match.group(1)
    if args.count("(") != args.count(")"):
        return line
    return DELETE


FIXERS: dict[str, Callable[[str], Optional[str]]] = {
    "slop/bare-except": _fix_bare_except,
    "slop/narrating-comment": _fix_delete_comment,
    "slop/debugger": _fix_debugger,
    "slop/console-log": _fix_console_log,
}


def fixable(issues: list[Issue]) -> list[Issue]:
    """Issues that have a safe deterministic fix."""
    return [i for i in issues if i.rule_id in FIXERS]


def apply_safe_fixes(issues: list[Issue], dry_run: bool = False) -> dict[str, int]:
    """Apply every safe fix. Returns {file_path: fixes_applied}.

    Files are edited bottom-up so line numbers stay valid. Python files are
    re-parsed after editing; if the result doesn't parse, the file is left untouched.
    """
    by_file: dict[str, list[Issue]] = defaultdict(list)
    for issue in fixable(issues):
        by_file[issue.file_path].append(issue)

    applied: dict[str, int] = {}
    for file_path, file_issues in by_file.items():
        path = Path(file_path)
        try:
            with open(path, encoding="utf-8", newline="") as handle:
                original = handle.read()
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Cannot fix %s: %s", path, e)
            continue
        lines = original.splitlines(keepends=True)
        count = 0
        done_lines: set[int] = set()
        for issue in sorted(file_issues, key=lambda i: i.line_start, reverse=True):
            index = issue.line_start - 1
            if index in done_lines or not 0 <= index < len(lines):
                continue
            raw = lines[index]
            ending = raw[len(raw.rstrip("\r\n")):]
            result = FIXERS[issue.rule_id](raw.rstrip("\r\n"))
            if result is DELETE:
                del lines[index]
            elif result != raw.rstrip("\r\n"):
                lines[index] = result + ending
            else:
                continue
            done_lines.add(index)
            issue.applied = True
            count += 1
        if not count:
            continue
        updated = "".join(lines)
        if path.suffix == ".py":
            try:
                ast.parse(updated)
            except SyntaxError:
                logger.warning("Safe fixes would break %s — skipped", path)
                for issue in file_issues:
                    issue.applied = False
                continue
        if not dry_run:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(updated)
        applied[file_path] = count
    return applied
