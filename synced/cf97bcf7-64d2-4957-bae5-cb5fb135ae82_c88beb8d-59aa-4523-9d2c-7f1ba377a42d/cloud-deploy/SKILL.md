---
name: cloud-deploy
description: >
  Deploy web pages, apps, and serverless functions to Cloudflare Pages, Cloudflare Workers, and GitHub.
  Use this skill whenever the user wants to: deploy a site or app, push a Worker script to Cloudflare,
  publish to GitHub Pages, commit and push code, create a pull request, set up secrets or environment
  variables on Cloudflare, or check deployment status. Trigger on keywords like "deploy", "push to
  Cloudflare", "publish my site", "create a PR", "push my code", "set up a Worker", "pages deploy",
  "wrangler deploy", "git push", "open a pull request", or any mention of Cloudflare Pages/Workers or
  GitHub deployment workflows. When the user wants to get their code live, use this skill.
---

# Cloud Deploy Skill

You are helping the user deploy their project to Cloudflare Pages, Cloudflare Workers, or GitHub (or some combination). This skill gives you the knowledge to guide them through the full process reliably.

## Step 1: Identify the Target(s)

First, figure out where the user wants to deploy. Ask if it's not clear:

- **Cloudflare Pages** — Static sites, full-stack apps (Next.js, SvelteKit, Astro, etc.)
- **Cloudflare Workers** — Serverless functions, APIs, edge scripts (`wrangler.toml` present)
- **GitHub** — Push code to a repo, open a PR, push to trigger CI/CD

It's common to do GitHub + Cloudflare together (push code, then deploy). Handle multiple targets in sequence.

## Step 2: Check and Install Required Tools

Before doing anything else, verify the needed tools are available.

### For Cloudflare (Pages or Workers):

```bash
# Check if wrangler is available
npx wrangler --version 2>/dev/null || npm install -D wrangler
```

If it's not globally installed, use `npx wrangler` for all commands throughout. Prefer local project installation (`npm i -D wrangler`) over global to keep versions consistent.

Check authentication status:
```bash
npx wrangler whoami
```

If not authenticated, run `npx wrangler login` — this opens a browser for OAuth. In CI/headless environments, use `CLOUDFLARE_API_TOKEN` env var instead.

### For GitHub:

```bash
# Check git
git --version

# Check gh CLI
gh --version 2>/dev/null || echo "gh not installed"
```

If `gh` is missing, tell the user to install it:
- macOS: `brew install gh`
- Linux: see https://github.com/cli/cli/blob/trunk/docs/install_linux.md
- Windows: `winget install GitHub.cli`

Check authentication:
```bash
gh auth status
```

If not authenticated, run `gh auth login`.

## Step 3: Deploy to the Target

Read the relevant reference file for detailed commands and options:

- **Cloudflare Pages** → Read `references/cloudflare-pages.md`
- **Cloudflare Workers** → Read `references/cloudflare-workers.md`
- **GitHub (push/PR)** → Read `references/github.md`

## General Principles

**Be a guide, not just a command runner.** Explain what each step does if the user seems unfamiliar. Flag likely issues before they happen (e.g., "your build output is in `./dist` — if it's somewhere else, let me know").

**Confirm before deploying to production.** If deploying to a production environment or merging to main, confirm with the user first.

**Surface errors clearly.** If a command fails, show the error output and diagnose it — don't just retry blindly.

**Handle the build step.** If the project has a build command (e.g., `npm run build`), run it before deploying. Check `package.json` for a `build` script. Ask if unsure.

**Secrets stay secret.** Never log or display secret values. Use `wrangler secret put` for Cloudflare secrets, and remind users to add `.env` and `.dev.vars` to `.gitignore`.

**Keep `wrangler.toml` as the source of truth.** Avoid dashboard-only changes for Workers — they get overwritten on the next deploy.
