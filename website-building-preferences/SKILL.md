---
name: website-building-preferences
description: >-
  Will's standing rules for every website Claude builds for him (written with Claude chat, adopted
  2026-10-23): GRT-first typography via grt.py, OKLCH palettes proposed as 2-3 options, no AI-slop
  defaults, hand-written CSS + vanilla JS + Eleventy, self-hosted fonts, Playwright screenshot loop,
  Cloudflare Pages via dashboard Git integration, WordPress-to-11ty migration rules, per-project
  notes (williejackson.com, abernathymagazine.com, photos.jackson2w.com). Load BEFORE any website,
  landing page, redesign, migration, 11ty, GRT, typography, palette or Cloudflare Pages work for Will.
  Trigger phrases: "build me a website", "new site", "landing page", "redesign", "migrate from
  WordPress", "11ty", "eleventy", "golden ratio typography", "GRT", "grt.py", "palette", "font pairing".
---

# Website-building preferences (Will)

## Local notes (read first; these amend the document below)

- **Caching is HELD (Will, 2026-10-23).** Don't add immutable `Cache-Control` rules, CSS fingerprinting
  or rename-on-change image rules from §10 until Will lifts the hold: during iteration they keep old
  files cached and make updates hard to see. Security headers on `/*` are fine.
- **Install:** this file is the global copy (synced via the skills repo). `grt.py` lives next to it and
  is symlinked at `~/.claude/tools/grt.py`. Each site repo also carries a `CLAUDE.md` with its own
  §13 entry; the repo file wins.
- **grt.py v2 (2026-10-23, Will approved the fix).** Rebuilt on the calculator's published equation
  (grtcalculator.com/math/): `h = f·[(3−φ) + (2φ−3)·w/(34f) + c]`, `c = (x − (φ−1))/φ`, with sizes rounded
  to whole px before their line heights and spacing chain-rounded, exactly as the calculator does.
  `--self-test` replays **168 stored calculator answers** (6 fonts × 7 sizes × 4 widths) and matches all of
  them. Output is rem plus Utopia-style fluid `--grt-step-N` / `--grt-step-lh-N`; no border-left quotes.
  v1 ran heading line heights 4–8% tight.
- **x-height means x-height ÷ CAP height** in GRT. §3's `--x-height 0.49`-style values are x-height ÷ em and
  give wrong line heights; v2 refuses `--x-height` and takes `--font-file <ttf/otf>` (reads OS/2) or
  `--x-ratio`. File-measured ratios can differ slightly from the calculator's browser-measured ones
  (Source Serif 4 0.709 vs 0.736, ≤1 px difference); the calculator applies no correction at all for fonts it
  has no data for (Inter: implied 0.618). Prefer the font file: it's reproducible for any face.
