---
name: golden-ratio-typography
description: >
  Apply Golden Ratio Typography (GRT) to any web page or project. Use this skill whenever
  the user wants to improve typography, fix line heights, set up a type scale, apply the
  golden ratio to fonts or CSS, generate GRT variables, add typographic rhythm, or make
  text more readable. Triggers on phrases like "golden ratio typography", "GRT", "type
  scale", "line height formula", "typographic rhythm", "phi typography", "readable
  typography", "improve my fonts/CSS", "apply typography to my project/page/site", "fix
  my line heights", or any mention of grtcalculator.com or pearsonified.com typography.
  Even if the user just says their typography looks off or asks to improve readability,
  use this skill.
---

# Golden Ratio Typography (GRT) Skill

Applies the Golden Ratio (φ ≈ 1.618) to typography — generating a complete CSS/SCSS type system covering font size scale, line heights, spacing units, and heading styles. Based on the formulas from [grtcalculator.com](https://grtcalculator.com/math/) and Chris Pearson's research.

## Quick reference

**The two core GRT numbers:**
- φ = 1.618033988749895
- Line height = font_size × φ (base formula)

**What GRT produces:**
1. A 6-level typographic scale (each step = previous × φ)
2. A line height for each scale level (tuned by content width)
3. 6 spacing units (xs → xxl) derived from body line height
4. Practical heading sizes h1–h6 using half-phi steps
5. Applied CSS styles for body, headings, paragraphs, blockquotes, etc.

---

## Workflow

### Step 1 — Gather inputs

Ask the user (or inspect their project to infer):

| Input | Default | Notes |
|---|---|---|
| `font-size` | **16px** | Base body font size in pixels |
| `content-width` | **680px** | Max width of readable content column |
| `format` | **css** | `css` (custom properties) or `scss` (variables) |
| `target` | **`.grt`** | CSS selector to scope applied styles |
| `output` | — | File path to write the stylesheet to |

If the user provides a live HTML file, web page, or project directory, inspect it first to infer the current font size and content width. Look for `font-size` and `max-width` values in existing CSS.

**Sensible defaults** if you need to just proceed:
- Blog/article site: 16–18px, 640–720px wide
- Marketing/landing page: 16–20px, 720–960px wide
- Documentation: 16px, 680px wide
- Mobile-first: 14–16px, treat content width as the readable column (often 320–480px)

### Step 2 — Run the calculator

The GRT calculator script is bundled with this skill at `scripts/grt.py` relative to the directory containing this SKILL.md file. Before running any command, resolve the absolute path to the skill directory (the folder containing this SKILL.md) — you can find it from the path you used to read this file.

```bash
# Generate CSS and print summary
python {SKILL_DIR}/scripts/grt.py \
  --font-size 16 \
  --content-width 680

# Generate SCSS variables
python {SKILL_DIR}/scripts/grt.py \
  --font-size 18 \
  --content-width 800 \
  --format scss \
  --output path/to/styles/_grt.scss

# Inject directly into an HTML file (adds <style> block inside <head>)
python {SKILL_DIR}/scripts/grt.py \
  --font-size 16 \
  --content-width 680 \
  --inject path/to/index.html

# Scan a project directory — saves grt.css and shows import instructions
python {SKILL_DIR}/scripts/grt.py \
  --font-size 16 \
  --content-width 680 \
  --scan path/to/project

# Get just the CSS (no summary)
python {SKILL_DIR}/scripts/grt.py \
  --font-size 16 \
  --content-width 680 \
  --css-only
```

**All flags:**
```
--font-size / -f       Base font size in pixels (required)
--content-width / -w   Column width in pixels (default: 680)
--format               css or scss (default: css)
--prefix               Variable name prefix (default: grt-)
--target               CSS selector (default: .grt)
--output / -o          Write to file path
--inject               Inject into HTML file
--scan                 Save to project dir and show import locations
--x-height             Font x-height ratio for correction (0.45–0.60)
--no-summary           Suppress the summary table
--css-only             Print CSS only, no summary
```

### Step 3 — Apply to project

Choose the right integration method based on what the user has:

#### HTML file (single page)
Use `--inject path/to/file.html`. This inserts a `<style>` block inside `<head>`, wrapped in `<!-- GRT-START -->` / `<!-- GRT-END -->` comments so it can be safely replaced on re-runs.

Add `class="grt"` to the `<html>` or `<body>` element (or adjust `--target` to match an existing wrapper selector like `.container` or `main`).

#### Web project (CSS/SCSS workflow)
Use `--scan path/to/project` to save `grt.css` or `grt.scss` to the project root. Then:
- **CSS**: add `@import url('./grt.css');` at the top of the main stylesheet, or add a `<link>` tag in HTML
- **SCSS**: add `@use './grt' as *;` or `@import './grt';` to the main `.scss` file

Then update the project's existing CSS to use the `--grt-*` variables or SCSS variables. For example:
```css
/* Before */
body { font-size: 16px; line-height: 1.5; }
h1 { font-size: 32px; }

/* After */
body { font-size: var(--grt-scale-1); line-height: var(--grt-lh-1); }
h1 { font-size: var(--grt-h1-size); line-height: var(--grt-h1-lh); }
```

#### Framework / design token project
Generate SCSS variables with `--format scss`. For Tailwind, generate a config extension. For CSS Modules, import the CSS file at the global level.

#### Just show the user the values
If the user wants to understand the numbers or apply them manually, run the script without `--output` and share the summary table.

---

## Understanding the output

### Typographic scale (CSS variables)
```
--grt-scale-1   body text (base)
--grt-scale-2   1 step × φ
--grt-scale-3   2 steps × φ²  ← h1 size for most sites
--grt-scale-4   3 steps × φ³  ← large display text
--grt-scale-5   4 steps × φ⁴  ← hero/poster text
--grt-scale-6   5 steps × φ⁵  ← very large display
```

### Heading scale
The practical heading scale uses half-phi steps to keep h1 at a reasonable size:
```
h1 = base × φ²        (≈ 2.6× base, e.g. ~42px for 16px)
h2 = base × φ^1.5     (≈ 2.1×, e.g. ~33px)
h3 = base × φ         (≈ 1.6×, e.g. ~26px)
h4 = base × √φ        (≈ 1.3×, e.g. ~20px)
h5 = base × φ^0.25    (≈ 1.1×, e.g. ~18px)
h6 = base              (same as body)
```

### Spacing units
Derived from the primary line height (`lh-1 = base × φ`):
```
xs  = lh / φ²
sm  = lh / φ
md  = lh           ← use this as the standard paragraph margin
lg  = lh × φ       ← heading top margin
xl  = lh × φ²
xxl = lh × φ³
```

### Applied `.grt` styles
The output CSS includes a ready-to-use `.grt` block that sets:
- Body font size and line height
- Paragraph/list max-width and rhythm
- All heading sizes and line heights
- Blockquote indentation and border
- Spacing utility classes (`.mt-sm`, `.mb-lg`, etc.)

---

## Tips for different scenarios

**The user wants to apply GRT to their whole site:**
Use `--target body` or `--target :root` so the styles apply globally without needing a wrapper class.

**The user's content is narrower or wider than expected:**
Adjust `--content-width` to match the actual readable column (the `max-width` of the `<article>`, `.content`, or `.prose` element, not the full page width).

**Fonts that need x-height correction:**
Some fonts (like Georgia, Merriweather) have unusually tall or short x-heights. Pass `--x-height 0.52` (or whatever the font's ratio is) to slightly adjust line heights. For web-safe fonts: Georgia ≈ 0.49, Arial ≈ 0.52, Times New Roman ≈ 0.45.

**The user has Tailwind CSS:**
Generate CSS variables and add them to `tailwind.config.js` under `theme.extend.fontSize` and `theme.extend.lineHeight`. Or use the CSS custom properties directly in Tailwind's JIT mode with `text-[var(--grt-h1-size)]`.

**The user wants relative units (rem/em instead of px):**
The script outputs px values. To convert: divide every px value by the root font size (usually 16). For example, `--grt-scale-1: 16px` becomes `--grt-scale-1: 1rem`.

**The user asks "what font size / line height should I use?":**
Start with `--font-size 16 --content-width 680` and show them the summary. Recommend increasing the base to 18–20px for longer-form reading content, and adjusting content-width to match their actual layout column.

---

## Reference

Formulas from [grtcalculator.com/math/](https://grtcalculator.com/math/):
- φ = (1 + √5) / 2 ≈ 1.618033988749895
- Typographic scale: f, f×φ, f×φ², f×φ³, f×φ⁴, f×φ⁵
- Base line height: h = f × φ
- Width-adjusted line height: uses content width and a width constant (W=34) to increase line height for longer lines
- X-height correction: adjusts h based on the font's x-height ratio relative to 1/φ ≈ 0.618
- Spacing: primary line height × powers of φ

Script: `scripts/grt.py` (relative to this skill's directory)
