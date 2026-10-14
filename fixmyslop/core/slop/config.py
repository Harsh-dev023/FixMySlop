"""
Project configuration for the slop engine.

Looked up in `.fixmyslop.yml` at the project root, falling back to
`[tool.fixmyslop]` in pyproject.toml. Example:

    exclude: ["legacy/**", "**/*.generated.ts"]
    disable: ["ui/default-font", "slop/ts-any"]
    severity: {"slop/console-log": "INFO"}
    fail_on: high
"""
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from fixmyslop.macros import PROJECT_CONFIG_FILE, SEVERITY_RANK
from fixmyslop.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SlopConfig:
    """User-tunable engine settings."""

    exclude: list[str] = field(default_factory=list)
    disable: list[str] = field(default_factory=list)
    only: list[str] = field(default_factory=list)
    severity: dict[str, str] = field(default_factory=dict)
    fail_on: str = ""
    hook_min_severity: str = "MEDIUM"

    def rule_enabled(self, rule_id: str) -> bool:
        """True when the rule isn't disabled and passes the `only` filter (ids or prefixes)."""
        if any(_matches_rule(rule_id, d) for d in self.disable):
            return False
        if self.only and not any(_matches_rule(rule_id, o) for o in self.only):
            return False
        return True

    def allow(self, rel_target: str):
        """Drop exclude globs that cover an explicitly requested target (explicit beats config)."""
        rel = rel_target.replace("\\", "/").strip("/")
        if not rel or rel == ".":
            return
        probe = rel + "/__probe__"
        self.exclude = [p for p in self.exclude
                        if not SlopConfig(exclude=[p]).is_excluded(rel)
                        and not SlopConfig(exclude=[p]).is_excluded(probe)]

    def is_excluded(self, rel_path: str) -> bool:
        """True when a project-relative path matches an exclude glob."""
        rel = rel_path.replace("\\", "/")
        for pattern in self.exclude:
            pattern = pattern.strip().rstrip("/")
            if not pattern:
                continue
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, pattern + "/*") \
                    or rel.startswith(pattern + "/") or fnmatch.fnmatch(rel, "*/" + pattern):
                return True
        return False


def _matches_rule(rule_id: str, selector: str) -> bool:
    """Match a rule id against an id, a prefix like 'ui' / 'ui/', or a glob."""
    selector = selector.strip()
    if not selector:
        return False
    if "/" not in selector and "*" not in selector:
        return rule_id.split("/")[0] == selector or rule_id == selector
    if selector.endswith("/"):
        return rule_id.startswith(selector)
    return fnmatch.fnmatch(rule_id, selector)


def _from_mapping(data: dict) -> SlopConfig:
    """Build a config from a parsed YAML/TOML mapping, ignoring unknown keys."""
    def as_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(v) for v in value]

    severity = {}
    for key, value in (data.get("severity") or {}).items():
        value = str(value).upper()
        if value in SEVERITY_RANK:
            severity[str(key)] = value
    hook = data.get("hook") or {}
    return SlopConfig(
        exclude=as_list(data.get("exclude")),
        disable=as_list(data.get("disable")),
        only=as_list(data.get("only")),
        severity=severity,
        fail_on=str(data.get("fail_on") or data.get("fail-on") or ""),
        hook_min_severity=str(hook.get("min_severity", "MEDIUM")).upper(),
    )


def load_config(root: Path) -> SlopConfig:
    """Load project config from .fixmyslop.yml or pyproject.toml; defaults if absent/broken."""
    root = root if root.is_dir() else root.parent
    yml = root / PROJECT_CONFIG_FILE
    if yml.exists():
        try:
            import yaml
            data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return _from_mapping(data)
        except Exception as e:
            logger.warning("Could not parse %s: %s", yml, e)
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            section = data.get("tool", {}).get("fixmyslop")
            if isinstance(section, dict):
                return _from_mapping(section)
        except (ImportError, OSError, ValueError) as e:  # tomllib is 3.11+; TOMLDecodeError is a ValueError
            logger.debug("Ignoring [tool.fixmyslop] in %s: %s", pyproject, e)
    return SlopConfig()


DEFAULT_CONFIG_YAML = """\
# FixMySlop configuration — https://github.com/MrSpideyNihal/FixMySlop
# Paths to skip (globs, relative to this file)
exclude:
  - "**/*.min.js"
  - "**/vendor/**"

# Rules or rule groups to turn off: ui, a11y, slop, sec, deps, or ids like "ui/default-font"
disable: []

# Per-rule severity overrides (CRITICAL, HIGH, MEDIUM, LOW, INFO)
severity: {}

# Exit non-zero in CI when an issue at or above this severity is found
fail_on: high

# Claude Code / agent hook: only block the agent for issues at or above this severity
hook:
  min_severity: MEDIUM
"""
