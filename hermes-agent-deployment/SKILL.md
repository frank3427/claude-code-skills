---
name: hermes-agent-deployment
description: This skill should be used when deploying or debugging a self-hosted Hermes Agent (Nous Research's self-hosted personal-assistant gateway bridging Telegram/WhatsApp/Slack/Discord to an LLM with tool/skill/cron access — Will calls his instance "Chuka") — including install via the `hermes` CLI, the `hermes-gateway.service` systemd unit, native `hermes cron` scheduled jobs, the `hermes skills` system (SKILL.md drop-in files distinct from Claude Code's own skills), Debian 13 install gotchas (python3.13-venv, broken IPv6/gai.conf), fleet-readonly SSH access design, or UID-scoped egress firewalling. For credential protection via Agent Vault specifically, see the separate `agent-vault-credential-broker` skill — this skill covers Hermes's own deployment, not the broker. Trigger phrases include "hermes agent", "hermes gateway", "hermes cli", "hermes cron create", "hermes skills list", "hermes-gateway.service", "hermes mcp install", "ensurepip is not available", "HERMES_HOME", "hermes gateway install --system", "chuka", "hermes_cli.main gateway run", "LunaRoute glm-5.3-flash", "hermes fleet access", "hermes-remote", "hermes_egress table", "hermes gateway setup selector drops to done", "hermes setup tools", "hermes homeassistant setup not prompting", "aiohttp trust_env proxy bypass", "hermes update reverted patch", "uv pip install no pip module hermes venv", "hermes memory provider", "hindsight plugin", "memory.provider hindsight", "lazy_deps exact pin", "Feature memory.hindsight unavailable", "local_external".
---

# Hermes Agent deployment

Built and verified end-to-end 2026-08-31 deploying a personal instance on a Vultr VPS
(`hermes-agent`, Dallas, Debian 13), wired to Telegram, LunaRoute (custom LLM provider), and
Groq (voice transcription) — Will's nickname for the running instance is "Chuka" (a personal
name, not an infra rename; every host/user/vault stays `hermes-*`). Every gotcha below was hit
for real building it and its follow-on capabilities, not assumed from docs. Deliberately kept
separate from the `homelab-ansible`-managed fleet (Will's call) but, per his standing
Ansible-first instruction for this project, fully Ansible-managed from day one via its own
`hermes-ansible` repo run **locally on the box** (`ansible_connection=local`), mirroring how
`dfw-ansible` runs locally for OpenClaw rather than being pushed from `ansible-ctrl`.

## Install

```bash
npm install -g @nousresearch/hermes-agent   # exact package name — verify against current docs,
                                             # this is a fast-moving research-preview tool
hermes --version
```

Run as a dedicated non-root `hermes` system user — Hermes's own installer refuses `--system`
install as root without an override, since running a Telegram-driven exec-capable process as
root indefinitely is a real risk, same reasoning as OpenClaw's `openclaw` user.

Gateway service install is a CLI subcommand, not a hand-written unit file:

```bash
hermes gateway install --system --run-as-user hermes --start-now --start-on-login
```

Confirmed idempotent as-is — a second invocation prints "Service already installed ... Use
--force to reinstall" and just ensures the service is running; it does **not** silently no-op
forever, so **don't** add a `creates:` guard in Ansible around this command (that would
permanently block a deliberate future reinstall, e.g. after a CLI upgrade changes the generated
unit template — same "creates: guard blocks upgrade" failure shape documented in the
`proxmox-node-systemd-service` skill for n8n). Use an idempotency check on the command's own
stdout instead (`changed_when: "'already installed' not in result.stdout"`), and a separate
`-e hermes_gateway_force_reinstall=true`-gated `--force` path for deliberate reinstalls.

The resulting unit (`hermes-gateway.service`) has **no** `ProtectSystem=`/`ReadWritePaths=`
hardening by default — plain `Type=simple`, `User=hermes`, `WorkingDirectory=/home/hermes/.hermes`,
`ExecStart=<venv>/bin/python -m hermes_cli.main gateway run`. This matters if you ever wrap it
with `agent-vault run --` or add hardening later — no pre-existing `ReadWritePaths=` mount-
namespace gotcha to worry about here (unlike OpenClaw's already-hardened unit).

## Two real Debian 13 install-time gotchas, baked into Ansible so a rebuild doesn't rediscover them

1. **`python3.13-venv` isn't preinstalled.** `hermes mcp install <name>` bootstraps each MCP
   server into its own venv via the *system* `python3 -m venv`, not Hermes's own bundled
   interpreter — fails with `ensurepip is not available` until `apt install python3.13-venv`
   (or whatever minor version matches `python3 --version` — don't hardcode `3.13`, derive it).
2. **Broken outbound IPv6 + DNS still returning AAAA records.** This VPS class has no real IPv6
   route (`curl -6 https://api.telegram.org` hangs/fails) but some hosts still resolve an
   IPv6-only AAAA record, so glibc's `getaddrinfo()` prefers a dead candidate by default. Fix:
   uncomment `precedence ::ffff:0:0/96 100` in `/etc/gai.conf` (deprioritizes IPv6 without
   disabling it — general OS hygiene, not disruptive). **Note**: this was NOT the actual root
   cause of a real Telegram-connection hang hit the same day — Hermes's own Telegram adapter
   already has a hostname-preserving IPv4-literal fallback transport built in for exactly this
   "blackholed IPv6 AAAA" scenario. Keep the `gai.conf` fix anyway as correct-regardless-of-cause
   OS-level hygiene for any *other* process on the box that lacks Hermes's own workaround.

## Config and secrets

`~/.hermes/config.yaml` — model provider config (`providers.<name>.base_url`/`key_env`/
`api_mode`), voice/STT provider (`groq: model: whisper-large-v3-turbo`), memory settings. This
project's instance uses a **custom** provider, `custom:lunaroute` (LunaRoute — an OpenAI-
compatible `chat_completions`-mode gateway, `base_url: https://gw.lunaroute.com/v1`), not a
first-party Anthropic/OpenAI provider — check `config.yaml` directly for the real auth header
shape before assuming a custom provider is plain bearer auth (it happened to be, here, but that's
not guaranteed for every custom provider).

`~/.hermes/.env` holds credential values Hermes reads at its own application layer (via
python-dotenv or similar) — **these do not appear in `/proc/<pid>/environ`** even after the
gateway is running, since Hermes loads `.env` itself rather than relying on systemd's
`EnvironmentFile=` for it. Don't use a `/proc/<pid>/environ` check to verify `.env` changes took
effect — check the file's own content (structurally, e.g. `cut -d= -f1` for field names, never
`cat`/`grep` a full line — see the credential-rotation-protocol skill) and confirm via a real
functional test instead. See the separate `agent-vault-credential-broker` skill for how this
project migrated `.env`'s three real values (LunaRoute/Telegram/Groq) to placeholders backed by
Agent Vault — that migration uses a genuinely different systemd wiring pattern than OpenClaw's
(a plain `HTTPS_PROXY`/CA-trust `EnvironmentFile=` via a `.service.d/override.conf` drop-in, not
an `ExecStart` wrapper), confirmed via Agent Vault's own `hermes-on-vps.mdx` guide, not guessed
from OpenClaw's pattern.

