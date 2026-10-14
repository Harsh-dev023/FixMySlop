"""
The FixMySlop agent skill (SKILL.md) — the reason an agent reaches for this
tool without being told to. Claude Code (and other skill-aware agents) load a
skill when the task matches its description, so the description names the
exact moments slop gets written: building UI, finishing a task, adding deps.
"""
from pathlib import Path

SKILL_MD = """\
---
name: fixmyslop
description: Catch and fix AI slop in code you write. Use after creating or editing UI (React/Vue/Svelte/HTML/CSS/Tailwind), before saying a coding task is done, when adding imports or dependencies, and when the user mentions "slop", "looks AI-generated", "generic UI", code review, or cleanup. Runs a deterministic sub-second linter for purple gradients, gradient text, emoji icons, marketing copy, fake stats, accessibility bugs, elided "... existing code" markers, placeholder logic, swallowed errors, hallucinated packages and leaked secrets.
---

# FixMySlop

FixMySlop is a deterministic linter (no LLM, sub-second) for the mistakes AI agents
make — including you. Use it as your self-check loop.

## When to run it

- Right after you build or restyle any UI.
- After adding imports or dependencies (catches packages that don't exist).
- Before you tell the user a task is complete.
- When the user asks to "clean up", "de-slop", review, or make something look less AI-generated.

## How

Prefer the MCP tool `check_slop` if it's available. Otherwise use the CLI:

```bash
fixmyslop scan --changed -f compact          # only what you touched (git)
fixmyslop scan path/to/file.tsx -f compact   # specific files
fixmyslop fix --safe-only                    # apply behavior-preserving fixes
fixmyslop rules ui/ai-gradient               # explain a rule
```

If `fixmyslop` isn't installed: `pipx install fixmyslop` (or `uvx fixmyslop scan ...`).

## Loop

1. Run the scan on the files you changed.
2. Fix every CRITICAL/HIGH/MEDIUM item. Each rule ships with a concrete fix hint — follow it.
3. Re-run until it's clean. Don't silence findings to make them go away; for a genuine
   false positive add a `fixmyslop-ignore[<rule-id>]` comment with a one-line reason.
4. Mention the before/after slop score in your summary to the user.

## Writing UI without slop

- Use the project's existing tokens. One accent color plus neutrals.
- No purple→pink gradients, gradient text, glassmorphism stacks, blurred blobs, or hover:scale everywhere.
- No glowing orbs or colored glows in any hue, pulsing dots, two-tone headlines, or eyebrow labels on every section.
- Charts only from real data; otherwise an empty state.
- Icons from the installed icon library, never emoji.
- Plain, specific copy — no hype ("revolutionize") and no aphorisms ("make space for what matters",
  "intentional by design"). Never invent stats, ratings, logos, or testimonials — ask the user.
- `<button>` not clickable `<div>`; alt text; aria-label on icon buttons; visible focus styles.
"""


def install_skill(base: Path) -> str:
    """Write SKILL.md under <base>/skills/fixmyslop/ (base = .claude or ~/.claude)."""
    path = base / "skills" / "fixmyslop" / "SKILL.md"
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_MD, encoding="utf-8")
    return f"{'updated' if existed else 'installed'} skill {path.as_posix()}"
