"""
Agent hand-off — run the coding agent the user already has (Claude Code, Codex,
Gemini CLI, or any custom command) against a FixMySlop fix brief, or fall back
to a whole-file rewrite through any OpenAI-compatible LLM endpoint.
"""
import ast
import difflib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from fixmyslop.core.issue import Issue
from fixmyslop.macros import WORK_DIR_NAME
from fixmyslop.utils.logger import get_logger

logger = get_logger(__name__)

_INSTRUCTION = (
    "Read the FixMySlop fix brief at {brief} and fix every item in it, following its rules of "
    "engagement. Edit the files directly. Finish with a two-line summary of what you changed."
)


@dataclass
class AgentSpec:
    """How to launch one coding-agent CLI non-interactively."""

    name: str
    binary: str
    build: Callable[[str, str], list[str]]   # (executable, prompt) -> argv


AGENTS: dict[str, AgentSpec] = {
    "claude": AgentSpec("Claude Code", "claude",
                        lambda exe, prompt: [exe, "-p", prompt, "--permission-mode", "acceptEdits"]),
    "codex": AgentSpec("Codex CLI", "codex",
                       lambda exe, prompt: [exe, "exec", "--full-auto", prompt]),
    "gemini": AgentSpec("Gemini CLI", "gemini",
                        lambda exe, prompt: [exe, "-p", prompt, "--yolo"]),
}


def detect_agent() -> Optional[str]:
    """First agent CLI found on PATH, in preference order."""
    for key, spec in AGENTS.items():
        if shutil.which(spec.binary):
            return key
    return None


def work_dir(root: Path) -> Path:
    """<root>/.fixmyslop/, created on demand; it ignores itself in git."""
    work = root / WORK_DIR_NAME
    work.mkdir(parents=True, exist_ok=True)
    gitignore = work / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
    return work


def write_brief(root: Path, brief: str) -> Path:
    """Write the brief to <root>/.fixmyslop/brief.md."""
    path = work_dir(root) / "brief.md"
    path.write_text(brief, encoding="utf-8")
    return path


def run_agent(agent: str, root: Path, brief_path: Path, custom_cmd: Optional[str] = None) -> int:
    """Run an agent CLI in `root` with output streamed to the terminal. Returns its exit code."""
    rel_brief = brief_path.relative_to(root).as_posix()
    prompt = _INSTRUCTION.format(brief=rel_brief)
    if custom_cmd:
        command = custom_cmd.replace("{brief}", rel_brief).replace("{prompt}", prompt)
        logger.info("Running custom agent command: %s", command)
        return subprocess.run(command, cwd=root, shell=True).returncode  # nosec B602 — user's own command
    spec = AGENTS[agent]
    exe = shutil.which(spec.binary)
    if not exe:
        raise FileNotFoundError(f"{spec.name} (`{spec.binary}`) is not on PATH")
    argv = spec.build(exe, prompt)
    logger.info("Running agent: %s", argv)
    return subprocess.run(argv, cwd=root).returncode


# ─── LLM whole-file rewrite (local or cloud OpenAI-compatible endpoint) ──────

_LLM_SYSTEM = (
    "You are FixMySlop's fixer. You receive one source file and a list of concrete issues. "
    "Return the COMPLETE corrected file in a single fenced code block and nothing else. "
    "Fix only the listed issues; keep everything else byte-for-byte identical. "
    "Never elide code with comments like '... existing code ...'. Never add placeholder implementations."
)

_FENCE = re.compile(r"```[\w+-]*[ \t]*\n(.*?)\n```", re.DOTALL)


@dataclass
class FileRewrite:
    """A proposed whole-file fix from the LLM."""

    path: Path
    original: str
    updated: str
    rejected_reason: str = ""

    @property
    def diff(self) -> str:
        """Unified diff of the proposal."""
        return "".join(difflib.unified_diff(
            self.original.splitlines(keepends=True), self.updated.splitlines(keepends=True),
            fromfile=f"a/{self.path.name}", tofile=f"b/{self.path.name}",
        ))


def llm_rewrite_file(llm_client, path: Path, issues: list[Issue], brief_rules: str = "") -> FileRewrite:
    """Ask an LLM for a corrected version of one file and validate the answer."""
    with open(path, encoding="utf-8", newline="") as handle:
        original = handle.read()
    listing = "\n".join(
        f"- line {i.line_start} [{i.rule_id}] {i.title}. Fix: {i.suggested_fix or i.description}"
        for i in sorted(issues, key=lambda i: i.line_start)
    )
    prompt = (
        f"File: {path.name}\n\nIssues to fix:\n{listing}\n\n{brief_rules}\n"
        f"Current file:\n```\n{original}\n```\n\nReturn the full corrected file."
    )
    max_tokens = min(32000, max(2048, len(original) // 2 + 1024))
    raw = llm_client.chat(_LLM_SYSTEM, prompt, temperature=0.1, max_tokens=max_tokens)
    match = _FENCE.search(raw or "")
    updated = match.group(1) if match else (raw or "").strip()
    if original.endswith("\n") and not updated.endswith("\n"):
        updated += "\n"
    if "\r\n" in original and "\r\n" not in updated:
        updated = updated.replace("\n", "\r\n")
    return FileRewrite(path, original, updated, _validate(path, original, updated))


def _validate(path: Path, original: str, updated: str) -> str:
    """Reject rewrites that are empty, truncated, elided, or don't parse."""
    if not updated.strip():
        return "model returned nothing"
    if updated == original:
        return "model made no changes"
    if len(updated.splitlines()) < 0.6 * len(original.splitlines()):
        return "model output is much shorter than the original (likely truncated)"
    if re.search(r"(?:#|//)\s*\.\.\.\s*(?:rest|existing|remaining|unchanged)", updated, re.IGNORECASE):
        return "model elided code with a placeholder comment"
    if path.suffix == ".py":
        try:
            ast.parse(updated)
        except SyntaxError as e:
            return f"result is not valid Python ({e.msg}, line {e.lineno})"
    return ""


def apply_rewrite(rewrite: FileRewrite):
    """Write an accepted rewrite to disk (preserving newline style)."""
    with open(rewrite.path, "w", encoding="utf-8", newline="") as handle:
        handle.write(rewrite.updated)
