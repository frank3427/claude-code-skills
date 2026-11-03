---
name: agent-vault-credential-broker
description: This skill should be used when deploying or debugging Infisical's Agent Vault (a self-hosted, research-preview credential broker that intercepts an agent's outbound HTTPS calls via a local MITM proxy and injects real API keys so the agent process never holds them) — including provisioning a new instance, wiring it in front of an existing agent (OpenClaw, Hermes, a coding agent), the `agent-vault` CLI (vault/service/agent/run subcommands), or debugging a broken cutover. Trigger phrases include "agent vault", "credential broker", "get.agent-vault.dev", "agent-vault run", "AGENT_VAULT_TOKEN", "AGENT_VAULT_ADDR", "AGENT_VAULT_VAULT", "mitm-ca.pem", "agent-vault server", "unmatched_host_policy", "openclaw-on-vps.mdx", "hermes-on-vps.mdx", "placeholder api key vault", "__anthropic_api_key__", "Failed to set up mount namespacing", "agent process never holds credential", "MITM proxy inject api key", "vault service add catalog", "netguard blocked by network policy", "AGENT_VAULT_NETWORK_ALLOWLIST", "AGENT_VAULT_ALLOW_PRIVATE_RANGES", "agent vault 502 internal host", "agent vault tailnet private ip blocked", "credential set argv", "/v1/credentials", "copy credential between vaults", "Tunnel connection failed: 407", "urllib proxy auth", "one vault per consumer".
---

# Agent Vault (Infisical) — credential broker for agent processes

Built and verified end-to-end 2026-08-31 deploying a new instance and cutting an existing
OpenClaw gateway over to it. It's a **research preview** — re-check
`https://github.com/Infisical/agent-vault` and its `docs/` folder before trusting any exact
command here to still be current.

## What it actually protects against (and what it doesn't)

Agent Vault intercepts an agent's **own outbound HTTPS API calls** via a local MITM proxy
(`HTTPS_PROXY` + a trusted CA) and injects the real credential at the network layer — the agent
process's own environment only ever holds a placeholder. This is the right tool when the agent
*itself* holds a raw provider key and makes its own outbound calls with it (an OpenClaw/Hermes-
style gateway, a service account). It does **not** help with a human-driven interactive session
(e.g. Claude Code on a laptop) exposing a secret via an SSH command's output or shell history —
that's a command-construction/history-hygiene problem, not a network-credential-injection one.
Don't scope a pilot at "stop this specific SSH leak" without checking the mechanism actually
covers it first.

## Deployment placement

**Must run on a separate machine from the agent(s) it protects** — the vendor's own docs are
explicit about this; co-locating defeats the isolation (a compromised agent session could reach
the local vault/master password). For a Proxmox-based fleet with a VMID convention, this is
exactly what a "security-isolated/agentic" VMID range is for.

Install via `curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL
https://get.agent-vault.dev | sh` (binary + systemd-style layout) or the `infisical/agent-vault`
Docker image (ports `14321` mgmt UI, `14322` MITM proxy). Bind both ports to the instance's
Tailscale IP specifically, never `0.0.0.0` — verify with `ss -tlnp`, not just "I set `--host`".
Master password (`AGENT_VAULT_MASTER_PASSWORD`) has no built-in backup guidance from the tool
itself; treat it the same as any other durable secret — generate strong, back up off-host
before relying on the instance.

**No native TLS on the mgmt/API port** — confirmed via `agent-vault server --help` and the
vendor's own env-var docs: there's no TLS flag or config option at all, the server is plain HTTP
by design (default `--host` is even `127.0.0.1`), and the docs assume you'll front it with a
reverse proxy or platform-native TLS (Fly.io is their own example) if you want HTTPS. For a
Tailscale-only deployment, front the mgmt port (14321, not the MITM proxy port 14322 — see
below) with Tailscale Serve, matching this homelab's standard access pattern:
`tailscale serve --bg --https=443 http://<the-instance's-own-tailscale-IP>:14321` — **use the
instance's own Tailscale IP as the proxy target, not `localhost`**, since the server is bound to
that IP specifically, not loopback (`localhost:14321` gets a `502` from Serve, not a connection).
Purely additive — the raw port stays reachable unless separately blocked (see below). Then
update every consumer's `AGENT_VAULT_ADDR` (`gateway.env`, `openclaw-agentvault.env`, etc.) to
the new `https://` hostname and restart each gateway — the MITM proxy env vars
(`HTTPS_PROXY`/`HTTP_PROXY`) stay pointed at the raw IP:14322, unaffected.

