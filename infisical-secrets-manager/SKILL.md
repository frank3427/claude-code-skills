---
name: infisical-secrets-manager
description: This skill should be used when migrating a credential off a plaintext .env file onto self-hosted Infisical (the fleet secrets-management platform — distinct from Agent Vault, its separate MITM-proxy product), when provisioning a new host's Infisical machine identity, when debugging an `infisical-wrapper.sh`/`infisical-get.sh` fetch failure, or when auditing which fleet credentials still live in plaintext. Trigger phrases include "infisical secrets get empty", "secret not found exit 0", "*not found* infisical", "infisical secrets manager", "infisical-wrapper.sh", "infisical-get.sh", "infisical machine identity", "infisical login universal-auth", "homelab-fleet project", "migrate credential to infisical", "retire .env file", "Injecting N Infisical secrets", "infisical secrets get", "lookup('pipe', '/root/bin/infisical-get.sh", "deployed-copy vs git-tracked-source".
---

# Infisical secrets manager — fleet credential migration

Self-hosted Infisical (VM 111 `infisical`, `192.168.50.29`, `https://infisical.tail922cee.ts.net`),
project `homelab-fleet` (ID `4655aace-2e75-4c2a-8d29-9bd438868396`), environment `dev`. Path `/` held everything until 2026-09-05, when a second agent host needed the same secret NAMES with different values and moved to a per-host folder (`--path=/hermes`) -- read the folder-vs-prefix gotcha below before adding a host. Built and fully rolled out
2026-09-02 across `ansible-ctrl`, `pbs`, `n8n`, `immich`, `dfw`, and Claude Code's own interactive
Cloudflare admin tokens (30 secrets total) — see `project_infisical_secrets_manager` memory for
the full incident-by-incident history. This skill is the durable "how," not the narrative.

**Not the same as Agent Vault.** Agent Vault (also Infisical, separate product) is a MITM proxy
that injects credentials into an *agent's own outbound API calls* at the network layer. This
skill's Infisical is a real secrets *store* — a scoped, authenticated pull of one named value.
Genuinely independent products, no shared backend. Don't conflate deployment steps between them.

## Before migrating anything: verify it's real and still live

Two real findings this session, both caught by verifying instead of assuming:

- **A `.env` file existing doesn't mean it holds a real secret.** `pihole-exporter.env` looked
  like a normal credential file (right permissions, right shape) but held only explanatory
  comments — Pi-hole's password auth had been disabled months earlier, so the exporter had been
  running unauthenticated by design the whole time. A first-pass playbook edit to render this
  "credential" from Infisical was written, then reverted, once the live file was actually
  checked. Always read the current live file's *content* (or have the user do it) before writing
  migration code around it, not just its existence/permissions.
- **A credential can go dead with zero automated consumer to notice, for weeks.** Two Cloudflare
  admin tokens (`claude-code-cf-account`/`claude-code-cf-zone`) were purely interactive-use — no
  cron/service ever read them, only an ad-hoc Claude Code session doing Cloudflare admin work. They
  went stale sometime after their last real use and nobody knew until this migration's own
  functional-verification step (`curl .../user/tokens/verify`) caught it. **For any credential
  being migrated, do a real functional check against the provider *before* trusting the migration
  is meaningful** — an Infisical secret that round-trips a dead value isn't actually fixing
  anything. If a credential turns out dead, that's a separate problem from the migration itself:
  diagnose the real cause (check for a related rotation event, check if a broker like Agent Vault
  or another host already holds a live replacement) before minting a blind replacement.

## Two consumer mechanisms — pick based on how the credential is currently used

