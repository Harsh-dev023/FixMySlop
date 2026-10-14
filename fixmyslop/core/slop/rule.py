"""
Rule model, file context, and registry for the deterministic slop engine.

Every rule is a pure function over a FileContext that yields Hit objects.
No LLM, no network — rules must be fast and reproducible so they can run
on every keystroke of an agent (Claude Code hook) and in CI.
"""
import bisect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

# ─── File kinds ──────────────────────────────────────────────────────────────
# A file can have several kinds (a .tsx file is script + markup).
KIND_PYTHON = "python"
KIND_SCRIPT = "script"      # JS/TS family
KIND_TS = "ts"
KIND_MARKUP = "markup"      # renders UI: html, jsx, tsx, vue, svelte, astro
KIND_STYLE = "style"        # css family (or files with <style> blocks)
KIND_CODE = "code"          # any programming language
KIND_ANY = "any"

_EXT_KINDS = {
    ".py": {KIND_PYTHON, KIND_CODE},
    ".js": {KIND_SCRIPT, KIND_CODE},
    ".mjs": {KIND_SCRIPT, KIND_CODE},
    ".cjs": {KIND_SCRIPT, KIND_CODE},
    ".ts": {KIND_SCRIPT, KIND_TS, KIND_CODE},
    ".mts": {KIND_SCRIPT, KIND_TS, KIND_CODE},
    ".cts": {KIND_SCRIPT, KIND_TS, KIND_CODE},
    ".jsx": {KIND_SCRIPT, KIND_MARKUP, KIND_CODE},
    ".tsx": {KIND_SCRIPT, KIND_TS, KIND_MARKUP, KIND_CODE},
    ".vue": {KIND_SCRIPT, KIND_MARKUP, KIND_STYLE, KIND_CODE},
    ".svelte": {KIND_SCRIPT, KIND_MARKUP, KIND_STYLE, KIND_CODE},
    ".astro": {KIND_SCRIPT, KIND_MARKUP, KIND_STYLE, KIND_CODE},
    ".html": {KIND_MARKUP, KIND_STYLE},
    ".htm": {KIND_MARKUP, KIND_STYLE},
    ".css": {KIND_STYLE},
    ".scss": {KIND_STYLE},
    ".sass": {KIND_STYLE},
    ".less": {KIND_STYLE},
}


def kinds_for(ext: str) -> frozenset:
    """Return the set of kinds for a file extension (always includes 'any')."""
    kinds = set(_EXT_KINDS.get(ext.lower(), {KIND_CODE}))
    kinds.add(KIND_ANY)
    return frozenset(kinds)


TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|__mocks__|spec|specs|fixtures|e2e|cypress|stories)/"
    r"|(_test|\.test|\.spec|_spec|\.stories)\.\w+$"
    r"|(^|/)(test_[^/]*|conftest)\.py$"
    r"|\.pyi$",
    re.IGNORECASE,
)

# Whole-line comment openers per family.
_HASH_COMMENT = re.compile(r"^\s*#(?!!)")
_SLASH_COMMENT = re.compile(r"^\s*(//|\{/\*|\*(?!\*/)|/\*)")
_HTML_COMMENT_OPEN = "<!--"
_HTML_COMMENT_CLOSE = "-->"


@dataclass(frozen=True)
class Hit:
    """One rule match inside a file."""

    line: int
    evidence: str = ""
    message: str = ""
    end_line: int = 0
    severity: str = ""      # overrides the rule's default severity when set


