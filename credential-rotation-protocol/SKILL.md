---
name: credential-rotation-protocol
description: This skill should be used whenever a live credential (API key, bot token, access token, etc.) needs to be rotated, changed, OR REMOVED ENTIRELY — whether because it leaked, is being proactively refreshed, is being replaced as part of an incident response, or auth is simply being turned off on a service. Disabling/removing a password is the same category of change as rotating it and needs the same consumer inventory — arguably more so, since there's no new value to hand out, only broken consumers to discover the hard way if you skip the check. Also load it whenever verifying that a credential file/rotation is correct, since that's exactly the step that causes leaks if done wrong. Trigger phrases include "rotate this credential", "the key leaked", "update this token everywhere", "credential rotation", "verify the new key works", "did the secret change", "disable the password", "turn off auth", "remove the login requirement", "no longer needs a password".
---

# Safe credential rotation protocol

Born from a single 2026-07-19 homelab session that required **four rotations** (three of a
Cloudflare R2 key, two of a shared Telegram bot token) because the *verification* step kept
leaking the very credential being verified — via three genuinely different mechanisms
(`rclone -vv`, `cat file | sed 's/FIELD=.../redacted/'`, `ansible-playbook --check --diff`).
Chasing each mechanism reactively (ban `-vv`, then ban `cat`, then ban `--diff`) doesn't scale —
the next leak just needs a fourth mechanism nobody thought to ban yet. This skill exists so
verification *never requires seeing the secret's actual value*, full stop, regardless of which
command someone reaches for.

## A mechanical backstop now exists, but don't rely on it alone

As of 2026-09-02, `~/.claude/hooks/block-credential-dump.sh` (wired into `~/.claude/settings.json`
as a global `PreToolUse` hook on `Bash`) hard-blocks `cat`/`less`/`head`/`tail`/etc. against a
path matching credential-shaped keywords (`.env`, `credential`, `secret`, `password`, `token`,
`.ssh/`, `id_rsa`/`id_ed25519`, `.pem`/`.pfx`/`.p12`) — including through an SSH wrapper
(`ssh host 'cat ...'`), which is the exact shape of the incident this skill was born from. This
is the actual mechanical rule the "prose guidance alone isn't sufficient" note below was asking
for. It stays permissive for the safe patterns in the table below (`cut -d=`, `grep -c`, `wc -l`,
`ls -la`, checksums, `ansible-vault`).