- **Preview deploys:** throwaway mockups go to the Direct Upload project `wj-site-mockups` (wj-site-mockups.pages.dev) with `CF_PAGES_TOKEN` (Infisical homelab-fleet/dev, Pages Write, Will 2026-10-23). Create new Pages projects via the API, not `wrangler pages project create` (see cloudflare-pages-gotchas). Never touch the live `j2wtalent` Pages project from a mockup.
- Reference sites and measured values: `website-design-references` skill. Where a reference site
  uses something §7 bans (neverenough.com's cream paper, small-caps eyebrows), this document wins.

---

# Website-Building Preferences: Will Jackson

Global preferences for every website Will builds with you. Drop this in `~/.claude/CLAUDE.md` (global) or a repo root.
Precedence: a project's own `CLAUDE.md` > this file > your defaults. If an `AESTHETICS.md` exists alongside this file, read it before any design work.

Will's site entity name is **"Willie Jackson"** (structured data, author fields, copyright). In conversation he goes by Will.

---

## 0. The non-negotiables (read even if you read nothing else)

1. **GRT first.** Golden Ratio Typography sets every font size, line height and spacing value. Run `grt.py` before writing CSS. Never hardcode type or spacing values.
2. **Color is proposed, never defaulted.** Give 2–3 OKLCH palette options per site, then wait for a pick.
3. **No AI-slop defaults.** See §7. When in doubt, the generic choice is the wrong one.
4. **Playwright screenshot loop before any UI is called done.** Desktop and mobile widths, then look at the screenshots and fix what you see.
5. **Performance ships by default.** Semantic HTML, `_headers`, sized/lazy images, self-hosted fonts, no render-blocking JS.
6. **Hand-written CSS. Vanilla JS. 11ty.** No Tailwind, no CSS or animation frameworks, no SPA frameworks, and don't propose switching to Astro.
7. **Confirm before deploying to production**, unless a project file says otherwise.
8. **Never commit or embed secrets.** That includes tokens in git remote URLs.

---

## 1. How to work with Will

- Planning and research happen in Claude.ai, and you do the implementation. Treat any spec file or checklist in the repo (`SPEC-*.md`, tiered checklists) as the brief.
- **Work in phases. Don't expand scope.** If something is marked "held" or "Tier 2," leave it alone and note anything you'd add for later.
- **Be opinionated, terse and prioritized.** Make a concrete recommendation with a one-line reason, not a menu of vague categories.
- **Before committing to any design direction, show 2–3 concrete options** (type pairing, palette, layout) and offer to mock them up. Commit fully once Will picks.
- Identify the mode up front: **New site**, **Migration** (WordPress → 11ty) or **Add page**. Ask if it's unclear.
- For a new site, collect: project slug, purpose/audience (1–2 sentences), aesthetic direction, base font size, content column width, brand colors or references, and whether search/pagination is needed.
- **No manual steps beyond the terminal.** If something can only be done in a dashboard (custom domains, Git connection), say exactly where to click.
- When revising, **preserve Will's own edits and wording.** List any text you changed.
- Will prefers methodical, repeatable systems over one-off fixes. If something will recur across sites, suggest making it a plugin, include or script.
- Avoid jargon in UI copy and in explanations.

---

## 2. Stack defaults

| Layer | Default |
|---|---|
| Generator | Eleventy (11ty) v3, Nunjucks + Markdown |
| CSS | Hand-written, custom properties, GRT tokens. No frameworks. |
| JS | None by default. Vanilla, `defer`red. Use islands (`<is-land>`) for anything heavy. |
| Typography | GRT (`grt.py`) → Utopia fluid type calibrated to GRT |
| Color | OKLCH tokens |
| Images | Build-time pipeline: AVIF + WebP fallback, originals untouched (see §10) |
| Search | Pagefind (post-build, static, no service) |
| SEO | `eleventy-plugin-jackson-seo` (Will's private GitHub plugin) when available |
| CMS (if editing needed) | Sveltia CMS (git-based, mobile-friendly) |
| Hosting | Cloudflare Pages, Git-integrated with GitHub |
| QA | Playwright screenshots |

### Scaffold

```
{slug}/
├── src/
│   ├── _includes/   base.njk, nav.njk, footer.njk (+ post.njk etc.)
│   ├── _data/       site.js  (name, url, description, author: "Willie Jackson")
│   ├── css/         grt.css (GENERATED, never hand-edit) + style.css
│   ├── images/      source originals (never modified)
│   ├── fonts/       self-hosted woff2
│   └── index.njk
├── public/          _headers, _redirects  (passthrough to _site root)
├── scripts/         image pipeline, etc.
├── eleventy.config.js (or existing .eleventy.js; match what's there)
├── package.json     scripts: dev, build, build:prod, deploy:preview, deploy:prod
└── wrangler.toml    minimal: name + pages_build_output_dir = "_site"
```

`.gitignore`: `node_modules/ _site/ .DS_Store .env .dev.vars`. `_site/` is always a build artifact.

---

## 3. Typography

### GRT is mandatory and comes first
The calculator lives at `~/.claude/tools/grt.py` (copy it there, or into the repo's `scripts/`).

```bash
python3 ~/.claude/tools/grt.py --font-size 18 --content-width 680 --x-height 0.49 \
  --target body --output src/css/grt.css
```

| Site type | font-size | content-width |
|---|---|---|
| Content / article / magazine | 18 | 680 |
| Portfolio / professional | 17 | 720 |
| Marketing / landing | 16 | 860 |
| Documentation | 16 | 680 |

- `--content-width` is the **readable column** (the article's `max-width`), not the page width.
- x-height: Georgia/Merriweather/Lora 0.49 · Playfair 0.47 · Source Serif 0.50 · DM Sans/Nunito Sans/Work Sans 0.53 · most other sans 0.52. Measure it if the font isn't listed.
- Always `--target body`. Regenerate (don't edit) when base size, column width (>40px change) or primary typeface changes.
- Tokens it produces: `--grt-scale-1..6`, `--grt-lh-1..6`, `--grt-h1-size..h6-size`, `--grt-h1-lh..h6-lh`, `--grt-space-xs|sm|md|lg|xl|xxl`, `--grt-content-width`.
- Map: body → `scale-1`/`lh-1`; paragraph margin → `space-md`; heading top margin → `space-lg`; section padding → `space-xl`; component gap → `space-sm`. Only one derived value is allowed: metadata/bylines at `calc(var(--grt-scale-1) * 0.85)`.
- Load `grt.css` via a `<link>` before `style.css`. **Do not also `@import` it** from `style.css`, because that loads it twice.

```css
/* Never */  h1 { font-size: 42px; line-height: 1.2; }
/* Always */ h1 { font-size: var(--grt-h1-size); line-height: var(--grt-h1-lh); }
```

### Then make it fluid (Utopia, anchored to GRT)
GRT values are the **max-viewport** sizes. Generate Utopia `clamp()` steps so the large end equals GRT:
- Max: base = GRT base; ratio = √φ ≈ **1.272** (this lands step 1–4 on GRT's h4, h3, h2, h1 exactly).
- Min (around 360px viewport): base 1–2px smaller, ratio ~1.2.
- Formula: `slope = (max − min) / (maxVw − minVw)`; `clamp(min, (min − slope·minVw) + slope·100vw, max)`. Express sizes in **rem**, not px, so a user's browser font setting is respected.
- Convert GRT line heights to unitless ratios (`lh / size`) so they scale with fluid sizes.

### Typefaces
- **No house style.** Every site gets its own pairing, proposed as 2–3 options tied to the aesthetic direction.
- Not as defaults: Inter, Roboto, Arial, system-ui-only. Also avoid reaching for the stock "AI editorial" pairings (Playfair + Source Serif, Instrument Serif + DM Sans, Fraunces + anything) unless Will picks one on purpose.
- Prefer one family with hierarchy through weight and size, or one deliberate pair. Use 4–5 sizes, reused.
- Self-host `woff2` in `src/fonts/`, subset where possible, `font-display: swap`, and preload only the primary body face.

---

## 4. Color
- OKLCH everywhere: `--color-bg`, `--color-text`, `--color-accent`, `--color-border`, `--color-muted`, all on `:root`.
- **Propose 2–3 palettes and wait.** Never ship a placeholder palette as the real one.
- Contrast: 4.5:1 for body/small text, 3:1 for large text and UI. A bright accent usually fails at small sizes, so use it for large text, shapes and markers and derive a darker, text-safe variant for links and labels.
- Client work: get the **real, current** brand first (live site computed styles, current template, logo files). Check dates, because old templates lie.

## 5. Layout and design
- **Choose layout from the content**, not from a template: a real timeline, a real table, split panels, plain lists separated by rules.
- Vertical rhythm comes from GRT spacing tokens only.
- Vary the pacing. Sparse sections, dense working sections and generous whitespace on statements. Not every section should have the same margins, density and structure.
- At most one brand-native motif, used sparingly and consistently.
- Reference shelf (study for craft, don't copy): craigmod.com, andy-bell.co.uk, frankchimero.com, robinrendle.com, klim.co.nz.
- Aesthetic lanes to offer when no direction is given: editorial/magazine, luxury/refined, brutalist/raw, warm/professional, minimal/clean, bold/expressive.

## 6. Motion
- Transitions only. Use native cross-document View Transitions (`@view-transition { navigation: auto; }`) as progressive enhancement.
- No animation libraries unless justified in writing first.
- Always honor `prefers-reduced-motion`.

## 7. Never do these (AI-slop tells)

**Visual**
- Cream/beige backgrounds with terracotta or brick-red accents (the default AI palette)
- Generic serif-plus-sans "editorial" pairings unrelated to the brand
- Small uppercase, letter-spaced eyebrow labels above every heading
- Colored accent bars on every block
- Rows of identical rounded, thin-bordered cards, section after section
- "01 / 02 / 03" numbering used as decoration
- Italic pull quotes with a colored left border (use large plain text with real quotation marks and thin rules instead; override GRT's default blockquote border if needed)
- Stat tiles giving many numbers equal weight, and invented round numbers
- "Diagrams" that are a row of boxes with arrows
- Decorative elements that carry no meaning; generic stock imagery
- **Image hover zoom/scale effects** (`transform: scale()` on `:hover`)
- The same footer text repeated for no reason

**Copy** (if you write any placeholder or real copy)
- Em dashes; "It's not X, it's Y"; reflexive groups of three; colon titles everywhere; filler that could belong to anyone; jargon
- Never invent testimonials, stats or client names. Use obvious `[PLACEHOLDER]` markers.

---

## 8. HTML and accessibility (every page)
- `<html lang="en">`; one `<h1>` per page (the page title, not the site name); no skipped heading levels
- `<main>`, `<nav>`, `<footer>` landmarks; `<article>` for posts and cards
- Descriptive `alt` on every `<img>` (`alt=""` only for decorative images)
- `<time datetime="YYYY-MM-DD">` for dates; `aria-label` on icon-only links and buttons
- Visible focus styles; full keyboard navigation; nav and footer get `data-pagefind-ignore`

## 9. SEO and sharing
- Every page: description (150–160 chars), canonical, OG title/description/url/type (`article` for posts), `og:image` at 1200×630.
- **Use JPG or PNG for `og:image`**, not WebP. Support for WebP in social previews is inconsistent, and Will cross-posts to LinkedIn.
- JSON-LD `@graph` with `@id` cross-links: Person ("Willie Jackson"), WebSite, BlogPosting, BreadcrumbList. Use `eleventy-plugin-jackson-seo` if it's installed instead of hand-rolling.
- Sitemap and robots.txt generated at build time. `llms.txt` is low priority, so skip it unless asked.

## 10. Performance

### Images
- Source originals live in `src/images/` and are **never modified**. The build generates derivatives (prefer `@11ty/eleventy-img` or a `sharp` script): **AVIF primary, WebP fallback** via `<picture>`, responsive `srcset`/`sizes`, blur-up LQIP for large photos.
- Always set `width` and `height` (or `aspect-ratio`) to prevent layout shift.
- LCP/hero image: `fetchpriority="high"` and **no** `loading="lazy"`. Everything below the fold gets `loading="lazy" decoding="async"`.
- Never replace an image in place under the same filename (it's cached as immutable). Rename it instead.
- SVGs pass through untouched.

### CSS, JS and fonts
- All CSS in `src/css/`. Inline only critical above-the-fold CSS.
- Fingerprint CSS URLs (a content-hash query string via an 11ty filter) so the immutable cache rule is safe.
- Every `<script>` gets `defer` or `async`. Zero JS is the target for content pages.

### `public/_headers`
Cloudflare **joins duplicate headers with commas** when several rules match, so never put `Cache-Control` on `/*`. Security headers go on `/*` and cache headers go on asset paths only:

```
/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin

/css/*
  Cache-Control: public, max-age=31536000, immutable
/images/*
  Cache-Control: public, max-age=31536000, immutable
/fonts/*
  Cache-Control: public, max-age=31536000, immutable
/pagefind/*
  Cache-Control: public, max-age=31536000, immutable
```
(A `/*.html` rule does not match 11ty's pretty URLs like `/about/`, so don't use one.)

### Pre-deploy Core Web Vitals check
- [ ] LCP image is prioritized and not lazy
- [ ] All images have dimensions and AVIF/WebP derivatives exist in `_site/`
- [ ] Fonts don't shift layout
- [ ] `_site/_headers` (and `_redirects` if any) exist after build
- [ ] No render-blocking scripts
- [ ] Heading hierarchy is clean
- [ ] Playwright screenshots reviewed at ~390px and ~1280px

---

## 11. WordPress → 11ty migrations
- Prefer a clean migration (no headless WordPress). Use `@11ty/import` (or `wordpress-export-to-markdown` if a project already uses it) to produce `src/posts/*.md` with frontmatter and downloaded images.
- **Preserve URLs exactly.** Use computed permalinks that match the old structure, plus `public/_redirects` 301s for anything that moves. Test 3–5 old URLs.
- **Preserve RSS GUIDs** in WordPress `?p=<id>` form so subscribers don't get re-flooded. Use `@11ty/eleventy-plugin-rss`.
- Build-time pagination (12 per page), category pages, Pagefind with `data-pagefind-body` on articles and `data-pagefind-filter="category:…"`. Pagefind runs **after** eleventy in the `build` script.
- Before the first deploy, confirm the post count in `_site/` matches WordPress and that category pages, `/page/2/`, the search index, image derivatives and redirects all work.

## 12. Deploy (Cloudflare Pages + GitHub)
- **Create long-lived sites in the Cloudflare dashboard with Git integration** (Pages → Create → Connect to Git; build `npm run build`, output `_site`). Pushing to `main` deploys production; any other branch gets a preview URL.
- **Do not run `npx wrangler pages project create` for a real site.** That makes a Direct Upload project, which can never be switched to Git integration. Direct Upload is fine only for throwaway mockups. Git-integrated projects can still take manual `wrangler pages deploy` uploads when needed.
- Keep `wrangler.toml` minimal. Its `name` must equal the Pages project name.
- Custom domains are set up in the dashboard (Pages → project → Custom domains).
- Secrets: `.env`/`.dev.vars` are gitignored; use `wrangler pages secret put`. Authenticate git with `gh auth login` or a credential helper. **Never embed a PAT in the remote URL.**
- Git: stage specific files (no blind `git add -A`), use conventional commits (`feat: fix: style: chore: docs: refactor:`), and never force-push `main`.
- Pushing to `main` is a production deploy, so **confirm first** unless the project's `CLAUDE.md` says to auto-push.

### End every session that changed files with:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEPLOY: {Project}
Preview:     git push origin <branch>   (or npm run deploy:preview)
Production:  git push origin main       (or npm run deploy:prod)
Changed:     <files>
Check:       <URLs to eyeball>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 13. Known projects (move these into each repo's own CLAUDE.md)
- **williejackson.com.** *Status 2026-11-01:* an **interim** static copy on Pages (Git-integrated project `williejackson-com-static`, repo `jackson2w/williejackson-com-static`, `public/`), exported from a private WordPress on homelab CT 144 (`wordpress.tail922cee.ts.net/wp-admin`, Tailscale only). That WordPress is the import source for the rebuild below. See `wordpress-static-export`. The plan stays: WordPress → 11ty, about 100 posts (58 published as of 11-01). Flat root-level permalinks with no dates; preserve them exactly. RSS GUIDs as `?p=<wpId>`. Sveltia CMS for mobile editing. Uses the jackson-seo plugin. Aesthetic direction is minimal/clean; typeface still open. Needs positioning content tying Will to talent management.
- **abernathymagazine.com.** Static redesign, repo `jackson2w/abernathymagazine`, auto-deploys on push to `main`. **Auto-commit and push after every change** (project override of §12). Atlantic-inspired. GRT at 18px base / 640px text column / 1080px image column. Playfair Display (headings), Source Serif 4 (body), Inter (UI labels only). Link-hover accent `#e7131a`. Italic serif bylines, centered under the title, author name linked to the archive. No image hover effects.
- **photos.jackson2w.com.** Photo pipeline: AVIF, Display-P3, blur-up LQIP, EXIF extraction via prepare scripts.

## 14. Decisions log (where older skill notes were superseded)
- WebP-only at quality 85 → **AVIF + WebP fallback** (matches the newer photo pipeline).
- Hex color tokens → **OKLCH, proposed per site**.
- Static px GRT → **GRT + Utopia fluid, in rem**.
- The suggested font-pairing list and the terracotta `#c45c2e` example accent were **dropped** because they match the slop defaults in §7.
- The "pull quotes: italic + left border" magazine pattern was **dropped** (§7).
- `wrangler pages project create` as step one → **dashboard Git integration** (Direct Upload lock-in).
- The `_headers` `/*.html` rule plus HTML Cache-Control → **security headers on `/*`, cache rules on assets only**.
- `grt.css` both linked and `@import`ed → **linked only**.
- `wordpress-export-to-markdown` → **`@11ty/import` preferred**.