**To actually enforce HTTPS-only (not just make it available)**, block the raw port at the host
firewall rather than relying on `--host` alone — `agent-vault server` has a single `--host` flag
covering *both* the mgmt port and the MITM proxy, so rebinding just the mgmt port to loopback
isn't possible without also breaking the MITM proxy for every consumer that reaches it directly
via the Tailscale IP. The fix: add an nftables rule dropping the mgmt port specifically when it
arrives from a real tailnet peer, while leaving Serve's own backend connection untouched —
`iifname "tailscale0" tcp dport 14321 drop` in the host's own `inet filter` input chain (don't
touch tailscale's own `iptables-nft`-managed tables, add to a separate/existing plain table
instead). This works because a same-host connection to the box's *own* Tailscale IP routes via
`lo`, not `tailscale0` (confirmed via `ip route get <own-tailscale-ip>` showing `dev lo`), so
Serve's own reverse-proxy connection to the backend never matches the drop rule while a genuine
external peer's direct connection does. Verify both directions: direct `http://` to the raw IP
times out/fails, `https://` via the Serve hostname still returns 200, and the MITM proxy port is
unaffected. If persisting this in `/etc/nftables.conf` (Debian's base nftables.service loads it
at boot), remember the file always starts with `flush ruleset` — editing it live is safe (takes
effect next boot only, when boot ordering means nftables.service runs before tailscaled installs
its own rules), but never `systemctl restart nftables` while tailscaled already has live rules
programmed — that flushes them too (see the Tailscale-pihole-dns-routing skill's nftables-reload
gotcha for the general case).

If the LXC/VM is unprivileged and needs Tailscale, the standard TUN-passthrough gotcha applies
(`lxc.cgroup2.devices.allow`/`lxc.mount.entry` + full stop/start, not a service restart) — not
specific to Agent Vault, covered generically elsewhere in this environment's Proxmox skills.

## Rotating `AGENT_VAULT_MASTER_PASSWORD`

Confirmed working end-to-end 2026-09-02. The master password is a KDF input (Argon2id) for a KEK
that wraps the DEK, which uniformly encrypts every stored credential — per the vendor's own
security docs, rotating it via the proper command is "a single database update with zero
credential re-encryption." It is **not** the same credential as the web UI/CLI owner-account
login (`agent-vault auth register`/`auth login`, a normal human email+password) — the two are
structurally independent; rotating one has zero effect on the other.

