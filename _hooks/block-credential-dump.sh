#!/usr/bin/env bash
# PreToolUse guard (Bash matcher): blocks commands that look like they'd dump
# the raw contents of a credential-shaped file (cat/less/head/tail/etc.) into
# the Claude Code transcript. Backstop for the incident class documented in
# ~/.claude/CLAUDE.md ("Never print a secret via a standalone command's
# output...") -- e.g. a blind `cat /root/.config/agent-vault.env` that once
# printed a live master password straight into a session transcript.
#
# This is a heuristic backstop, not a parser: it looks at the command STRING
# before execution, matching on (a) a dump-shaped verb (cat/less/head/...)
# and (b) a credential-shaped path/keyword nearby. It deliberately stays
# permissive around already-established safe patterns (grep -c, cut -d=,
# wc -l, ls -la, ansible-vault, etc.) so it doesn't get in the way of the
# narrow/redacted inspection style already used throughout this repo's
# CLAUDE.md gotchas.
#
# 2026-09-07 addition (PROPOSED -- review before installing): a second rule for
# proxy URLs. On Agent-Vault-wired hosts, HTTPS_PROXY/HTTP_PROXY carry the agent
# token as URL userinfo, and a plain `grep '^HTTPS_PROXY=' gateway.env` printed a
# live token twice (2026-09-03 via /proc environ, 2026-09-07 via grep). The verb
# list above never covered grep/awk/sed because they are how the SAFE patterns are
# built -- so this rule is deliberately narrow: it fires only when the command
# both names a *_PROXY field and would print a matching line's VALUE (grep/awk/sed
# /perl without a count or a key-name cut). `grep -c`, `cut -d= -f1` and
# `grep -o '^HTTPS_PROXY='` (name only, no value) stay allowed.
set -euo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)

allow() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}\n'
  exit 0
}
deny() {
  jq -n --arg reason "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
  exit 0
}

[[ -z "$command" ]] && allow

# ---- Rule 2 (new): proxy URLs are credentials --------------------------------------------
# Fires when the command mentions a *_PROXY field AND uses a line-printing verb AND is not
# reduced to a count or key-name form. Kept independent of rule 1 so it cannot loosen it.
# The printing verb and the *_PROXY mention must sit in the SAME pipeline segment (no |, ;, &
# between them). A commit message that says "_PROXY" while an unrelated `| head -1` sits at the
# end of the command is not a leak, and the first version of this rule denied exactly that twice.
# Regex-ish spellings like HTTPS?_PROXY inside a grep pattern still match, since _PROXY is literal.
proxy_print_re='(^|[;&|(]|[[:space:]]|['"'"'"])(grep|egrep|awk|sed|perl|cat|head|tail|less|more)([[:space:]]|['"'"'"])[^|;&]*_PROXY'
proxy_safe_re='(grep[[:space:]]+-[a-zA-Z]*c([[:space:]]|$)|cut[[:space:]]+-d=[[:space:]]*-f1|wc[[:space:]]+-l|md5sum|sha256sum|-o[[:space:]]+['"'"'"]\^?[A-Z_]*PROXY=['"'"'"])'
if printf '%s' "$command" | grep -Eiq "$proxy_print_re" \
   && ! printf '%s' "$command" | grep -Eq "$proxy_safe_re"; then
  deny 'This command would print the value of a *_PROXY variable. On Agent-Vault-wired hosts (dfw, hermes) HTTPS_PROXY/HTTP_PROXY embed the live agent token as URL userinfo, and a plain grep of an env file for the proxy line has printed a live token into this transcript twice (2026-09-03, 2026-09-07), each requiring a rotation. Read key names only (`cut -d= -f1`), count matches (`grep -c`), or compare hashes; if you need the proxy host:port, it is a non-secret Ansible var (agent_vault_proxy_host_port) in the playbook, not something to read out of the rendered file.'
fi

# ---- Rule 1 (unchanged): dump verbs against credential-shaped paths -----------------------
cred_re='(\.env([^A-Za-z]|$)|credential|secret|passwd|password|\btoken\b|\.ssh/|id_rsa|id_ed25519|\.pem\b|\.pfx\b|\.p12\b|master[_-]?password|api[_-]?key)'

printf '%s' "$command" | grep -Eiq "$cred_re" || allow

dump_re='(^|[;&|(]|[[:space:]]|['"'"'"])(cat|less|more|tail|head|bat|xxd|od|hexdump|strings|nl|vim|vi|nano|emacs|pico|view)([[:space:]]|$|['"'"'"])'

printf '%s' "$command" | grep -Eiq "$dump_re" || allow

safe_re='(cut[[:space:]]+-d=|grep[[:space:]]+-[a-zA-Z]*c([[:space:]]|$)|wc[[:space:]]+-l|md5sum|sha256sum|sha1sum|--dry-run|ansible-vault)'

printf '%s' "$command" | grep -Eiq "$safe_re" && allow

deny 'This command looks like it would print the raw contents of a credential-shaped file (cat/less/head/tail/etc. against a path matching .env, credential, secret, password, token, .ssh/, id_rsa/id_ed25519, .pem, or similar). That is the exact shape of a real incident: a blind `cat /root/.config/agent-vault.env` once printed a live master password into this transcript. If you genuinely need to inspect this file, use a narrow/redacted probe instead -- `ls -la` for metadata, `cut -d= -f1` for key names only, `grep -c` for match counts, `wc -l` for line counts, `md5sum`/`sha256sum` to verify content without revealing it, or a purpose-built tool (ansible-vault, the credential-rotation-protocol skill). If a full read is genuinely required, ask the user to run it themselves in their own terminal rather than through this tool.'
