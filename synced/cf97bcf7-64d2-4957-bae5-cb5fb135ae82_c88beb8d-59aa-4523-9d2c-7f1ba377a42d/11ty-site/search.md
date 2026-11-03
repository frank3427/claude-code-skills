# Search, Filtering, and Pagination Reference

Use this reference when a project needs search, category filtering, or paginated archives.
Primary use case: Abernathy Magazine WordPress migration.

---

## Pagination — 11ty Native (Free, Build-Time)

11ty generates paginated pages at build time. No JavaScript required.

### Post Archive with Pagination

In `src/posts.njk` (or `src/blog/index.njk`):

```njk
---
pagination:
  data: collections.post
  size: 12
  alias: posts
  reverse: true
permalink: "/{% if pagination.pageNumber > 0 %}page/{{ pagination.pageNumber + 1 }}/{% endif %}"
---
{% extends "base.njk" %}
{% block content %}
<section class="post-grid">
  {% for post in posts %}
  <article class="post-card">
    <a href="{{ post.url }}">
      {% if post.data.featuredImage %}
      <img src="{{ post.data.featuredImage }}" alt="{{ post.data.title }}" loading="lazy" decoding="async">
      {% endif %}
      <h2>{{ post.data.title }}</h2>
      <time datetime="{{ post.date | dateIso }}">{{ post.date | dateReadable }}</time>
      {% if post.data.excerpt %}<p>{{ post.data.excerpt }}</p>{% endif %}
    </a>
  </article>
  {% endfor %}
</section>

{% if pagination.href.previous or pagination.href.next %}
<nav class="pagination" aria-label="Post navigation">
  {% if pagination.href.previous %}
  <a href="{{ pagination.href.previous }}" class="pagination__prev">← Newer</a>
  {% endif %}
  {% if pagination.href.next %}
  <a href="{{ pagination.href.next }}" class="pagination__next">Older →</a>
  {% endif %}
</nav>
{% endif %}
{% endblock %}
```

### Per-Category Pages with Pagination

In `.eleventy.js`, add a collection per category:

```js
// Auto-generate a collection for each unique category tag
eleventyConfig.addCollection("postsByCategory", function(collectionApi) {
  const posts = collectionApi.getFilteredByTag("post");
  const byCategory = {};
  posts.forEach(post => {
    const cats = post.data.categories || [];
    cats.forEach(cat => {
      if (!byCategory[cat]) byCategory[cat] = [];
      byCategory[cat].push(post);
    });
  });
  return byCategory;
});
```

Then create `src/category/[category].njk` using 11ty's `pagination` over the category data.

Add date filters to `.eleventy.js`:
```js
const { DateTime } = require("luxon");
eleventyConfig.addFilter("dateIso", date => DateTime.fromJSDate(date).toISODate());
eleventyConfig.addFilter("dateReadable", date => DateTime.fromJSDate(date).toFormat("LLLL d, yyyy"));
```

Add `luxon` to package.json devDependencies.

---

## Search — Pagefind

Pagefind runs after the 11ty build and indexes all HTML output. It generates a WASM-based
search UI that ships as a small static bundle (~10KB). No external service, no API key,
no ongoing cost. Works on Cloudflare Pages with zero configuration.

### Install

```bash
npm install --save-dev pagefind
```

### Add to package.json Scripts

```json
"build": "eleventy && pagefind --site _site --output-path _site/pagefind",
"build:prod": "eleventy && pagefind --site _site --output-path _site/pagefind && node scripts/images.js",
```

Pagefind must run **after** eleventy so it indexes the full built HTML.

### Add Search UI to a Page

Add to any template where search should appear (e.g., a dedicated `/search/` page or the nav):

```html
<!-- In <head> -->
<link href="/pagefind/pagefind-ui.css" rel="stylesheet">

<!-- Where search box should appear -->
<div id="search"></div>

<!-- Before </body> -->
<script src="/pagefind/pagefind-ui.js"></script>
<script>
  new PagefindUI({
    element: "#search",
    showSubResults: true,
    excerptLength: 15
  });
</script>
```

### Control What Gets Indexed

Exclude elements from search index using `data-pagefind-ignore`:
```html
<nav data-pagefind-ignore>...</nav>
<footer data-pagefind-ignore>...</footer>
```

Tag content for filtering by category:
```html
<!-- In post template, inside <article> -->
<article data-pagefind-filter="category:{{ category }}">
```

This enables Pagefind's built-in filtering UI — users can filter results by category
without any additional code.

### _headers Addition for Pagefind Assets

Add to `public/_headers`:
```
/pagefind/*
  Cache-Control: public, max-age=31536000, immutable
```

---

## Category Index Pages

Generate a category index page automatically. In `src/categories/index.njk`:

```njk
---
title: Categories
permalink: /categories/
---
{% extends "base.njk" %}
{% block content %}
<h1>Categories</h1>
<ul class="category-list">
  {% for tag in collections | keys %}
  {% if tag != "all" and tag != "post" %}
  <li><a href="/category/{{ tag | slug }}/">{{ tag }}</a></li>
  {% endif %}
  {% endfor %}
</ul>
{% endblock %}
```

---

## Recommended Search Page Layout

Create `src/search/index.njk`:

```njk
---
title: Search
permalink: /search/
---
{% extends "base.njk" %}
{% block content %}
<section class="search-page">
  <h1>Search</h1>
  <div id="search"></div>
</section>
{% endblock %}
```

Style `.pagefind-ui` in `style.css` using GRT variables and project color palette.
Pagefind UI exposes CSS custom properties for theming:

```css
.pagefind-ui {
  --pagefind-ui-scale: 1;
  --pagefind-ui-primary: var(--color-accent);
  --pagefind-ui-text: var(--color-text);
  --pagefind-ui-background: var(--color-bg);
  --pagefind-ui-border: var(--color-border);
  --pagefind-ui-font: var(--font-body);
}
```