**Procedure** (single-instance SQLite, this project's deployment shape — no `DATABASE_URL` set):
1. `agent-vault master-password change` **refuses to run while the server is active** ("server is
   running (PID ...) -- stop it first"). Stop it via the process manager actually supervising it
   (`systemctl stop agent-vault.service` here), not `agent-vault server stop` directly, to avoid
   racing systemd's own restart handling.
2. Run `agent-vault master-password change` — interactive prompts for current password, then new
   (twice, to confirm). `--force` is only for PostgreSQL multi-instance setups with all instances
   stopped; not needed here.
3. Update the systemd `EnvironmentFile` (`/root/.config/agent-vault.env` here) so
   `AGENT_VAULT_MASTER_PASSWORD=` matches **exactly** what was just set at the prompt.
4. `systemctl start agent-vault.service`, then `systemctl status` — confirm `active (running)`,
   not `activating (auto-restart)`.

**Real gotcha hit doing this**: after rotating, the service crash-looped (`systemctl status`
showed `activating (auto-restart)`, exit code 1; `journalctl -u agent-vault.service` showed a
plain `wrong password` error). Root cause was a copy/typo mismatch between the password actually
set at the interactive prompt and what ended up written into the env file — they're typed/pasted
independently, so nothing catches a mismatch until the next start attempt. **Minimize this
surface**: generate the new password once, copy it via clipboard into both the CLI prompt and the
env file rather than re-typing/re-pasting separately, and don't consider the rotation done until
`systemctl status` shows a clean `active (running)` with no restart-loop.

**Verifying no data was lost, without touching any live credential value**: `agent-vault catalog
--json` is the wrong command for this — it's the static built-in *reference* list of supported
providers (Anthropic, OpenAI, GitHub, Cloudflare, etc.), not what's actually configured in your
vaults. Use `agent-vault vault list` (requires successfully decrypting the DB to run at all — its
mere success is already evidence the rotation worked) and `agent-vault vault service list --vault
<name>` for each vault, which prints service names/hosts/auth-type/header-or-token-*key-name*
metadata — never the actual credential values — confirming every configured service survived the
rotation intact.

**If you don't know the current password**: it's sitting in the systemd `EnvironmentFile` in
plaintext (`/root/.config/agent-vault.env` here) — have the human read it directly in their own
terminal (`cat` on that file, or any credential file, is exactly what
`~/.claude/hooks/block-credential-dump.sh` — see the `credential-rotation-protocol` skill — now
hard-blocks Claude Code itself from doing).

## CLI workflow

1. **Owner account**: the first person to `agent-vault auth register` (web UI or CLI) becomes
   the instance owner — a real human login, not something to create on someone else's behalf.
   Subsequent CLI use needs `agent-vault auth login --address http://<ip>:14321 --email <...>`,
   which prompts for the password interactively — never pipe/relay a password through an agent
   session for this.
2. **Vault**: `agent-vault vault create <name>` (defaults to `--credential-store builtin`,
   i.e. local SQLite — fine for a single-instance pilot; `infisical` backing store is for later).
   `agent-vault vault use <name>` sets the active context so subsequent commands don't need
   `--vault` repeated.
3. **Service**: check `agent-vault catalog --json` first — it has built-in entries for common
   providers (Anthropic, OpenAI, GitHub, Cloudflare, etc.) with the **real** header name, which
   is not always `Authorization` (Anthropic's is `x-api-key` — confirmed via the catalog JSON,
   not guessed). Add with `agent-vault vault service add --name <n> --host <host> --auth-type
   api-key --api-key-header <header> --api-key-key <CREDENTIAL_KEY>`.
4. **Credential**: `agent-vault vault credential set KEY=$(...)` — the value is a literal argv
   string, so assemble it entirely within a single-quoted remote-shell command (never build the
   value locally where it'd transit visible output); see the credential-rotation-protocol skill
   for the general discipline. Verify success by byte-length comparison against the source, not
   by printing the value — a failed extraction (e.g. `grep` permission-denied inside a
   `$(...)`) silently sets an **empty string**, and the CLI still reports "✓ Set credential"
   either way.
5. **Agent identity**: `agent-vault agent create <name> --role no-access --vault
   <vault>:proxy --token-only` — mint a separate identity per consumer, never reuse one across
   multiple agents/services (same principle as any credential scoping).
6. **Wrapping**: `agent-vault run --vault <name> -- <command>` is the documented, correct way
   to wrap either an interactive CLI (admin mode, reuses the on-disk `auth login` session,
   mints a fresh scoped token per invocation) or an unattended systemd service (agent mode:
   pre-supply `AGENT_VAULT_TOKEN`/`AGENT_VAULT_ADDR`/`AGENT_VAULT_VAULT` via
   `EnvironmentFile=`). It sets `HTTPS_PROXY`/`HTTP_PROXY`, all the CA-trust env vars
   (`SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`,
   `GIT_SSL_CAINFO`, `DENO_CERT`), and `NODE_USE_ENV_PROXY=1` automatically — **don't hand-
   assemble these as a raw `EnvironmentFile=`**, that's how a first attempt broke unrelated
   outbound traffic (see below).

## Check for a named integration guide before hand-wiring

The repo ships `docs/guides/<tool>-on-<platform>.mdx` for common pairings (confirmed:
`openclaw-on-vps.mdx`, `hermes-on-vps.mdx`) — genuinely different config shapes per tool. Check
for one before assembling a config from the generic README/`--help` text; two guessed-wrong
attempts (a `proxy.enabled` config key that doesn't exist for a plain-env-var install; a hand-
rolled `HTTPS_PROXY` that broke non-target traffic) both would've been avoided by finding the
real guide first. Different tools want genuinely different patterns — OpenClaw's example wraps
`ExecStart` with `agent-vault run --`; Hermes' example instead writes placeholder strings
directly into its own `.env` plus a hand-assembled `EnvironmentFile=`. Don't assume one tool's
pattern transfers to another.

## systemd wrapping gotchas (wrapping an existing service's `ExecStart`)

- **`ReadWritePaths=` must already exist on disk** — systemd sets up the mount namespace before
  `ExecStart` runs; a missing path fails immediately (`Failed to set up mount namespacing: ...:
  No such file or directory`, `226/NAMESPACE`) and crash-loops on `Restart=always`.
  `agent-vault run` writes its CA cert to `~/.agent-vault/mitm-ca.pem` under the invoking user's
  home on first run — if wrapping a hardened systemd unit (`ProtectSystem=strict`), that
  directory must be **pre-created** (`mkdir -p`, correct ownership) and added to
  `ReadWritePaths=` before the restart, not assumed to appear on its own.
- **Roll back env-file and unit-file changes together, atomically** — if a cutover swaps a real
  credential for a placeholder (to prove the vault handles auth) and the unit-file change fails
  and gets rolled back, the placeholder left in the env file is a "looks completely healthy,
  silently broken" state: the service starts fine, channels connect fine, but every real
  provider call would 401 with nothing left to intercept it. Confirmed 2026-08-31 — caught
  within about a minute by remembering to check, not by any error surfacing on its own. Back up
  the real credential file before touching it (plain `cp`, not a content-modifying command —
  see below) and restore from that backup, not from memory, if a rollback is needed.
- **Verify against the live process, not just a synthetic test**: `sudo tr '\0' '\n' <
  /proc/<pid>/environ | grep '^ANTHROPIC_API_KEY='` (or equivalent) on the actual running
  service's PID is the real proof the credential swap took effect — a `curl` proving the proxy
  mechanism works in isolation doesn't prove the *specific service* picked up the change.
- **`HTTPS_PROXY`/`HTTP_PROXY` are themselves credential-shaped, not just `AGENT_VAULT_TOKEN`
  — the agent-vault access token is embedded as URL userinfo** (`http://<token>@host:port`),
  confirmed live 2026-09-03 reading `hermes-gateway`'s `/proc/<pid>/environ` to confirm proxy
  wiring for an unrelated new-credential add — the grep only filtered for
  `HTTPS_PROXY|HTTP_PROXY|SSL_CERT_FILE`, deliberately excluding `AGENT_VAULT_TOKEN`, and still
  printed a live token straight into the transcript. `~/.claude/hooks/block-credential-dump.sh`
  does **not** catch this shape at all — it only blocks `cat`/`less`/`head`/`tail` against
  credential-*named paths*, not a `tr`/`grep` read of `/proc/<pid>/environ` (not a path that
  looks credential-shaped) revealing a credential-shaped *value*. Treat any live-process environ
  inspection on an agent-vault-wrapped service as exposing `HTTPS_PROXY`/`HTTP_PROXY` too — grep
  for the specific var you need and treat proxy-shaped values as unsafe to display, or better,
  test functionally instead (source the env file into a subshell and make a real call, per the
  credential-rotation-protocol skill's safe toolkit, rather than ever printing resolved env).
  **Recurred 2026-09-07 through a third command shape:** `grep -E '^(HTTPS?_PROXY|NO_PROXY)='
  gateway.env`, run to compare a template change against the live file, printed the live
  `hermes-gateway` token. `grep` is not in the hook's blocked list and the *intent* was a
  non-secret proxy host:port. The only safe reads of an Agent-Vault env file are key names
  (`cut -d= -f1`) and counts; anything that prints a `*_PROXY=` **value** is a token dump.
  Rotated the same sitting via the recipe above (`agent rotate --token-only` → one-time file →
  re-render playbook → restart); the old process's own `407`s in the minute before restart were
  the proof the old token had died.
  Remediation if this happens: rotate the exposed agent's token immediately (`agent-vault agent
  rotate <name> --token-only`, piped straight into a fresh token file, never printed — see that
  command's own `--token-only` flag), re-render the consuming service's env via its existing
  templated playbook (do NOT hand-edit — Ansible's `no_log: true` on the relevant tasks is what
  keeps a re-render safe), restart the service, and verify the *new* token works with a real
  proxied call before considering it closed. `agent rotate` invalidates the old token as part of
  the same operation, so there's no separate "confirm the old one is dead" step needed.

## If the target agent has its own egress firewall

A pre-existing UID-scoped or cgroup-scoped egress allowlist (built for defense-in-depth around
an exec-capable agent) has no way to know about a new internal service — it'll drop the new
destination by default, producing a **TCP timeout** (not "connection refused") that looks like
a Tailscale ACL or the vault's own firewall problem but isn't. Diagnostic signature: identical
network namespace/cgroup as a process that reaches the destination fine, yet still times out —
check `nft list ruleset | grep -i <service-account-name>` for a dedicated table before chasing
Tailscale. Fix is a narrowly-scoped addition (destination IP + the vault's specific ports), not
a broad port-open. See the homelab-specific `reference_openclaw_egress_firewall` memory for a
worked example.

## Confirmed live on a second cutover (Hermes, 2026-08-31) — concrete CLI gotchas

Deploying the `hermes-on-vps.mdx` pattern for real (not just reading the guide) surfaced several
exact CLI behaviors worth knowing before you hit them:

- **`agent-vault ca fetch --address` needs a full URL scheme**, not bare `host:port` — `--address
  100.117.235.3:14321` fails (`first path segment in URL cannot contain colon`); `--address
  http://100.117.235.3:14321` works. Likely applies to other subcommands' `--address` flag too.
- **`auth login`'s auto-detected "local instance" option can be wrong and must not be trusted
  blindly** — if the server is bound only to its Tailscale IP (not loopback, per the deployment-
  placement guidance above), the CLI's auto-detected `Agent Vault (127.0.0.1:14321)` option
  fails with `connection refused` even when run *on the same host* as the server. Pick "Self-
  Hosting or Dedicated Instance" and supply the real bound address explicitly instead.
- **`auth: type: custom` requires a non-empty `headers` map — it is the wrong type for a
  pure path-substitution service with no header injection at all.** `headers: {}` is rejected
  (`"headers" is required for custom auth`). Use `auth: passthrough` instead — substitutions and
  auth are independent, so a service can use either, both, or neither; `passthrough` is the
  "neither header injection nor blocking" type.
- **`agent create <name> --vault <vault>:proxy --token-only`** is the confirmed working syntax
  (default `--role` is already `no-access`; `--vault` format is `name:role`, role defaulting to
  `proxy` if omitted).
- **When the vault CLI lives on a different host than the credential's source `.env`** (true for
  any agent box that doesn't have `agent-vault` installed locally, which is normal for the
  Hermes-native pattern — no CLI install needed on the agent host at all), the non-echoing
  credential-transfer pattern spans two hosts, not one: `ssh source-host "grep '^KEY=' .env |
  cut -d= -f2-" | ssh vault-host "read -r VAL; agent-vault vault credential set --vault <v>
  KEY=\$VAL"`. Verify by piping `agent-vault vault credential get ... | wc -c` back through SSH
  and comparing byte-length against the source — never by printing the value on either end.
- **Ansible idempotency trap**: if a playbook reads a one-time-use token file (`lookup('file',
  ...)`) and then deletes it after embedding the value in a rendered template (reasonable — don't
  leave the secret duplicated on disk), a second run of that same playbook will fail outright
  (`lookup` on a missing file), not report `changed=0`. Guard both the read and the render tasks
  with a `stat` check on the token file first (`when: token_stat.stat.exists`) so a re-run
  without a fresh token cleanly skips rather than errors.

## Gap found during the Hermes cutover's plaintext-leak sweep — check this on every future cutover

**An agent's own conversation/tool-call history database can retain a credential's real value
from before it was ever migrated to the vault, even after the source `.env` is scrubbed and even
after the key is rotated at the provider.** Confirmed 2026-08-31: Hermes's `state.db` (its own
session/tool-call history) contained a fragment of the original Groq API key, verbatim, from when
it had once been set up via a chat-driven shell command (a `printf`/`grep` round-trip Hermes
itself executed at Will's request, long before this migration). This is a **structurally
different exposure path than the `.env` file itself** — scrubbing `.env` and wiring the vault
does nothing to a value that was ever typed into or executed by the agent in a prior session. Any
future Agent Vault cutover should treat "does the agent's own history/state store contain this
value" as its own explicit check, not assumed covered by the `.env`-focused sweep. This is
speculative but plausible for OpenClaw/dfw too (its Anthropic key may have been set up the same
way) — unverified, since Claude Code cannot touch `/home/openclaw` at all (see
`feedback_no_claude_code_home_openclaw_access`); worth Olu or Will checking directly.

**A second, self-inflicted risk found during that same sweep**: a bounded-context `grep -o
'.{0,N}KEYNAME.{0,M}'` search (used to inspect *what* is adjacent to a credential-name match
without printing a whole file) is not automatically safe — a context window wide enough to be
useful for reading structure is also wide enough to capture and print part of a real secret if
one happens to be there, and seven clean/metadata-only files in a row provide no guarantee the
eighth is also clean. This is a variant of the "pattern-matched redaction has the identical
failure mode for anything it doesn't expect" lesson in global CLAUDE.md — check for an explicit
redaction marker (`grep -c REDACTED`) or a byte-length/format heuristic *before* revealing any
surrounding context, rather than assuming a fixed context width is safe because it has been so
far in the same sweep.

## Adding a new credential once an agent is already cut over

The heavy lift (firewall widening, CA cert, proxy env wiring) is one-time per agent host — a
*new* credential for an already-wired agent is cheap:

1. **Never type the real value into a chat with the agent itself** — that's exactly the exposure
   path in the gap above. Set it directly via the vault CLI, run by a human on the vault host.
2. `agent-vault vault service add --vault <v> --name <svc> --host <host> --auth-type ...` (check
   `agent-vault catalog --json` first for a known provider's real header shape).
3. `agent-vault vault credential set KEY=<value>` on the vault host, never relayed through the
   agent.
4. Add only the placeholder to the agent's own env file (e.g. `NEW_KEY=__new_key__`) — the
   existing `HTTPS_PROXY`/firewall wiring already covers any new outbound **public-internet**
   host, no repeat of the firewall/CA/systemd phases. **If the new host is internal/tailnet-only
   (not on the public internet), see "netguard blocks private IP ranges by default" below first**
   — it needs one more step the public-host case doesn't.
5. Restart the agent's gateway service to pick up the new placeholder.

## netguard blocks private/internal IP ranges by default — a real gap for tailnet-only services

Agent Vault has a built-in SSRF-protection layer ("netguard", undocumented in the top-level
README/guides as of 2026-09-01 — found by grepping symbol strings out of the binary, confirmed
via `docs.agent-vault.dev/self-hosting/environment-variables.md`) that blocks the MITM proxy from
dialing private/reserved IP ranges (RFC-1918, loopback, link-local, IPv6 ULA, **CGNAT — this
includes Tailscale's own `100.64.0.0/10` range**) by default
(`AGENT_VAULT_ALLOW_PRIVATE_RANGES=false`). Cloud metadata endpoints stay blocked regardless of
this setting. Every credential this project brokered before Home Assistant (Anthropic, OpenAI,
Groq, LunaRoute, Telegram) was a public-internet host, so this never came up — the first
tailnet-only service hit it immediately, producing a plain `502` on the client side with **no
hint in the default-level logs at all**. Confirmed live 2026-09-01 (hermes-agent → Home
Assistant, `homeassistant.tail922cee.ts.net` → `100.116.152.84`), full incident in
[[project_agent_vault_hermes_migration]].

**Diagnosis**: bump logging to see it — add a temporary systemd drop-in
(`ExecStart=` cleared then re-specified with `--log-level debug`), `daemon-reload`, restart,
reproduce the failing request, then `journalctl -u agent-vault`. The real error only shows at
debug level: `netguard: connection to <host> (<ip>) blocked by network policy`. Remove the
drop-in and restart back to normal (default `info`) once diagnosed — debug level logs full
per-request proxy details continuously, not something to leave on.

**Fix**: add the destination's IP to `AGENT_VAULT_NETWORK_ALLOWLIST` in
`/root/.config/agent-vault.env` on the broker host (comma-separated bare IPs or CIDRs — this env
var is only consulted when `AGENT_VAULT_ALLOW_PRIVATE_RANGES=false`, the correct default to leave
alone). **Allowlist the specific IP, not the whole Tailscale CGNAT range** — a shared
multi-tenant broker instance serving more than one agent/vault (this project's does: `dfw` +
`hermes`) shouldn't have its SSRF protection loosened tailnet-wide just because one service on
one vault needs one internal host; that defeats the point of the guard for every other vault on
the same instance. Restart `agent-vault.service` to apply. Tailscale IPs are normally stable
per-device, but a future identity-churn event (device remove/re-add — see the
`tailscale-pihole-dns-routing` skill) could change it, requiring the allowlist entry to be
updated to match.

**Any future internal/tailnet-only credential on any vault on this broker needs this same step**
— it's not specific to Home Assistant, just the first time this category of destination was
exercised.

## Claude Code's own classifier and this workflow

Editing an *existing* credentials `.env` file (even to swap one value for a placeholder) reliably
trips Claude Code's own auto-mode safety classifier, regardless of encoding — ask the human to
run that one command themselves rather than retrying. A plain `cp` for backup/restore of the
same file is not blocked (it's not writing new/modified content). Creating a brand-new file
(e.g. a fresh `AGENT_VAULT_TOKEN`/`ADDR`/`VAULT` env file) has not been observed to trip it.

## `HTTPS_PROXY` with a token and no password silently breaks every Python `requests` client

**Found 2026-09-06 on Hermes, after roughly an hour spent blaming the wrong component three
times.** The vendor guide's env shape is a URL with a **username and no password**:

```
HTTPS_PROXY=http://{{ agent_vault_token }}@{{ proxy_host_port }}
```

`urllib3` v2 (2.7.0 here, with `requests` 2.33.0) builds Basic proxy auth **only from a
`user:pass` pair** — given bare `user@host` it sends no `Proxy-Authorization` header at all, and
the proxy answers `407 Proxy Authentication Required`. `curl` sends the header regardless, so the
two disagree about whether the proxy works.

**The one-character fix** — a colon, making the empty password explicit:

```
HTTPS_PROXY=http://{{ agent_vault_token }}:@{{ proxy_host_port }}
HTTP_PROXY=http://{{ agent_vault_token }}:@{{ proxy_host_port }}
```

Fix it in the **Ansible template**, then re-run the playbook and restart the unit. A hand-edit to
the live env file is reverted by the next run — the controller is authoritative.

### Why this is expensive to diagnose rather than merely obscure

- **It is partial.** The agent's *model* calls keep working, because that transport uses a
  different HTTP library. The service looks healthy, answers questions, and only its
  `requests`-based tools (web search, fetchers, MCP clients) fail. Nothing points at a proxy.
- **The error names the wrong thing.** `ProxyError('Unable to connect to proxy')` reads as an
  egress or network fault. Direct egress works fine, which makes it look like the *destination*
  hosts are blocked. Two wrong conclusions followed: "egress is firewalled", then "those hosts
  need registering as vault services."
- **`curl` through the same proxy exonerates it**, so the obvious probe reinforces the wrong
  answer. Worse, a `curl` carrying *no* credentials returns the same `407`, which reads as "the
  proxy is broken" — a healthy `agent-vault` was restarted on exactly that evidence.

### The probe that actually settles it

Run the failing client's **own library**, in the unit's **own environment**, printing the
exception type with credentials scrubbed:

```bash
sudo bash -c 'set -a; source <gateway env path>; set +a; <venv>/bin/python3 - <<PY
import requests, re
def clean(s): return re.sub(r"//[^@/]*@", "//<redacted>@", str(s))[:200]
try: print("OK", requests.get("https://mcp.exa.ai", timeout=12).status_code)
except Exception as e: print(type(e).__name__, "|", clean(e))
PY'
```

A `407` there is this bug. Confirm by retrying with the proxy URL rebuilt as `user:@host` — if
that returns a real status code, it is settled without changing anything yet.

**The general rule:** when one client through a proxy works and another does not, the proxy is
not the variable. Reproduce with the **failing library**, never with `curl`.

## Setting a credential without putting it in argv — use the API, in-process (2026-10-03)

`agent-vault vault credential set` only takes `KEY=VALUE` as an argument (no `--stdin`, no file),
so the value would sit in the process list. The CLI is a thin client for
`POST {address}/v1/credentials` with `{"vault": "<name>", "credentials": {"KEY": "<value>"}}`
and `Authorization: Bearer <token>`. Both `address` and `token` are in `/root/.agent-vault/session.json`.
Do it in one Python process on the broker host, reading the value from stdin or from another
vault's `GET /v1/credentials?vault=<v>&reveal=true&key=<K>`. Then read it back and compare by
**hash only**; never print it. Used twice on 2026-10-03: copying `LUNAROUTE_API_KEY` vault-to-vault
inside the broker, and piping `HINDSIGHT_API_KEY` from ansible-ctrl's `infisical-get.sh` over SSH stdin.

## One vault per consumer, even when the credential is shared

An identity with `<vault>:proxy` can use **every** service in that vault. Hindsight needed only
LunaRoute, but Chuka's `hermes` vault also holds Telegram, Home Assistant, n8n and Groq. So it got
its own vault, `hindsight`, holding just the `lunaroute` service with a copied key, and the
identity `hindsight-server` has `hindsight:proxy` only. The key still lives only in the broker; the
blast radius of a compromised consumer shrinks to that one service.

## Python `urllib` gets 407 through the proxy even with the `token:@` form

`urllib.request` does not send proxy credentials on an HTTPS `CONNECT` built from the env
userinfo. It fails with `Tunnel connection failed: 407 Proxy Authentication Required`, even with
the trailing-colon URL from the section above. `httpx`, `requests` (with the colon) and `aiohttp`
with `trust_env=True` all work. Seen 2026-10-03: Hermes's Hindsight plugin probes `/version` with
urllib, gets 407, and falls back to per-process document IDs, while its real calls (aiohttp) work.
Check which HTTP library a client uses before assuming the proxy covers it.

## Don't `head`/`cat` files in `~/.agent-vault/ca/`

Only `ca.crt.pem` is public. `ca.key.enc` is the CA private key, encrypted under the master
password. Listing the directory with `head -1` of each file printed its first line into a session
transcript (2026-10-03; harmless while the master password stays private). To fetch the public
cert for a consumer's trust bundle, read **only** `ca.crt.pem`, e.g. an Ansible `slurp` with
`delegate_to: agent-vault`.

## Upgrading, telemetry, and the two products named "Agent Vault" (2026-10-11)

**If the host is Ansible-managed, backport the version pin in the same session.** `homelab-ansible`'s `agent-vault-install.yml` pins the binary by version and sha256 (tarball + extracted binary). A hand upgrade changes only the live host; the next real playbook run reinstalls the old pin. Happened 10-11 → caught 10-17 (fixed in `9004af5`): take the tarball sha from the release `checksums.txt`, confirm the extracted binary sha equals the live `/usr/local/bin/agent-vault`, bump all three vars, `--check` must be changed=0.

- **In-place upgrade, 0.39.1 → 0.40.0, verified.** Back up `/usr/local/bin/agent-vault`, download
  `agent-vault_<v>_linux_amd64.tar.gz` and `checksums.txt` from the GitHub release, then run
  `sha256sum --ignore-missing -c`. Verify the signature with cosign wherever cosign is available,
  using the command in the release notes (`--bundle checksums.txt.sig`). Then `install -m 755`
  and `systemctl restart agent-vault`. The vaults, services and credentials in the database all
  survive. **Send Olu and Chuka an fyi before the restart**: Chuka's Telegram long-poll drops
  once and reconnects within 5 s.
- **Telemetry is on by default** (`--telemetry` defaults to true; it sends anonymous usage data to
  PostHog). Turn it off by adding `AGENT_VAULT_TELEMETRY=false` to the unit's EnvironmentFile.
  Verify it from `/proc/<pid>/environ`, not from the file.
- **Two different products share the name.** Infisical's docs at
  `infisical.com/docs/documentation/platform/agent-vault/*` describe a *platform-integrated*
  Agent Vault: access bundles and sessions in the Infisical UI, a proxy enrolled with
  `infisical agent-vault proxy --enrollment-token`, listening on port **17323**, and agents
  launched with `infisical agent-vault run --session-token`. It is a separate product from the
  standalone `agent-vault` server (`docs.agent-vault.dev`, ports 14321/14322). Its sessions expire
  and can be revoked, which the standalone server's agent tokens can't. As of 10-11 Infisical
  labels it a preview and "not recommended for production". Don't follow its quickstart against
  the standalone server.
- **Strict deny mode (`unmatched_host_policy`) has no CLI command in 0.40.0.** It is a web-UI
  toggle ("Strict deny mode") backed by `GET`/`PATCH /v1/vaults/<vault>/settings` with
  `{"unmatched_host_policy": "deny"|"passthrough"}`. From the server host, use the CLI's session
  (`/root/.agent-vault/session.json`: `token`, `address`), passing the bearer header to curl on
  stdin (`--config -`). Before switching, add every legitimate un-credentialed host as
  `--auth-type passthrough` (no behaviour change), then probe as the agent user with its env:
  covered hosts 200, an unknown host 403. Deny applies only to traffic that goes through the
  proxy; anything that ignores `HTTPS_PROXY` and has open egress goes direct. Done for `hermes`
  2026-10-27 after a week of watching unmatched hosts. **A week of traffic is not the full list:**
  the same day it turned out Chuka's 3x/week gym-parking API (`ogr-api.offstreet.io`) never ran
  while the watcher was up. Before switching, also read the agent's cron jobs and the skills they
  load (`~/.hermes/cron/jobs.json`, the SKILL.md files they name) for every host they call.
  **OAuth-backed tools refresh on a different host than they call.** Google calls
  www.googleapis.com and refreshes at oauth2.googleapis.com. Krisp MCP calls mcp.krisp.ai and
  refreshes at api.krisp.ai/platform/v1/oauth2/token. A week of watching can't show the refresh
  host, because it is only hit when the access token expires. After the switch, the first expiry
  fails, and the tool looks broken days later. Read each tool's OAuth metadata
  (`/.well-known/oauth-authorization-server`) and allow its `token_endpoint`, path-scoped.
  Hermes then parks the MCP server "until credentials change", so after the fix, restart the
  gateway; don't wait for the 5-minute probe.
- **Coverage audit.** Traffic to a host that no service in the vault covers passes through
  untouched under the default policy. So "the agent's traffic goes through the proxy" does not
  mean "its keys are brokered". Compare `agent-vault vault service list --vault <v>` against the
  hosts the agent actually calls. A MITM log line for a host with no matching service means the
  agent still holds that key itself.
- `agent-vault vault list` prints a box-drawn table with ANSI codes. Don't parse it with awk;
  name the vaults explicitly.

## Moving an agent's remaining keys into the vault (OpenClaw on dfw, 2026-10-12)

Moved 7 keys in about 5 minutes with 3 restarts. Everything below was verified live.
- **Two credentials on one host** (Cloudflare's API token and email token both go to
  `api.cloudflare.com`): an auth type can inject only one header value per host. Use
  `auth: passthrough` plus two `substitutions` with `in: [header]`, each with its own placeholder
  (`__cloudflare_api_token__`, `__cloudflare_email_token__`). The agent sends
  `Authorization: Bearer <placeholder>`, and the broker swaps in whichever value matches.
- **git over HTTPS** sends `Authorization: Basic base64(user:token)`, which substitution can't
  match. Add a separate `github.com` service with `type: basic`, with `username` pointing at a
  credential holding the literal `x-access-token` and `password` at the token. Private
  `git ls-remote` then works with no credential helper. `api.github.com` is a separate `bearer` service.
- **Test each service before the swap**, as root on the agent host, using the gateway's own
  wrapper: `set -a; . <agentvault.env>; agent-vault run --vault <v> -- curl -H "<header with
  placeholder>" <url>` should return 200. The same curl with `env -u HTTPS_PROXY` must fail
  (401/404/422). That failure is the control proving the 200 came from the vault.
- **Before swapping a path-substituted key** (Telegram), check that the process has no direct
  sockets to the provider's IP ranges (`ss -tnp | grep 149.154.`). A client that bypasses the proxy
  sends the placeholder straight upstream and goes offline. Success signal: OpenClaw logs
  `starting provider (@<botname>)`, which only happens after getMe resolves.
- Bearer/api-key services take over live traffic **as soon as they're added**, before any swap.
  So copy the value first and compare hashes, then add the service. Add the primary model
  provider's service last, right before its own swap.
- Restart order: the low-risk keys together, then chat, then the model provider. Write the planned-restart marker
  (`/root/state/openclaw-planned-restart`) before each hand-run restart.
