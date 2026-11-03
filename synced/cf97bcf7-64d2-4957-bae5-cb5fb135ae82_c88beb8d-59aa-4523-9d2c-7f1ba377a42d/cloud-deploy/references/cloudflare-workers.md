# Cloudflare Workers Deployment Reference

## Quick Deployment Flow

```bash
# Deploy using wrangler.toml config
npx wrangler deploy

# Deploy to a specific environment
npx wrangler deploy --env production

# Dry run (compile without deploying)
npx wrangler deploy --dry-run
```

---

## wrangler.toml Structure

Every Workers project needs a `wrangler.toml` (or `wrangler.jsonc`) in the project root.

### Minimal config:
```toml
name = "my-worker"
main = "src/index.ts"
compatibility_date = "2024-01-01"
```

### Full config with common options:
```toml
name = "my-worker"
main = "src/index.ts"
compatibility_date = "2024-01-01"
workers_dev = true  # Enable <worker>.workers.dev URL

# Environment variables (visible in dashboard)
[vars]
API_URL = "https://api.example.com"
LOG_LEVEL = "info"

# Routes (custom domain)
[[routes]]
pattern = "example.com/*"
custom_domain = true

# KV Namespace binding
[[kv_namespaces]]
binding = "CACHE"
id = "e29b263ab50e42ce9b637fa8370175e8"

# D1 Database binding
[[d1_databases]]
binding = "DB"
database_name = "my-database"
database_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# R2 Bucket binding
[[r2_buckets]]
binding = "BUCKET"
bucket_name = "my-assets"

# Cron triggers
[triggers]
crons = ["0 0 * * *"]

# Observability (traces/logs)
[observability]
enabled = true
```

---

## Environments (staging vs production)

Environments let you deploy the same Worker to different configs. **Bindings are NOT inherited** — redeclare them in each environment.

```toml
name = "my-worker"
main = "src/index.ts"
compatibility_date = "2024-01-01"

[env.staging]
name = "my-worker-staging"
routes = [{ pattern = "staging.example.com/*" }]

[[env.staging.kv_namespaces]]
binding = "CACHE"
id = "staging-kv-id"

[env.staging.vars]
LOG_LEVEL = "debug"

[env.production]
name = "my-worker-prod"
routes = [{ pattern = "example.com/*", custom_domain = true }]

[[env.production.kv_namespaces]]
binding = "CACHE"
id = "prod-kv-id"

[env.production.vars]
LOG_LEVEL = "warn"
```

Deploy to environments:
```bash
npx wrangler deploy --env staging
npx wrangler deploy --env production
```

---

## Secrets Management

Secrets are encrypted — not visible in dashboard or logs. Use for API keys, database passwords, etc.

```bash
# Add/update a secret (prompts for value)
npx wrangler secret put MY_API_KEY

# Environment-specific secret
npx wrangler secret put MY_API_KEY --env production

# Bulk upload from JSON
npx wrangler secret bulk ./secrets.json

# List secrets (names only)
npx wrangler secret list

# Delete a secret
npx wrangler secret delete MY_API_KEY
```

**secrets.json format:**
```json
{
  "DATABASE_PASSWORD": "...",
  "STRIPE_SECRET_KEY": "sk_live_..."
}
```

**Important:** `wrangler secret put` immediately creates and deploys a new Worker version. Use `wrangler versions secret put` if you want to stage it without deploying.

**Local development:** Create `.dev.vars` in project root:
```
MY_API_KEY=dev-key
DATABASE_URL=postgres://localhost/mydb
```
Add `.dev.vars` to `.gitignore`.

---

## Checking What's Deployed

```bash
# See all Workers in your account
npx wrangler deploy --dry-run  # Validate config
npx wrangler tail              # Stream live logs from deployed Worker
npx wrangler tail --env production
```

---

## Local Development

```bash
# Run locally
npx wrangler dev

# Run against a specific environment
npx wrangler dev --env staging

# Use remote resources (real KV/D1/R2 in preview mode)
npx wrangler dev --remote
```

---

## Deploy Command Flags Reference

| Flag | Purpose |
|------|---------|
| `--env <name>` | Target environment (staging, production, etc.) |
| `--dry-run` | Compile without deploying — good for validation |
| `--minify` | Minify the Worker bundle |
| `--keep-vars` | Don't overwrite dashboard-set variables |
| `--source-maps` | Include source maps |
| `--name <name>` | Override the Worker name |
| `--routes <pattern>` | Specify route(s) inline |
| `--var <key:value>` | Inject variables at deploy time |

---

## CI/CD with API Token

For automated deployments (GitHub Actions, etc.), use an API token instead of OAuth:

```bash
export CLOUDFLARE_API_TOKEN="your-api-token"
npx wrangler deploy --env production
```

Get your API token from: Cloudflare Dashboard → My Profile → API Tokens → Create Token → "Edit Cloudflare Workers" template.

---

## Key Gotchas

- **Bindings not inherited:** Every environment must redeclare its own KV, D1, R2 bindings
- **`workers_dev = false`:** Set this if you only want custom domain access, not a `.workers.dev` URL
- **`keep_vars`:** Without this, any variable defined only in the dashboard gets deleted on next `wrangler deploy`
- **`compatibility_date`:** Keep this updated to get new runtime features; check https://developers.cloudflare.com/workers/configuration/compatibility-dates/
- **Account ID:** Find yours at Cloudflare Dashboard → right sidebar or Workers & Pages overview