**Real, generalizable gap found 2026-08-31**: if a credential is ever set up by pasting the real
value into a chat message *with Hermes itself* (e.g. asking Chuka to write it into `.env` for
you), that value persists in Hermes's own `state.db`/session history indefinitely, surviving
both a later `.env` scrub and a provider-side key rotation. Always set new credentials directly
via the Agent Vault CLI (or hand-edit `.env` yourself) — never relay a real secret value through
a message to the agent.

## Native scheduling: `hermes cron`

Hermes ships a full first-party cron system — durable (tracked in `~/.hermes/cron/*.db` with
real run history, survives gateway restarts), **not** analogous to Claude Code's session-scoped
`CronCreate` tool. Key subcommands:

```bash
hermes cron list                                    # see existing jobs
hermes cron create '<schedule>' '<prompt>' \
  --name <name> --deliver telegram --skill <skill-name>
hermes cron run <name>                               # fire on the next tick, for testing
hermes cron runs <job-id>                            # durable execution history
```

Schedule accepts cron syntax (`0 12 * * 0`) — **the box's own system timezone applies** (UTC by
default on a fresh Vultr Debian image; check `timedatectl` before picking a schedule, don't
assume it matches Will's local time). `--deliver telegram` sends the job's final response
straight to the paired chat; the prompt is automatically told it's running as an unattended cron
job and to respond with exactly `[SILENT]` (nothing else) to suppress delivery when there's
nothing to report — a real, working convention, not something to reinvent.

**A DST change silently skips jobs (confirmed 2026-11-01, v0.20.6).** `next_run_at` is stored
with a fixed UTC offset. After a DST change, any job whose stored time was computed before it is an
hour off. At that tick the scheduler logs `next_run_at ... does not match its current cron expression
... re-anchoring to <next> without firing`, so that run is **lost** (the weekly report missed 11-01).
A one-shot day-of-year job re-anchors to next year, so it never fires. Fix it **after** the change:
compare each job's `next_run_at` hour with its expression (jobs.json), and recompute any mismatch
with `hermes cron edit <id> --schedule "<same expr>"`. That leaves the prompt, skills and delivery
untouched.

No dedup/idempotency built into `cron create` itself — an Ansible task wrapping it needs its own
`hermes cron list | grep <name>` guard before creating, or a re-run duplicates the job.

Verify a new job for real, don't trust "created successfully" alone: `hermes cron run <name>`
then check `~/.hermes/cron/output/<job-id>/*.md` for the actual rendered prompt + response —
this project caught a version-drift discrepancy (an LLM-reported n8n version newer than the last
confirmed-live one) this way, worth a quick sanity skim even on a "successful" test run.

**Two real gotchas found building the agent-exchange channel (2026-09-01), both worth checking
before trusting a cron test:**

