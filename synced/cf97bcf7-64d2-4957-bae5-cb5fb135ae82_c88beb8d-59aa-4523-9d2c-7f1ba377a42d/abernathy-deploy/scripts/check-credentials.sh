#!/usr/bin/env bash
# check-credentials.sh
# Exits 0 if the git remote already has a PAT embedded, 1 if not.

PROJECT_DIR="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null || echo "")"

if [[ -z "$PROJECT_DIR" ]]; then
  echo "NOT_A_REPO"
  exit 1
fi

REMOTE_URL="$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null || echo "")"

if echo "$REMOTE_URL" | grep -q '@'; then
  echo "CREDENTIALS_OK"
  exit 0
else
  echo "CREDENTIALS_MISSING"
  exit 1
fi
