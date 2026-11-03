# GitHub Deployment Reference

## Typical Deployment Workflow

```bash
# 1. Stage and commit changes
git add <files>           # or: git add -A for everything (verify first)
git commit -m "feat: your message here"

# 2. Push to remote
git push origin <branch>
git push -u origin <branch>   # First push: sets tracking branch

# 3. Open a PR (if not pushing directly to main)
gh pr create --fill

# 4. Check CI status
gh pr status
gh run view
```

---

## Authentication

```bash
# Check status
gh auth status

# Login interactively
gh auth login

# Or set environment variable (for CI/headless)
export GITHUB_TOKEN="ghp_..."
```

---

## Committing and Pushing

Before committing, check what's changed:
```bash
git status
git diff
```

Stage selectively (safer than `git add -A`):
```bash
git add src/          # Stage a directory
git add file.ts       # Stage a specific file
git add -p            # Interactive staging (review each change)
```

Commit with a clear message:
```bash
git commit -m "feat: add user authentication"
git commit -m "fix: resolve null pointer in user service"
git commit -m "chore: update dependencies"
```

Push to remote:
```bash
git push                          # Push current branch (if tracking set)
git push origin main              # Push main
git push -u origin feature/login  # Push new branch and track it
```

---

## Branch Management

```bash
# Create and switch to a new branch
git checkout -b feature/my-feature

# Switch to an existing branch
git checkout main

# List branches
git branch -a

# Delete a branch (local)
git branch -d feature/my-feature

# Delete a branch (remote)
git push origin --delete feature/my-feature
```

---

## Pull Requests

### Create a PR

```bash
# Interactive (best for first-time)
gh pr create

# Auto-fill title/body from commits
gh pr create --fill

# With explicit title and body
gh pr create --title "Add login feature" --body "Implements JWT auth"

# Draft PR
gh pr create --fill --draft

# With reviewers and labels
gh pr create --fill --reviewer teammate1,teammate2 --label "feature"

# Target a specific base branch
gh pr create --base develop --fill

# Preview without creating
gh pr create --fill --dry-run
```

### Check PR Status

```bash
gh pr status              # Your open PRs and review requests
gh pr view                # View current branch's PR
gh pr view <number>       # View specific PR
gh pr view --web          # Open in browser
```

### Check CI / Workflow Runs

```bash
gh run list               # List recent workflow runs
gh run view               # View latest run
gh run view <run-id>      # View specific run with details
gh run watch              # Watch a run live (streams output)
gh run view --log         # Show full logs
```

### Merge a PR

```bash
gh pr merge               # Interactive
gh pr merge <number> --merge           # Merge commit
gh pr merge <number> --squash          # Squash all commits into one
gh pr merge <number> --rebase          # Rebase and merge
gh pr merge <number> --squash --delete-branch  # Squash and clean up branch
```

### List and Search PRs

```bash
gh pr list                        # Open PRs
gh pr list --state merged         # Merged PRs
gh pr list --author @me           # Your PRs
gh pr list --label "needs-review"
```

---

## GitHub Actions Workflows

```bash
# List available workflows
gh workflow list

# Manually trigger a workflow
gh workflow run <workflow-name-or-id>

# With inputs
gh workflow run deploy.yml --field environment=production

# Check status of latest run
gh run view
gh run watch
```

---

## Common Patterns

### Push code and open PR in one flow:
```bash
git add -A
git commit -m "feat: implement X"
git push -u origin feature/implement-x
gh pr create --fill --reviewer @me
```

### Check if CI passed before merging:
```bash
gh pr checks <pr-number>      # Show all checks for a PR
gh run watch                   # Watch live run
```

### Push directly to trigger a Cloudflare Pages/Workers CI deploy:
```bash
git add .
git commit -m "chore: deploy update"
git push origin main           # Triggers GitHub Actions or CF git integration
gh run view                    # Monitor the deploy workflow
```

---

## Key Flags Cheat Sheet

| Command | Useful Flags |
|---------|-------------|
| `gh pr create` | `--fill`, `--draft`, `--reviewer`, `--label`, `--base`, `--dry-run` |
| `gh pr merge` | `--merge`, `--squash`, `--rebase`, `--delete-branch` |
| `gh run view` | `--log`, `--log-failed` |
| `gh workflow run` | `--field key=value` |

---

## Writing Good Commit Messages

Follow a simple convention: `type: short description`

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `style`

Examples:
```
feat: add Stripe payment integration
fix: resolve CORS error on /api/users
chore: bump wrangler to 3.78.0
refactor: extract auth logic into middleware
```

This makes PR descriptions and changelogs much cleaner, and many tools (like semantic-release) can parse them automatically.

---

## Key Gotchas

- **Sensitive files in commits:** Always check `.gitignore` before `git add -A` — avoid committing `.env`, `.dev.vars`, API keys, or `node_modules`
- **Force push to main:** Avoid `git push --force` on shared branches; use `--force-with-lease` if absolutely necessary
- **gh CLI requires git remote:** `gh pr create` needs a GitHub remote set — verify with `git remote -v`
- **PR templates:** If the repo has `.github/pull_request_template.md`, `gh pr create` will use it automatically
