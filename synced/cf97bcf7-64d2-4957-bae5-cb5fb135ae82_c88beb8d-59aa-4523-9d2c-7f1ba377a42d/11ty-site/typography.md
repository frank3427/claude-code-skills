# Typography Reference — GRT Integration

Typography is always set by the GRT calculator. Never hand-code font sizes, line heights,
or spacing values. This reference defines exactly how to run GRT and integrate the output
into every project.

---

## GRT Skill Location

The GRT calculator script and SKILL.md are at:
```
/mnt/skills/user/golden-ratio-typography/SKILL.md
/mnt/skills/user/golden-ratio-typography/scripts/grt.py
```

Always read the GRT SKILL.md before running the calculator if there are any questions
about inputs or flags.

---

## Standard Inputs by Site Type

| Site Type | font-size | content-width | x-height |
|---|---|---|---|
| Content/article/magazine | 18px | 680px | per font |
| Marketing/landing page | 16px | 860px | per font |
| Portfolio/professional | 17px | 720px | per font |
| Documentation | 16px | 680px | per font |

X-height values by font family (pass via `--x-height`):
- Merriweather, Lora, Georgia: 0.49
- Playfair Display: 0.47
- Source Serif Pro: 0.50
- DM Sans, Nunito Sans, Work Sans: 0.53
- Jost, Syne, Epilogue: 0.52
- Most sans-serifs not listed: 0.52

---

## How to Run

```bash
SKILL_DIR="/mnt/skills/user/golden-ratio-typography"

# Generate grt.css for a project
python $SKILL_DIR/scripts/grt.py \
  --font-size 18 \
  --content-width 680 \
  --x-height 0.49 \
  --target body \
  --output /path/to/project/src/css/grt.css

# Or inject directly into a single HTML file
python $SKILL_DIR/scripts/grt.py \
  --font-size 16 \
  --content-width 860 \
  --target body \
  --inject /path/to/project/src/index.html
```

Always use `--target body` so GRT applies globally without requiring a wrapper class.

---

## Integration Into Project CSS

After running the calculator, `grt.css` is written to `src/css/`. It is:
- Imported at the top of `style.css` via `@import url('./grt.css');`
- Linked in `base.njk` before `style.css`
- **Never manually edited** — it is regenerated whenever inputs change

All typographic values in `style.css` must reference GRT variables:

```css
/* Font sizes */
body    → var(--grt-scale-1)      /* base */
small   → var(--grt-scale-1)      /* same as body, styled via opacity */
h6      → var(--grt-scale-1)
h5      → var(--grt-h5-size)
h4      → var(--grt-h4-size)
h3      → var(--grt-h3-size)
h2      → var(--grt-h2-size)
h1      → var(--grt-h1-size)
display → var(--grt-scale-3)      /* hero/poster text */

/* Line heights */
body    → var(--grt-lh-1)
h1–h6   → var(--grt-h1-lh) etc.

/* Spacing — always derive from GRT spacing units */
paragraph margin  → var(--grt-space-md)
section padding   → var(--grt-space-xl)
heading top margin → var(--grt-space-lg)
component gap     → var(--grt-space-sm)
```

---

## When to Regenerate GRT

Regenerate `grt.css` when:
- The base font size changes
- The content column width changes significantly (>40px)
- The primary font family changes (x-height correction changes)

When regenerating: delete the old `grt.css`, re-run the script, commit the new file.

---

## Magazine / Multi-Column Layouts (Abernathy Pattern)

For magazine-style sites with article cards and narrow content columns:
- Run GRT at the **article body** column width, not the full page width
- Article cards may use smaller type: derive from `var(--grt-scale-1)` with reduced opacity
- Pull quotes: `var(--grt-h3-size)` with `var(--grt-h3-lh)`, italic, left border accent
- Bylines/metadata: `calc(var(--grt-scale-1) * 0.85)` — the only acceptable derived value

---

## Single HTML File (No 11ty)

For standalone mockups not yet using 11ty:
```bash
python $SKILL_DIR/scripts/grt.py \
  --font-size 17 \
  --content-width 720 \
  --target body \
  --inject /path/to/index.html
```

The script adds a `<style>` block inside `<head>` wrapped in GRT comment markers.
All font-size and line-height values in the file's other CSS must then reference
the injected variables.
