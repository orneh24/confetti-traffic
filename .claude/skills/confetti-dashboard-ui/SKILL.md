---
name: confetti-dashboard-ui
description: Authoring checklist for changes to Confetti Traffic's hub pages (hub/templates/dashboard.html, syslog.html, timeline.html) — what must stay identical across the three pages, the four dashboard layouts, matrix header widths, and where new data comes from. Read before editing anything under hub/templates/, not after.
origin: confetti
---

# Hub pages: authoring checklist

`dashboard-ui-checker` looks at a finished change. This is what to get right
while writing it.

## Three pages, shared blocks
The themes list, theme picker, Shuffle, `confettiBlast()`, header confetti
and footer buttons are inline in **all three** pages and must match.
`dev/regress.py` R31 compares them. Edit all three or none. Page-specific
CSS (variable sets, Neon box selectors) is not compared.

## Layouts (dashboard.html only)
Classic (no attribute), Modern, Retro 95, Amber CRT, Neon Green CRT. Any new visual state
needs a look in each:
- Retro 95 and the CRT layouts bring their own colours (Amber and Neon Green share one block, palettes in `--crt-*`); add overrides next to their
  `.indicator` / `.btn-small` rules. Retro 95 must stay after all theme rules.
- The CRT layouts are one hue, so status must not rest on colour: use shape, underline
  or inversion (the flapping marker is a dashed outline for this reason).
- `.kpi-row` and `.side-nav` exist only in Modern. A new KPI tile means
  changing `grid-template-columns: repeat(N, …)` too.

## Matrix headers
An extra label goes on its **own line** (`display: block`), never inline in
the row header. An inline label widens the sticky first column, the matrix
overflows its panel, and clicking a cell scrolls the first column under the
header. The group label did exactly this once.

## Data
- Render from what `refresh()` already fetched (`changeHistoryResults` is
  60 minutes). Build a new lookup in `refresh()` before `renderMatrix()`.
- Excluded pairs (`ruleFor`) are left out of every count and marker.
- `/endpoints` is a bare array that deployed nodes also parse: add keys, never
  reshape it.

## Conventions
- `esc()` / `escAttr()` on every value that came from the API.
- Per-viewer choices go in localStorage, keys prefixed `confetti-`, every
  read and write inside try/catch.
- No external libraries or fonts: the hub may be offline.
- Admin panels start folded (`data-default="collapsed"`).

## Before handover
1. `python dev/regress.py`.
2. `dashboard-ui-checker`, in all four layouts.
3. If the change shows in the README images, run `readme-image-capturer`.
4. Docs: CLAUDE.md (and BUILD_GUIDE §6.1 for themes) via `drift-checker`.