**Mechanism A — direct-execution host, systemd-invoked.** The consuming process runs on the same
host that will fetch the secret, invoked by a systemd unit's `ExecStart=`. Wrap it with a shared
`infisical-wrapper.sh` instead of the unit sourcing a local `.env` (via `EnvironmentFile=` or the
script's own `source`):
```
ExecStart=/root/bin/infisical-wrapper.sh /root/bin/some-script.sh [args...]
```
The wrapper logs in via the host's machine identity, then `exec infisical run ... -- "$@"` —
every secret in the project lands as an env var, same shape `EnvironmentFile=` gave before. In the
consumer script itself, delete the `source /root/.config/X.env` lines and change any
`[[ -f /root/.config/X.env ]]` existence-gate into `[[ -n "${VAR:-}" ]]` (the script may still run
standalone/ad-hoc without the wrapper — keep the graceful-degrade warn path).

**For a script invoked directly by something other than systemd** (a cron job, a `fail2ban`
action hook, anything that can't have its `ExecStart=` wrapped), use the sibling
`infisical-get.sh` inline instead, fetching one value at a time:
```bash
TELEGRAM_BOT_TOKEN="$(/root/bin/infisical-get.sh TELEGRAM_BOT_TOKEN)"
TELEGRAM_CHAT_ID="$(/root/bin/infisical-get.sh TELEGRAM_CHAT_ID)"
export TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
```

**Mechanism B — Ansible-templated push.** A controller (e.g. `ansible-ctrl`) renders a credential
onto a *different* target host via `ansible.builtin.copy`/`template`, historically sourced via
`lookup('file', '/root/.config/<name>-creds.env')` + `regex_findall`. Replace the `vars:` entry
with a `lookup('pipe', ...)` call to `infisical-get.sh` on the controller instead — the rendered
output on the target host is byte-identical, only where Ansible sources the value from changes:
```yaml
r2_access_key_id: "{{ lookup('pipe', '/root/bin/infisical-get.sh R2_ACCESS_KEY_ID') }}"
```
This needs no changes on the target host at all — it keeps its real rendered `.env` file and
`EnvironmentFile=` wiring exactly as before. Don't try to eliminate the target host's file too
unless there's a real reason (a new machine identity there is extra ongoing maintenance for
marginal benefit — this was explicitly declined for `pbs`'s R2/B2 backup jobs).

## The two shared helper scripts (copy these verbatim per host/repo)

`infisical-wrapper.sh` and `infisical-get.sh` — same content shape everywhere, only the
`INFISICAL_PROJECT_ID`/`INFISICAL_DOMAIN` constants are shared (identical across every
consumer), while `IDENTITY_FILE` is always the *local* host's own
`/root/.config/infisical-machine-identity.env`. Deploy via a small dedicated playbook
(`infisical-tooling-install.yml`) that other credential-consuming playbooks depend on running
first — don't fold the deploy into an existing playbook, since multiple consumers need these
scripts independently.

```bash
# infisical-wrapper.sh
#!/usr/bin/env bash
set -euo pipefail
INFISICAL_DOMAIN="https://infisical.tail922cee.ts.net/api"
INFISICAL_PROJECT_ID="4655aace-2e75-4c2a-8d29-9bd438868396"
IDENTITY_FILE="/root/.config/infisical-machine-identity.env"
[[ $# -eq 0 ]] && { echo "usage: infisical-wrapper.sh <command> [args...]" >&2; exit 2; }
set -a; source "$IDENTITY_FILE"; set +a
# Neither the token NOR the client credential goes on the command line -- see the argv
# exposure gotcha below. These two env vars are undocumented in `infisical login --help`.
export INFISICAL_UNIVERSAL_AUTH_CLIENT_ID="$INFISICAL_CLIENT_ID"
export INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET="$INFISICAL_CLIENT_SECRET"
INFISICAL_TOKEN=$(infisical login --method=universal-auth \
  --domain="$INFISICAL_DOMAIN" --silent --plain)
export INFISICAL_TOKEN
exec infisical run --projectId="$INFISICAL_PROJECT_ID" \
  --env=dev --domain="$INFISICAL_DOMAIN" --silent -- "$@"
```

```bash
# infisical-get.sh
#!/usr/bin/env bash
set -euo pipefail
INFISICAL_DOMAIN="https://infisical.tail922cee.ts.net/api"
INFISICAL_PROJECT_ID="4655aace-2e75-4c2a-8d29-9bd438868396"
IDENTITY_FILE="/root/.config/infisical-machine-identity.env"
[[ $# -ne 1 ]] && { echo "usage: infisical-get.sh SECRET_NAME" >&2; exit 2; }
set -a; source "$IDENTITY_FILE"; set +a
# Neither the token NOR the client credential goes on the command line -- see the argv
# exposure gotcha below. These two env vars are undocumented in `infisical login --help`.
export INFISICAL_UNIVERSAL_AUTH_CLIENT_ID="$INFISICAL_CLIENT_ID"
export INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET="$INFISICAL_CLIENT_SECRET"
INFISICAL_TOKEN=$(infisical login --method=universal-auth \
  --domain="$INFISICAL_DOMAIN" --silent --plain)
export INFISICAL_TOKEN
infisical secrets get "$1" --projectId="$INFISICAL_PROJECT_ID" \
  --env=dev --domain="$INFISICAL_DOMAIN" --plain --silent
```

The `infisical login ... --silent` banner line ("Injecting N Infisical secrets into your
application process") goes to **stderr**, not stdout — a script that pipes `infisical-wrapper.sh`'s
child process output into `jq`/JSON parsing is safe by default. Only breaks if you explicitly
merge stderr into stdout (`2>&1`) while testing — that's a test artifact, not a real bug.

## Provisioning a new host (one not already on `ansible-ctrl`'s identity)

A host outside `homelab-ansible`'s own reach (e.g. `dfw`, which runs its own separate
`dfw-ansible` repo locally, `ansible_connection=local`) needs its **own** Universal Auth machine
identity — reusing `ansible-ctrl`'s identity file across hosts is not how Infisical scopes access.
1. Will creates it directly in the Infisical UI (cannot be automated/provisioned by an agent):
   Organization → Access Control → Identities → Create Identity (name it after the host, org role
   `no-access`, auth method Universal Auth) → open it → Add to Project → `homelab-fleet` → same
   access level as `ansible-ctrl`'s identity → generate a Client Secret with TTL=0/max-uses=0.
   **No further per-secret association step is needed** — a project-level identity can read every
   secret in that project immediately, including ones added to the project *after* the identity
   was created.
2. Client ID/Secret saved to `/root/.config/infisical-machine-identity.env` on the new host by
   Will directly (never through chat).
3. Install the Infisical CLI via the same apt repo used everywhere else:
   `curl -1sLf https://artifacts-cli.infisical.com/setup.deb.sh | bash && apt-get install -y infisical`.
4. Deploy the two helper scripts (see above), pointed at the same project/domain constants.

**Least privilege on the free plan = a separate project (2026-10-05, hermes).** Custom project roles
(and so path conditions like `/hermes/**`) need Infisical Enterprise; the free plan offers only Admin,
Member, Viewer, No Access, and each applies to a whole project. Anything given a role on `homelab-fleet`
can read every fleet secret. For a host that must see only its own credentials (an agent host), create
its own project, give its identity **Viewer** there and no `homelab-fleet` membership, and point its
helper scripts' `INFISICAL_PROJECT_ID` at it (path `/`). To load values without them reaching chat or
argv, add `ansible-ctrl`'s identity to the new project as Member and write via the API
(`POST /api/v3/secrets/raw/<name>`, JSON body built by `jq` into a 600 file, token in a `curl -H @file`
header). `GET /api/v1/workspace` lists the projects an identity can see, IDs included. Done this way for
hermes: project `hermes` = `7a848701-b64d-412b-b6b9-de7f530940a4`.
Once a host's watchers run through the wrapper, every alert depends on Infisical being reachable:
the wrapper exits non-zero (a failed unit, visible in the sweep) rather than running without
credentials. dfw has accepted that since 2026-09. Prove a migration with the old file **gone** (rename
to `.bak`), plus a negative control: the same script run without the wrapper must refuse.

## Upgrading the self-hosted server (2026-10-06)

`homelab-ansible` `playbooks/infisical-server.yml` owns `/opt/infisical/docker-compose.prod.yml` and the
unit (`.env` is asserted, never managed). **To upgrade:** read Infisical's upgrade-impact note for every
release in between (`upgrade-impact/data/releases/<version>.yaml` in the GitHub repo; `gh api
repos/Infisical/infisical/contents/upgrade-impact/data/releases` lists them), and prefer a release that
already has one: the newest often doesn't on its release day. Bump the tag in
`files/infisical-server/docker-compose.prod.yml` and run the playbook; it pulls, `pg_dump`s, restarts, waits
for `/api/status` and checks the migration line. Schema migrations are one-way: rollback is the previous
compose plus the dump. The whole fleet's fetches fail for the ~30 s restart, so stay clear of the
02:30–03:30 CT backup hour. v0.162.20 → v0.165.16 on 2026-10-06 took 32 s with zero error logs.

## Verification discipline — do all of this, in order, for every credential

1. Non-revealing length check: `infisical-get.sh NAME | wc -c` on the new host — confirms the
   secret exists and is fetchable before touching any consumer.
2. For Mechanism B: capture a `sha256sum` of the target host's currently-rendered file *before*
   re-running the playbook, re-run it, confirm Ansible reports `ok` (not `changed`) on the
   credential-file task, and confirm the checksum is unchanged after.
3. Real functional check against the actual consumer/provider — an API call that authenticates, a
   real triggered service run that produces its real side effect (an email actually delivered, a
   backup that actually completes with `no errors were found`), not just "exited 0." A clean exit
   code alone doesn't prove the credential value is correct, only that nothing crashed.
4. **Retire the old plaintext file only after step 3 passes** — rename to `.bak`, never delete
   outright (non-destructive-automation-default; keep for at least one full week of clean runs).
5. **Re-run the same real functional checks from step 3 with the old file genuinely gone.** This
   is the step most likely to be skipped and most likely to catch a real bug — twice this session
   it caught a genuine miss: once, editing the git-tracked source script but forgetting to
   redeploy it to the host's actual `/root/bin`/`/usr/local/bin` copy (see the next section); the
   fix in each case was mechanical once found, but neither would have been caught by step 3 alone
   since the old file was still present when step 3 ran.

## Gotchas hit building this out

- **`infisical run`/`infisical secrets get --token=...` leaks the token via process argv —
  `ps`, `systemctl status`, and `journalctl -u <unit>` all print it in full.** Confirmed
  2026-09-03: a routine `systemctl status weekly-housekeeping.service` (run to check on an
  in-progress sweep, nothing unusual) printed a live 30-day Infisical machine-identity
  access token straight into a Claude Code session transcript, because the unit's
  `ExecStart=` was `infisical-wrapper.sh`, whose `exec infisical run --token="$TOK" ...`
  put the token in the child process's command line. `--help` doesn't document it, but
  `INFISICAL_TOKEN` as an exported env var works identically for both `infisical run` and
  `infisical secrets get` (confirmed live) and never appears in argv. Fixed in both
  `infisical-wrapper.sh` and `infisical-get.sh`, on both `ansible-ctrl`
  (`homelab-ansible` `7a82244`) and `dfw` (`dfw-ansible` `027b862`) — if either script is
  ever rewritten from scratch, keep the token in an env var, not a `--token=` flag. General
  lesson: any wrapper that execs a subprocess with a secret as a CLI flag has this same
  exposure to `ps`/`systemctl status`/`journalctl`, not just to a careless `cat` — check
  for an env-var alternative before accepting `--token=`/`--password=`-shaped flags as the
  only option.
- **The same fix stopped one step short for a year of habit's worth of scripts: the CLIENT
  CREDENTIAL was still in argv.** Found 2026-09-05 while porting these scripts to a third
  host. The 09-03 fix moved `INFISICAL_TOKEN` off the command line but left
  `infisical login --client-id=... --client-secret=...` — the call that *mints* the token —
  fully exposed to the same `ps`/`/proc`/`systemctl status`/`journalctl` read, on a
  credential that does not expire on its own. `INFISICAL_UNIVERSAL_AUTH_CLIENT_ID` and
  `INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET` work and are undocumented in
  `infisical login --help`, exactly as `INFISICAL_TOKEN` is undocumented in
  `infisical run --help`. Fixed fleet-wide: `homelab-ansible@7b17b50`, `dfw-ansible@898afe0`,
  hermes's copy correct from the start. **Verify an undocumented env var in BOTH directions
  before relying on it** — `infisical login` also succeeds from a cached local session, so a
  positive test alone proves nothing. The negative control is
  `env -u INFISICAL_UNIVERSAL_AUTH_CLIENT_ID -u INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET
  infisical login --method=universal-auth ...`, which must exit 1 with no output. General
  lesson: after fixing a secret-in-argv leak, look one call UPSTREAM — the thing that
  produced the secret you just protected is usually passed the same way.
- **The helper's install path is not the same on every host, and the mismatch fails
  silently.** `ansible-ctrl` keeps it at `/root/bin/infisical-get.sh`; `dfw` installs to
  `/usr/local/bin/` via `infisical-tooling-install.yml`. A consumer that hardcoded
  `/root/bin/...` on dfw therefore never invoked Infisical at all — its `[[ -x ... ]]` test
  simply failed and it fell through to a plaintext file, for every run since it was built,
  while the comment above the branch claimed Infisical was in use. Confirmed 2026-09-05 in
  `agent-mail-dispatch.sh`. **Nothing errored, which is the point: a fallback chain that
  silently succeeds by the worse route is indistinguishable from one that took the good
  route.** Two fixes worth copying: probe both locations, and have the consumer log which
  route actually answered (`cred_source=infisical:/usr/local/bin/infisical-get.sh`) so the
  question is answerable from the log instead of by re-reading the chain.
- **Use a per-host FOLDER, never a name prefix, when two hosts need the same secret names.**
  `infisical run` injects each secret into the environment under its *stored* name, so
  renaming `RESTIC_PASSWORD` to `HERMES_RESTIC_PASSWORD` to dodge a collision silently
  delivers nothing to a consumer that reads `RESTIC_PASSWORD`. Pass `--path=/<host>` in both
  helper scripts instead and keep the names the consumers require. Trade-off to state up
  front: a genuinely shared value (e.g. a Postmark server token) then exists in two folders
  and a rotation must hit both — the tidy end state is `/<host>` folders for host-specific
  values with shared ones at the root.
- **A host's "onboarding complete" record can drift from live reality without anything
  erroring.** `infisical`'s own build memory said "full `new-host-closing.yml` run, all 8
  touchpoints closed" (2026-09-02) with node-exporter "installed, confirmed up via a real
  API query" — but by 2026-09-03 the real systemd-managed `prometheus-node-exporter.service`
  had never actually started (a leftover manually-run `node_exporter` binary from the build
  session was squatting on port 9100, so Prometheus scraping looked healthy the whole time
  regardless), and the Pi-hole DNS drop-in (`/etc/systemd/resolved.conf.d/10-pihole.conf`)
  didn't exist on disk at all despite being a scoped, supposedly-applied task. Both surfaced
  only because the weekly sweep's own `ansible_check`-style drift detection flagged them —
  re-running the two relevant idempotent playbooks (`pihole-dns-client.yml`,
  `node-exporter.yml`, both `--limit infisical`) fixed both. Lesson: "closed all touchpoints"
  at build time is a snapshot, not a guarantee — a host's first post-build weekly sweep is
  worth checking for real, not just trusting the build session's own self-report.

  **Correction, 2026-09-07: the 9/3 fix above was itself incomplete, and the same bug
  recurred.** "Killed the rogue binary" stopped the *process* but never removed its systemd
  unit (`/etc/systemd/system/node_exporter.service`, `WantedBy=multi-user.target`, still
  enabled). Left enabled, it silently raced `prometheus-node-exporter.service` for port 9100
  on every subsequent boot — invisible the whole time because a stopped-but-enabled unit
  isn't "failed," so `systemctl --failed` (what both the daily drift-check and weekly sweep
  actually query) had nothing to report. Four days of clean checks later, the first real
  reboot (an unrelated `pve` host apt/kernel upgrade, 2026-09-07) started every enabled unit
  at once and crash-looped the real service to `start-limit-hit`. Fixed properly this time by
  deleting the unit file, the orphaned binary, and its associated system user outright — not
  just disabling. **General lesson for this whole fleet, not just Infisical**: on a rushed or
  manually-touched build, "stop the process" and "remove what would restart it" are different
  claims, and a fix that only does the first is invisible between reboots and silently
  recurs at the next one. If a build session ever ran anything manually before the real
  Ansible role converged the host, check `systemctl list-unit-files --state=enabled` for a
  hand-created duplicate before calling the host settled, not just `systemctl --failed`.
  This exact collision pattern is now caught automatically going forward — see
  `weekly-housekeeping-checks.sh`'s `enabled_unit_dup_*` check (service category) and the
  `post-reboot-verify.timer` on `ansible-ctrl`, which runs it fleet-wide within ~5 minutes of
  any detected reboot (`project_post_reboot_verify` memory).
- **Deployed-copy vs. git-tracked-source split.** Several hosts in this fleet keep a git-tracked
  script (e.g. `homelab-ansible/scripts/weekly-housekeeping-checks.sh`) separate from its actually
  *running* deployed copy (`/root/bin/weekly-housekeeping-checks.sh` on `ansible-ctrl`), synced
  only by re-running the deploying playbook. Editing the source and testing against the deployed
  copy without redeploying first will silently test stale code — confirmed this exact mistake
  mid-migration: a post-retirement verification run showed real `fail`/`warn` results still
  referencing the old (already-renamed) filenames, because the deploy playbook hadn't been re-run
  after the script edit. Always redeploy before the post-retirement re-check, not just before the
  first functional check.
- **Audit a playbook's `hosts:` target before running it, especially a multi-member group.** A
  real pre-existing bug (`n8n-install.yml: hosts: productivity` instead of `hosts: n8n`) silently
  applied n8n's install tasks to two unrelated hosts (`immich`, `console`) sharing that inventory
  group, caught only because the run was taking unusually long and `ps auxf` on the controller
  showed the live SSH target was a host with no business being touched. See
  `feedback_verify_playbook_hosts_scope` memory for the full incident and the fleet-wide audit
  pattern (`grep -A5 '\[groupname\]' inventory.ini` against every playbook's `hosts:` line) that
  confirmed it was an isolated mistake, not systemic.
- **An uncommitted local diff on a target repo isn't automatically safe to overwrite or ignore.**
  Check `git status`/`git diff` before touching any file a migration needs to edit. If it turns
  out to be the agent's *own* earlier, unfinished, but real and already-deployed work (confirmed
  here by checking whether the live deployed copy matched the uncommitted source, and whether a
  project memory already described the feature), it's safe to fold in and commit alongside the
  migration edit — pull the live file down (`ssh host "sudo cat <path>"`, not a fresh clone, which
  would be missing the diff), edit on top of it, push, then on the target host
  `git checkout -- <file>` (only after confirming the local diff is a strict content subset of
  the incoming commit) followed by a clean `git pull`.
- **The global credential-dump guard hook (`block-credential-dump.sh`, a `PreToolUse` Bash hook)
  matches on *path text*, not actual content sensitivity.** A completely non-secret file whose
  name happens to contain "secret"/"credential"/"token" (e.g. this very memory file,
  `project_infisical_secrets_manager.md`) will trigger the same block as a real `.env` dump.
  Work around it with `ls -la` (metadata), `wc -l` (line count), `cut -d= -f1` (key names only),
  or the `Read` tool instead of `Bash cat`/`grep`/`tail` on such a path — don't fight it by trying
  to rephrase the same `cat` command.

## A secret can leak through the request path, and your own log read can re-leak it (2026-10-31)

`pbpaste | ssh root@ansible-ctrl /root/bin/infisical-set.sh HA_CLAUDE_CODE_TOKEN` failed with "unable to
process new secret creations ... POST /api/v3/secrets/raw/". The backend log showed the JWT had landed
in the URL as the secret *key*, so Infisical logged it. The root cause isn't found yet; the same script
worked the day before. Until it is, don't hand the `pbpaste | infisical-set.sh` path out for one-off
secrets: use the Infisical web UI. When reading any API server log, redact JWT-shaped tokens first
(`sed -E 's/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/<JWT>/g'`) and drop `/secrets/raw/<x>`
path tails. A `grep -v token=` filter still prints a token that arrived in the URL path. Full incident:
`reference_infisical_set_key_became_value` memory.

## Full secret inventory as of 2026-09-02 (for reference, not exhaustive going forward)

`homelab-fleet` holds: Tailscale OAuth, Postmark, shared Telegram bot token, Grafana API token,
Cloudflare billing + DNS + admin (account/zone) tokens, Immich admin + DB password, R2/B2 backup
keys, Vultr, Anthropic (both admin and headless-Claude-Code keys), Proxmox/Terraform, n8n's
encryption key, and dfw's restic backup credentials. **Deliberately not migrated**: Hermes's
credentials (uses Agent Vault instead, a different broker — see `agent-vault-credential-broker`
skill); Olu's own `openclaw-anthropic.env` bundle on `dfw` (a hard classifier-blocked file,
different ownership boundary); Infisical's own bootstrap `.env` and Agent Vault's master password
(unavoidable chicken-and-egg — the credential that proves identity *to* the store can't itself
live in the store); `n8n-import-key.env` (confirmed zero real consumers, orphaned).

