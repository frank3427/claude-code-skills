# Cloudflare Pages Deployment Reference

## Quick Deployment Flow

```bash
# 1. Build your site
npm run build

# 2. Deploy to Pages
npx wrangler pages deploy <BUILD_OUTPUT_DIR> --project-name <PROJECT_NAME>
```

The build output directory varies by framework:
| Framework | Build Command | Output Dir |
|-----------|---------------|-----------|
| Vite / React | `npm run build` | `dist/` |
| Next.js | `npm run build` | `.next/` or `out/` (static) |
| SvelteKit | `npm run build` | `.svelte-kit/output` |
| Astro | `npm run build` | `dist/` |
| Hugo | `hugo` | `public/` |
| Nuxt | `npm run generate` | `.output/public/` |

If the output directory isn't obvious, check `package.json` build script or framework docs.

---

## Project Setup (First-Time Only)

If the project doesn't exist on Cloudflare Pages yet:

```bash
# Create a new Pages project
npx wrangler pages project create <PROJECT_NAME>
# You'll be prompted to set the production branch (default: main)
```

To see existing projects:
```bash
npx wrangler pages project list
```

---

## Deploy Commands

### Production deploy (main branch)
```bash
npx wrangler pages deploy ./dist --project-name my-site
```

### Preview deploy (feature branch)
```bash
npx wrangler pages deploy ./dist --project-name my-site --branch feature/my-feature
```
Preview URL format: `<branch-name>.<project-name>.pages.dev`

### Deploy with source maps
```bash
npx wrangler pages deploy ./dist --project-name my-site --source-maps
```

---

## Verifying Deployments

```bash
# List all deployments for a project
npx wrangler pages deployment list <PROJECT_NAME>

# Tail live logs from Pages Functions
npx wrangler pages deployment tail <PROJECT_NAME>
```

---

## Secrets and Environment Variables

Secrets are encrypted and not visible in the dashboard. Use for API keys, tokens, etc.

```bash
# Add a secret (interactive prompt for value)
npx wrangler pages secret put MY_API_KEY --project-name my-site

# Bulk upload from a .json file
npx wrangler pages secret bulk secrets.json --project-name my-site

# List secrets (names only, not values)
npx wrangler pages secret list --project-name my-site

# Delete a secret
npx wrangler pages secret delete MY_API_KEY --project-name my-site
```

**secrets.json format:**
```json
{
  "API_KEY": "sk-...",
  "WEBHOOK_SECRET": "whsec-..."
}
```

**Local development:** Create `.dev.vars` in the project root:
```
API_KEY=dev-api-key
DATABASE_URL=postgres://localhost/mydb
```
Add `.dev.vars` to `.gitignore`.

---

## Pages Functions

If the project has a `functions/` directory, Wrangler compiles it automatically during deploy.

```bash
# Build functions separately (useful for validation)
npx wrangler pages functions build

# Run locally with functions
npx wrangler pages dev ./dist
```

**File-based routing** in `functions/`:
- `functions/api/users.ts` → `/api/users`
- `functions/api/[id].ts` → `/api/:id` (dynamic)
- `functions/_middleware.ts` → Runs on every request

---

## Local Development

```bash
npx wrangler pages dev ./dist
# or with a dev server:
npx wrangler pages dev --proxy 3000
```

---

## Key Gotchas

- **File limits:** Max 20,000 files per deployment, 25 MiB per file
- **Permanent choice:** Once using Direct Upload (Wrangler), you can't switch to Git integration — you'd need a new project
- **`keep_vars`:** Add `keep_vars = true` in `wrangler.toml` to prevent overwriting dashboard-set variables on deploy
- **Custom domains:** Configure via Cloudflare dashboard → Pages → your project → Custom domains (not CLI)
- **DNS propagation:** First-time custom domain setup can take 1-2 minutes
