# Performance Reference

Every project ships with these defaults. None are optional.

---

## _headers File

Place at `public/_headers`. Eleventy copies it to `_site/_headers` via passthrough.
Cloudflare Pages reads this file and applies headers at the CDN edge — no Worker needed.

```
# Immutable assets — fingerprinted by 11ty or manually versioned
/css/*
  Cache-Control: public, max-age=31536000, immutable

/images/*
  Cache-Control: public, max-age=31536000, immutable

/fonts/*
  Cache-Control: public, max-age=31536000, immutable
  Access-Control-Allow-Origin: *

# HTML — always revalidate
/*.html
  Cache-Control: public, max-age=0, must-revalidate
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin

# Root
/
  Cache-Control: public, max-age=0, must-revalidate
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin
```

---

## Semantic HTML Requirements

Every page must have:
- `<html lang="en">` (or correct language code)
- One `<h1>` per page — the page title, not the site name
- Logical heading hierarchy (h1 → h2 → h3, no skipping)
- `<main>`, `<nav>`, `<footer>` landmarks
- `<article>` for post/card content
- `alt` text on every `<img>` — descriptive, not "image of..." — empty `alt=""` only for decorative images
- `<time datetime="YYYY-MM-DD">` for all dates
- `aria-label` on icon-only links/buttons

---

## Image Requirements

### HTML
```html
<!-- Above fold (hero, LCP candidate) — NO lazy load, add fetchpriority -->
<img
  src="/images/hero.webp"
  alt="Descriptive text about the image"
  width="1200"
  height="630"
  fetchpriority="high"
>

<!-- Below fold — lazy load -->
<img
  src="/images/photo.webp"
  alt="Descriptive text"
  width="800"
  height="600"
  loading="lazy"
  decoding="async"
>
```

Always include `width` and `height` attributes to prevent layout shift (CLS).
Always reference `.webp` paths even if originals are jpg/png — the build script converts them.

### Format Rules
- Source files: any format (jpg, png, etc.) in `src/images/`
- Output: `.webp` at quality 85 via `scripts/images.js`
- Originals: never modified, never committed to `_site/`
- SVGs: pass through as-is, no conversion needed

---

## CSS Performance

- All CSS is in `src/css/` — never inline styles except for critical above-fold CSS
- No `@import` inside CSS files except `grt.css` at the top of `style.css`
- Load order in `<head>`: `grt.css` → `style.css`
- Fonts: use `font-display: swap` if loading from Google Fonts; prefer self-hosted for performance
- Self-hosted fonts go in `src/fonts/` and are declared with `@font-face` in `style.css`

### Self-Hosted Font @font-face Pattern
```css
@font-face {
  font-family: 'FontName';
  src: url('/fonts/fontname-regular.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
```

Preload the primary font in `<head>`:
```html
<link rel="preload" href="/fonts/fontname-regular.woff2" as="font" type="font/woff2" crossorigin>
```

---

## Meta Tags (Required for Every Page)

```html
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="...">  <!-- 150–160 chars -->
<link rel="canonical" href="https://domain.com/page-url/">

<!-- Open Graph -->
<meta property="og:title" content="...">
<meta property="og:description" content="...">
<meta property="og:url" content="https://domain.com/page-url/">
<meta property="og:type" content="website"> <!-- or "article" for posts -->
<meta property="og:image" content="https://domain.com/images/og.webp">
```

---

## Core Web Vitals Checklist

Before every prod deploy, verify:
- [ ] LCP image has `fetchpriority="high"` and NO `loading="lazy"`
- [ ] All images have explicit `width` and `height`
- [ ] No layout shift from font loading (`font-display: swap`)
- [ ] `_headers` file present in `_site/` after build
- [ ] No render-blocking scripts (use `defer` or `async` on all `<script>` tags)
- [ ] Heading hierarchy is logical (h1 → h2 → h3)
- [ ] All images are WebP