## `secrets set NAME=@/path/to/file` is documented and does not work (2026-09-06)

`infisical secrets set --help` advertises `<secretName=@/path/to/file>`. On the CLI version running
here it is **not interpreted**: it stores the literal string `@/root/.config/whatever.key` and
**exits 0**. Nothing about the command's output distinguishes this from a real write.

Caught only by reading the value back and comparing lengths — 31 characters stored against a
50-character source. Had the round-trip check been skipped, a credential in the vault would have
been the *path to* the credential, and the failure would have surfaced later as an auth error at
whatever consumed it.

**Use `--file` with an `.env`-format staging file instead**, which keeps the value out of argv the
same way the `@file` form was supposed to:

```bash
STAGE=$(mktemp); chmod 600 "$STAGE"
trap 'shred -u "$STAGE" 2>/dev/null || rm -f "$STAGE"' EXIT
{ printf 'NAME='; tr -d '\r\n' < "$KEYFILE"; printf '\n'; } > "$STAGE"
infisical secrets set --file "$STAGE" --projectId=... --env=dev --domain=... --silent
```

**Always verify the round trip without printing the value**: read it back and compare lengths and
equality in a single shell invocation (`[ "$v" = "$w" ]`), never by echoing either side.

## `set` and `delete` disagree about what a secret is by default

