---
name: website-design-references
description: >-
  Will's reference sites for the websites he has Claude build: what he likes about each, with the
  exact fonts, sizes, colours, spacing and interaction details measured from the live site, so a
  new site can start from proven choices instead of a fresh guess. Starts with neverenough.com
  (Andrew Wilkinson's essay site: warm paper and ink, three-serif-family editorial typography,
  62ch measure, drop cap, small-caps eyebrows, paper grain, ink-wipe buttons). Use when building
  or redesigning any website, blog, essay or long-form reading page, personal site, landing page
  or newsletter page for Will. Trigger phrases include "build me a website", "new site",
  "personal site", "blog design", "essay page", "make it look like neverenough", "editorial
  typography", "reading experience", "the look I like", "design reference".
---

# Website design references

Sites Will has pointed at and said "I like this". Each entry records **what he named** and
**measured values** (pulled from the live CSS, not eyeballed). Use them as the starting point for a
new site; don't copy a site's identity (name, logo, signature, colours as a set), borrow its
decisions.

**Will's rules win over any reference site.** Load `website-building-preferences` first; where a reference uses something its §7 bans (cream paper with warm accents, small-caps eyebrow labels, decorative numbering), take the craft, not the pattern.

When Will names a new reference site, analyse it the same way (fetch the HTML and the CSS bundle,
read `@font-face`, `:root`/theme variables and the article markup) and add an entry here.

## neverenough.com (added 2026-10-23)

Andrew Wilkinson's essay/newsletter/book site. Will: "I like the typography, the layout, the
simplicity." Reference page: `/essays/i-got-diagnosed-with-a-brain-disorder`.

**Platform:** Next.js (App Router, Turbopack build, `next/font`, `next/image`, generated
`opengraph-image` per essay) on **Vercel**, styled with **Tailwind CSS v4**. No headless CMS is
visible, and images are served from the site's own `/photos/`, so the essays most likely live in
the repo as Markdown/MDX. GTM for analytics. For Will's sites the equivalent is a static build
(11ty or Astro) on **Cloudflare Pages**: nothing on this site needs a server.

### Typography: three families, each with one job
| Role | Font | Used for |
|---|---|---|
| Display | **Newsreader** (variable, opsz, italic) | headlines, h2/h3, pull quotes, wordmark, eyebrows, drop cap |
| Text | **Source Serif 4** (variable) | body copy, card blurbs, form inputs |
| UI | **Inter Tight** | nav, buttons, read-time/date meta |
| Labels | **JetBrains Mono** | breadcrumbs, card meta (`2 MIN · APRIL 29, 2026`), signature line |

All free on Google Fonts. Fallback stacks name the premium faces they stand in for
(`"GT Sectra", "Tiempos Headline"` / `"Tiempos Text"`), so the design intent is
Tiempos-style editorial.

- Body: **1.1875rem (19px), line-height 1.7, max-width 62ch**, paragraphs `mb-7`. Site-wide base 1.125rem / 1.6667.
- H1: 2.25 → 2.75 → 3.25 → 3.5rem across breakpoints, **leading 1.04, tracking -0.018em**; one word set in *italic* for voice ("I *got* diagnosed…").
- H2: 1.75–2rem, leading 1.18, tracking -0.012em, `mt-14 mb-5`. H3: 1.375rem **italic** display.
- Blockquote: display italic 1.5–1.75rem, centred, max 52ch, in the accent blue.
- **Drop cap** on the first paragraph: display face, 4.6em, weight 500, accent colour, floated; first paragraph slightly larger (1.21rem).
- **Eyebrow** labels: display face in **true small caps** (`font-variant-caps: all-small-caps`, `smcp`/`c2sc`), 0.9375rem, +0.05em, soft ink.
- Mono labels: 0.6875rem, uppercase, **tracking 0.14–0.16em**.
- `text-wrap: balance` on headings/eyebrows, `pretty` on body; `hanging-punctuation: first last allow-end`; `font-feature-settings: "kern","liga","calt"`; `text-rendering: optimizeLegibility`.
- Header wordmark uses `font-variation-settings: 'opsz' 36`, i.e. the optical size axis is used on purpose.

### Colour: paper and ink, light + dark
| Token | Light | Dark |
|---|---|---|
| paper (bg) | `#f4eee2` | `#17130f` |
| paper-deep (code, wells) | `#ebe3d3` | `#211a14` |
| paper-shadow (rules, borders) | `#d9cfb8` | `#3a3026` |
| ink (text) | `#1c1b18` | `#f1e7d5` |
| ink-soft (meta) | `#5a554b` | `#b9ab95` |
| signature (links, drop cap, quotes) | `#2b4570` | `#9fb8ee` |
| coffee (hover, focus) | `#1f4ea8` | `#d99a56` |
| margin (red-pen accent) | `#b8361f` | `#e46d55` |

Warm off-white and near-black, never pure `#fff`/`#000`. One cool accent (fountain-pen blue) for
links, plus a hover colour. Dark mode is a `html.dark` class toggle (sun/moon button in the
header). `::selection` is accent-on-paper.

### Layout
- Sticky header: `bg-paper/88` + `backdrop-blur-sm` + hairline bottom rule; wordmark left, 6 small sans nav links centred, theme toggle, then a black **Subscribe** button. Mobile collapses nav into a menu button; tap targets 44px (`h-11`).
- Article: breadcrumb (mono) → eyebrow category → H1 → `10 min read · March 12, 2025` with a hairline under it → body.
- Body column 62ch; from `xl`, an **18rem sticky right rail** ("Filed under" categories). Plenty of side margin otherwise.
- Ending: handwritten **signature image** + mono line `Andrew · Victoria · March 12, 2025`; then "Read next" (3 cards, top hairline, mono meta, display title, serif blurb, "Read →"); then a book promo; then "Keep reading".
- Sections separated by **hairline rules** (`border-paper-shadow/60`) and big vertical gaps (`mt-20`), never boxes or shadows. Radius is tiny (2–3px) everywhere.
- In-article newsletter form: italic display line ("I send one of these roughly monthly. About 30,000 people read it.") + email + button.

### Texture and motion (subtle, all disabled by `prefers-reduced-motion`)
- **Paper grain:** a fixed `body::before` with an inline SVG `feTurbulence` noise at **4.5% opacity**, `mix-blend-mode: multiply` (screen, 3.5% in dark), drifting slowly (32s).
- **Ink-wipe button** (`.btn-ink`): ink background; a coffee-coloured `::before` scales in from the left on hover (`scaleX`, 0.42s `cubic-bezier(.77,0,.175,1)`), quicker out.
- Links: accent colour, **1px underline at 40% opacity, offset 3px**, turning to the hover colour.
- Page-load "veil" fade, headline lines rising in with a 3px blur, drop cap scaling in, pull quotes sliding in on scroll; book cover floats gently. One shared easing `--ease-ink: cubic-bezier(.22,.61,.36,1)`.
- Subscribe button pulses every 7s (pauses on hover). Use sparingly; it's the one attention-seeking thing on the page.

### What to take, in order of value
1. The three-serif-family split (display / text / UI sans) with mono for metadata.
2. 19px / 1.7 / 62ch body, tight-leading big display headlines.
3. Warm paper + ink palette with one blue accent, and a real dark mode.
4. Small-caps eyebrows, drop cap, italic voice words, hairline rules instead of boxes.
5. Grain and ink-wipe hover, only if the site is a reading site; skip the pulse and load animations for tools/dashboards.
