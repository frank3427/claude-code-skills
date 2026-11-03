# Deploy Reference

Covers wrangler.toml setup, deploy commands, GitHub integration, and dev/prod workflow.

---

## wrangler.toml Template

```toml
name = "{project-slug}"
pages_build_output_dir = "_site"

[env.preview]
# Preview deploys inherit from top-level config

[env.production]
# Production deploys inherit from top-level config
```

That's it. Cloudflare Pages does not need a complex `wrangler.toml` — keep it minimal.
The project name must match the Cloudflare Pages project name exactly.

---

## First-Time Project Setup

Run once per new project:
```bash
# Create the project on Cloudflare Pages
npx wrangler pages project create {project-slug}
# When prompted: set production branch to "main"

# Verify it exists
npx wrangler pages project list
```

---

## Dev Mode

No build step. Open `src/index.njk` (or run 11ty dev server) directly:

```bash
# 11ty dev server with live reload
npm run dev
# → http://localhost:8080

# Or for a quick preview deploy to Cloudflare (no custom domain yet)
npm run deploy:preview
# → https://preview.{project-slug}.pages.dev
```

Use dev mode during active design iteration. Switch to prod only when shipping.

---

## Prod Deploy

```bash
# Full build + image conversion + deploy to production
npm run deploy:prod
# → https://{project-slug}.pages.dev (or custom domain if configured)
```

This runs: `eleventy` → `pagefind` (if configured) → `scripts/images.js` → `wrangler pages deploy _site --branch main`

---

## Deploy Commands (Copy-Paste)

Always print these at the end of every session, with the actual project slug filled in:

```bash
# Preview deploy (iterate without touching production)
npm run deploy:preview

# Production deploy
npm run deploy:prod

# Or manually:
npm run build && npx wrangler pages deploy _site --project-name {project-slug} --branch main
```

---

## GitHub Integration (Preferred for Ongoing Projects)

For projects that have moved past initial mockup, connect GitHub to Cloudflare Pages
for automatic deploys on push. This replaces manual `wrangler pages deploy` calls.

### Setup (one-time, done in Cloudflare dashboard):
1. Cloudflare Dashboard → Pages → your project → Settings → Build & Deployments
2. Connect to GitHub → select repo → set build command and output directory

Build settings:
```
Build command:      npm run build
Build output dir:   _site
Root directory:     /  (or subdirectory if monorepo)
```

After connecting:
- Push to `main` → production deploy
- Push to any other branch → preview deploy (gets a unique URL)

### GitHub Actions (alternative to dashboard integration)

If Will prefers to keep deploy control in the repo (recommended for audit trail):

`.github/workflows/deploy.yml`:
```yaml
name: Deploy to Cloudflare Pages
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Build
        run: npm run build

      - name: Deploy to Cloudflare Pages
        uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy _site --project-name {project-slug} --branch ${{ github.ref_name }}
```

Secrets to add in GitHub repo settings:
- `CLOUDFLARE_API_TOKEN` — create in Cloudflare dashboard → My Profile → API Tokens → "Cloudflare Pages" template
- `CLOUDFLARE_ACCOUNT_ID` — found in Cloudflare dashboard right sidebar

---

## Custom Domain Setup

Done in Cloudflare dashboard only (not CLI):
1. Pages → your project → Custom domains → Add custom domain
2. If domain is already on Cloudflare (DNS managed by CF): auto-configured
3. If external DNS: add CNAME record pointing to `{project-slug}.pages.dev`

Propagation: typically < 2 minutes when domain is already on Cloudflare.

---

## .gitignore (Standard)

```
node_modules/
_site/
.DS_Store
.env
.dev.vars
```

`_site/` is always gitignored — it's a build artifact. Cloudflare Pages (or GitHub Actions)
builds it fresh on every deploy.

---

## End-of-Session Checklist

Before ending any work session, always output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEPLOY COMMANDS — {Project Name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Preview (iterate):
  npm run deploy:preview

Production:
  npm run deploy:prod

First time only (create CF project):
  npx wrangler pages project create {project-slug}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Print this block at the end of every session involving file creation or code changes.