`infisical secrets set` defaults to `--type shared`. `infisical secrets delete` defaults to
`--type personal`. Same noun namespace, same project, opposite defaults — so a `set` followed
later by a `delete` with otherwise-matching arguments silently addresses **two different objects**,
and the cleanup fails while looking entirely correct.

The failure message is the expensive part. Deleting something that does not exist returns:

```
• Unable to complete your delete request
  If this issue continues, get support at https://infisical.com/slack
```

No cause, no object name, no status. Against a **scoped machine identity** this reads as an
authorization denial — such a plausible story that it gets accepted without a second invocation.
Confirmed 2026-09-06: it was reported to the user and to another agent as a capability limit
("this identity can create and update but not delete") before `--type=shared` deleted the same
value on the first try.

**Always pass `--type=shared` explicitly to `delete`.** Anything written by `set`, by `--file`, or
through the UI is shared unless someone deliberately chose otherwise.

The transferable tell: **a real authorization failure from this CLI names authorization.** A
message that names nothing is evidence of a missing object far more often than a missing
permission. Before concluding an identity lacks a permission, try the operation once more with the
object's type, path and environment stated explicitly — a scoped identity is such a satisfying
explanation for a destructive operation failing that it substitutes for the check.

Corollary for cleanup after any test that writes a value: confirm it is **gone** by listing, rather
than trusting the delete's exit status or its error text. A leftover under a plausible-looking name
is worse than no cleanup at all, because the next reader cannot tell it from something live.

