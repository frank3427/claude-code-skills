---
name: abernathy-deploy
description: >
  Deploy the Abernathy Magazine static site to GitHub and Cloudflare Pages.
  Use this skill whenever the user says "deploy", "push", "publish", "go live",
  "push to GitHub", or "update the site" in the context of the Abernathy Magazine
  project. Also use it to set up GitHub credentials in the sandbox for the first
  time. Triggers on any mention of deploying, pushing, or publishing changes to
  abernathymagazine.com, the abernathymagazine GitHub repo, or Cloudflare Pages.
---

# Abernathy Deploy Skill

Pushes changes in the local `abernathymagazine.com` project folder to
[github.com/jackson2w/abernathymagazine](https://github.com/jackson2w/abernathymagazine),
which triggers an automatic Cloudflare Pages deployment.

## Project details

| | |
|---|---|
| **Local path** | The user's mounted workspace folder (`abernathymagazine.com`) |
| **GitHub repo** | `https://github.com/jackson2w/abernathymagazine` |
| **Branch** | `main` |
| **Cloudflare** | Auto-deploys on every push to `main` via git integration |

---

## Step 1 — Check credentials

Before pushing, verify the sandbox has GitHub credentials configured:

```bash
bash /sessions/gifted-intelligent-archimedes/mnt/.claude/skills/abernathy-deploy/scripts/check-credentials.sh
```

- **`CREDENTIALS_OK`** → skip to Step 3
- **`CREDENTIALS_MISSING`** → follow Step 2

---

## Step 2 — One-time credential setup (first time only)

The sandbox can't use the user's system keychain, so we embed a GitHub Personal
Access Token (PAT) directly into the local git remote URL. This is safe — the URL
lives only in `.git/config`, which is never committed.

### Ask the user to create a PAT

Tell the user:

> "I need a GitHub Personal Access Token to push from this sandbox. Please go to:
> **github.com/settings/tokens/new** (or use a fine-grained token at
> github.com/settings/personal-access-tokens/new) and create a token with
> **Contents: Read and Write** access (or `repo` scope for classic tokens).
> Copy the token value and paste it here."

**Important:** Do NOT ask the user to paste the token in a way that would expose
it in the conversation permanently. Accept it, use it immediately in the setup
script, and do not log or repeat it.

### Run the setup script

Once the user provides the token:

```bash
bash /sessions/gifted-intelligent-archimedes/mnt/.claude/skills/abernathy-deploy/scripts/setup-credentials.sh <PAT>
```

Confirm success with a test push (or `git ls-remote origin` if no new commits):

```bash
git -C /path/to/abernathymagazine.com ls-remote origin HEAD
```

---

## Step 3 — Stage, commit, and push

```bash
cd /path/to/abernathymagazine.com

# Stage changed files (be specific — avoid git add -A)
git add <changed-files>

# Commit with a conventional message
git commit -m "style: describe what changed"

# Push to main — Cloudflare picks it up automatically
git push
```

Use conventional commit prefixes: `feat:`, `fix:`, `style:`, `chore:`, `docs:`

---

## Step 4 — Confirm deployment

After a successful push, let the user know:

> "Pushed to GitHub. Cloudflare Pages will deploy automatically — the live site
> at [abernathymagazine.pages.dev](https://abernathymagazine.pages.dev) (or the
> custom domain) should update within 30–60 seconds."

To verify the Cloudflare deployment from the terminal (if the user has `wrangler`):

```bash
npx wrangler pages deployment list abernathymagazine
```

---

## Notes

- The PAT is stored in `.git/config` as part of the remote URL — never in a
  committed file. It will persist across Cowork sessions as long as the user's
  folder remains mounted.
- If a push fails with a 401/403 error, the token may have expired. Re-run
  Step 2 with a fresh token.
- The Cloudflare Pages build takes 20–60 seconds. No build command is needed —
  the repo root is the deploy directory.
