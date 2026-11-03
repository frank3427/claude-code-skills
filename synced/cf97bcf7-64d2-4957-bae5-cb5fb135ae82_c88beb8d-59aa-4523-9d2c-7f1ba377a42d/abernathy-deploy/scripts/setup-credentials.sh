#!/usr/bin/env bash
# setup-credentials.sh
# Embeds a GitHub PAT into the local git remote URL so the sandbox
# can push without interactive authentication.
# Usage: bash setup-credentials.sh <GITHUB_PAT>

set -euo pipefail

PAT="${1:-}"
REPO="github.com/jackson2w/abernathymagazine.git"
PROJECT_DIR="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null || echo "")"

if [[ -z "$PAT" ]]; then
  echo "Usage: bash setup-credentials.sh <GITHUB_PAT>"
  exit 1
fi

if [[ -z "$PROJECT_DIR" ]]; then
  echo "Error: could not find git repo root. Run this from inside the project folder."
  exit 1
fi

git -C "$PROJECT_DIR" remote set-url origin "https://${PAT}@${REPO}"
echo "✓ Credentials configured. Remote is now set to use your PAT."
echo "  Run 'git push' to verify."
