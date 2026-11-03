---
name: 11ty-site
description: >
  Build, scaffold, and deploy static sites and content migrations using Eleventy (11ty),
  Golden Ratio Typography, and Cloudflare Pages. Use this skill whenever Will asks to:
  create a new site or mockup, migrate a WordPress site to static, add pages to an existing
  11ty project, generate HTML/CSS for a design, set up a deploy workflow, or convert images
  to WebP. Triggers on: "new site", "mockup", "build a page", "migrate wordpress",
  "abernathy", "static site", "11ty", "eleventy", "deploy to cloudflare", "add a page",
  "new project", or any request to design and build a web page or site.
---

# 11ty Site Skill

This skill governs all static site creation, design generation, WordPress migration, and
Cloudflare Pages deployment work for Will Jackson. It integrates Eleventy (11ty), Golden
Ratio Typography (GRT), Pagefind search, and Wrangler deployment into a single repeatable
workflow.

**Always read the relevant reference file(s) before writing any code or files.**

---

## Step 1 — Identify the Mode

Ask Will if it's not clear from context:

| Mode | Trigger |
|---|---|
| **New Site** | New project, mockup, landing page, portfolio site, marketing page |
| **Migration** | WordPress export → static, converting an existing site |
| **Add Page** | Extending an existing 11ty project with new pages or sections |

Multiple modes can apply (e.g., scaffold a new site that will later receive migrated content).

---

## Step 2 — Read the Reference Files

Load **all** references relevant to the current mode:

| Reference | When to read |
|---|---|
| `references/new-site.md` | New site or mockup |
| `references/migration.md` | WordPress migration |
| `references/typography.md` | Always — every project gets GRT |
| `references/search.md` | When search/filtering/pagination is needed |
| `references/performance.md` | Always — every project gets performance defaults |
| `references/deploy.md` | Before generating wrangler.toml or deploy commands |

**Typography and performance references are mandatory for every project.**
Never generate CSS without first running the GRT calculator per `references/typography.md`.

---

## Step 3 — Gather Design Inputs

Before writing any code, collect from Will (or ask if not provided):

**Required:**
- Project name and slug (e.g., `j2wtalent`, `abernathy-magazine`)
- Purpose / audience (1–2 sentences)
- Aesthetic direction (or ask Will to choose — see `references/new-site.md`)

**Typography inputs (feed into GRT):**
- Base font size preference (default: 18px for content sites, 16px for marketing)
- Primary content column width (default: 680px for articles, 860px for marketing)

**Optional but ask:**
- Color palette or brand colors
- Reference sites or aesthetic inspiration
- Whether search/pagination is needed (triggers `references/search.md`)
- Whether images need WebP conversion

---

## Step 4 — Execute

Follow the loaded reference files precisely. The output of every session must include:

1. All project files written to disk (or presented as artifacts if no computer use)
2. A `_headers` file (from `references/performance.md`)
3. A `wrangler.toml` (from `references/deploy.md`)
4. GRT CSS injected or linked (from `references/typography.md`)
5. The exact deploy commands to run — printed at the end of every session

---

## Core Principles

**No manual steps beyond the terminal.** Everything Will needs to do after a session should
be reducible to copy-paste terminal commands. If something requires clicking in a dashboard,
note it explicitly.

**Dev mode vs prod mode is a deploy flag, not a different workflow.** `--branch preview`
for iteration, `--branch main` for production. The codebase is identical.

**GRT is non-negotiable.** Typography is set by the calculator, not by intuition. Run the
script first; derive all font sizes, line heights, and spacing from its output.

**Performance defaults ship with every project.** `_headers` cache rules, semantic HTML,
`loading="lazy"` on images below the fold, and descriptive `alt` text are always included.

**Image references always use WebP paths.** Even in dev, reference `/images/foo.webp`.
The conversion script handles the actual files; the HTML shouldn't need to change.
