"""
SlopEngine — runs every deterministic rule over files and produces Issues.

Usage:
    engine = SlopEngine(root)
    for path, text in files:
        issues += engine.check_file(path, text)
    issues += engine.finalize()       # project-level rules (palette sprawl, thresholds)
"""
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from core.issue import Issue
from core.slop.config import SlopConfig, load_config
from core.slop.rule import RULES, FileContext, Hit, Rule, KIND_MARKUP, KIND_STYLE
from core.slop import rules_ui, rules_code, rules_security, rules_deps  # noqa: F401  (register rules)
from core.slop.rules_deps import DependencyIndex
from macros import (
    SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW, SEVERITY_INFO,
    SEVERITY_RANK, CATEGORY_UI_SLOP, SLOP_TOOL,
    MAX_HITS_PER_RULE_PER_FILE, IGNORE_MARKER, IGNORE_FILE_MARKER,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── Project-level rule metadata (checked in finalize) ──────────────────────
RULES["ui/rainbow-palette"] = Rule(
    id="ui/rainbow-palette", title="Too many accent color families", severity=SEVERITY_MEDIUM,
    category=CATEGORY_UI_SLOP, kinds=frozenset({KIND_MARKUP}),
    why="Each generated component picked its own accent (blue here, emerald there, a purple hero…). "
        "A coherent product uses one accent plus neutrals and a few semantic colors.",
    fix="Choose one primary accent and map every other decorative color to it or to neutrals. Keep "
        "red/amber/green only for semantic states (error/warning/success).",
)
RULES["ui/palette-sprawl"] = Rule(
    id="ui/palette-sprawl", title="Palette sprawl", severity=SEVERITY_MEDIUM,
    category=CATEGORY_UI_SLOP, kinds=frozenset({KIND_STYLE, KIND_MARKUP}),
    why="Dozens of distinct hardcoded hex colors means there is no design system — every screen "
        "drifts a little.",
    fix="Define color tokens (CSS variables or tailwind theme) for the handful of colors you need and "
        "replace raw hex values with them.",
)

RAINBOW_FAMILY_LIMIT = 6
PALETTE_HEX_LIMIT = 24
SEVERITY_WEIGHTS = {
    SEVERITY_CRITICAL: 10.0, SEVERITY_HIGH: 5.0, SEVERITY_MEDIUM: 2.0,
    SEVERITY_LOW: 0.75, SEVERITY_INFO: 0.1,
}
_IGNORE_RE = re.compile(re.escape(IGNORE_MARKER) + r"(?:\[([^\]]*)\])?")


class SlopEngine:
    """Deterministic, offline slop detector."""

    def __init__(self, root: Path, config: Optional[SlopConfig] = None, online: bool = False):
        """Prepare rules and the project dependency index."""
        self.root = Path(root).resolve()
        if self.root.is_file():
            self.root = self.root.parent
        self.config = config or load_config(self.root)
        self.online = online
        self.rules = [r for r in RULES.values() if r.check is not None and self.config.rule_enabled(r.id)]
        self._deps: Optional[DependencyIndex] = None
        self._pending: dict[str, list[Issue]] = defaultdict(list)
        self._color_families: dict[str, tuple[str, int]] = {}
        self._hex_by_file: dict[str, set[str]] = defaultdict(set)
        self.lines_scanned = 0
        self.files_scanned = 0

    @property
    def deps(self) -> DependencyIndex:
        """Lazily build the dependency index (walks the tree once)."""
        if self._deps is None:
            self._deps = DependencyIndex(self.root, online=self.online)
        return self._deps

    def relpath(self, path: Path) -> str:
        """Project-relative POSIX path (falls back to the absolute path)."""
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return Path(path).as_posix()

    # ── per-file ────────────────────────────────────────────────────────────
    def check_file(self, path: Path, content: str) -> list[Issue]:
        """Run every applicable rule on one file and return its issues."""
        path = Path(path)
        rel = self.relpath(path)
        if self.config.is_excluded(rel):
            return []
        head = "\n".join(content.splitlines()[:10])
        if IGNORE_FILE_MARKER in head:
            return []
        ctx = FileContext(path, rel, content, project=self)
        self.files_scanned += 1
        self.lines_scanned += sum(1 for line in ctx.lines if line.strip())

        issues: list[Issue] = []
        for rule in self.rules:
            if not rule.applies_to(ctx):
                continue
            try:
                hits = list(rule.check(ctx))
            except Exception as e:
                logger.warning("Rule %s crashed on %s: %s", rule.id, rel, e)
                continue
            for hit in hits[:MAX_HITS_PER_RULE_PER_FILE]:
                if self._suppressed(ctx, hit.line, rule.id):
                    continue
                issue = self._to_issue(rule, ctx, hit)
                if rule.project_threshold or rule.once_per_project:
                    self._pending[rule.id].append(issue)
                else:
                    issues.append(issue)

        if not ctx.is_test and (ctx.has(KIND_MARKUP) or ctx.has(KIND_STYLE)):
            self._observe_palette(ctx)
        return issues

    def _suppressed(self, ctx: FileContext, line: int, rule_id: str) -> bool:
        """Honor `fixmyslop-ignore` / `fixmyslop-ignore[rule,...]` on the line or the line above."""
        for text in (ctx.line_text(line), ctx.line_text(line - 1)):
            match = _IGNORE_RE.search(text)
            if not match:
                continue
            if not match.group(1):
                return True
            wanted = [r.strip() for r in match.group(1).split(",")]
            if any(rule_id == w or (w.endswith("/") and rule_id.startswith(w))
                   or rule_id.split("/")[0] == w for w in wanted):
                return True
        return False

    def _to_issue(self, rule: Rule, ctx: FileContext, hit: Hit) -> Issue:
        """Convert a rule hit into the shared Issue model."""
        severity = self.config.severity.get(rule.id) or hit.severity or rule.severity
        description = rule.why
        if hit.message:
            description = f"{hit.message}. {rule.why}" if len(hit.message) > 3 else rule.why
        return Issue(
            file_path=str(ctx.path),
            line_start=hit.line,
            line_end=hit.end_line or hit.line,
            severity=severity,
            category=rule.category,
            rule_id=rule.id,
            title=rule.title,
            description=description,
            evidence=hit.evidence[:300],
            suggested_fix=rule.fix,
            source_tool=SLOP_TOOL,
        )

    # ── project-level ───────────────────────────────────────────────────────
    def _observe_palette(self, ctx: FileContext):
        """Track Tailwind color families and raw hex colors for palette rules."""
        for n, line in enumerate(ctx.lines, 1):
            if ctx.is_comment(n):
                continue
            for family in rules_ui.TW_COLOR_FAMILY.findall(line):
                self._color_families.setdefault(family, (str(ctx.path), n))
            for hex_color in rules_ui.HEX_COLOR.findall(line):
                self._hex_by_file[str(ctx.path)].add(_normalize_hex(hex_color))

    def finalize(self) -> list[Issue]:
        """Emit threshold-gated rule hits and project-level palette findings."""
        issues: list[Issue] = []
        for rule_id, pending in self._pending.items():
            rule = RULES[rule_id]
            if rule.once_per_project:
                first = pending[0]
                if len(pending) > 1:
                    first.description = f"Seen in {len(pending)} places. {first.description}"
                issues.append(first)
            elif len(pending) >= rule.project_threshold:
                issues.extend(pending)
        self._pending.clear()

        if self.config.rule_enabled("ui/rainbow-palette") and len(self._color_families) > RAINBOW_FAMILY_LIMIT:
            path, line = min(self._color_families.values())
            families = ", ".join(sorted(self._color_families))
            issues.append(self._project_issue(
                "ui/rainbow-palette", path, line,
                f"{len(self._color_families)} accent color families in use: {families}",
            ))
        all_hex = set().union(*self._hex_by_file.values()) if self._hex_by_file else set()
        if self.config.rule_enabled("ui/palette-sprawl") and len(all_hex) > PALETTE_HEX_LIMIT:
            worst = max(self._hex_by_file, key=lambda p: len(self._hex_by_file[p]))
            issues.append(self._project_issue(
                "ui/palette-sprawl", worst, 1,
                f"{len(all_hex)} distinct hardcoded colors across the project "
                f"({len(self._hex_by_file[worst])} in this file)",
            ))
        return issues

    def _project_issue(self, rule_id: str, path: str, line: int, message: str) -> Issue:
        """Build an Issue for a project-level rule."""
        rule = RULES[rule_id]
        hit = Hit(line, "", message)
        ctx_like = type("Ctx", (), {"path": Path(path)})()
        return self._to_issue(rule, ctx_like, hit)


def _normalize_hex(value: str) -> str:
    """#abc → #aabbcc, lowercase."""
    value = value.lower().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return "#" + value


# ─── Scoring ────────────────────────────────────────────────────────────────

def slop_score(issues: list[Issue], lines_scanned: int) -> float:
    """0 (clean) → 100 (pure slop), from severity-weighted issue density per 1k lines."""
    if not issues:
        return 0.0
    weight = sum(SEVERITY_WEIGHTS.get(i.severity, 1.0) for i in issues)
    density = weight / max(lines_scanned, 200) * 1000
    return round(100 * (1 - math.exp(-density / 40)), 1)


def grade(score: float) -> str:
    """Letter grade for a slop score."""
    if score < 10:
        return "A"
    if score < 25:
        return "B"
    if score < 45:
        return "C"
    if score < 65:
        return "D"
    return "F"


def at_or_above(issues: list[Issue], threshold: str) -> list[Issue]:
    """Issues whose severity is at or above a threshold name (e.g. 'high')."""
    limit = SEVERITY_RANK.get(threshold.upper())
    if limit is None:
        return []
    return [i for i in issues if SEVERITY_RANK.get(i.severity, 99) <= limit]
