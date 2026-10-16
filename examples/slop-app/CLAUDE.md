<!-- fixmyslop:start -->
## Anti-slop rules (enforced by FixMySlop)

These rules are checked automatically by `fixmyslop scan`. Code that violates them will be flagged.

### Code
- Never write placeholder implementations ("in a real app you would…", "simplified for demo", `pass` stubs).
  Implement it properly or raise an explicit error and say so.
- Never elide code with comments like `// ... existing code ...` or `# rest of the file unchanged`.
- No comments that narrate the next line (`# Initialize the list`). Comment *why*, not *what*.
- Never swallow exceptions (`except Exception: pass`, empty `catch {}`). Handle, log with context, or re-raise.
- Don't import packages that aren't in the manifest. Never guess a package name — check it exists first.
- No `any`, `@ts-ignore`, or file-wide lint/type suppressions to make errors disappear.
- No emoji in log messages; no `console.log`/`debugger`/`breakpoint()` left behind.

### UI
- Use the existing design tokens. One accent color plus neutrals; don't add one-off hex colors or `w-[347px]` values.
- No purple→pink gradients, gradient text, glassmorphism stacks, decorative blurred blobs, or `hover:scale-105` on everything.
- No glowing orbs or colored glows (any hue), pulsing status dots, two-tone accent headlines, or uppercase letter-spaced
  "eyebrow" labels above every section. Charts only from real data — otherwise an empty state.
- No emoji as icons — use the project's icon library.
- Copy must be plain and specific. Never write "revolutionize", "seamless", "unlock the power of", or calm-sounding
  aphorisms ("make space for what matters", "intentional by design", "your data stays yours", "less X. more Y."),
  and never invent stats, ratings, logos, or testimonials.
- Accessibility is not optional: alt text on images, `<button>` not clickable `<div>`, `aria-label`
  on icon-only buttons, visible focus styles, real `href`s.

### Security
- Never hardcode keys, tokens or passwords. Never put secrets in `NEXT_PUBLIC_`/`VITE_` variables.
- Parameterised SQL only. No wildcard CORS, no `verify=False`, no unsanitized `innerHTML`/`dangerouslySetInnerHTML`.

Before finishing a task, run `fixmyslop scan --changed --fail-on medium` and fix what it reports.
<!-- fixmyslop:end -->
