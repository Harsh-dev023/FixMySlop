"""
Static tools — subprocess wrappers for Ruff, Bandit, and Semgrep.
Parses their JSON output into Issue objects for unified consumption.
"""
import json
import subprocess
import shutil
from pathlib import Path
from typing import Optional
from fixmyslop.core.issue import Issue
from fixmyslop.core.slop.rule import TEST_PATH_RE
from fixmyslop.macros import (
    TOOL_RUFF, TOOL_BANDIT, TOOL_SEMGREP,
    SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW, SEVERITY_INFO,
    CATEGORY_SECURITY, CATEGORY_DEBT, CATEGORY_MAINTAINABILITY,
)
from fixmyslop.utils.logger import get_logger

logger = get_logger(__name__)

_RUFF_HIGH = {"F821", "F822", "F823", "F632", "F702", "F704", "F706"}
_RUFF_LOW = {"F401", "F841", "F811", "F541"}


class StaticToolRunner:
    """
    Runs static analysis tools (Ruff, Bandit, Semgrep) on source files
    and converts their output into Issue objects.
    """

    def __init__(self):
        """Initialize and detect available tools."""
        self._available = {
            TOOL_RUFF: shutil.which("ruff") is not None,
            TOOL_BANDIT: shutil.which("bandit") is not None,
            TOOL_SEMGREP: shutil.which("semgrep") is not None,
        }
        for tool, available in self._available.items():
            if available:
                logger.info("Static tool '%s' found", tool)
            else:
                logger.debug("Static tool '%s' not found on PATH", tool)
        self._prefetched: dict[str, list[Issue]] = {}

    def prefetch(self, paths: list[Path], chunk_size: int = 200):
        """Run ruff and bandit once per chunk of Python files instead of once per file.

        Results are cached and returned by run() — a large speedup on big repos.
        """
        python_files = [p for p in paths if p.suffix == ".py"]
        for start in range(0, len(python_files), chunk_size):
            chunk = python_files[start:start + chunk_size]
            for path in chunk:
                self._prefetched.setdefault(self._key(path), [])
            if self._available[TOOL_RUFF]:
                for issue in self._run_ruff_paths(chunk):
                    self._prefetched.setdefault(self._key(Path(issue.file_path)), []).append(issue)
            bandit_targets = [p for p in chunk if not TEST_PATH_RE.search(p.as_posix())]
            if self._available[TOOL_BANDIT] and bandit_targets:
                for issue in self._run_bandit_paths(bandit_targets):
                    self._prefetched.setdefault(self._key(Path(issue.file_path)), []).append(issue)

    @staticmethod
    def _key(path: Path) -> str:
        """Normalized cache key for a path."""
        try:
            return str(path.resolve()).lower()
        except OSError:
            return str(path).lower()

    def run(self, file_path: Path, content: str, language: str) -> list[Issue]:
        """
        Run all available static tools on a file and return combined issues.
        Only runs Python tools on .py files.
        """
        issues: list[Issue] = []
        key = self._key(file_path)
        if key in self._prefetched:
            issues.extend(self._prefetched.pop(key))
        elif language == "python" or file_path.suffix == ".py":
            if self._available[TOOL_RUFF]:
                issues.extend(self._run_ruff(file_path))
            if self._available[TOOL_BANDIT]:
                issues.extend(self._run_bandit(file_path))

        if self._available[TOOL_SEMGREP]:
            issues.extend(self._run_semgrep(file_path))

        return issues

    def _run_ruff(self, file_path: Path) -> list[Issue]:
        """Run Ruff linter on one file and parse results into Issues."""
        return self._run_ruff_paths([file_path])

    def _run_ruff_paths(self, paths: list[Path]) -> list[Issue]:
        """Run Ruff once over several files."""
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=json", "--no-fix", "--exit-zero",
                 *[str(p) for p in paths]],
                capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace",
            )
            if not result.stdout.strip():
                return []

            data = json.loads(result.stdout)
            issues = []
            for item in data:
                code = item.get("code") or "ruff_unknown"
                issues.append(Issue(
                    file_path=item.get("filename") or str(paths[0]),
                    line_start=(item.get("location") or {}).get("row", 0),
                    line_end=(item.get("end_location") or {}).get("row", 0),
                    severity=self._ruff_severity(code),
                    category=CATEGORY_SECURITY if code.startswith("S") else CATEGORY_MAINTAINABILITY,
                    rule_id=code,
                    title=item.get("message", "Ruff issue"),
                    description=item.get("message", ""),
                    evidence="",
                    source_tool=TOOL_RUFF,
                ))
            return issues
        except Exception as e:
            logger.warning("Ruff failed for %s: %s", paths[0] if paths else "?", e)
            return []

    def _run_bandit(self, file_path: Path) -> list[Issue]:
        """Run Bandit security scanner on one file and parse results into Issues."""
        if TEST_PATH_RE.search(file_path.as_posix()):
            return []
        return self._run_bandit_paths([file_path])

    def _run_bandit_paths(self, paths: list[Path]) -> list[Issue]:
        """Run Bandit once over several files (skips B101 asserts and B404/B603/B607, which flag *safe* subprocess use)."""
        try:
            result = subprocess.run(
                ["bandit", "-f", "json", "-q", "-s", "B101,B404,B603,B607", *[str(p) for p in paths]],
                capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace",
            )
            if not result.stdout.strip():
                return []

            data = json.loads(result.stdout)
            severity_map = {
                "HIGH": SEVERITY_HIGH,
                "MEDIUM": SEVERITY_MEDIUM,
                "LOW": SEVERITY_LOW,
            }
            issues = []
            for item in data.get("results", []):
                issues.append(Issue(
                    file_path=item.get("filename") or str(paths[0]),
                    line_start=item.get("line_number", 0),
                    line_end=item.get("line_number", 0),
                    severity=severity_map.get(item.get("issue_severity", ""), SEVERITY_MEDIUM),
                    category=CATEGORY_SECURITY,
                    rule_id=item.get("test_id", "bandit_unknown"),
                    title=item.get("issue_text", "Bandit issue"),
                    description=item.get("issue_text", ""),
                    evidence=item.get("code", ""),
                    source_tool=TOOL_BANDIT,
                ))
            return issues
        except Exception as e:
            logger.warning("Bandit failed for %s: %s", paths[0] if paths else "?", e)
            return []

    def _run_semgrep(self, file_path: Path) -> list[Issue]:
        """Run Semgrep and parse results into Issues."""
        try:
            result = subprocess.run(
                ["semgrep", "--json", "--quiet", str(file_path)],
                capture_output=True, text=True, timeout=60,
            )
            if not result.stdout.strip():
                return []

            data = json.loads(result.stdout)
            issues = []
            for item in data.get("results", []):
                severity_map = {
                    "ERROR": SEVERITY_HIGH,
                    "WARNING": SEVERITY_MEDIUM,
                    "INFO": SEVERITY_INFO,
                }
                issues.append(Issue(
                    file_path=str(file_path),
                    line_start=item.get("start", {}).get("line", 0),
                    line_end=item.get("end", {}).get("line", 0),
                    severity=severity_map.get(item.get("extra", {}).get("severity", ""), SEVERITY_MEDIUM),
                    category=CATEGORY_DEBT,
                    rule_id=item.get("check_id", "semgrep_unknown"),
                    title=item.get("extra", {}).get("message", "Semgrep issue"),
                    description=item.get("extra", {}).get("message", ""),
                    evidence=item.get("extra", {}).get("lines", ""),
                    source_tool=TOOL_SEMGREP,
                ))
            return issues
        except Exception as e:
            logger.warning("Semgrep failed for %s: %s", file_path, e)
            return []

    @staticmethod
    def _ruff_severity(code: str) -> str:
        """Map Ruff rule codes to severity levels.

        Real bugs rank high; style and unused-name findings rank low so they
        don't drown out security issues in the slop score.
        """
        if code.startswith("S") or code.startswith("E9") or code in _RUFF_HIGH:
            return SEVERITY_HIGH  # security, undefined names, syntax errors
        if code in _RUFF_LOW:
            return SEVERITY_LOW  # unused imports/variables, empty f-strings
        if code.startswith(("B", "F", "E7", "PLE")):
            return SEVERITY_MEDIUM  # bugbear / pyflakes / statement errors
        return SEVERITY_LOW

    def get_tool_versions(self) -> dict[str, Optional[str]]:
        """Return version strings for all available tools."""
        versions = {}
        for tool in (TOOL_RUFF, TOOL_BANDIT, TOOL_SEMGREP):
            if self._available[tool]:
                try:
                    result = subprocess.run(
                        [tool, "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    versions[tool] = result.stdout.strip()
                except Exception:
                    versions[tool] = "unknown"
            else:
                versions[tool] = None
        return versions