**Don't treat it as a substitute for the discipline in this skill** — it's a string-match
heuristic on the Bash command, not a parser: it won't catch `bash -x`/`set -x` on a script that
sources a credential file, a Python/Node one-liner that reads and prints a file's content, or any
non-Bash tool path. It also has real false positives — it'll flag a `cat` of a file whose *name*
merely contains "secret" or "credential" even when the file holds no live secret (e.g. this
project's own memory files, like `feedback_secret_exposure_addition_not_subtraction.md`) — use
the Read tool for those instead of fighting the hook, since Read isn't gated by it and is the
right tool for plain file reads anyway.

## The hard rule

**Before running any command whose target is a credential-bearing file, or any host/service
reached using one, ask: "does this command's output structurally contain the secret's actual
value?"** If the answer is anything other than a confident no, don't run it — use one of the safe
patterns below instead. Don't reason about whether *this specific* command "should be fine" —
that reasoning is exactly what failed three times in the incident this skill is named after.

## The complete safe toolkit — every legitimate verification need, none of them can leak

| Question | Safe method | Never use for this |
|---|---|---|
| Did a field in the file change? | Prefix check: `grep '^FIELD=' file \| cut -c1-N` (a handful of characters — enough to confirm a *change*, not enough to be useful if intercepted) | `cat file`, `cat file \| sed 's/.../.../'` or any other full-content dump, however "redacted" |
| Is the file structurally correct (right fields present, none dropped)? | `cut -d= -f1 file` — field **names** only | Anything that shows values |
| Does the new credential actually work? | A real functional test: use it to perform its real action (send a message, make an authenticated API call) with the value sourced into a shell variable (`set -a; source file; set +a`) and *never echoed* — then check the **service's own response**, not local exit code alone | Printing the credential "just to look at it" |
| Is the old/leaked credential actually dead? | The identical functional test, using the **old** value directly — always safe, since that value is already known-compromised; testing it creates no new exposure | N/A, this one is always fine |
| Will a command/playbook change something unexpected? | `--check` / `--dry-run` **alone** — reports changed/unchanged per task, nothing else | `--check --diff`, `--check -v`, or any verbosity flag stacked on top of a dry-run against a credentialed file — the dry-run part is safe, the added verbosity is not |
| Did two values end up equal (e.g. confirming a copy-paste worked)? | Compare **hashes** computed server-side (`sha256sum` on each side, compare the digests — the digest itself reveals nothing) rather than any prefix/value comparison | Diffing or printing either raw value |

If a genuine verification need doesn't fit any row above, don't invent a new one-off command under
time pressure — that improvisation is precisely how each of the three leaks happened. Stop and
ask, or fall back to the least-revealing option that exists (e.g. `-v` over `-vv`, `--check` alone
over `--check --diff`) while flagging the uncertainty explicitly rather than assuming it's fine.

**Telegram-specific trap, confirmed 2026-08-30: a private chat's `chat_id` never proves which bot
is involved.** For a 1:1 bot conversation, Telegram's `chat.id` equals the *recipient's own user
ID* — it's identical across every bot that messages that same person, so a matching `chat_id`
between two hosts' config files proves nothing about whether they're using the same bot. Verify
bot identity with the hash-comparison method in the table above (hash the token itself, not the
chat_id) — or, if you need to confirm which bot a token *currently* belongs to without ever
printing it, call `getMe` with it and compare the numeric `id` field (permanent) rather than
`username` alone (Telegram usernames can be reassigned after a bot is renamed via BotFather,
same family of issue as the revoke-mixup incident under Rotation checklist item 2 below). Spent a
full investigation turn chasing a "maybe this bot got renamed" theory before a direct token hash
compare (the method this skill already recommends) settled it in one shot — check the obvious
row in the table above before inventing a more elaborate identity check.

**A proxy URL is a credential when the proxy authenticates by userinfo.** `HTTPS_PROXY=http://
<token>:@host:port` is the Agent Vault wiring shape on every agent host here, so `grep
'^HTTPS_PROXY=' env` prints a live token — confirmed 2026-09-03 via `/proc/<pid>/environ` and
again 2026-09-07 via a plain `grep` of `gateway.env`, both times while looking for a host:port.
The safe-toolkit rows above already cover it (key names via `cut -d= -f1`, prefix via `cut -c1-N`
of a *known non-secret* field only, hashes for equality); the trap is that a `*_PROXY` field does
not *look* like a secret-bearing field, so the "is this field a secret?" question gets skipped.
Treat every `*_PROXY=` line on an agent host as secret-bearing until proven otherwise.

**Before building a fresh incident theory from raw verification, check whether this project has
already documented the exact situation.** The same session above spent real effort hypothesizing
about Telegram bot renames and client-side caching before re-reading this very skill file turned
up the actual, already-recorded 2026-08-29 incident (the revoke-mixup below) that fully explained
what was being observed. This project keeps disciplined incident records specifically so this
kind of confusion doesn't need re-solving from scratch — search project memory and relevant
skills for the symptom (a bot name, a host, an error string) before spending a turn re-deriving
what's likely already written down.

## Rotation checklist

**This checklist applies verbatim when *disabling* or *removing* a credential requirement, not
just when swapping in a new value** — e.g. turning off a service's password/auth entirely. Step 1
(enumerate consumers) is not optional just because there's no new value to hand out afterward;
skipping it because "nothing to rotate, just turning it off" is exactly the failure mode this
section exists to prevent. Confirmed the hard way 2026-08: Pi-hole's admin/API password was
disabled at Will's request with no consumer inventory done first, silently breaking a Prometheus
exporter that authenticated to Pi-hole's API — 20 hours of crash-looping and blank dashboards
before anyone noticed, on infrastructure with an active weekly automated sweep that didn't happen
to check that particular failure mode either. Full incident: `project_pihole6_exporter_fix`
memory in the homelab project. It happened to be the *only* consumer that broke this time — that
was luck, not something the process guaranteed, and isn't a reason to skip the step next time.

1. **Enumerate every place the credential is used, before touching anything** — including before
   *removing* it, not just before generating a replacement. A shared credential (a bot token, a
   bucket key reused across several jobs, a service's admin password used by any script that
   calls its API) can have more reach than expected. Check project docs for "shared credential"
   notes, `grep` Ansible playbooks/Terraform for the env var name AND for auth-header patterns the
   service uses (e.g. a service-specific header name, not just the obvious `*_TOKEN` var name),
   list Cloudflare Worker secrets, check any app's own credential store (n8n, etc.). Discovering a
   forgotten integration point *after* declaring the change done means repeating this whole
   process for something that could have been caught up front — or worse, not discovering it until
   a dashboard has been silently blank for hours. **The mistake runs both directions**: confirmed
   2026-08-30, a fleet-wide "shared credential" was assumed present on 8 hosts by pattern-matching
   against other project conventions, without checking — a plain `test -f` on each host showed
   none of them actually had the file (it was only ever needed on the 2 hosts that independently
   send Telegram messages). Over-assuming reach is just as real a mistake as under-counting it —
   it leads to proposing remediation work (a rotation, a fleet-wide push) against hosts that were
   never actually affected. Verify presence on every candidate host; don't infer it from what
   "should" be true given other project conventions.
   **Apps that keep their own copy count too, and they fail silently.** Found 2026-09-28: Uptime
   Kuma on the iMac held the homelab bot token in its own SQLite (`notification.config`), not in
   Infisical or any file a fleet grep would find. The bot's rotation (most likely the 2026-08-29/30
   one) never reached it, so every Kuma alert since got a 401 — no error in Kuma's log, nothing in
   the fleet's `telegram-path-check` (which only sees `ansible-ctrl`'s sends). Surfaced only when a
   deliberate Pi-hole outage produced no alert. Verify a rotated token **from inside each
   consumer** (for Kuma: a `getChat` run in its container with the token it has stored), not
   once from wherever the new token was minted.
