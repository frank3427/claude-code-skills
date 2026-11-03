# Claude Code hooks

Not skills. These are `PreToolUse` guard scripts that Claude Code runs before executing a tool
call. They live here so they are version-controlled alongside the skills and travel to every
machine the same way; `~/.claude/hooks/` on its own is not a repo, and until 2026-09-07 a rebuild
would have lost them silently.

Install (idempotent — symlinks into `~/.claude/hooks/`, backs up any file it replaces, and
reports whether `~/.claude/settings.json` references each hook):

```bash
~/.claude/skills/_hooks/install.sh
```

The script does not edit `settings.json`; it prints the snippet to add if a hook is unwired.
Because the installed path is a symlink, `git pull` in `~/.claude/skills` updates the live hook.

## block-credential-dump.sh

Blocks Bash commands that would print a secret into the transcript. Two independent rules, each
born from a real incident on this fleet:

1. **Dump verb against a credential-shaped path** (2026-09-02): `cat`/`less`/`head`/`tail`/editors
   near `.env`, `credential`, `secret`, `password`, `token`, `.ssh/`, key files. A blind `cat` of an
   Agent Vault env file had printed a live master password.
2. **Printing a `*_PROXY` value** (2026-09-07): `grep`/`awk`/`sed`/`cat` of a line naming a proxy
   variable, unless reduced to a count, key names, a hash, or a name-only match. On Agent-Vault-
   wired hosts `HTTPS_PROXY` carries the agent token as URL userinfo, and a plain `grep` of that
   line leaked a live token twice (once via `/proc/<pid>/environ`, once via the env file), each
   costing a rotation.

Safe patterns stay allowed: `cut -d= -f1`, `grep -c`, `wc -l`, `ls -la`, checksums, `--dry-run`,
`ansible-vault`. Known false positive: a file whose *name* contains a keyword (a memory note about
credentials) is blocked from `cat` even when it holds no secret — use the Read tool for those.

Test a change without installing it:

```bash
for c in "cat /root/.config/agent-vault.env" "grep -c PROXY x.env" \
         "grep -E '^HTTPS_PROXY=' gateway.env" "ls -la /root/.config/"; do
  printf '%-45s -> ' "$c"
  jq -cn --arg c "$c" '{tool_input:{command:$c}}' | bash _hooks/block-credential-dump.sh \
    | jq -r '.hookSpecificOutput.permissionDecision'
done
# expected: deny, allow, deny, allow
```

Full history and the reasoning behind each rule: the `credential-rotation-protocol` and
`agent-vault-credential-broker` skills.