## A wrapper that injects a whole path gives every job every secret — name new secrets distinctly (2026-09-12)

`infisical run --projectId=… --env=…` with no `--path` injects **every secret at the root path** into
the job's environment, and so does every other host's wrapper reading the same project and env. On
this fleet that meant ansible-ctrl's report scripts *and* seven wrapper-based units on another host
all received a newly added secret.

**So a generic name is a collision risk.** Adding `LUNAROUTE_API_KEY` for one consumer could shadow a
variable of the same name that another consumer, on another host, expects to hold *its own* key.
Before adding a secret:
- Check which identities read that project, env and path, and which units use the wrapper
  (`grep -l infisical-wrapper /etc/systemd/system/*.service` on each).
- Grep those consumers' EnvironmentFiles and scripts for the proposed name (names only).
- **Prefer a consumer-prefixed name** (`CLAUDE_CODE_LUNAROUTE_API_KEY`), even when no collision exists
  today.

Longer-term, per-consumer folders read with `--path` are the real isolation. A distinct name is the
cheap guard until then. Every secret at a shared path is readable by every job that wrapper runs, so
say so when adding one.

## `secrets get --plain` exits 0 with an empty line for a secret that does not exist

Infisical CLI 0.43.x: `infisical secrets get NAME --plain` for a missing NAME prints an empty line and
**exits 0**. The table and JSON forms show the API's sentinel instead (`--output json` gives
`[{"secretKey":"NAME","secretValue":"*not found*"}]`). So any `lookup('pipe', 'infisical-get.sh NAME')`
with a typo templated a **blank credential** onto a host with no error. Fixed 2026-10-04 in all three
`infisical-get.sh` copies (homelab-ansible `704dcbf`, dfw-ansible `7ff249f`, hermes-ansible `b9fd7d0`):
they read `--output json`, check the shape (exit 5 if unexpected) and the `*not found*` sentinel (**exit 4**,
nothing on stdout, a message on stderr), then print with `jq -r`. That output is byte-identical to
`--plain`, verified by sha256 over all 38 secrets on ansible-ctrl and dfw, and the value never goes
through argv or a `$( )`. An Ansible pipe lookup on a missing name now fails the task ("returned 4").
**Anything new that calls the CLI directly needs the same check**; don't test existence by exit code alone.