2. **Generate the new credential** wherever it's actually minted (dashboard, BotFather, `openssl
   rand`, etc.). **If more than one similarly-named/similarly-purposed credential of the same
   type exists (e.g. two Telegram bots), name the exact identifier explicitly before the human
   acts in the external UI** — don't assume "the bot" is unambiguous. Confirmed 2026-08-29: a
   BotFather revoke aimed at a shared homelab bot (`@homelab4712bot`) instead hit a *different*
   bot (`@dfwclaw_bot`, a separate agent's own dedicated bot) because the instruction didn't
   pin the exact username, costing a second incident (that agent's Telegram channel crash-looped
   until its own token was separately fixed) layered on top of the original rotation.
3. **The human writes it directly to wherever it needs to live** — never pasted into chat (see the
   global CLAUDE.md secret-handling rule). If the same value needs to land in multiple files,
   write it to all of them in the same sitting rather than trickling out over separate round
   trips — each additional trip is another chance for an unrelated slip during the manual edit
   (e.g. dropping an adjacent, unrelated field by accident — see the `RCLONE_CONFIG_R2_TYPE`
   gotcha in the `cloudflare-r2-rclone-backup` skill for a concrete example of "structurally
   incomplete after a hand edit" biting twice in the same incident).
   - **Not every integration point is a file a human can just edit** — some destinations (a
     Cloudflare Worker secret, an app's own encrypted credential store like n8n's) only accept
     the value through their own API/CLI. For those, the agent can propagate the value safely
     *from* an already-human-provided source, without it ever appearing in the agent's visible
     output:
     - **Worker secrets**: pipe it straight from the source file into `wrangler secret put`,
       never through an intermediate variable that gets echoed: `ssh source-host "grep '^FIELD='
       file | cut -d= -f2-" | wrangler secret put SECRET_NAME --name worker-name`. Confirmed
       working 2026-07-19 propagating a rotated Telegram token to two Workers this way.
     - **An app's own credential-update API**: build the request body **server-side, on the host
       that already holds the source value**, using a small script (Python `urllib`/`requests`,
       not raw shell string interpolation) run over SSH on that host — the value only exists in
       that host's process memory long enough to make the call. See the `n8n-workflow-api-authoring`
       skill's credential-update section for a concrete worked example (`PATCH
       /api/v1/credentials/{id}`).
4. **Verify structurally** — field names all present (step 4 in the table above).
5. **Verify functionally** — a real send/call, reading the *service's* response.
   - **When the integration has no synthetic test endpoint** (a cron-triggered Worker with only a
     `scheduled` handler, a queue consumer with no manual-invoke path), the correct functional
     test is triggering the *real underlying condition* rather than inventing a fake one — e.g.
     stopping the actual monitored service briefly and waiting for the real alert to fire, then
     restarting it. Confirmed working 2026-07-19 for both a Grafana alert rule (stopped
     node-exporter) and a Cloudflare cron Worker (stopped a health-check proxy).
   - **It's OK to end a rotation at "high confidence but not independently fire-tested"** for a
     surface whose real trigger path is genuinely impractical to force (a 30-minute exponential
     backoff, a queue's internal retry-count metadata that can't be set from outside) — *if* the
     code path is confirmed identical to one that *was* fire-tested with the same credential, and
     the credential update itself was confirmed accepted (a 200 response, an `updatedAt` that
     changed). State this honestly as a distinct, weaker confidence level rather than either
     skipping the surface silently or claiming full verification that wasn't actually done.
6. **Verify the old credential is actually dead** — same functional test, old value.
7. **Only after that**, move to the next integration point if there's more than one, repeating
   steps 4–6 for each. Don't declare a multi-surface rotation done until every surface has been
   functionally verified individually — a credential can work in one integration and be
   misconfigured in another.

## Batch, don't trickle

If a rotation is already underway because of a leak and the credential touches multiple systems,
handle all of them in the same sitting rather than discovering integration points one at a time
across hours. Slower, serialized rotations don't just cost time — each one is a fresh opportunity
for the human's manual file edit to introduce an unrelated mistake, and for whoever's verifying to
reach for an unvetted "just this once" command under the accumulated time pressure.

## A credential that cannot be rotated headlessly — find these before an incident does

Added 2026-09-04 after inventorying the agent hosts' email credentials.

Most of this skill assumes rotation is a scripted operation. Some credentials aren't. The HEY
agent CLI (`~/.config/hey-cli/credentials.json` on each agent host) uses a refresh-token flow
whose only re-issuance path is `hey auth logout` → `hey auth login`, and **login requires
completing a browser sign-in**. There is no headless equivalent. `HEY_TOKEN` looks like an escape
hatch but accepts only the *short-lived access token*, so it cannot be sourced from a secrets
manager and left alone.

The practical consequences, all of which are worse discovered mid-incident:

- **It cannot be migrated into Infisical/Vaultwarden as the live source.** The file on disk is
  the authoritative store, by design of the tool. Trying to centralise it produces a broken
  integration, not a safer one.
- **Rotation needs a human at a browser, per host.** Two agent hosts means two sign-ins.
- **A compromise cannot be remediated in seconds.** That changes the calculus on what the
  credential is allowed to reach — which is why agent-*originated* email moved to Postmark
  (revocable in one dashboard click, per-address) while HEY stayed for read/triage only.

**When inventorying any credential, record the rotation mechanism, not just the location.**
"Where does it live" is the easy half; "what does re-issuing it actually require, and who has to
be awake for it" is the half that matters when something has gone wrong. A credential whose
rotation is browser-interactive is a different operational object from one behind an API, and the
inventory should say so explicitly rather than leaving a future reader to discover it.

**Corollary for detection**: because these can't be rotated quickly, detecting a *lapse* early
matters more than usual. Both agent hosts now publish `email_creds_missing` and
`email_creds_bad_mode` (presence and mode only — never contents) into the tailnet health document
their peer watches, so a vanished or loosened credential file surfaces cross-host within 15
minutes rather than at the next attempted send. Counts, not paths: there is no reason to publish
the location of every credential on a host to anything that can reach the health port.