- **`hermes cron run <id>` invoked via a manual `su hermes -c '...'` (or any shell outside the
  running `hermes-gateway` process) does not have that process's environment** —
  `EnvironmentFile=/home/hermes/.hermes/gateway.env` is only sourced by systemd at the
  gateway's own launch, and that file carries `HTTPS_PROXY`/`HTTP_PROXY` pointing at Agent
  Vault's MITM listener plus its CA-trust env vars (`REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
  etc. — see the `agent-vault-credential-broker` skill). A manually-triggered run makes real,
  unproxied calls straight to the model provider with no credential, and fails with a plain
  auth error (`401`, "provide your API key") that looks like a broken cron job rather than a
  test-methodology artifact. Same failure shape as the documented `EnvironmentFile=` gotcha in
  the global CLAUDE.md ("a script tested by direct invocation instead of `systemctl start`
  silently runs with zero credentials"), just one layer further removed since the credential
  here is injected at the network layer, not the process env directly.
- **For a `--monitor-script` job specifically, that same manual `hermes cron run` still executes
  the monitor-script check before failing** — so it updates the scheduler's "last known output"
  baseline even though the agent turn itself errors out. The *next real scheduled tick* then
  sees "no change" against that stale-but-recorded baseline and silently suppresses the agent
  run entirely (`cron.scheduler: monitor output unchanged — suppressing agent run` in
  `~/.hermes/logs/agent.log`) — the real trigger that prompted your test never actually gets
  processed, with no error anywhere. **Never manually `hermes cron run` a `--monitor-script`
  job to test it.** Wait for a real scheduled tick, or check `~/.hermes/logs/agent.log` for
  `monitor output unchanged` after a manual trigger to confirm whether this happened.
- Separately (not a monitor-script issue): `--deliver telegram` on a `hermes cron create` job
  can silently fail to resolve a delivery target (`hermes cron list` shows "⚠ Delivery failed:
  no delivery target resolved for deliver=telegram") even on a job that completes `ok` —
  confirmed on this project's `weekly-fleet-report` job. **Root-caused and fixed 2026-09-01**:
  the bare `telegram` delivery target (and `hermes send --to telegram`) resolves against a
  `TELEGRAM_HOME_CHANNEL` config key that's easy to miss setting during initial setup — check
  `hermes config get TELEGRAM_HOME_CHANNEL` (chat ID visible via `hermes send --list telegram`,
  which shows the already-paired contact even when the home-channel key itself is unset).
  **Setting it is not enough on its own** — `hermes-gateway` reads `config.yaml` once at
  startup and does not hot-reload, so a running gateway keeps failing until restarted
  (`systemctl restart hermes-gateway`) after any `hermes config set`. `hermes-config-
  install.yml` in `hermes-ansible` now restarts the gateway automatically whenever a config
  value actually changes — model this pattern for any future `hermes config set` task rather
  than assuming a config edit takes effect live. Verify a delivery fix via a real scheduled
  tick (throwaway one-shot `--repeat 1` job), never a manual `hermes cron run` — same reasoning
  as the monitor-script gotcha above, a manual trigger's own credential/env gaps can produce a
  misleading result either way. In general: if a cron job's Telegram delivery matters, verify
  an actual message arrives, don't trust `Execution: completed` alone; `--deliver local` (or
  writing output to a file the job manages itself, as `agent-exchange-poll` does) is the right
  choice whenever you don't need Hermes's own delivery path at all.

### The credential trap has a second, far more deceptive symptom: `hermes send` → "Not Found"

Added 2026-09-04, after the gotcha above — already written down here since 2026-09-01 — was
rediscovered the hard way three times in one session, because **only the `401` symptom was
documented and the other symptom looks nothing like a credentials problem.**

`hermes send` invoked from a plain SSH shell has no bot token, for exactly the same reason
`hermes cron run` has no API key: `EnvironmentFile=/home/hermes/.hermes/gateway.env` is sourced
only by systemd at the gateway's launch. But its failure is not an auth error. Telegram's API
returns **HTTP 404 for a bad/absent bot token in the URL path**, so the CLI reports:

```
hermes send: Telegram send failed: Not Found
```

which reads as *"that chat doesn't exist"* or *"the bot isn't in that group"* — a plausible,
specific, and completely wrong conclusion. It cost a real one: a canary was pointed at a user's
DM instead of a shared group, and Will was asked to add a bot to a group it was probably already
in.

**The control test that settles it in ten seconds** — run before drawing any conclusion from a
`hermes send` failure:

```bash
# Send to a chat you KNOW works (one with confirmed deliveries in agent.log).
sudo -u hermes -H env HERMES_HOME=/home/hermes/.hermes hermes send -t telegram:<known-good-id> 'control'
```

If that *also* returns "Not Found", the token is missing and the result says nothing about the
chat you actually care about.

**Generalised rule for this host — the one to remember instead of the individual symptoms:**
any `hermes` CLI subcommand run from a plain SSH shell runs without credentials and **is not a
probe of the live system**. `cron run` shows it as `401`, `send` shows it as `Not Found`, and a
future subcommand will invent a third disguise. Verify through the gateway — temporarily
reschedule the job to fire in a couple of minutes, read `agent.log`, restore the schedule — or
claim nothing.

### Per-message delivery is logged in `agent.log`, NOT the systemd journal

This is the enabling fact for any external verification of Hermes's output, and it is easy to
conclude the opposite. `journalctl -u hermes-gateway` carries Telegram **connection** health
only — reconnects, 502s, polling state — and never a per-message line. Three days of journal on
a live box contained zero `chat_id`/`chatId` strings, which supported a confident and wrong
conclusion that Hermes could not be externally verified at all.

The delivery record lives in `~/.hermes/logs/agent.log`:

```
INFO cron.scheduler: Job '<job_id>': delivered to telegram:<chat_id> via live adapter
INFO cron.scheduler: Job '<job_id>': mirrored delivery into telegram:<chat_id> session transcript
INFO cron.scheduler: Job '<job_id>': agent returned [SILENT] — skipping delivery
```

Root can read it while the agent cannot forge systemd's view of its own liveness, which is what
makes an out-of-process verifier possible — see the `agent-delivery-canary` skill for the
architecture built on top of this.

## A gateway process restart does NOT reset Chuka's live chat session

**Confirmed 2026-09-01.** Restarting `hermes-gateway.service` restarts the Python process, but
each messaging-platform conversation (Telegram, etc.) is a persistent session tracked in
`~/.hermes/state.db`/`~/.hermes/sessions/` (`hermes sessions list` shows title, last-active,
and session ID) — the gateway resumes that same session's history on the new process, it does
not start fresh. If you install a new skill or otherwise change something the *live chat*
needs to know about, restarting the gateway does not make an already-running long-lived session
aware of it — that session's own context/skill-awareness was established whenever it last
started (in one real case, over 24 hours and multiple unrelated gateway restarts earlier),
completely independent of the service's process lifecycle.

Cron-triggered jobs don't have this problem — each tick is a genuinely fresh, isolated session
(`cron_<jobid>_<timestamp>`), so a `--skill` attached to a cron job definition is visible on
every run regardless of how old the gateway process is. It's specifically the long-running
interactive chat sessions (Telegram/etc.) where new skills/context can go unnoticed.

**The reliable fix is direct**: tell Chuka in the live chat (a message from Will, or content
Chuka is asked to read) rather than assuming a restart or a new skill install will surface
automatically. Chuka has full file-read tools, so pointing it at a specific path
(`~/.hermes/skills/devops/<name>/SKILL.md`, a doc, etc.) mid-conversation works immediately —
the gap is discovery, not capability. If a live session genuinely needs to be reset (rare — this
loses its conversational context), that's a different, more disruptive action; don't reach for
it just to pick up a new skill.

**Recurred 2026-09-01 with a different capability** (first was the agent-exchange channel;
second was the dfw `hermes-dfw-admin-changes.sh` restart/trigger script added the same day) —
treat this as a standing pattern, not a one-off: any deploy that updates a skill the live chat
would need to know about should be followed by an explicit "here's what's new" message into the
live session, every time, not just the first time this bit someone. Distinguish this from a
`pre_tool_call`-hook plugin (e.g. `homelab-changes-approval`): that kind of change enforces at
the tool-executor layer regardless of what the live session's own context knows, so it does NOT
need this same nudge — only skill/doc *content* the model is expected to reason from does.

## `hermes plugins doctor` with no target can exhaust /tmp on a small VPS

**Confirmed 2026-09-01** (found by Chuka itself, verifying the `homelab-changes-approval`
plugin). Run bare (`hermes plugins doctor`, no plugin id/path argument), it copies the entire
Hermes home tree into a tmpdir to validate every plugin at once — on a small VPS where `/tmp` is
a ~1GB tmpfs, `~/.cache/uv` and any per-tool venvs (e.g. `~/.hermes/venvs/stt`) blow through that
easily and it dies with `No space left on device`. Moving `TMPDIR` to a disk-backed path doesn't
fully fix it either — the copy then chokes trying to copy live Unix sockets (`gateway.sock`,
`Errno 6`). **Always use targeted mode**: `hermes plugins doctor <plugin-id-or-path>` validates
just that one plugin and works fine. Don't take a bare `hermes plugins doctor` failure as
evidence a specific plugin is broken — check whether it was even given a target first.

## Forcing approval for a command the built-in detector won't flag

**Confirmed 2026-09-01.** Hermes's `approvals.mode` (even `smart`) is only ever consulted for a
`terminal` command that first matches `tools.approval.DANGEROUS_PATTERNS` — a fixed regex list
looking for known-risky shapes (`rm -rf`, `systemctl restart/stop`, `git push --force`, `chmod
777`, etc.). There is no catch-all for "this command does something opaque/remote that I can't
reason about" — a command like `ssh host "sudo /usr/local/bin/some-custom-script.sh restart
nginx"` never matches any pattern (no `systemctl` substring, no `rm`, nothing recognizable), so
`detect_dangerous_command()` returns `False` and the entire approval gate — including
`smart_policy`, which is only read *inside* the gate — is skipped by construction. This bit a
real deployment: two homelab dispatch scripts (`hermes-fleet-admin-changes.sh`,
`hermes-dfw-admin-changes.sh`) had been executing with zero approval for their entire lifetime,
despite every doc claiming otherwise, because SSHing to a custom script name doesn't look
"dangerous" to the pattern list. `approvals.smart_policy` (a config string appended to the
guardian LLM's system prompt) **cannot fix this** — it's a dead end for any command the pattern
list never routes to the guardian in the first place.

**The fix: a `pre_tool_call` plugin hook.** Hermes's plugin system lets a hook run before any
tool call and return `{"action": "approve", "message": "..."}`, which escalates through
`tools.approval.request_tool_approval()` — the exact same human-approval gate dangerous shell
patterns use (session/`[o]nce`/`[s]ession`/`[a]lways`/`[d]eny`, cron/single-query/unattended
context handling, fail-closed when no human is present) — regardless of whether the built-in
detector flagged anything. This is Hermes's own documented answer for exactly this situation;
don't try to hand-patch the vendored `DANGEROUS_PATTERNS` list in `/usr/local/lib/hermes-agent/`
instead (fragile, and wiped on `hermes update`).

Minimal recipe (see `homelab-changes-approval` for a real deployed example, or the bundled
`security-guidance` plugin at `/usr/local/lib/hermes-agent/plugins/security-guidance/` for
another reference shape):

```
~/.hermes/plugins/<plugin-name>/
├── plugin.yaml      # name, version, description, provides_hooks: [pre_tool_call]
└── __init__.py      # register(ctx): ctx.register_hook("pre_tool_call", fn)
```

```python
def _on_pre_tool_call(tool_name="", args=None, **_):
    if tool_name != "terminal":          # the shell/exec tool's name
        return None
    command = (args or {}).get("command")
    if not isinstance(command, str) or not MY_PATTERN.search(command):
        return None
    return {"action": "approve", "message": "Why this needs a human to confirm"}
```

Notes:
- `tool_name == "terminal"` and `args["command"]` is the shell tool's actual shape — verified by
  reading `tools/terminal_tool.py`'s tool registration, not assumed.
- Omit `rule_key` unless you want a specific `[a]lways` allowlist grain; the default derives a
  key from `tool_name` + a hash of `message`, so distinct messages (e.g. one per matched command
  string) get independent `[a]lways` entries rather than one blanket bypass for the whole
  category.
- Deploy the same way as a skill: a small Ansible playbook (`ansible.builtin.copy` for each
  file, `validate: "python3 -c \"import ast; ast.parse(open('%s').read())\""` on `__init__.py`)
  plus a task running `hermes plugins enable <name> --no-allow-tool-override` guarded by `when:
  "'<name>' not in <hermes config get plugins.enabled output>"`, and a gateway-restart handler.
  No `capabilities:` entry needed for a plain `pre_tool_call` hook (that's only for
  `tools.override`/LLM-override surfaces).
- Validate with `hermes plugins doctor <plugin-name>` (targeted mode — see the /tmp-exhaustion
  gotcha above) before trusting it's wired; `hermes plugins show <name>` should report `Status:
  enabled`.
- This kind of fix enforces at the tool-executor layer regardless of the live chat session's own
  context/skill-awareness, unlike a skill-content change — see "gateway restart does not reset
  live chat session" above for why that distinction matters for whether a live-chat nudge is
  also needed.
- **The one thing SSH-based testing as `will`/root can never verify**: whether a real
  interactive-session invocation actually produces a live Telegram approval prompt. Manually
  SSHing in and running the command never goes through Hermes's own tool-call loop, so it can't
  exercise the approval path at all — only a genuine live agent turn (a real Telegram message
  asking Chuka to do the thing) proves the plugin fires in practice, not just that it registers
  cleanly.

### `action: "block"` — the self-correcting variant, and when to prefer it over `"approve"`

`_resolve_block_from_details()` in `hermes_cli/plugins.py` handles two directives, not one:
`{"action": "approve", ...}` escalates to the human gate, and **`{"action": "block", "message":
...}` returns the message to the model** and the call never runs. Fail-closed applies to
`approve` only (a gate that errors, denies, or times out becomes a block).

`block` is the right choice when the command is *categorically* wrong rather than risky, because
the message becomes an instruction the agent acts on in the same turn — the gate teaches instead
of merely stopping. Confirmed 2026-09-04 with `hey compose`: `hey` authenticates as Will's own
HEY account, so an approval prompt asks him to bless a message that is already addressed wrongly,
and when the message is the one he asked for, approving is the natural thing to do. Blocking with
a message naming the correct command (`agent-send-email.sh`) let Chuka correct itself without
another round trip. Reserve `approve` for things that are legitimate but consequential — in the
same plugin, `reply`/`forward`/`share` stay gated because continuing a thread as Will is correct.

**The prompt text is part of the security control, not decoration.** The first version hardcoded
"from Will's own address (account 740440)" for every match, including a Postmark path whose whole
point is that it is *not* that account. Chuka caught it while being asked to approve one and
flagged the reasoning exactly right: a gate that misdescribes what it is gating trains reflexive
approving, and an unread prompt is worse than none because it still costs a click and now buys
nothing. Make the message reflect the route that actually matched.

**Cover every route in the same change that creates one.** Adding the Postmark sender immediately
created a second send path the original regex did not match, which would have silently defeated a
gate deployed hours earlier. A gate is only as good as its coverage.

### A sudoers grant to the `hermes` service account can never work — `NoNewPrivileges=yes`

`hermes-gateway.service` sets `NoNewPrivileges=yes`, so the kernel refuses escalation before sudo
reads sudoers. Any `NOPASSWD` grant to `hermes` is decorative, and the error (`sudo: The "no new
privileges" flag is set`) reads like a container quirk rather than a dead design. Confirmed
2026-09-04: an agent-email sender shipped as a root script plus a path-scoped grant had never once
run from the agent, and looked healthy because the only audit-log entries were root's own test
sends — exactly what a working path produces.

Check `systemctl show hermes-gateway -p NoNewPrivileges` before designing anything needing
escalation. If `yes`, **invert the boundary**: the agent writes a job file into a spool it can
already write, and a root-owned systemd `.path` unit collects it — keeping the credential out of
the agent process entirely, which is what the grant was reaching for anyway. `ProtectSystem=strict`
means the spool also needs a `ReadWritePaths=` drop-in **and a restart** (applied at process
start), and `sudo -u hermes` does **not** reproduce the confinement — verify against the running
process instead:

```bash
grep /var/spool/agent-email /proc/$(systemctl show hermes-gateway -p MainPID --value)/mountinfo
# want: ... /var/spool/agent-email/queue rw,nosuid,...
```

See `project_agent_email_identity_path` memory for the deployed design.

## `hermes skills` — a separate skills system from Claude Code's own

Hermes has its own bundled skills feature, unrelated to `~/.claude/skills/` — a plain file drop
at `~/.hermes/skills/<category>/<name>/SKILL.md` is sufficient for registration, no install
step. Verify via `hermes skills list` (shows name/category/source/trust/status columns). Used in
this project to give Hermes durable operational knowledge about its own SSH-based fleet access
(which user, which host, which dispatch-script subcommands) after a live session tried 12 wrong
usernames and misread an intentional egress-firewall timeout as a bug — the fix was documentation
Hermes could actually read, not a config change.

## Fleet-readonly/changes SSH access pattern

This project gave Hermes SSH-based visibility (and later, a curated non-destructive changes
capability) into the wider homelab fleet, structured identically to OpenClaw's own equivalent on
`dfw` but as a **fully independent identity** — separate SSH keypair, separate system user
(`hermes-remote` on `ansible-ctrl`, `hermes-dfw-remote` on `dfw`), separate dispatch scripts and
sudoers grants, never shared or generalized with OpenClaw's. "The dispatch script is the security
boundary, not the sudoers grant" — curated, array-based, no-shell-interpolation scripts; sudoers
scoped to exactly one script path each; destructive operations categorically excluded rather than
prompt-gated. The **changes** dispatch script (as opposed to the readonly one) is deliberately
never added to Hermes's own `command_allowlist`, so every invocation still triggers a live
Telegram approval — the same split OpenClaw uses.

## UID-scoped egress firewall (`hermes_egress` nftables table)

Same defense-in-depth pattern as `dfw`'s `openclaw_egress` table (see
`reference_openclaw_egress_firewall`) — once Hermes holds any real SSH key or credential worth
protecting, a `meta skuid <hermes-uid>`-scoped nftables table allowlists only: outbound 443/53 to
any destination (the model provider, Telegram, GitHub, apt), and SSH (22)/Agent Vault's proxy
ports (14321/14322) to specific Tailscale IPs only. Everything else hits a counted `drop`. Look
up the UID at deploy time via `getent`, never hardcode it — this project's `hermes` user is UID
999, no reason to assume it matches another host's service account. Diagnostic signature for a
missing rule: a **TCP timeout** (not "connection refused") from this specific UID, easily
mistaken for a Tailscale ACL or destination-side problem.

## `hermes gateway setup` vs `hermes setup tools` — two different config surfaces, easy to confuse

`hermes gateway setup` configures messaging **platforms** (Telegram, WhatsApp, Signal, Discord,
...). `hermes setup tools` (or `hermes setup` → tools section) configures **tools** the agent can
call (Smart Home/Home Assistant, browser backends, Spotify, computer-use, ...) — a materially
different registry with its own `env_vars`/provider schema in `hermes_cli/tools_config.py`.

**Confirmed 2026-09-01**: Home Assistant appears in `gateway setup`'s platform picker
(`platform_toolsets.homeassistant`), but that registry entry has **no `setup_fn` and no `vars`
schema** — selecting it falls through to `_configure_platform()`'s generic no-op path
(`hermes_cli/gateway.py`), which just prints a static banner (`Set these env vars in
~/.hermes/.env: HASS_TOKEN` / a hardcoded `pip install aiohttp` hint) and returns immediately —
this looks exactly like a broken interactive picker (the cursor "drops to Done" on selection, no
matter what key you press) but is actually working as designed; there's no real flow at that
menu entry at all, for any input. The `pip install aiohttp` hint is unconditional static text,
not a live dependency check — don't chase it as a lead.

The **real** Home Assistant setup path is `hermes setup tools` → "Configure all platforms
(global)" → Smart Home category → Home Assistant → REST API integration, which has a genuine
`env_vars` schema (`HASS_TOKEN` prompt, `HASS_URL` prompt defaulting to
`http://homeassistant.local:8123`) and actually asks. Saves to `~/.hermes/config.yaml` (toolset
enablement) + `~/.hermes/.env` (the two vars) and needs `systemctl restart hermes-gateway` to
take effect (the wizard itself can't restart a **system**-installed gateway service — it's
root-owned, the wizard runs as the unprivileged `hermes` user — it'll tell you to `sudo systemctl
restart hermes-gateway` yourself, which is expected, not a bug).

If a `hermes setup <platform>` menu entry behaves like this (silently no-ops back to the picker
on selection, prints only a passive env-var banner), check `hermes_cli/tools_config.py` for a
matching entry under a *different* top-level `hermes setup` section before assuming a UI bug —
Hermes splits "platforms I receive messages from" and "tools I can call" into genuinely separate
config surfaces that happen to share overlapping labels (e.g. "homeassistant" exists as both a
disabled-by-default platform key *and* a tools-category key).

## Suppressing vendor log noise with a plugin instead of patching `gateway/run.py`

Hermes's own logging config exposes only a global `level` — there is no per-logger knob — and
patching a file under `/usr/local/lib/hermes-agent` is reverted by the next `hermes update`
(see the local-source-patches section above). So when vendor code emits a warning that is wrong
on this host's configuration, the durable fix is a **plugin that installs a `logging.Filter` at
import**, Ansible-managed like any other.

Worked example, built 2026-09-05 (`stream-diagnostic-filter`, `hermes-ansible@4715a64`):
`gateway/run.py` warns `Normal final-send NOT suppressed despite active stream consumer ...
possible duplicate send` whenever a stream consumer *object* exists and suppression didn't fire.
With `streaming.enabled: false` and `interim_assistant_messages: true`, consumer creation is
gated on `_want_stream_deltas or _want_interim_consumer` (run.py ~5779), so the second term alone
builds a consumer that nothing ever streams through — every firing carried
`streamed=False previewed=False content_delivered=False`, meaning nothing reached the user and
the final send was the only delivery. 155 warnings in six days, all wrong.

Three mechanics worth keeping:

- **Mutating `record.levelno` inside a logger-attached filter works**, because `Logger.handle()`
  applies the logger's filters *before* `callHandlers()` compares the level against each
  handler's. Downgrade to DEBUG rather than dropping — the line stays reachable under
  `logging.level: DEBUG` instead of vanishing.
- **A plugin with no hooks still needs a no-op `register()`.** Without one the loader logs
  `Plugin 'x' has no register() function` at WARNING on every start *and* leaves the plugin out
  of the `N found, M enabled` tally (57/50 → 57/51 once added), even though `hermes plugins list`
  already showed it `enabled`. A noise-suppressing plugin that adds a warning on every boot is a
  self-defeating deploy; caught only by reading the load log afterwards rather than assuming it
  was clean.
- **Filter narrowly and fail loud.** Suppress only the provably-impossible shape, pass anything
  ambiguous through untouched, and leave a message whose *shape* changed upstream at full
  volume rather than guessing at it. Ship the tests beside the plugin and run them against the
  **deployed** file during the play, before the restart handler fires — a filter's whole job is
  to suppress a log line, so a regression that suppresses the wrong line is invisible by
  construction unless a test asserts what a handler actually emits.

The upstream report is still the real fix (the predicate should require
`_streamed or _previewed or _content_delivered`); the plugin keeps the error stream readable
until it lands. Worth being explicit that this is a local mute of a known-wrong signal, not a
correction of the underlying condition.

## Local source patches don't survive `hermes update` — check after every update

The install is an **editable pip install** (`/usr/local/lib/hermes-agent`, venv at
`/usr/local/lib/hermes-agent/venv`, `uv`-managed — no `pip` module in it; use `uv pip install
--python <venv>/bin/python <pkg>`, run from a directory the invoking user can actually read, not
`/root`, or `uv` fails trying to discover `uv.toml`/`pyproject.toml` config by walking up from
CWD). Any local edit to files under `/usr/local/lib/hermes-agent/` (not `~/.hermes/` — that's
config/data, safe) is a patch to vendor source, not IaC-tracked, and **will silently vanish on
the next `hermes update`** with no warning.

Confirmed real case, 2026-09-01: `tools/homeassistant_tool.py` (4 call sites) and
`plugins/platforms/homeassistant/adapter.py` (5 call sites) construct bare
`aiohttp.ClientSession()` with no `trust_env=True` — unlike Hermes's own LLM-provider calls
(routed through a shared `httpx`-based client in `agent/process_bootstrap.py` that explicitly
honors `HTTPS_PROXY`/`NO_PROXY`), aiohttp **ignores proxy env vars by default**, so this silently
bypassed Agent Vault's credential-injection proxy entirely and sent a raw placeholder token
straight to Home Assistant — a real 401, not a broker bug. Patched locally by adding
`trust_env=True` to all 9 sites. **After any future `hermes update`, re-check**: `grep -c
trust_env /usr/local/lib/hermes-agent/tools/homeassistant_tool.py
/usr/local/lib/hermes-agent/plugins/platforms/homeassistant/adapter.py` should show 4 and 5 —
if either drops, the update reverted the patch and any vault-brokered credential routed through
that tool will silently start bypassing the proxy again. Worth filing upstream to Nous Research
too (same spirit as OpenClaw's known-upstream-bug pattern, `openclaw/openclaw#128314`).

## Narrow a `--monitor-script` so only real work wakes the agent (2026-09-12)

A monitor that prints a raw directory listing changes on **every** filesystem event: archive moves, a
peer's `STATE.md` rewrite, an ack entry. Each change wakes a full agent turn. On one inbox, ~35
woken turns in 12 days ended `[SILENT]`, clustered right after a daily job acked and archived
topics. Watch out for this before reading audit rows as billing bugs: `response_silent: true` means
the monitor *did* see a change and the agent read everything, then had nothing to do. It's real input
(usually 95–99% cached). Unchanged ticks never call the model and write no audit row.

**Pattern: a seen-file, with output that changes only on qualifying additions.**
- Compute the qualifying set: new numbered entries that are not `action: fyi` (a missing or unreadable
  action line counts, failing toward waking), plus any `HELD.md` marker.
- Compare with the previous tick's set stored in a seen-file. If it gained a member, rewrite a one-line
  header `wake N: <new paths>`. **Removals never change the output**, but they do shrink the stored
  set, so a path that disappears and reappears still wakes.
- Write atomically (tmp + `mv`), with `2>/dev/null` *before* the `>` redirect so a failed open stays
  silent. If the seen-file can't be written, print the raw set so a wake is never lost.
- **Deploying it causes one wake** (the format change). The seed marks everything present as seen, so
  confirm nothing unanswered is sitting in the inbox first; the job prompt should re-scan open topics on
  any wake.
- Test with `EXCHANGE_DIR`/`SEEN_FILE` overrides on throwaway copies, as the service user: fyi,
  STATE.md and archive stay silent; a required entry, a HELD appearance or reappearance, a missing
  action and an unreadable file all wake; a brand-new fyi-only topic stays silent; the unwritable
  fallback works.
- **Never run the monitor by hand against the real seen-file.** Like `hermes cron run`, it consumes the
  next real tick's change signal.
- **The side effect for writers:** anything the agent must act on has to be marked `action: required`,
  so document that in the channel convention.

**Script-only cron jobs (`--no-agent`) for canaries.** An agent-run canary is exposed to model drift.
On one day the model invented commands that didn't exist (`~/.hermes/bin/canary-status`) instead of
the prompt's real script, which produced false "status unavailable" lines, and several fires failed on
provider 429s. A `--no-agent` job that runs the status script and formats the line itself removes both,
at the cost of the anti-fabrication framing an agent turn gives. Running both side by side for a week,
with a visible prefix such as `[script]`, is a cheap way to decide. When checking an existing job's
name before create, avoid names that substring-match another job's (the create guard greps `cron
list`).

## Cutting a cron job's per-wake cost: trim its toolset (2026-10-30)

**What a cron wake actually costs.** Every run is a fresh session (`cron_<job>_<timestamp>`,
`history=0`; `scheduler.py` builds it new each time), so there is **no history replay**. The cost is
API calls × the base prompt. The base is mostly tool schemas, and it is ~97–100% cached. On Chuka's
`agent-exchange-poll` the monitor gated the model down to 168 wakes out of ~42,300 ticks, and the
"~1.3M tokens/day" was ~35k base × calls per wake. Proposals to "summarise history" or "shorten the
prompt" don't touch either factor.

**The lever is a per-job `enabled_toolsets`.**
- Each MCP server adds all of its tools to every call (Krisp 26 + n8n 12 + HEY 6 = 44 tools, plus 30
  native ones).
- A job that only reads files and writes one reply needs `[terminal, file, skills, memory, web,
  no_mcp]`. The `no_mcp` sentinel drops every MCP server for that job only
  (`_merge_mcp_into_per_job_toolsets`).
- `hermes cron edit` has **no toolset flag**. Set it with `cron.jobs.update_job(job_id,
  {"enabled_toolsets": [...]})` from the Hermes venv, as hermes-ansible
  `hermes-agent-exchange-cron-install.yml` does, with an assert that reads the value back.
- The scheduler re-reads `jobs.json` every tick, so no restart is needed.
- Before changing anything, check every tool the job's prompt and skill call is still in the trimmed
  set: an "Unknown tool" error mid-turn is the failure mode.

**Measure offline:** `hermes prompt-size --platform cron --json` gives the base without MCP tools;
add the MCP tool schemas yourself. Then confirm on the next real wake: call #1's input tokens should
drop (35k → ≤20k expected here) and the reply should still land.
**Control:** another job with MCP still on (here the gym jobs, ~26.7k at start) shows that the drop
came from the trim, not from a quieter day.

## Web dashboard + Desktop app remote backend (built 2026-11-02, v0.20.6)

`hermes dashboard` (UI + API) / `hermes serve` (API only) on port 9119 is what both the browser and
Hermes Desktop's "Remote gateway" connect to; the Telegram gateway is a separate process. Facts from
the source:
- **Auth:** a non-loopback bind, or a non-loopback `HERMES_DASHBOARD_PUBLIC_URL`, engages the gate,
  and with no provider it fails closed. The bundled `dashboard_auth/basic` reads
  `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `_PASSWORD_HASH` (scrypt, contains `$`, so single-quote it
  in a systemd EnvironmentFile) / `_SECRET`. The login is `POST /auth/password-login` with
  `{"provider":"basic","username","password"}`. `/api/status` is public and shows `auth_required`
  and `auth_providers`.
- **Tailscale Serve, not `--host 0.0.0.0`:** bind 127.0.0.1 and set PUBLIC_URL to the ts.net
  name. Serve's peer is loopback and the Host header matches, so both guards pass.
- **No second scheduler:** the dashboard's own cron ticker and orphan-gateway reaper run only with
  `HERMES_DESKTOP=1`, the app's local backend, so a server dashboard can't double-fire jobs.
- **Build the web UI first:** it isn't shipped built. Run `npm run build` in `web/` to produce
  `hermes_cli/web_dist` (gitignored), then use `--skip-build`. The build takes ~40 s; the dashboard
  idles at ~355 MB.
- **Give it the gateway's environment** (gateway.env for the Agent Vault proxy, the same
  ReadWritePaths), because dashboard chats run agent turns.
- **YOLO skips every approval, plugin `approve` gates included** (`request_tool_approval` →
  `_run_approval_gate`). A Shift+click on Desktop's zap sets global `approvals.mode: off`, which
  also affects Telegram and cron. There is no config option to disable the toggle, so pin
  `approvals.mode` and watch it for drift.

## Telegram identity

`getMe` against the live bot token returns `{"id": 8810663021, "username": "DFWHermesBot",
"first_name": "Chuka Hermes", ...}` — useful as a sanity check after any credential change
(bot-token mixups have happened twice on this project's other Telegram bots during unrelated
rotations; confirm the numeric `id` matches, not just that *some* bot responds).

## Turn watchdog — the layer systemd, the stability check and the canary cannot see

Built 2026-09-07 (`hermes-turn-watchdog-install.yml` in `hermes-ansible`). Two incidents motivated
it: a 420-API-call runaway turn looping on empty probe results, and a corrupt `state.db` that made
every scheduled turn die at its first write for ~90 minutes while `hermes-gateway.service` stayed
`active`. In both, the *unit* was healthy and the *service* was dead. The watchdog is root-owned,
script-only, reads `~/.hermes` read-only every 2 minutes, and never talks to a model.

Facts about Hermes's storage that the design rests on, all verified on the box:

- `~/.hermes/state.db` holds `sessions` (`id`, `source` in `cron|telegram|subagent|cli`,
  `started_at`/`ended_at`/`last_activity_at` as epoch floats, `tool_call_count`,
  `api_call_count`) and `messages` (`session_id`, `role` in `assistant|tool|user|session_meta`,
  `tool_name`, `content`, `timestamp`). Cron sessions are named `cron_<jobid>_<ts>` and end with
  `end_reason = cron_complete`. **A dead-but-unclosed session has `ended_at` null forever**, so
  "stuck" must also require recent `last_activity_at`, or a stale row alerts every tick.
- `~/.hermes/cron/executions.db` holds `executions` (`job_id`, `status` in
  `completed|failed|unknown`, ISO timestamps, `error`) and `cron_incidents` — Hermes already
  records per-job failures with an `error_sig`; read those rather than re-deriving from logs.
- **`executions.pid` is the gateway's PID, not a per-turn process.** Turns are threads inside one
  process, so there is no surgical kill; remediation is a gateway restart or nothing.
- **`session_turn_leases` was empty while a DM turn was demonstrably in progress**, so it cannot
  be the only "is a human talking to him right now" check. Also treat any non-cron session with
  `last_activity_at` in the last 3 minutes as live.
- `.recover` on a corrupt `state.db` emits the FTS5 virtual tables as `sqlite_master` inserts the
  CLI rejects, leaving shadow tables and the `messages_fts_*` triggers behind; Hermes then falls
  back to JSONL session storage with "shadow table already exists". Recreate both virtual tables
  by hand (`content='messages'` and `content='messages_fts_trigram_src'`) and `rebuild`.
- There was no `sqlite3` CLI on the box by default; it is now installed by
  `hermes-system-deps-install.yml` (added 2026-09-07 after being needed mid-incident).
  `/usr/bin/python3`'s `sqlite3` module is the other always-available tool, and `~/.venv` does
  not exist for the `hermes` user.

Test it against a **copy** of the databases, never the live ones: `HTW_HERMES_HOME=<copy>
HTW_STATE_FILE=<tmp> HTW_UNIT=no-such-unit.service HTW_LOG_FILE=<tmp>` plus
`HTW_TELEGRAM_STUB=1` to exercise state/dedupe without paging anyone, and `--dry-run` for a
read-only verdict. The first control run against live data will report whatever is genuinely
standing; seed the dedupe state with a stub run before enabling the timer if those findings are
already known and handled.

## Pinning the checkout — `hermes update` cannot, so Ansible does (2026-09-07)

`hermes update` tracks `origin/main`, never a release tag, and moves a tag-pinned checkout back
onto `main` (upstream #34514 closed P3 without a fix; #13603 rollback still open). On this
project it is therefore never run; `hermes-ansible`'s `hermes-checkout-pin-install.yml` owns the
checkout and `updates.check: false` stops the CLI suggesting it. Three facts that cost a wrong
first run, worth knowing before building the same thing elsewhere:

- **The installer's clone is shallow** (`git rev-parse --is-shallow-repository` → `true`,
  `.git/shallow` lists boundary commits). On a shallow clone `git describe`, `merge-base
  --is-ancestor` and `rev-list --count` all answer confidently and wrongly (`v2026.8.27` reported
  "not an ancestor" of a HEAD built from it). `git fetch --unshallow --tags origin` once, metadata
  only, before trusting any ancestry check.
- **The "upstream <sha>" that `hermes --version` prints is NOT the commit the checkout was built
  from.** It is `origin/main`'s tip at the last fetch (what an update would move to). The real
  base is the parent of the first carried commit (`git rev-parse <carried>^`). Declaring the
  printed sha as the base made the pin playbook refuse, correctly.
- **Local patches belong on a branch, as commits.** The `trust_env` patch sat as an uncommitted
  modification for a week; `hermes update` would have stashed it (`updates.non_interactive_local_changes:
  stash`) and parked the carried commit onto `main` with a notice nobody reads. It now lives on
  `local` beside the quarantine fix; `hermes-stability-check.sh` alerts on a dirty tree or a
  base mismatch every morning. The "Local source patches don't survive `hermes update`" section
  above still applies to any *new* patch until it is committed the same way.

Also set the same day: `updates.pre_update_backup: full` (was `false`, i.e. no backup at all)
and `tool_loop_guardrails.hard_stop_enabled: true`. v0.20.6 has no interactive-vs-cron split for
the hard stop; it applies to DM turns too, at upstream's default thresholds (5/8/5). The
per-turn `loop_caps` (50 web searches, 50 subagents) are always on regardless.

## External memory provider plugins (Hindsight pilot, 2026-10-03) — the traps

Hermes 0.20.6 ships in-core memory plugins (`plugins/memory/<name>`). They are enabled with
`memory.provider: <name>` (`hermes-config-install.yml`) and each reads `~/.hermes/<name>/config.json`.
Built-in MEMORY.md/USER.md stays on alongside. Checking `hermes memory status` as `hermes`, with
`HERMES_HOME`, shows `Provider`, `Plugin: installed`, `Status: available`.

- **Exact client pin.** `tools/lazy_deps.py` pins each plugin's SDK exactly (for example
  `"memory.hindsight": ("hindsight-client==0.6.1",)`). Any other installed version fails that
  check, so Hermes tries to pip-install as `hermes` into the root-owned venv, fails, and **disables
  the feature at runtime** (`retain failed: Feature 'memory.hindsight' unavailable`). Install
  exactly the pinned version, and re-check the pin after every Hermes upgrade.
