# Changelog

All notable changes. Versions follow [semantic versioning](https://semver.org/); while in 0.x, minor versions may
include breaking changes.

## 0.6.1
- `fixmyslop ui`: code previews failed when the opened folder is a subfolder of a git repo (monorepos).

## 0.6.0

**Adopt it on an existing codebase**
- **Baseline mode**: `fixmyslop baseline` accepts today's issues; later scans and CI report only new slop.
  Fingerprints ignore line numbers, so editing above old issues doesn't resurface them. Also in the app (Setup).

**Backend rules**
- `slop/empty-test` — tests (pytest, Jest, Vitest, Mocha) that assert nothing or only `assert True`;
  understands local asserting helpers and "does not throw" smoke tests.
- `slop/duplicate-function` — the same function body in several places (variable names ignored).
- `slop/pointless-wrapper`, `slop/catch-rethrow`, `slop/catch-rethrow-js`.
- Go: `slop/ignored-error` (`if err != nil {}` / `return nil`). Java/Kotlin: `slop/print-stacktrace`.
  `slop/empty-catch` now covers Java, C#, Kotlin, Swift, PHP and Dart.

**UI rules**
- New: `ui/fake-feature` (buttons that only `alert('…preview…')`), `ui/fake-ratings` (hard-coded ratings and
  review counts).
- `ui/fake-social-proof` knows more audiences ("2,400+ happy travelers") and needs a real social-proof number
  (100+), so "5+ guests" in a dropdown is fine; form placeholders are ignored.
- `ui/aphorism-copy` catches more of the "lovely little stays" voice; `ui/two-tone-headline` catches headlines
  styled through `h1 em { color }`; symbols like ⌂ ✦ ✿ count as icons.

**Accuracy** (from a hand-reviewed benchmark — see [benchmarks/BENCHMARK.md](benchmarks/BENCHMARK.md), 95% precision)
- Fixed: single-file HTML pages with long CSS lines were skipped as "minified" and reported as grade A.
- Fixed: a line starting with the CSS `*` selector was treated as a comment.
- Fixed false positives: modal backdrops and `stopPropagation()` wrappers (clickable-div), shadcn `asChild`
  buttons, `aria-selected:` focus styles, `.catch(() => null)` fallbacks, `any` inside strings, overlays with
  blur/big shadows, Java/Go syntax rules matching text inside Python strings.
- Generated files (`*.gen.ts`, `@generated`, "do not edit") are only checked for leaked secrets.
- A scan that finds no supported files now says so instead of "No slop found".

**Trust**
- Reproducible benchmark (`benchmarks/`), SECURITY.md, this changelog, npm provenance on releases.

## 0.5.0
- `fixmyslop ui`: a rules-first local web app replacing the PyQt desktop app.
- Non-English button labels no longer flagged as icon-only; design tokens don't count as palette sprawl;
  code previews redact keys; "AI Smell" renamed "Code Slop".

## 0.4.0
- Rules for the newer AI UI look: `ui/aphorism-copy`, `ui/eyebrow-labels`, `ui/two-tone-headline`,
  `ui/fake-chart`; glow orbs in any hue; pulsing status dots.

## 0.3.x
- Deterministic rules engine, agent hand-off (`fix`, MCP server, Claude Code hook, `init`), SARIF, interactive
  HTML report, GitHub Action, pre-commit hook, npx launcher, calibration on real AI-built apps.
