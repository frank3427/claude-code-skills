#!/usr/bin/env bash
# Install the Claude Code hooks in this directory by symlinking them into ~/.claude/hooks/, so
# the repo copy is the live copy and `git pull` updates the running hook. Idempotent; re-run any
# time. Backs up any pre-existing regular file it would replace (never overwrites silently).
#
# The hook also needs a wiring entry in ~/.claude/settings.json, which this script does NOT edit
# (that file shapes Claude Code's own permissions and is deliberately left to the human). It prints
# the snippet to add if it is missing.
#
# Usage: ~/.claude/skills/_hooks/install.sh
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dest="${CLAUDE_HOOKS_DIR:-$HOME/.claude/hooks}"
settings="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
mkdir -p "$dest"

for src in "$here"/*.sh; do
  name=$(basename "$src")
  [[ "$name" == "install.sh" ]] && continue
  chmod 755 "$src"
  target="$dest/$name"
  if [[ -L "$target" && "$(readlink "$target")" == "$src" ]]; then
    echo "ok        $target -> $src"
    continue
  fi
  if [[ -e "$target" && ! -L "$target" ]]; then
    bak="$target.bak-$(date +%Y-%m-%d)"
    mv "$target" "$bak"
    echo "backed up $target -> $bak"
  fi
  ln -sfn "$src" "$target"
  echo "linked    $target -> $src"
done

# Wiring check: every hook here should be referenced from settings.json. Report, don't edit.
missing=0
for src in "$here"/*.sh; do
  name=$(basename "$src"); [[ "$name" == "install.sh" ]] && continue
  if [[ -f "$settings" ]] && grep -q "hooks/$name" "$settings"; then
    echo "wired     $name (referenced in $settings)"
  else
    missing=1
    echo "NOT WIRED $name -- add to $settings under hooks.PreToolUse (matcher \"Bash\"):"
    cat <<EOF
    { "matcher": "Bash", "hooks": [ { "type": "command", "command": "~/.claude/hooks/$name" } ] }
EOF
  fi
done
exit $missing