- **The venv has no pip.** It was built by uv. `uv` exists only as hermes-owned binaries
  (`~/.local/bin/uv`, `~/.hermes/bin/uv`), and **root must not execute a file the hermes user can
  write**, because that's an escalation path. Bootstrap with the interpreter's stdlib:
  `/usr/local/lib/hermes-agent/venv/bin/python -m ensurepip`. It installs **`pip3`**, not `pip`
  (an Ansible `pip` task pointed at `bin/pip` fails rc=2 with no output).
- **Default mode is cloud.** Hindsight's plugin defaults to `mode: cloud` (Vectorize's hosted API).
  Its `is_available()` returns true in cloud mode once an API key **or** an `api_url` exists. Write
  `config.json` (`local_external`, your URL) **before** setting `memory.provider`, and gate each
  step on the previous one's exit code. A failed install hidden by `| grep` in an `&&` chain once
  let the provider go live with no config. It stayed inert only because no key or URL existed yet.
- **Status indicators:** `recall_indicator`/`retain_indicator` print a status line in Telegram on
  every turn; set both false.
- **Cron turns don't retain:** Chuka's 2-minute cron turns created nothing, so background jobs
  don't flood the store.
- **Test with an incidental detail, not an explicit fact.** "For the record: X" is written to
  USER.md by the built-in memory tool, so it proves nothing about the provider. Check the
  provider's own store directly (e.g. Hindsight bank `chuka` documents), and mention the test
  detail in passing.