class FileContext:
    """Everything a rule needs to know about one file."""

    def __init__(self, path: Path, rel: str, text: str, project=None):
        """Index the file for fast line lookups and comment detection."""
        self.path = path
        self.rel = rel.replace("\\", "/")
        self.text = text
        self.lines = text.splitlines()
        self.ext = path.suffix.lower()
        self.kinds = kinds_for(self.ext)
        self.is_test = bool(TEST_PATH_RE.search(self.rel))
        self.project = project
        self._line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
        self.comment_lines = self._find_comment_lines()

    def _find_comment_lines(self) -> set[int]:
        """Return 1-based numbers of lines that are entirely comments."""
        result: set[int] = set()
        is_python = KIND_PYTHON in self.kinds
        in_block = False
        in_html = False
        for n, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if in_html:
                result.add(n)
                if _HTML_COMMENT_CLOSE in stripped:
                    in_html = False
                continue
            if in_block:
                result.add(n)
                if "*/" in stripped:
                    in_block = False
                continue
            if stripped.startswith(_HTML_COMMENT_OPEN):
                result.add(n)
                if _HTML_COMMENT_CLOSE not in stripped:
                    in_html = True
                continue
            if is_python:
                if _HASH_COMMENT.match(line):
                    result.add(n)
                continue
            if _SLASH_COMMENT.match(line):
                result.add(n)
                if (stripped.startswith("/*") or stripped.startswith("{/*")) and "*/" not in stripped:
                    in_block = True
        return result

    def is_comment(self, line_no: int) -> bool:
        """True when the given 1-based line is a whole-line comment."""
        return line_no in self.comment_lines

    def line_of(self, offset: int) -> int:
        """Convert a character offset into a 1-based line number."""
        return bisect.bisect_right(self._line_starts, offset)

    def line_text(self, line_no: int) -> str:
        """Return the raw text of a 1-based line ('' when out of range)."""
        if 1 <= line_no <= len(self.lines):
            return self.lines[line_no - 1]
        return ""

    def has(self, kind: str) -> bool:
        """True when this file is of the given kind."""
        return kind in self.kinds


CheckFn = Callable[[FileContext], Iterable[Hit]]


@dataclass
class Rule:
    """Metadata + check function for one slop rule."""

    id: str
    title: str
    severity: str
    category: str
    kinds: frozenset
    why: str
    fix: str
    check: Optional[CheckFn] = None
    skip_tests: bool = False
    project_threshold: int = 0     # >0: only report when the project total reaches this
    once_per_project: bool = False
    fixable: bool = False
    aggregate_per_file: bool = False   # collapse many hits in one file into a single finding

    def applies_to(self, ctx: FileContext) -> bool:
        """True when this rule should run on the given file."""
        if self.skip_tests and ctx.is_test:
            return False
        return bool(self.kinds & ctx.kinds)


RULES: dict[str, Rule] = {}


def rule(id: str, title: str, severity: str, category: str, kinds: Iterable[str],
         why: str, fix: str, **options) -> Callable[[CheckFn], CheckFn]:
    """Decorator registering a check function as a rule."""
    def decorator(fn: CheckFn) -> CheckFn:
        RULES[id] = Rule(
            id=id, title=title, severity=severity, category=category,
            kinds=frozenset(kinds), why=why, fix=fix, check=fn, **options,
        )
        return fn
    return decorator


def line_rule(id: str, title: str, severity: str, category: str, kinds: Iterable[str],
              why: str, fix: str, pattern: str, flags: int = re.IGNORECASE,
              scope: str = "code", **options) -> None:
    """Register a rule that matches a regex against individual lines.

    scope: "code" skips comment lines, "comment" only checks comment lines,
    "all" checks every line.
    """
    regex = re.compile(pattern, flags)

    def check(ctx: FileContext) -> Iterable[Hit]:
        for n, line in enumerate(ctx.lines, 1):
            is_comment = ctx.is_comment(n)
            if scope == "code" and is_comment:
                continue
            if scope == "comment" and not is_comment:
                continue
            match = regex.search(line)
            if match:
                yield Hit(n, line.strip(), match.group(0).strip())

    rule(id, title, severity, category, kinds, why, fix, **options)(check)


def find_tag_end(text: str, start: int) -> int:
    """Return the index of the '>' closing a tag opened at `start`.

    Aware of quotes and JSX braces, so `onClick={() => x}` does not end the tag.
    Returns -1 when the tag never closes.
    """
    depth = 0
    quote = ""
    i = start + 1
    limit = min(len(text), start + 4000)
    while i < limit:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ("'", '"', "`"):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif ch == ">" and depth == 0:
            return i
        i += 1
    return -1


def iter_tags(ctx: FileContext, names: Iterable[str]) -> Iterable[tuple[str, str, int, int]]:
    """Yield (tag_name, attrs_text, start_offset, end_offset) for opening tags."""
    pattern = re.compile(r"<(" + "|".join(names) + r")(?=[\s/>])")
    for match in pattern.finditer(ctx.text):
        end = find_tag_end(ctx.text, match.start())
        if end == -1:
            continue
        line = ctx.line_of(match.start())
        if ctx.is_comment(line):
            continue
        yield match.group(1), ctx.text[match.end():end], match.start(), end
