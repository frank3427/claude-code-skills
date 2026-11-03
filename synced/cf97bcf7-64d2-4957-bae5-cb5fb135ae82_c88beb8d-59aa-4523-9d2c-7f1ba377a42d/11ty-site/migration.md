# WordPress Migration Reference

Use this reference when converting a WordPress site to a static 11ty site.
Primary use case: Abernathy Magazine (abernathymagazine.com → static 11ty + Cloudflare Pages).

---

## Migration Overview

```
WP XML Export
    ↓
wordpress-export-to-markdown  →  src/posts/*.md  (with frontmatter)
    ↓                         →  src/images/*    (downloaded originals)
11ty build                    →  _site/          (HTML output)
    ↓
pagefind --site _site         →  _site/pagefind/ (search index)
    ↓
scripts/images.js             →  _site/images/*.webp (WebP conversion)
    ↓
wrangler pages deploy _site
```

---

## Step 1 — Export from WordPress

In WordPress admin: **Tools → Export → All content → Download Export File**

This produces a `.xml` file (e.g., `abernathy.wordpress.xml`).

---

## Step 2 — Convert to Markdown

```bash
# Install globally (one-time)
npm install -g wordpress-export-to-markdown

# Run the converter
wordpress-export-to-markdown \
  --input abernathy.wordpress.xml \
  --output src/posts \
  --post-folders false \
  --include-other-types false \
  --save-attached-images true \
  --save-scraped-images true
```

This produces:
- `src/posts/post-slug.md` for each published post
- `src/images/` with downloaded featured images

### Frontmatter Output

Each `.md` file gets frontmatter like:
```yaml
---
title: "Post Title"
date: 2015-03-14
author: willie jackson
categories:
  - Culture
  - Business
excerpt: "First paragraph or manual excerpt"
featuredImage: /images/filename.jpg
slug: post-slug
---
```

---

## Step 3 — 11ty Configuration for Posts

In `.eleventy.js`, add the posts collection and tag handling:

```js
const { DateTime } = require("luxon");

module.exports = function(eleventyConfig) {
  // Passthrough
  eleventyConfig.addPassthroughCopy("src/css");
  eleventyConfig.addPassthroughCopy("src/images");
  eleventyConfig.addPassthroughCopy("src/fonts");
  eleventyConfig.addPassthroughCopy("public");

  // Watch CSS
  eleventyConfig.addWatchTarget("src/css/");

  // Date filters
  eleventyConfig.addFilter("dateIso", date =>
    DateTime.fromJSDate(date, { zone: "utc" }).toISODate()
  );
  eleventyConfig.addFilter("dateReadable", date =>
    DateTime.fromJSDate(date, { zone: "utc" }).toFormat("LLLL d, yyyy")
  );
  eleventyConfig.addFilter("slug", str =>
    str.toLowerCase().replace(/\s+/g, "-").replace(/[^\w-]/g, "")
  );

  // Posts collection — sorted newest first
  eleventyConfig.addCollection("post", function(collectionApi) {
    return collectionApi
      .getFilteredByGlob("src/posts/*.md")
      .sort((a, b) => b.date - a.date);
  });

  // Collections by category
  eleventyConfig.addCollection("categories", function(collectionApi) {
    const posts = collectionApi.getFilteredByGlob("src/posts/*.md");
    const cats = new Set();
    posts.forEach(p => (p.data.categories || []).forEach(c => cats.add(c)));
    return [...cats].sort();
  });

  return {
    dir: {
      input: "src",
      output: "_site",
      includes: "_includes",
      data: "_data"
    },
    templateFormats: ["njk", "md", "html"],
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk"
  };
};
```

---

## Step 4 — Post Template

`src/_includes/post.njk`:
```njk
---
layout: base.njk
---
<article class="post grt" data-pagefind-body>
  <header class="post__header">
    {% for cat in categories %}
    <a href="/category/{{ cat | slug }}/"
       class="post__category"
       data-pagefind-filter="category:{{ cat }}">{{ cat }}</a>
    {% endfor %}

    <h1 class="post__title">{{ title }}</h1>

    <div class="post__meta">
      <span class="post__author">by {{ author }}</span>
      <time class="post__date" datetime="{{ date | dateIso }}">
        {{ date | dateReadable }}
      </time>
    </div>

    {% if featuredImage %}
    <img
      class="post__hero"
      src="{{ featuredImage | replace('.jpg', '.webp') | replace('.png', '.webp') }}"
      alt="{{ title }}"
      width="1200"
      height="630"
      fetchpriority="high"
    >
    {% endif %}
  </header>

  <div class="post__body">
    {{ content | safe }}
  </div>
</article>
```

Posts in `src/posts/*.md` set their layout via a directory data file.

`src/posts/posts.11tydata.js`:
```js
module.exports = {
  layout: "post.njk",
  tags: ["post"],
  permalink: "/{{ slug }}/index.html"
};
```

---

## Step 5 — Category Pages

`src/category/category.njk` — generates one paginated page per category:

```njk
---
pagination:
  data: collections.categories
  size: 1
  alias: category
permalink: /category/{{ category | slug }}/
---
{% extends "base.njk" %}
{% block content %}
<h1>{{ category }}</h1>
<div class="post-grid">
  {% set catPosts = collections.post | selectattr("data.categories", "contains", category) %}
  {% for post in catPosts %}
  {% include "post-card.njk" %}
  {% endfor %}
</div>
{% endblock %}
```

---

## Step 6 — URL Preservation

If preserving WordPress URLs (important for SEO):
- WordPress default: `/year/month/day/post-slug/`
- Set permalink in `posts.11tydata.js` to match: `permalink: "/{{ date | year }}/{{ date | month }}/{{ date | day }}/{{ slug }}/index.html"`

Or use a `_redirects` file in `public/` to redirect old URLs to new cleaner ones:
```
/2015/03/14/launch-event-recap/ /launch-event-recap/ 301
```

Cloudflare Pages reads `_redirects` at the edge — no server needed.

---

## Step 7 — Image Cleanup

After conversion, some images may be `.jpg` or `.png` in `src/images/`. The build script
in `scripts/images.js` converts all to WebP. Post templates should replace extensions:

```njk
{{ featuredImage | replace('.jpg', '.webp') | replace('.png', '.webp') }}
```

Or add a custom 11ty filter in `.eleventy.js`:
```js
eleventyConfig.addFilter("toWebp", str =>
  str ? str.replace(/\.(jpg|jpeg|png)$/i, '.webp') : str
);
```

Usage: `{{ featuredImage | toWebp }}`

---

## Checklist Before First Deploy

- [ ] All posts converted from XML to Markdown
- [ ] Featured images downloaded to `src/images/`
- [ ] Post count in `_site/` matches WordPress post count
- [ ] Category pages generated for all categories
- [ ] Pagination working (check `/page/2/` etc.)
- [ ] Search index generated (`_site/pagefind/` exists)
- [ ] Images converted to WebP (`_site/images/*.webp`)
- [ ] Old URLs redirect correctly (test 3–5 posts)
- [ ] `_headers` present in `_site/`
- [ ] OG tags on post template include `og:type: article`