- **Keys through Agent Vault:** a placeholder `HINDSIGHT_API_KEY` in `.env`, with the real key in
  the `hermes` vault as service `hindsight`. The tailnet IP had to be added to netguard's
  `AGENT_VAULT_NETWORK_ALLOWLIST`. The client is aiohttp with `trust_env=True` set by the library itself (unlike the
  bare `aiohttp.ClientSession()` calls in the Home Assistant tool above), so it honors gateway.env's proxy. Its urllib `/version` probe does not (407): harmless, it only disables
  `update_mode='append'`.


## Gotchas found 2026-11-02 (v0.20.6 pinned build)

- **Never press the Desktop app's "Update Hermes" button** ("Backend out of date"). It runs
  `hermes update`, which tracks origin/main, not a release, and parks the carried local commits.
  Version changes go through `hermes-checkout-pin-install.yml`. The Desktop's version check is
  separate from `updates.check`, so turning that off doesn't hide the banner.
- **Edge TTS (the default when config.yaml has no `tts:` block) fails with a WebSocket 403 on
  edge-tts 7.2.7.** Microsoft rejects old client versions. It fails without the proxy too, so it's
  not Agent Vault. edge-tts 7.3.1 works, and Hermes v0.22.5 pins it. Telegram voice replies are
  `/voice on` (reply in voice to voice notes) or `/voice tts` (every reply). They need the `tts`
  toolset and ffmpeg.
- **An OAuth MCP server that fails at gateway start is parked "until credentials change"** and is
  never retried by the 5-minute self-probe. After fixing the cause (here, an Agent Vault deny on the
  token endpoint `api.krisp.ai/platform/v1/oauth2/*`), restart the gateway. A 403 on the refresh
  came from the vault and never reached the provider, so the refresh token was still good.
- **Plugin approvals are keyed `plugin_rule:<tool>:<sha256(message)[:12]>`.** Embed the command in
  the message so "session" or "always" covers only that call. `command_allowlist: [execute_code]`
  (one "always" press) silences the built-in whole-script prompt forever, but plugin hooks still
  fire. Details are in the agent-command-approval-gate skill.
- **"Auxiliary approval: using ..." in agent.log** right before a `pending_approval` tool error means
  the BUILT-IN detector plus smart mode flagged a command, not a plugin. In a cron session it can
  never be approved.
