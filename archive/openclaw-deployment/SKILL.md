---
name: openclaw-deployment
description: This skill should be used when deploying or debugging a self-hosted OpenClaw (formerly Clawdbot/Moltbot) agent gateway — a Node.js personal-assistant service bridging Telegram/WhatsApp/Discord to an LLM with tool/skill access. Covers install, secure baseline config (loopback bind, token auth, exec approval gating), the two non-obvious config traps that silently break things (model selection vs. API key, exec security vs. ask), Telegram channel lockdown, configuring the web_search tool/Brave provider, voice-note transcription (tools.media.audio/Groq), memory indexing and its embedding-provider auth (openclaw memory index/status), evaluating ClawHub skills/plugins by real usage data, and building trustworthy custom skills instead of pulling from the unvetted ClawHub marketplace. Trigger phrases include "openclaw config", "openclaw gateway", "tools.exec.security", "openclaw model not found", "ProviderAuthError No API key found for provider openai", "exec denied security=deny", "openclaw dashboard", "openclaw pairing", "ClawHub skill", "openclaw skills install local", "openclaw web search", "tools.web.search.provider", "web_search provider is not available", "openclaw plugins install clawhub", "plugins.allow is empty", "tools.media.audio", "voice memo transcription", "openclaw skills search --json", "ClawHub popular skills", "EXTERNALLY-MANAGED pip openclaw", "AgentMail openclaw", "clawdbot paths in skill", "openclaw memory index", "memorySearch.provider", "memory index failed no api key", "credit_balance_exhausted", "insufficient_quota embeddings", "memory index --force", "scoped sudo for openclaw agent", "dispatch script security boundary", "openclaw agent --message-file", "openclaw agent --session-key timeout", "brief openclaw on new capabilities", "openclaw treats primer as prompt injection", "openclaw session jsonl toolCall", "arm olu with new tools", "expand openclaw agent privilege incrementally", "skill_workshop", "openclaw agent rejects everything as injected", "telegram reply quote looks like injection", "exec preflight complex interpreter invocation", "did openclaw actually send this or hallucinate it", "journalctl vs session transcript openclaw", "how to hand openclaw a new capability", "openclaw agent won't trust primer document".
---

# OpenClaw deployment

Built and verified end-to-end 2026-08-16 deploying a personal instance on a Vultr VPS
(`dfw`), wired to Telegram, Anthropic, GitHub, and Cloudflare. Every gotcha below was hit for
real — found by reading actual error logs and `openclaw config schema`, not by trusting docs
pages (several official doc pages returned "not found in this excerpt" for exactly the config
keys that mattered most; the installed CLI's own `config schema` output is the real source of
truth).

## Install

```bash
# Node.js via NodeSource (nodistro repo works fine on Debian 13/trixie, see
# proxmox-node-systemd-service skill for the full apt-repo setup sequence)
npm install -g openclaw@latest
openclaw --version
```

Run as a dedicated non-root, non-login system user (`adduser --disabled-password
--disabled-login openclaw; passwd -l openclaw`), managed via a systemd unit with `User=openclaw`,
`ProtectSystem=strict`, `PrivateTmp=true`, `ReadWritePaths=/home/openclaw/.openclaw`.
`ReadWritePaths=` is space-separated and grows as OpenClaw needs write access elsewhere — e.g.
the homelab's `/srv/agent-exchange/to-claude` (a filesystem-based cross-agent handoff channel,
one-way by design: only that specific subpath is writable, not its sibling `to-olu`) was added
alongside the `.openclaw` path on 2026-08-23. Verify any such addition against real confinement
(`systemd-run` matching the unit's properties + a check of the live process's
`/proc/<pid>/mountinfo`), not a `sudo -u openclaw` shortcut — see "`NoNewPrivileges=yes`
silently kills `sudo`" below for why that shortcut misses confinement bugs generally. Full
detail on the agent-exchange channel specifically is in the homelab planning repo's
`project_agent_exchange_channel` memory, not this skill.

**Every path in `ReadWritePaths=` must already exist on disk before the unit starts** —
systemd builds the mount namespace before `ExecStart` runs, and a missing path fails the whole
start with `Failed to set up mount namespacing: <path>: No such file or directory` /
`Failed at step NAMESPACE`, then crash-loops on `Restart=always`. It does not create the
directory for you, unlike `ReadWritePaths=` in some other tools' documentation examples.
Confirmed 2026-08-31 wiring OpenClaw through Agent Vault's `agent-vault run --` wrapper (see
the `agent-vault-credential-broker` skill): added `/home/openclaw/.agent-vault` to
`ReadWritePaths=` for the wrapper's CA-cert cache, but the directory didn't exist yet — instant
crash loop, caught within a couple restart cycles and rolled back. Create any new
`ReadWritePaths=` target first (`mkdir -p`, correct ownership) before adding it to the unit,
never as a "the process will create it" assumption.

## Gotcha 1 — setting the API key does NOT select which model gets used

Configuring `models.providers.anthropic.apiKey` is necessary but not sufficient. Without also
setting a default model, the gateway silently defaults to `openai/gpt-5.5` — and if no OpenAI key
is configured (because you're using Anthropic), every request fails:

```
ProviderAuthError: No API key found for provider "openai". Auth store: ...
model fallback decision: decision=candidate_failed requested=openai/gpt-5.5 ... reason=auth
```

This looks like an Anthropic auth problem. It isn't — the Anthropic key is fine, the *model
selection* just defaulted somewhere else entirely. Fix:

```json5
{ agents: { defaults: { model: "anthropic/claude-sonnet-5" } } }
```

Don't guess the model string — OpenClaw maintains its own alias registry that doesn't
necessarily match Anthropic's raw API model IDs, and it changes over time. Get the current valid
list straight from the installed CLI:

```bash
openclaw models list
```

## Gotcha 2 — `tools.exec.security: "deny"` is a HARD BLOCK, not an approval gate

The two exec-control fields look like they compose, but they don't the way you'd expect:

- `tools.exec.security`: `deny` | `allowlist` | `full` — **eligibility gate**. `deny` refuses
  every exec call outright, unconditionally, before `ask` is ever consulted.
- `tools.exec.ask`: `off` | `on-miss` | `always` — **approval-prompt control**. Only matters for
  calls that already passed the `security` gate.

If you want "the agent can run anything, but must ask permission every time" (a common and
sensible posture for a personal assistant with real infra access), the correct pairing is:

```json5
{ tools: { exec: { security: "full", ask: "always" } } }
```

**Not** `security: "deny"` — that sounds like the safer/stricter choice and is the literal value
shown in some published "secure baseline" examples, but it silently refuses everything with no
prompt ever sent. Symptom in the logs when this is misconfigured:

```
[tools] exec failed: exec denied: host=gateway security=deny raw_params={...}
[tools] exec failed: exec denied: host=sandbox security=deny raw_params={...}
```

Both `host=gateway` and `host=sandbox` get tried and both refuse — no approval request is ever
generated. Confirm the fix actually worked by watching for the real approval flow in the logs
after a live test:

```
[ws] ⇄ res ✓ exec.approval.request 68ms ...
[ws] ⇄ res ✓ exec.approval.waitDecision 8946ms ...
```

The `waitDecision` timing (matches how long the human actually took to respond) is the tell that
it's genuinely gating on a live decision, not rubber-stamping.

When in doubt about any enum's valid values, don't trust doc pages piecemeal — pull the schema
directly from the installed binary:

```bash
openclaw config schema > /tmp/openclaw-schema.json
python3 -c "
import json
s = json.load(open('/tmp/openclaw-schema.json'))
def find(o, path=''):
    if isinstance(o, dict):
        if 'enum' in o: print(path, o['enum'])
        for k,v in o.items(): find(v, path+'/'+k)
    elif isinstance(o, list):
        for v in o: find(v, path)
find(s)
"
```

## Gotcha 3 — web_search providers aren't bundled; ClawHub install is required even for "official" ones

Unlike the CLI-wrapper skills (`github`, `weather`), which ship bundled and just need a binary
(`gh`) present, `tools.web.search` providers like Brave are **not** in the base install.
`openclaw plugins list` won't show `brave` at all until it's installed — the plugin registry it
prints only covers model providers + chat channels, not search providers. Setting
`tools.web.search.provider: "brave"` (or running `openclaw config validate`/`config set`) before
installing fails with a misleading error:

```
tools.web.search.provider: web_search provider is not available: brave
(install or enable plugin "brave", then run openclaw doctor --fix)
```

`openclaw plugins enable brave` also fails at this point (`Plugin not found: brave`) — `enable`
only toggles a plugin that's already discovered on disk, it doesn't install one. The actual fix
is `openclaw plugins search <provider>` to find the ClawHub package (prefer the `official`-tagged
`@openclaw/<name>-plugin` entry over community alternatives, same trust reasoning as the ClawHub
section below), then:

```bash
openclaw plugins install clawhub:@openclaw/brave-plugin
openclaw config set tools.web.search.provider brave
sudo systemctl restart openclaw.service   # plugin install requires a gateway restart to load
```

**`openclaw doctor --fix` does not fix this** — when it hits the same "provider not available"
error, it silently *deletes* the offending `tools.web.search` block from config instead of
installing/enabling the plugin, and reports success. Always diff the config before/after running
`--fix`; don't assume it did the intelligent thing.

A new ClawHub plugin install also triggers a standing warning once `plugins.allow` is empty
(the default): `discovered non-bundled plugins may auto-load: brave ... To trust them explicitly,
set plugins.allow`. Fix: read the exact active set from the `[gateway] http server listening (N
plugins: ...)` log line after a restart — `openclaw plugins list` alone overstates it, since it
shows every *discovered* bundled plugin (51 on a stock install: unused providers like
`azure-speech`, `cohere`, `deepgram`, etc. all show `enabled`), not just the ones actually loaded
at runtime. Set `plugins.allow` to the smaller runtime-active list (confirm it's stable across at
least two independent restarts before trusting it), e.g.:

```bash
openclaw config set plugins.allow '["brave","browser","canvas","device-pair","file-transfer","memory-core","ollama","phone-control","talk-voice","telegram"]' --json
```

The schema notes bundled *chat channel* plugins (telegram, etc.) auto-activate when their channel
is explicitly enabled even if left off `plugins.allow` — but that exception doesn't cover
non-channel bundled plugins (`browser`, `canvas`, `memory-core`, ...), so list those explicitly
too; a partial list silently breaks whatever's left off. This kind of `config set` mid-session can
land while a real conversation is in flight (Telegram) — the gateway's reload logic detects that
and *defers the restart* until the in-flight turn/background task finishes
(`[reload] restart blocked by active background task run(s)`) rather than dropping it, so it's
safe to apply without warning the user first. After restart, diff the plugin list in the log
line against the pre-change baseline (should be identical), then re-run the same
`openclaw agent --json` / `toolSummary` live check to prove the allowlist didn't silently break
what you were trying to protect.

**Ad-hoc `sudo -u openclaw openclaw ...` CLI commands don't see the service's env vars.**
Provider API keys (`BRAVE_API_KEY`, etc.) typically live in a file wired into the systemd unit via
`EnvironmentFile=` — only the actual service process reads that file. A plain `sudo -u openclaw
openclaw config validate` run by hand won't have the key in its environment even though the
running service does, and will report the provider as unavailable for what looks like a config
reason but is really a missing-credential-in-this-shell reason. To test as the CLI would see it in
production, source the env file and fix `HOME` explicitly (`sudo -E` alone doesn't fix `HOME` when
switching from root):

```bash
sudo bash -c 'set -a; source /root/.config/openclaw-*.env; set +a; \
  sudo -u openclaw HOME=/home/openclaw openclaw config validate'
```

**Verify a tool actually fired, don't trust "service restarted clean."** `openclaw agent --agent
<id> -m "<message that forces the tool>" --json` runs a real turn through the live gateway
(omit `--local` to use the actual running service, not an embedded one-off) and returns a
`toolSummary: { calls, tools: [...], failures }` field — concrete proof a specific tool executed,
plus the model's own reply usually names the provider it used. This is the same "verify the
actual feature, not just connectivity" lesson as the loopback-firewall incident below, applied to
a new feature instead of a new firewall.

## Exec sandboxing interacts badly with a host-level uid firewall

`agents.defaults.sandbox` (Docker/Podman-based exec isolation) puts sandboxed commands in their
own network namespace. If you've also built a host-level outbound firewall scoped by uid (e.g.
nftables `meta skuid <id>` rules) to restrict what the service account can reach, **that firewall
will not apply to sandboxed exec calls** — Docker's networking bypasses it entirely unless you
build a second, separate firewall for the Docker network (e.g. `DOCKER-USER` iptables chain
rules). This is a general Docker-vs-`ufw`/host-firewall gotcha, not OpenClaw-specific, but it's
easy to only discover once you've built both pieces separately and assumed they compose.

Given `security: "full"` + `ask: "always"` already means nothing executes without a live human
decision, treat Docker sandboxing as an *additional* defense-in-depth layer to add deliberately
later (with its own matching network firewall), not something to enable casually alongside a
host-level firewall and assume both apply.

## Uid-scoped outbound firewall (composes correctly with `ufw`)

To restrict what the service account can reach outbound (e.g. only the LLM/messaging/deploy
APIs it actually needs, plus one explicit SSH carve-out to a specific internal host) without
touching `ufw`'s own tables: add a **separate** nftables table at a **later** priority than
`ufw`'s default (`filter + 10` composes correctly after `ufw`'s `priority 0` — nftables
processes all base chains at a given hook across all tables, in priority order; `ufw`'s ACCEPT
at priority 0 doesn't terminate the hook, so your later-priority DROP still gets evaluated):

```
table inet openclaw_egress {
  chain output {
    type filter hook output priority 10; policy accept;
    oifname "lo" accept
    meta skuid 1002 tcp dport 443 accept
    meta skuid 1002 udp dport 53 accept
    meta skuid 1002 tcp dport 53 accept
    meta skuid 1002 tcp dport 22 ip daddr <trusted-host-ip> accept
    meta skuid 1002 counter drop
  }
}
```

**The `oifname "lo" accept` line is not optional.** OpenClaw's own gateway process connects to
*itself* over loopback (`127.0.0.1:<gateway-port>`) for its internal exec-approval handler — this
is not exposed traffic in any meaningful sense (it never leaves the host), but a uid-scoped
egress rule with no loopback exemption drops it exactly like any other unlisted destination.
Symptom: exec calls silently hang forever with no approval prompt ever reaching Telegram, no
error surfaced to the user, and only an occasional `[telegram] failed to start native approval
handler: Error: connect ETIMEDOUT 127.0.0.1:<port>` in the gateway's own logs as a clue — easy to
miss since the gateway otherwise looks completely healthy (`systemctl status` active, Telegram
polling running, model API calls succeeding). Confirm via `nft list table inet openclaw_egress`
— a nonzero packet counter on the final `drop` rule while loopback connections are failing is
the tell. **After building this firewall, always re-run a live end-to-end exec-approval test
(not just the external allow/deny checks) — the loopback break only shows up when something
actually tries to invoke exec, not from checking connectivity to external hosts.**

Never `nft flush ruleset` to apply this (wipes `ufw`'s and `tailscaled`'s own tables too — see
the homelab's general Tailscale/nftables gotcha). Use `nft delete table inet openclaw_egress
2>/dev/null; nft -f <file>` — scoped to just this one table, safe to re-run. Persist via a
systemd oneshot unit (`ExecStart=` that same delete-then-load line, `RemainAfterExit=yes`), not
`nftables.service`/`/etc/nftables.conf` if `ufw` isn't already using that mechanism on the host
(check `systemctl is-active nftables` first — if `ufw` is managing its own tables independently,
adding your rules into the same lifecycle is unnecessary and can cause confusion about which
mechanism owns what).

Verify both the allow and deny cases explicitly, as the target uid — a passing curl to an
allowed host doesn't prove the deny side works:

```bash
sudo -u openclaw curl -s -m 5 -o /dev/null -w '%{http_code}\n' https://api.anthropic.com/
sudo -u openclaw timeout 5 bash -c 'echo > /dev/tcp/<some-other-internal-host>/22' \
  2>&1 && echo "BAD: connected" || echo "good: refused"
```

## Telegram channel lockdown

Numeric user ID only — Telegram usernames/phone numbers are not accepted in `allowFrom`. Get
your own ID via `/whoami@<bot_username>` in a DM, or from the pairing request record.

Initial setup uses `dmPolicy: "pairing"` (generates a one-time code on first DM), approved via:

```bash
openclaw pairing list telegram
openclaw pairing approve telegram <CODE>
```

The first approval auto-bootstraps `commands.ownerAllowFrom` if empty. **This does not fully
lock the channel down by itself** — anyone can still trigger a new pairing *request* (even if
they can't get approved) while `dmPolicy` stays `"pairing"`. For a single-owner personal
instance, switch to a hard allowlist afterward so no one else can even initiate pairing:

```json5
{
  channels: { telegram: { dmPolicy: "allowlist", allowFrom: ["<your-numeric-id>"] } },
  commands: { ownerAllowFrom: ["telegram:<your-numeric-id>"] }
}
```

## Skills: prefer first-party bundled or local-authored over ClawHub

`openclaw skills search <name>` queries ClawHub, an open, unvetted community marketplace —
results routinely include several near-duplicate submissions from different authors under the
same apparent name, and outright spam/SEO-farming content mixed in. Before installing anything
from there, check whether a **first-party bundled** skill already covers it — these ship with
OpenClaw itself (`Source: openclaw-bundled` in `openclaw skills info <name>`) and just need a
binary requirement satisfied to go from `△ needs setup` to `✓ ready`:

```bash
openclaw skills list                  # shows bundled skills gated on missing binaries
openclaw skills info <name>           # confirms Source: openclaw-bundled vs. clawhub/other
```

Example: the bundled `github` skill needs only the official `gh` CLI installed — no ClawHub
install required at all, and it's first-party-trusted rather than arbitrary community code.

For anything with no bundled equivalent (e.g. Cloudflare, as of this writing), author a small
local `SKILL.md` yourself instead of pulling an unreviewed ClawHub entry — same frontmatter
shape as bundled skills, installed via:

```bash
openclaw skills install <local-dir> --as <slug>
```

This keeps every piece of skill *code* either first-party or self-authored, with only
credentials (scoped API tokens) as the actual trust boundary being extended to third parties.

## Dashboard / Control UI

`openclaw dashboard` opens a web Control UI — but if the gateway is `bind: "loopback"` (the
right choice per OpenClaw's own security docs for anything with real infra access), it's only
reachable from the box itself at `http://127.0.0.1:<port>/`. From a workstation, either SSH
port-forward (`ssh -L <port>:127.0.0.1:<port> user@host`, then open the URL locally) or expose it
deliberately via the same reverse-proxy pattern used for everything else (Tailscale Serve on its
own port, not the loopback bind). Get the real bound port and dashboard URL from:

```bash
openclaw gateway status --deep
```

This same command is the right first diagnostic for "the CLI can't connect to my running
gateway" — it separates "gateway process isn't running" from "gateway is running but the CLI's
own auth/probe handshake is failing" (the latter showed up as a `Connectivity probe: failed /
timeout` even with the gateway confirmed `running` and correctly bound — a CLI-context auth
issue, not a service-health issue; don't treat it as proof the gateway itself is unhealthy).

Logging into the dashboard from a browser takes two more steps beyond just the URL:

1. **`openclaw config get gateway.auth.token` prints `__OPENCLAW_REDACTED__`, not the real
   value** — the CLI deliberately masks secrets in its own terminal output. Read the raw config
   file instead: `python3 -c "import json; print(json.load(open('~/.openclaw/openclaw.json'))
   ['gateway']['auth']['token'])"` (expand `~` or use the real path).
2. **The Control UI needs its own device-pairing approval**, separate from any channel (Telegram
   etc.) pairing already done — first connection attempt shows "Device pairing required" with a
   request ID. Approve it the same way as a channel pairing, just a different command:
   `openclaw devices list` / `openclaw devices approve <request-id>`.

## Secrets: two valid patterns, pick per-field based on what's documented

- `SecretRef` sourced from env (for values wired through the systemd unit's `EnvironmentFile=`):
  `{ "source": "env", "provider": "default", "id": "ANTHROPIC_API_KEY" }`
- Plaintext directly in `openclaw.json` (for values with no natural env-var home, like the
  gateway's own auth token) — OpenClaw's own docs explicitly say to protect this via file
  permissions (`chmod 600 ~/.openclaw/openclaw.json`, `chmod 700 ~/.openclaw/`), confirming this
  is an intended, not accidental, pattern.

Generate any value that needs to land in either place server-side, in one script, so it never
transits through your own shell history or an assistant's chat transcript.

## Evaluating ClawHub skills/plugins by real usage, not vibes

`openclaw skills search <query> --json` and `openclaw plugins search <query> --json` return real
metrics per result: `stats.{installs,downloads,stars}`, `isSuspicious`, and for plugins
`channel` (`official`/`community`) + `isOfficial`. Use these to rank, don't guess from
descriptions. Two real findings from a 2026-08-16 survey across ~15 categories on `dfw`:

- **The "plugins" (code-level) family is a much thinner ecosystem than "skills"** (CLI-wrapper
  style). Outside `@openclaw/`-official entries (Brave, LanceDB memory), almost nothing broke 35
  installs across a dozen categories checked. Real adoption numbers (500-1500+ installs, dozens
  of stars) live in the skills family — Slack, PDF, Calendar, Linear, etc. Don't recommend a
  "plugin" for a capability that has a well-adopted "skill" equivalent instead.
- **High install/star counts and `isSuspicious: false` don't mean the skill is well-built or
  even a clean fit** — always read the actual `SKILL.md`/scripts, not just the search-result
  summary, before installing something security-relevant or expecting a specific behavior:
  - `ivangdavila/translate` (381 installs, 10★): not a standalone translator — it's a thin skin
    over a separate third-party product ("Clawic", clawic.com) that expects a whole personal-data
    directory tree (`~/Clawic/data/contacts/`, `~/Clawic/data/projects/`, `~/Clawic/data/finances/`,
    `~/Clawic/profile.yaml`) before it'll even activate (`Visible to model: no` until then).
    Adopting it means adopting a second personal-assistant memory system, not just getting
    translation. Skip unless that tradeoff is deliberately wanted.
  - `cclank/news-aggregator-skill` (349 installs, 23★): summary says "8 major sources" but the
    actual list (read `scripts/fetch_news.py`) is Hacker News, GitHub Trending, Product Hunt, plus
    **36Kr, Tencent News, WallStreetCN, V2EX, and Weibo** — mostly Chinese tech/finance/social
    sources, not general news. If that's not wanted, patch the script's `--source all` default
    (a `sources_map` dict keyed by source name) rather than relying on the agent remembering to
    pass `--source hackernews,github,producthunt` every time.
  - `adboio/agentmail` (1138 installs, 66★ — by far the most-used of 5 competing ClawHub wrappers
    for the same underlying AgentMail service): its bundled example code was written against an
    older `agentmail` PyPI SDK version. Against the real installed SDK (0.5.9),
    `client.inboxes.create(username=..., client_id=...)` throws `TypeError: unexpected keyword
    argument 'username'` — the current SDK wants `client.inboxes.create(request=
    CreateInboxRequest(username=..., client_id=...))`. `send()` and `list()` still match the
    documented flat-kwarg style; only `create()` drifted. Check `inspect.signature(...)` against
    the actually-installed package before trusting a skill's example code verbatim, especially
    for the first call in a quick-start.
  - Same skill's "Security: Webhook Allowlist (CRITICAL)" section — the actual defense against
    prompt-injection-via-arbitrary-inbound-email — was written for the pre-rename **Clawdbot**
    product and references `~/.clawdbot/hooks/`, `~/.clawdbot/clawdbot.json`, and a `clawdbot
    gateway restart` command. None of those paths/commands exist on a real OpenClaw install
    (`~/.openclaw/openclaw.json`, `openclaw gateway restart`). Following it as written produces
    something that *looks* configured but provides zero actual protection. Grep any
    security-critical section of a ClawHub skill for stale product-name paths before trusting it
    — general lesson: a skill's popularity is a signal about the *capability* being useful, not
    a guarantee the *documentation* was ever updated across a product rename or an SDK major
    version bump.

## Voice-note transcription (`tools.media.audio`)

Inbound voice notes (Telegram etc.) are transcribed by OpenClaw's own `tools.media.audio`
pipeline, not by installing a "skill" — this is a core feature, currently unconfigured by
default. Auto-detect order when no provider is pinned: **Groq → OpenAI → xAI → Deepgram → Google
→ SenseAudio → ElevenLabs → Mistral**, then local CLI fallback (`whisper-cli`/`whisper`) if no
provider auth resolves. The legacy `audio.transcription.command` config key still parses but is
retired — use `tools.media.audio.models` (`openclaw doctor --fix` migrates old `{input}`
placeholders, not the key itself).

On a small VPS (1 vCPU/4GB), prefer a cloud provider over local Whisper — local transcription adds
real CPU load per voice note plus first-run model-download latency. **Groq is a good default**:
first in auto-detect priority, cheap/fast, generous free tier. Setup:

```bash
openclaw plugins install @openclaw/groq-provider   # official external package, not bundled
openclaw config set tools.media.audio.models '[{"provider":"groq"}]'
# bare GROQ_API_KEY in the EnvironmentFile is NOT enough for the audio path -- see below
openclaw config set models.providers.groq.apiKey '{"source":"env","provider":"default","id":"GROQ_API_KEY"}'
# add "groq" to plugins.allow if you've locked it down (see the plugins.allow section above)
sudo systemctl restart openclaw.service
```

**The docs say a bare `GROQ_API_KEY` env var is sufficient ("Auth env var: GROQ_API_KEY"), and
two independent checks appeared to confirm that — both were false positives for the audio path
specifically.** `curl` directly against `api.groq.com/.../audio/transcriptions` with the key
returned a real 200 + transcript, and `openclaw models list --provider groq` showed every model
with `Auth: yes`. Both genuinely passed. A real inbound Telegram voice note still failed with
`[media-understanding] audio: failed (0/1) reason=ProviderAuthError`, even though `GROQ_API_KEY`
was confirmed present in the actual running gateway process's environment
(`sudo cat /proc/$(systemctl show openclaw.service -p MainPID --value)/environ | tr '\0' '\n'`
— **use the real systemd `MainPID`, not `pgrep -f 'openclaw gateway'`, which can match a stray
interactive CLI invocation and silently check the wrong process's environment entirely**). The
`models list` check only exercises chat-model auth resolution, not the separate audio
media-understanding auth path — a passing chat-model check doesn't prove the audio path will
resolve auth the same way. Fix: add an explicit `models.providers.groq.apiKey` SecretRef (same
pattern already used for `anthropic` in a working config) rather than relying on bare env-var
auto-pickup for the audio path. Confirmed fixed via a real voice memo after adding it.

**There's no CLI flag to attach a media file to a test turn** (`openclaw agent --help` has no
audio/attachment option), so the curl+`models list` checks above are the best CLI-only
verification available — but given the false-positive above, treat them as necessary, not
sufficient. A real voice memo through the actual channel is the only thing that fully exercises
OpenClaw's own attachment-download-and-inject glue plus the audio-specific auth path.

## Memory indexing (`openclaw memory index`) needs its own embedding provider auth

Same theme as the audio path above: `memorySearch.provider` **defaults to `"openai"`**, entirely
independent of whatever chat-model provider is configured (Anthropic, in a typical build here).
Configuring `ANTHROPIC_API_KEY` for chat does nothing for memory embeddings — `openclaw memory
index --force --agent <id>` fails with `No API key found for provider "openai"` until an OpenAI
(or another explicit `memorySearch.provider`) credential exists. This is the third distinct
instance of "OpenClaw subsystems each need their own separate provider auth" (see model-selection
and Groq-audio notes above) — always check `openclaw memory status --index --agent <id>` (`Auth
store:` line names the exact sqlite file, `Provider:`/`Embeddings:` lines show real state) rather
than assuming a working chat model implies memory search works too.

Fix: get an `OPENAI_API_KEY`, scoped narrowly (OpenAI dashboard → Restricted →  expand **Model
capabilities** → set only `Embeddings (/v1/embeddings)` to `Request`, everything else `None` —
this key never needs chat/completions/files/etc access), add it to the same `EnvironmentFile` as
the other provider keys, restart `openclaw.service`, then reindex:

```bash
sudo bash -c "echo 'OPENAI_API_KEY=sk-...' >> /root/.config/openclaw-anthropic.env"
sudo systemctl restart openclaw.service
sudo bash -c 'set -a; source /root/.config/openclaw-anthropic.env; set +a; \
  sudo -u openclaw --preserve-env=OPENAI_API_KEY,ANTHROPIC_API_KEY HOME=/home/openclaw \
  openclaw memory index --force --agent main'
```

Non-Ollama/non-local alternatives (Bedrock, DeepInfra, Gemini, Mistral, Voyage,
`openai-compatible`) and the fully-local `provider: "local"` (GGUF via llama.cpp, no API key,
~0.6GB auto-downloaded default model) are documented in the package's own
`/usr/lib/node_modules/openclaw/docs/reference/memory-config.md` — check the bundled copy, it's
far more complete than the public docs site (same lesson as elsewhere in this file). `ollama`
appearing in `plugins.allow` does **not** mean an Ollama daemon is actually installed/running —
that's just the bundled provider-adapter code; verify with `which ollama` /
`systemctl is-active ollama` before assuming the local-embeddings path is available on a given
box, especially a small VPS where standing up a whole second model-serving daemon has a real
resource cost worth weighing against a fractions-of-a-cent-per-month OpenAI embeddings bill.

**`memorySearch.extraPaths` indexes an arbitrary external directory of markdown files — separate
from, and easy to conflate with, conversation/session indexing.** `sources: ["memory","sessions"]`
(the more commonly documented option) indexes OpenClaw's *own* conversation history. `extraPaths`
(array of absolute or workspace-relative paths, same bundled `memory-config.md` reference) is a
different feature entirely: point it at a directory and it recursively indexes every `.md` file
found there as external knowledge — e.g. a synced Obsidian vault, a docs folder, notes a human
maintains by hand. Functionally the OpenClaw analog of Claude Code's `autoMemoryDirectory`, but
the consumption model differs even when both point at the same files: this is a chunked,
embedded, top-K-retrieved-per-query index (hybrid BM25+vector), not a curated set of files read
wholesale into context every turn. Same source notes, not guaranteed same "knowledge" from a
given note. Confirmed real and current 2026-08-18 via the bundled doc — not yet built/exercised
on any live instance, so treat the mechanics above as verified-on-paper, not verified-in-use.

**Redaction gotcha hit while debugging a bad key-append attempt**: when eyeballing an env file's
structure without printing secret values, a naive `grep -oE '^[A-Za-z_]+='`-style check only
shows lines that *match* the expected `NAME=value` shape — a malformed line (e.g. someone pasted
just the raw secret with no `NAME=` prefix, dropped when substituting into a copy-paste command
template) silently doesn't match and won't show up as an anomaly, but also won't get redacted if
you then try to eyeball "what's really in this file" with a `sed`/`awk` substitution that only
transforms matched lines — every unmatched line prints verbatim, secret value and all. Confirmed
the hard way: a bare unprefixed OpenAI key leaked into tool output this way and had to be
revoked/rotated. Safe pattern is to make truncation unconditional regardless of match, e.g.:

```bash
sudo awk '{ if (match($0, /^[A-Za-z_]+=/)) print substr($0,RSTART,RLENGTH) "[...]"; \
            else print "<unnamed line, " length($0) " chars>" }' /root/.config/openclaw-anthropic.env
```

so a malformed line still reveals *that* it's wrong (and its length) without ever printing its
content. See the global CLAUDE.md's "never cat-then-redact" gotcha — this is the same failure
mode, just via a pattern-matched redaction script instead of a raw `cat`.

### Non-chat provider use is invisible to a `model-fetch` journal grep (2026-09-12)

The two subsystems above (Groq audio transcription and OpenAI `memory_search` embeddings) **don't
emit `model-fetch` journal lines.** An audit that counted `provider=openai`/`provider=groq` model-fetch
lines over 7 days found zero and nearly retired both keys. The agent then checked its live config:
embeddings ran on every memory recall, and voice notes were being transcribed through Groq days earlier.

Before calling any provider key unused, check every capability it can back:
- `models.providers`, the model and fallback chains, and per-cron overrides
- `tools.media.models` (audio, image)
- `memorySearch.provider`, and whether its default applies
- `plugins.allow` / enabled provider plugins

The service account's config is usually off-limits to the operator, so **ask the agent to check its own
live config.** Removing a key also needs its capability re-pointed first. An unconfigured capability in
the media fallback chain can silently bill a more expensive provider.

## PEP 668 (`EXTERNALLY-MANAGED`) blocks pip for Python-based skills too

Some ClawHub skills (AgentMail, others with Python SDKs) need `pip install <package>` to actually
work. Debian 13's system Python refuses both plain `pip install` and `pip install --user` under
PEP 668 (`error: externally-managed-environment`) — same root cause as the Mac skill-creator
gotcha in the global CLAUDE.md, different fix since this is a dedicated single-purpose host
rather than a shared dev machine. Pattern that keeps plain `python3` calls from the agent's exec
tool working transparently (no venv-activation ceremony needed in every script):

```bash
sudo apt-get install -y python3.13-venv   # not installed by default; ensurepip fails without it
sudo -u openclaw python3 -m venv /home/openclaw/.venvs/base
sudo -u openclaw /home/openclaw/.venvs/base/bin/pip install agentmail python-dotenv
```

Then prepend the venv's `bin/` to the *service's* `PATH` (same mechanism already used for
Homebrew — see the Homebrew note above) so `python3` resolves to the venv, not system Python, for
every exec-spawned child of the gateway process:

```
Environment=PATH=/home/openclaw/.venvs/base/bin:/home/linuxbrew/.linuxbrew/bin:...(existing PATH)
```

`sudo systemctl daemon-reload && sudo systemctl restart openclaw.service` to apply. Verify with
the exact PATH the service will see (not just an interactive shell, which may differ):

```bash
sudo -u openclaw env -i HOME=/home/openclaw PATH='<paste the exact Environment=PATH value>' \
  bash -c 'which python3; python3 -c "import agentmail; print(1)"'
```

## Inbound webhooks (`hooks.mappings`) — the real delivery mechanism, and a recurring corruption bug

Built 2026-08-16: Cloudflare Email Routing → a Worker (`email()` handler, envelope
`message.from` — not spoofable, unlike a header `From:`) → POST to OpenClaw's `hooks` endpoint
→ `hooks.mappings` → agent turn → Telegram. Config:

```json5
{
  hooks: {
    enabled: true,
    token: "<dedicated random token, NOT the gateway auth token>",
    path: "/hooks-<random-suffix>",           // non-guessable path + token together
    allowedAgentIds: ["main"],
    mappings: [{
      id: "mail-inbound",
      match: { path: "mail" },                // RELATIVE to hooks.path -- NOT the full path.
                                                // match.path: "/hooks-xxx/mail" 404s; "mail" works.
      action: "agent",
      sessionKey: "telegram:direct:<chat-id>", // see below -- do NOT use a separate hook session
      messageTemplate: "...{{messages[0].from}}...{{messages[0].subject}}...{{messages[0].snippet}}",
      deliver: true,
      channel: "telegram",
      to: "<chat-id>",
      allowUnsafeExternalContent: false,       // keep false even for allowlisted senders --
                                                // body content is untrusted *information*, not
                                                // trusted *instructions*
    }],
  },
}
```

**Sender trust boundary belongs at the Worker, not the transform.** The Worker checks the SMTP
envelope `message.from` against an explicit allowlist and silently `return`s (no `setReject()`,
so probing senders can't confirm the address exists) before ever forwarding. `hooks.mappings`
templates (`messageTemplate`/`textTemplate`, `{{messages[0].field}}` syntax) are sufficient for
shaping the payload — there is no worked example of the `transform.module`/`export` JS-function
contract anywhere in the bundled docs, so don't guess at it for something handling untrusted
input; use templates against a payload shape you control instead (have the sender-side Worker
emit `{"messages":[{"id","from","subject","snippet"}]}` directly).

### `deliver`/`channel`/`to` did not work as documented — the real fix was session targeting

Setting `deliver: true, channel: "telegram", to: "<chat-id>"` had **zero effect** on where the
reply actually went, across many permutations (`to` as bare chat ID, `"direct:<id>"`,
`channel: "telegram"` vs the Gmail example's `channel: "last"`). In every case the agent's own
turn used a `sessions_send` **tool call** to relay into a session literally named `main`
(`agent:main:main`) — visible in the Control UI as "Forwarded from main" — regardless of the
mapping's delivery config. This looks like agent-driven behavior (the model choosing to relay
via `sessions_send` to what it treats as the canonical session), not something the mapping's
`channel`/`to` fields control for `action: "agent"`.

**The fix: point `sessionKey` directly at the real interactive channel session**, not a separate
hook-scoped key. Find the real session key from `openclaw sessions --json --active <n>` (look
for `kind: "direct"` bound to the real channel, e.g. `agent:main:telegram:direct:<chat-id>` —
the part after `agent:<agentId>:` is what `hooks.mappings[].sessionKey` takes). With
`sessionKey: "telegram:direct:<chat-id>"`, the hook-triggered turn runs *inside* the same
session as the user's normal conversation — no separate hook session, no cross-session relay,
no dependency on whatever `main` happens to be. Matching `hooks.allowedSessionKeyPrefixes` and
`hooks.defaultSessionKey` need the same real prefix (e.g. `["telegram:"]`), not a made-up
`"hook:"` prefix.

**Do not trust `openclaw config validate` for this class of bug.** It only does static schema
checks — `hooks.allowedSessionKeyPrefixes must include 'hook:' when hooks.defaultSessionKey is
unset` is a *startup-time* cross-field check that `validate` does not catch, and a bad value
here crash-loops the entire gateway (see below), not just the hooks feature.

### A cron job's `sessionTarget` pointed at the live conversation session can queue behind it and time out — caveat to the fix above

The section above recommends pointing a hook's `sessionKey` directly at the real interactive
channel session to avoid a separate hook-scoped session. The same pattern applied to a **cron
job's** `sessionTarget` (e.g. `"session:agent:main:telegram:direct:<chat-id>"`) has a real
downside: that session is a single lane, and a cron-triggered turn competing with an *active*
turn in the same lane (a live conversation in progress) queues behind it rather than running
concurrently.

Confirmed 2026-08-30/31 (LunaRoute pilot, `weekly-share-more-nudge` cron job): every forced test
run failed with `TimeoutError: cron: isolated agent setup timed out before runner start` (a fixed
~60s wait) while debugging was actively happening in that same session. `journalctl -u
openclaw.service` showed the real cause directly: `lane wait exceeded ... activeAhead=1` right
before the timeout — the cron turn was queued behind the live conversation's own in-flight turn,
not failing for any provider/config reason. This looked at first like a provider-specific bug
(the pilot was mid-switch to a new model provider at the time) and cost real debugging time before
the lane-contention signature was recognized in the logs.

**Fix**: for a cron job whose turns don't need to share context/history with a live conversation
(the common case — most cron jobs are self-contained, not conversational continuations), set
`sessionTarget: "isolated"` instead of pointing it at the interactive session. This is also
already the pattern other cron jobs in this environment use. A job that *does* need to run inside
the same session as live chat (relaying into an ongoing conversation, similar to the hooks case
above) will still hit this queuing behavior any time it fires mid-conversation — that's an
inherent tradeoff of sharing the lane, not a bug to fix, so don't pick shared-session targeting
for a cron job without weighing this.

### A specific session key can get "stuck" independent of the transcript file

`agent:main:main` returned `FailoverError: Unknown model: anthropic/claude-sonnet-5` on every
turn, for many minutes, while every other session (fresh hook sessions, the real Telegram
session, plain CLI tests) used the identical model string successfully. Diagnosis path that
worked: `openclaw sessions --json --all-agents --limit all`, find the session's `status` field
(`"failed"` — separate from whether its `.jsonl` transcript file was actually written to;
`stat`-checking the transcript file's mtime showed it predated the failures entirely, proving
the "failed" status lives in separate session-store metadata, not the transcript). Retrying the
exact same session key even with a **fresh** sessionId (confirmed via the session list) failed
identically — ruling out simple stale per-session state and pointing at something specific to
that session *key* or its bootstrap path (this session had a much larger `skillsSnapshot` than
hook sessions, i.e. a full "main" agent bootstrap vs. a lighter hook-triggered one).

**The actual fix was a full `systemctl restart openclaw.service`** — not a config change, not a
targeted per-session repair (no CLI command exists for the latter: `openclaw sessions` only has
`cleanup`/`compact`/`export-trajectory`/`tail`, nothing that resets a stuck status). This
strongly suggests the bug is in-memory/live-process state, not anything persisted to disk.

**This corruption recurred multiple times over one gateway process's lifetime, and it spread**
— it started isolated to `agent:main:main`, then later the same error hit a previously-healthy
hook session (`agent:main:hook:mail:inbox`) and `lane=cron-nested` in the same burst. The
trigger appears to be **repeated `openclaw config set` hot-reloads within one process run** —
each one logs `[reload] config change detected... hot reload applied`, and this session made
dozens of them in under an hour while iterating on the hooks config. **Lesson: past a handful of
hot-reload cycles in one debugging session, if a *different* error shape appears (e.g. a
"channel routing" bug suddenly presents as "Unknown model"), treat that shape change as the
signal to restart immediately** rather than continuing to iterate on config — a changed error
class is a stronger "try the cheap reset" signal than a repeated one. Prefer batching remaining
config edits into one `--batch-file` apply + single restart over many incremental `config set`
calls once a session has already needed one corruption-clearing restart.

**Recurred again, 2026-08-23, different session — same signature, same fix, worth trusting the
pattern-match over re-investigating from scratch.** A one-shot cron job (`lane=cron-nested`,
`sessionKey=agent:main:cron:<id>:run:<id>`) failed twice in a row with the identical
`FailoverError: Unknown model: anthropic/claude-sonnet-5`, in a gateway process that had by
then absorbed a full session's worth of plugin installs, config edits, and multiple prior
restarts (building a cross-agent filesystem channel, installing/testing a `before_agent_finalize`
hook plugin, several `config set`-driven hot reloads along the way). Recognized immediately from
the error string alone, confirmed via journal (`[reload] config change detected... hot reload
applied` entries earlier in the same window), fixed the same way — plain `systemctl restart
openclaw.service`, gateway came back with the same plugin list intact, no further recurrence
in the following minutes. Didn't re-diagnose from zero; matching this exact error string against
this section is faster and just as reliable as re-deriving it.

### Tailscale Funnel to a same-node Serve chain: use single-hop `--set-path`, not two hops

`tailscale funnel --bg 8445` (targeting an existing `tailscale serve --https=8445 ...` mount on
the same node) produced a **502 from the public URL** while the same request against the
tailnet-scoped `:8445` URL directly returned 200 — the two-hop chain (Funnel→Serve→gateway) had
a working Serve leg but a broken Funnel leg. Root cause not fully diagnosed (likely a TLS/backend
protocol mismatch specific to chaining Funnel into another local HTTPS-terminating Serve port),
but the fix sidesteps it entirely: **`funnel` supports `--set-path` directly**, same as `serve`.
Collapse to one hop instead of chaining:

```bash
tailscale serve --https=8445 off        # tear down the two-hop chain if already built
tailscale funnel --bg --set-path=/hooks-xxx http://127.0.0.1:18789/hooks-xxx
```

This also fixes a secondary problem: an earlier `tailscale funnel --bg 8445` (no `--set-path`)
put a **wildcard `/` mount on port 443**, publicly exposing the *entire* gateway (dashboard
included) rather than just the intended path — caught by testing the bare root URL from an
off-tailnet client (`curl -o /dev/null -w '%{http_code}'`) and seeing something other than a 404.
Always verify the bare root 404s (nothing else mounted) in addition to testing the actual
endpoint, for any Funnel exposing only one path of a multi-purpose gateway.

**The CLI syntax changed from older docs/muscle memory**: `tailscale funnel --bg <port> on` now
errors (`the CLI for serve and funnel has changed`) — current form drops the trailing `on`
(`tailscale funnel --bg <port>`), and `tailscale funnel status`/`tailscale serve status` (not
`--json`-only) are the fastest way to see the live real mount table.

### Verifying against a real inbound event needs to account for mail delivery latency

A `curl` straight to the gateway's hooks endpoint proves the OpenClaw-side pipeline; it does not
prove the Cloudflare→Worker leg. For that, either watch `wrangler tail --format pretty` live
(each real email shows as `Email from:X to:Y size:N @ <time> - Ok` plus the Worker's own
`console.log`) or check `openclaw journalctl` for real activity. **First-time delivery to a
brand-new MX/routing destination is commonly delayed by several minutes** (greylisting-like
behavior on the sending side is a plausible explanation, not confirmed) — a `wrangler tail`
session that expires (60-180s) or a narrow `journalctl --since` window checked too early will
both show nothing even though the email is genuinely in transit and arrives moments later.
Don't read "nothing captured in my tail window" as "the pipeline is broken" without first ruling
out a timing mismatch between when you're watching and when delivery actually completes —
re-arm a fresh watch and wait longer before concluding infrastructure is at fault, especially
once the known bugs above are already fixed.

### A CLI health-check probe can land directly in the user's real, visible conversation

`openclaw sessions --json` lists session keys like `agent:main:main` alongside ones you created
for testing — nothing distinguishes "this is a throwaway diagnostic target" from "this is the
user's actual default cross-device session." `agent:main:main` specifically is the **generic
default session used by bare CLI calls and by the web Control UI when accessed directly** (not
through a specific channel like Telegram) — labeled "Main Session" in the UI. Running
`openclaw agent --session-key agent:main:main -m "health check..."` repeatedly to probe whether
the model registry had recovered put that literal text into the user's real conversation
history, visible on every device logged into the Control UI (confirmed via a phone screenshot).
**Before using any specific session key as a health-check target, confirm via the Control UI or
by asking the user whether that key is something they actually view** — don't assume a
generic-sounding key name is safe to write test content into. Prefer verification paths that
don't inject a message into any conversation at all: `openclaw doctor`, `config validate`, or a
models-catalog list.

### OpenClaw's own session files are local context only — they don't reach already-sent Telegram messages

Once a hook-triggered (or any) turn's reply has actually been delivered to Telegram, editing or
deleting the underlying OpenClaw session `.jsonl` file does **nothing** to what's sitting in the
user's real Telegram chat history — that's Telegram's own server-side record, entirely separate
from OpenClaw's local transcript. To actually remove an already-delivered message, use the
Telegram Bot API directly with the bot's own token:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/deleteMessage" \
  -d chat_id=<chat-id> -d message_id=<id>
```

Get the real `message_id` values from the gateway's own logs (`[telegram] outbound send ok
accountId=default chatId=<id> messageId=<N> ...` in `journalctl -u openclaw.service`) — there's
no way to browse/preview a bot's own sent messages via the API first, so cross-reference by
timestamp against when you know test content was sent, and get the user's explicit go-ahead
before deleting anything from their real chat history (one wrong guess deletes a message you
can't identify to restore). Separately, editing a *local* session's `.jsonl` (e.g. to strip test
content while preserving the session's header/system lines) is safe and effective for cleaning
up the **web Control UI's own view** of a session — back the file up first, remove only the
specific message-type JSON lines by `id`, and leave header (`session`/`model_change`/etc.) lines
intact so the session itself keeps working.

## Granting an agent real infra privilege: scoped dispatch scripts, not broad sudo

Built and verified 2026-08-17 when Will asked for OpenClaw (running as "Olu") to be able to do
read-only + non-destructive homelab administration — the same category of task a Claude Code
session does interactively, but reachable by the agent itself via its own exec tool.

**The dispatch script is the security boundary, not the sudoers grant.** Don't write a sudoers
file with `Cmnd_Alias` wildcards (`ansible all -m shell -a *` is unrestricted root in disguise).
Instead grant `NOPASSWD` sudo to exactly one root-owned script path per capability tier, and put
all the real scoping logic — host/unit/playbook allowlists, regex-validated arguments, no shell
interpolation — inside that script:

```
# /etc/sudoers.d/openclaw-remote
openclaw-remote ALL=(root) NOPASSWD: /usr/local/bin/openclaw-fleet-admin-readonly.sh
openclaw-remote ALL=(root) NOPASSWD: /usr/local/bin/openclaw-fleet-admin-changes.sh
```

**Split into two scripts — readonly and changes — as separate files/paths, not one script with
internal risk-level branching.** OpenClaw's own `exec-approvals.json` allowlist matches on
*resolved binary path*, not arguments, so a single script mixing safe reads and real mutations
can't be partially allowlisted — it's all-or-nothing. Two paths let the path itself carry the
trust decision: add only the `*-readonly.sh` path to the allowlist (skips Will's Telegram
approval prompt), leave `*-changes.sh` off it entirely (every invocation still prompts). This
keeps "capability" and "auto-approval" as genuinely separate axes — granting the ability to
restart a service doesn't mean it happens without Will seeing it.

Verify the boundary holds, not just that the happy path works: attempt a raw `sudo <arbitrary
command>` as the granted user (should fail — not in sudoers), an out-of-scope subcommand (should
be rejected by the script's own `case`/`die` logic), and a path-traversal argument like
`playbook-run ../../etc/passwd` (should be rejected by regex validation before it ever reaches
`ansible-playbook`). All three are meaningful negative tests, not paranoia.

**sudoers `NOPASSWD` matches the literal granted command, not anything that merely invokes the
same script.** Confirmed 2026-08-18 auditing Olu's exec failures: `sudo bash -x
/usr/local/bin/openclaw-fleet-admin-changes.sh ...` (debugging with `bash -x`) and `sudo cat
/usr/local/bin/openclaw-fleet-admin-readonly.sh` (reading the source) both fell through to an
interactive password prompt and failed headless — sudoers saw `bash` and `cat` as the command,
not the script path it actually granted. The agent's own retries kept failing the identical way
because the error ("a terminal is required to read the password") looks like a broken sudo
grant, not a wrong invocation shape. Fix is on the calling side, not the sudoers config: the
granted script must be run bare (`sudo /usr/local/bin/openclaw-fleet-admin-changes.sh
<subcommand> <args>`) — never wrapped in `bash -x`, piped through `cat`, or prefixed with
anything else, even for debugging.

### This sudo pattern works for `openclaw-remote` over SSH, and CANNOT work for the `openclaw` service account

An important scoping limit on everything above. The dispatch-script pattern is granted to
`openclaw-remote`, a separate account reached over SSH — an ordinary login session with no
systemd confinement. **The same pattern is impossible for `openclaw` itself**, the account
`openclaw.service` runs as, because that unit sets `NoNewPrivileges=yes`: the kernel refuses the
escalation before sudo ever reads sudoers, so any grant to it is decorative. The error is a bare
`sudo: The "no new privileges" flag is set, which prevents sudo from running as root`, which
reads like a container quirk rather than "this design can never work."

Confirmed 2026-09-04: an agent-email sender shipped to both `dfw` and `hermes` as a root-owned
script plus a path-scoped `NOPASSWD` grant, and had never once run from an agent. It looked
healthy because the only entries in its audit log were the sends *root* made while testing —
exactly what a working path produces. **Olu found it by trying to use it and reporting the
failure**, which is the durable lesson: when a mechanism exists so a less-privileged actor can do
something, the acceptance test has to run as that actor under its real confinement. Testing as
root proves the plumbing exists, never that the intended caller can reach it.

`systemctl show openclaw -p NoNewPrivileges` before designing anything that needs the confined
agent to escalate. If it's `yes`, **invert the privilege boundary instead of widening it**: have
the agent write a job file into a spool directory it can already write, and have a root-owned
systemd `.path` unit collect and act on it. That keeps the credential entirely out of the agent
process, which is usually what the sudo grant was reaching for anyway. Two companions:
`ProtectSystem=strict` means the spool needs a `ReadWritePaths=` drop-in **and a restart**
(applied at process start), and a `sudo -u openclaw` test from a root shell does **not**
reproduce the confinement — verify against the running process:

```bash
grep /var/spool/agent-email /proc/$(systemctl show openclaw -p MainPID --value)/mountinfo
# want: ... /var/spool/agent-email/queue rw,nosuid,...
```

See `project_agent_email_identity_path` memory for the resulting design, and the global
CLAUDE.md entry for the general form.

### "Verified live" needs the never-before-exercised branch, not just the idempotent short-circuit

A dispatch subcommand that both mutates state and short-circuits on "already done" (e.g.
`dns-add-pihole`: skip everything if the record already exists) can pass every "verified live"
test you throw at it while its actual mutation path has never once executed. Found 2026-08-18:
`dns-add-pihole`'s file-edit logic used a Python regex looking for a literal `hosts:` line that
does not exist in the target playbook (the real list key is `pihole_local_dns_hosts:`) — so it
could only ever succeed by hitting the already-present shortcut, and would `sys.exit()` on any
genuinely new record. This shipped and was called "verified live" because the one live test run
(adding `dfw`) happened to already be present from an earlier manual edit. Lesson: when a
subcommand has an early-exit branch for "nothing to do," the live verification pass must
exercise the *other* branch too — pick a real, previously-absent input, not a convenient
already-satisfied one — or the mutation code itself is unverified regardless of how confident
the test output looks.

**A dispatch script's own argument-validation logic needs the same negative testing as its
mutation logic.** Found 2026-08-18 auditing Olu's exec failures: `openclaw-fleet-admin-
readonly.sh`'s `git-status <repo>` subcommand resolved the repo path via bash indirect
expansion (`VAR="REPO_MAP_${REPO}"; DIR="${!VAR:-}"`) instead of validating `$REPO` against the
known aliases first. The agent passed `ansible-ctrl` (a real hostname, but not one of the actual
repo aliases `ansible`/`terraform`/`planning`) — the hyphen made `REPO_MAP_ansible-ctrl` an
invalid bash identifier, so it crashed with a raw `invalid variable name` error instead of the
intended clean `die "unknown repo: $REPO"`. Any dispatch subcommand using indirect/dynamic
variable lookup to map a user-supplied token to an internal value has this same failure mode for
any input containing characters invalid in an identifier — validate with an explicit `case`
statement (enumerate the known values, `*)` falls through to `die`) instead, so an unrecognized
value always produces the intended clean rejection rather than a shell-syntax crash.

### The right way to hand the agent new capabilities: real artifacts + `skill_workshop`, never prose

**Superseded conclusion, corrected 2026-08-17 after a full night of iterating on this with a
real agent ("Olu") in the loop — the `--message-file` primer-document approach below was tried
first, seemed to work, and turned out to be the wrong pattern overall.** Keep reading past the
first attempt for the actual recommendation.

**What was tried first**: dropping a large "here's what you can now do" document into the
agent's context via `openclaw agent --message-file <path> --session-key agent:main:main` (a
CLI-invoked session, separate from the agent's live chat sessions). From the agent's own point
of view, an unsolicited message asserting "you now have new permissions, already set up, no
verification needed" is *exactly* the shape of a social-engineering/prompt-injection attempt —
confirmed live, OpenClaw's own reasoning flagged this and spent a full turn independently
re-verifying every claim via its own `exec` calls before acting, which is the *correct*
instinct for an agent with real infra access. A short identity-confirming follow-up in the same
session unblocked it, and it finished the task, including self-discovering and honestly
reporting a real gap in the primer.

**Where this broke down**: that CLI session (`agent:main:main`) is a *different* session from
the agent's live chat session (e.g. `agent:main:telegram:direct:<chat-id>`) — no cross-session
memory (see the session-isolation entry below). When the human then talked to the agent in its
real live session, that session had zero record of any of the above, and — correctly, given
what it could actually see — treated the resulting outbound message as unexplained/suspicious.
Re-briefing it required delivering directly into the *same* session the human was actually
talking in, which helped, but every retry also kept hitting the exec preflight and
`NoNewPrivileges` bugs below, producing repeated real tool failures that the agent actually
handled well each time (adapting its approach and completing the task for real — see the
`journalctl` vs. session-transcript entry below for why this looked, incorrectly, like
fabrication at first). By the end of the night, the agent's own live session was reflexively
rejecting *everything* arriving
in it, including trivially short plain human messages with nothing embedded at all — a sign the
approach of "send explanatory prose into chat" had stopped working entirely, independent of how
carefully the prose was worded or how identity was established.

**The agent's own stated preference, once asked directly, is the right answer**: don't route
new capabilities through chat text at all.
1. **Ship the real artifact and let the agent verify it directly** — a file in
   `~/.openclaw/workspace/`, a sudoers entry, a systemd unit, an SSH key. This already worked
   cleanly every time it was tried: the agent read/tested these itself and trusted them with no
   narration needed at all.
2. **For anything meant to be durable, reusable knowledge, use `skill_workshop`** — a real,
   built-in, governed OpenClaw tool (`docs/tools/skill-workshop.md`; included in the `coding`
   tool profile) for creating/updating the agent's own workspace skills through a
   propose → security-scan → apply lifecycle, with rollback metadata, never a direct write. The
   right shape: ask the agent to explore its own real capabilities and write its own
   `skill_workshop` proposal describing them, then the human reviews and applies it. Self-
   authored from things the agent verified itself, human-reviewed before going live — no
   impersonation surface, no cross-session gap, no "trust me" prose required at all.
3. **Confirm intent live, briefly, in plain language, when needed** — the agent itself said a
   short human sentence in the live chat ("yes, that's really new, go check it out") is
   sufficient; it does not need or want that wrapped in any kind of structured/JSON-looking
   context block.

If a verification-heavy first turn is still needed (e.g. the very first time a capability is
introduced before this pattern is fully adopted), budget more time than a normal request —
independently confirming several new capabilities via live SSH/exec calls can exceed a 300s
`--timeout` even with `--json` output.

### `NoNewPrivileges=yes` silently kills `sudo` for the agent, regardless of sudoers

If `openclaw.service`'s unit has `NoNewPrivileges=yes` (real hardening, common and
recommended), granting the `openclaw` user `sudo` access to a script via `/etc/sudoers.d/`
looks correct (`sudo -l -U openclaw` shows it) but **is dead on arrival** — the kernel-level
`no_new_privs` flag blocks `sudo`'s escalation regardless of what sudoers allows, with the
error surfacing only when actually invoked: `sudo: The "no new privileges" flag is set,
which prevents sudo from running as root.` **Testing this via `sudo -u openclaw bash -c
'sudo ...'` from an already-privileged shell does NOT catch the bug** — that spawns a fresh
process outside the real systemd unit's confinement, so it succeeds even though the actual
running service never could. To genuinely reproduce the real execution context:
`sudo systemd-run --uid=openclaw --gid=openclaw -p NoNewPrivileges=yes --wait --pipe bash -c
'sudo -n true'` — this fails the same way the real service does, catching the bug before
trusting the capability.

**Fix without relaxing the service's own hardening**: don't flip `NoNewPrivileges=no` on
`openclaw.service` (weakens sandboxing for everything, not just the one grant needed). Build
a **separate** systemd service — its own unit, no `NoNewPrivileges` restriction since it
doesn't need one — that listens on loopback with bearer-token auth and dispatches to the
already-existing scripts. The confined `openclaw` process then just does a plain
unprivileged `curl` with the token (no escalation attempt at all), sidestepping the kernel
restriction entirely rather than fighting it. Give the confined process the token via
`openclaw.service`'s existing `EnvironmentFile` (inherited by any real child process it
spawns) — verify it's actually present with `grep -c
'^TOKEN_VAR_NAME=' /proc/$(systemctl show openclaw.service -p MainPID --value)/environ`
rather than assuming the `EnvironmentFile` edit took effect.

### Verify the caller, not just the callee, for any new SSH-based capability

Testing a new SSH-reachable capability *from the receiving host's own local shell* (e.g. `su
- <remote-user> -c '...'` run directly on the target) only proves the target-side config is
correct — it exercises none of the actual outbound connection. A first real attempt from the
genuine calling side can fail immediately on `Host key verification failed` if that
identity has simply never connected before (no entry in its own `known_hosts`) — an easy,
easily-missed gap distinct from any sudoers/capability logic. Fix with `ssh-keyscan -H
<host> >> ~<user>/.ssh/known_hosts` (safe for a first-time connection to an already-trusted
internal host — this isn't the same risk category as a *changed* key on a previously-known
host, which does warrant independent verification before trusting).

### An outbound message from one session looks like unexplained/injected content in another

OpenClaw sessions are isolated by session key (`agent:main:main` vs.
`agent:main:telegram:direct:<chat-id>`, etc.) — each has its own separate context/history, with
**no cross-session memory of reasoning**, even though a tool call in one session (e.g. sending a
Telegram message) produces a real, visible artifact in a channel another session also has access
to. Confirmed live: briefing Olu via `--session-key agent:main:main` (a CLI-invoked session) led
that session to verify some new capabilities and push a summary out via its Telegram-send tool.
When the user then talked to Olu in the **live Telegram session** (a different session key), that
session had zero record of the primer, the verification work, or ever deciding to send that
message — from its own context, it looked exactly like a fabricated/injected reply attributed to
itself. **This is not paranoia malfunctioning and not an injection — it's genuine session
isolation working as designed**, and the agent's skepticism in that moment is correct: it
shouldn't trust an unexplained message just because a human relays "yes, that's real." The fix
isn't to convince the live session to trust it secondhand — point it at a way to verify
independently *in its own context* (re-read the source file if one exists, or re-run the same
checks itself) rather than trying to argue away the correct instinct.

### Telegram's own reply/quote feature can look exactly like a prompt injection to the agent

**Confirmed root cause** (the agent verified this itself against real source, not just a working
theory) for a real, escalating incident where an agent rejected *every* subsequent message in a
Telegram thread as a "fabricated internal-context block," including trivially short plain human
text ("will do") with nothing embedded at all — a pattern that had stopped correlating with
message content entirely: replying to (quoting) a specific prior message in Telegram, rather
than typing fresh, makes OpenClaw surface the quoted context to the model wrapped in a real,
built-in envelope (`<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>`, carrying identifiers including
`OPENCLAW_INTERNAL_CONTEXT` and `inbound_event_kind`). This is genuine, documented OpenClaw
behavior (`docs/tools/acp-agents.md`; shipped in `dist/internal-runtime-context-*.js` and
`dist/get-reply-*.js`) — not anything injected. An agent that's never encountered this specific
envelope before, especially one already primed by a genuinely-suspicious delivery earlier in the
same session, can pattern-match "structured internal metadata I don't recognize" onto it and
reject it as hostile, then keep repeating that same judgment on every later turn without
re-verifying against the real source.

**The fix, and the general lesson**: when an agent flags something as injection-shaped but the
surrounding facts don't add up (e.g. it's happening on content-free trivial messages too), have
it check its own actual installed source — bundled docs and shipped code — for the literal
envelope/tag names it's seeing, before concluding anything is fabricated. In the real incident
this section documents, doing exactly that resolved it in one turn, and the agent explicitly,
plainly corrected itself afterward, unprompted — good behavior worth recognizing, not just a bug
that happened to get fixed. Practically: avoid Telegram reply-quotes to an agent's own messages
until this has been established as expected/trusted, or expect the first one encountered to need
this exact self-verification step.

### `exec preflight: complex interpreter invocation detected` — write a script file, don't inline it

OpenClaw's exec tool has a built-in safety check (documented in `docs/tools/exec.md`) that
inspects commands for "common Python/Node shell-syntax mistakes" and refuses to run anything it
flags as a complex inline interpreter invocation — e.g. `python3 -c "..."` one-liners, or a
`curl` call with an embedded JSON body and nested quoting — with the error naming the fix
directly: `Use a direct 'python <file>.py' or 'node <file>.js' command.` This is easy to trigger
by accident when handing the agent example commands that look exactly like what a human would
paste into their own terminal (multi-line, quoted JSON payloads, inline `-c` snippets) — every
such example in a real incident failed this preflight check, silently costing the agent's entire
turn before it ever got to the actual verification. Per the docs, preflight only inspects files
inside the effective `workdir` and is skipped entirely when `security=full` **and** `ask=off` —
neither condition held in the config that hit this. When handing off any command more complex
than a single flat binary invocation, write it to an actual file first and tell the agent to run
it as `python <file>.py`/`node <file>.js`, rather than a shaped one-liner.

### `journalctl -u openclaw.service` only reliably shows tool-call *failures*, not successes — check the session `.jsonl` for the real record

A real incident, worth remembering precisely because the wrong conclusion was drawn from it
initially: a turn reported (with `stopReason: stop`, a clean finish) as having sent a Telegram
message and an email was checked against `journalctl -u openclaw.service` for that exact time
window, which showed several `[tools] exec failed` lines (real — exec preflight blocked two
inline-rendering attempts) but **no corresponding success lines for anything** — no
`[tools] exec ok`, nothing about the email. That absence was read as evidence the completion
report was fabricated, and relayed onward as fact. **It was wrong.** Checking the session's own
`.jsonl` transcript directly (`~/.openclaw/agents/<agent>/sessions/<id>.jsonl`, per the
tool-call parsing pattern below) showed the full real sequence: the agent hit the preflight
block, correctly adapted by writing the render step out to a real script file and running it as
`python3 <file>.py` exactly as the preflight error instructs, and completed both sends for
real, with genuine API responses (`{"ok":true,"messageId":"193"}` for Telegram,
`{"success":true,"result":{"message_id":"<...>@jackson2w.dev"}}` for email) sitting right there
in the transcript the whole time.

**The actual lesson: `journalctl` for this service surfaces failures prominently (they're
one-line, alertable events) but does not reliably surface successful generic `exec`/tool
results at the same log level** — likely deliberate (full command/response bodies would be
verbose and can contain credentials, matching the `"raw_params":{"reason":"exec command may
contain credentials"}` redaction already seen on failure lines too). **The session `.jsonl`
transcript is the only complete, authoritative record of what a turn actually did — journalctl
alone is not sufficient to disprove (or confirm) a completion claim.** Before concluding an
agent fabricated a result, check the real transcript first, not just the service log.

### `--message-file` bypasses the sandboxed `read` tool — and can deliver into the wrong directory

`openclaw agent --message-file <path>` reads the file **locally, outside OpenClaw's own tool
sandbox**, and injects its contents directly as the turn's user-message text — this works even if
the path sits outside `~/.openclaw/workspace/`, since it's the CLI host process reading the file,
not the agent's own `read` tool call. This creates an easy-to-miss asymmetry: the *first* delivery
of a document can succeed via `--message-file` regardless of where the file lives, but if the
agent later tries to **re-read that same file itself** (e.g. to re-verify content from a fresh
session, per the isolation gotcha above), its own `read` tool enforces the workspace-only
restriction and will refuse a path outside `~/.openclaw/workspace/` — a `Permission denied`-style
refusal that has nothing to do with the content being untrustworthy. Write any document meant to
be handed to the agent (via `--message-file` or otherwise) into `~/.openclaw/workspace/` (a
`handoffs/` subdirectory works well) from the start, owned by the `openclaw` user, so both the
initial delivery and any later independent re-verification use the same accessible path.

### Reading a session's `.jsonl` transcript for tool-call detail

The per-line `type` field is `"message"`, not the tool name — filter on `d["message"]["role"]`
and iterate `d["message"]["content"]` (a list). Assistant tool invocations show up as
`{"type": "toolCall", "toolName": ..., ...}` (not `tool_use`/`name`, despite that being the
Anthropic API's own field naming) alongside `{"type": "thinking"}` blocks; results arrive in a
following `"role": "toolResult"` entry. Large tool-call payloads (schemas, big text blocks) are
sometimes stored content-addressed (a `*Hash`/`*Chars` pair) rather than inline — don't assume a
missing/empty-looking field means the call had no real arguments before checking whether the
session format hashed it instead.

### A tool call mid-turn plus a literal `NO_REPLY` follow-up silently discards a real, already-generated reply

Real incident, 2026-08-23 on `dfw` ("Olu"): two inbound Telegram voice notes in a DM got no
reply at all — `journalctl -u openclaw.service` showed **two** Anthropic API calls per turn
(vs. one for a plain text turn in the same window), ending in
`[turn/kernel] visible channel turn dispatched with no queued reply payloads`. Initial
theories (a context-free isolated per-message session; the audio-transcript
`[Audio transcript (machine-generated, untrusted)]:` wrapper — see the voice-transcription
section above — inducing reflexive silence) were both wrong, and only ruled out by reading the
session's own raw `.jsonl` transcript directly (see the parsing section just above) rather than
trusting the summarized `sessions_history` tool output or the gateway log alone.

**Actual mechanism**: call #1 produced a real, substantive reply *and* a tool call (a memory
write). The tool ran. Call #2 — the required follow-up turn after any tool call resolves — was
the model, in isolation, judging "nothing more to add" and outputting the literal string
`NO_REPLY` as that follow-up's entire text. **The turn dispatcher uses only the final model
call's text as the turn's reply** — it does not concatenate or fall back to an earlier call's
substantive output. So the real, generated reply from call #1 was silently thrown away.

This is not audio-specific and not session-isolation-related at all — it will reproduce on
*any* turn where the model makes a tool call and then signs off the mandatory follow-up call
with `NO_REPLY` instead of substantive closing text (or a repeat of the earlier substance).
Reserve `NO_REPLY` for turns where it is the model's *only* output for the whole turn (the
documented ambient/group-silence use case) — never as a "nothing further to add" sign-off after
a tool call already produced something worth sending. `sessions_history`'s `session:<hash>`
labels on entries like these are just internal turn-grouping IDs for the multiple model calls
within one turn, not evidence of a separate isolated agent session — don't read them as such.

**Structural mitigation, built and live-verified same day.** A model's own commitment to "stop
doing this" is not enough on its own — it recurred **twice more within the hour**, on a plain
text turn (not audio), confirming the failure is generic to any tool-call-then-final-call turn,
not tied to the original audio trigger. Built a small local plugin (`before_agent_finalize`
hook — the documented extension point for "inspect the natural final answer and request one
more model pass") that detects the exact bad shape (final text is literally `NO_REPLY`, an
earlier assistant message in the same turn had substantive text, and a tool call happened
somewhere in between) and returns `{ action: "revise", retry: { instruction, maxAttempts } }`
to force one more pass instead of letting the turn dispatch silently.

**v1 caught the pattern but wasn't sufficient**: the guard correctly fired
(`before_agent_finalize requested revision`), but the forced retry pass *also* ended in
`NO_REPLY` — because the retry instruction only *described* the situation and asked the model
to decide again, the same judgment call it had already gotten wrong once in that same turn.
With `maxAttempts: 1`, one failed retry meant the harness gave up and dispatched silently
anyway — a real second failure on a live production turn, not a hypothetical.

**v2 fix, confirmed live**: extract the actual substantive text found earlier in the turn and
hand it back to the retry pass **verbatim**, inside the instruction ("send this exact text");
the retry's job becomes mechanical repetition instead of a second decision. Bumped
`maxAttempts` 1→2 as cheap defense-in-depth, not the primary fix. Verified two ways before
trusting it: (1) confirmed the deployed file actually contained v2's `substantiveTexts`/
`recoveredText` extraction, not v1's plain boolean check; (2) re-ran the exact synthetic repro
that had caught the v1 failure, isolated in a subagent so it wouldn't touch the live
conversation — the retry pass's actual output was the distinctive marker text handed to it,
sent verbatim, `stopReason=stop`, no silent-drop warning. A real pass, not just "the hook
fired." Treat this as closing the specific tool-call-then-NO_REPLY shape, not as proof no
further NO_REPLY-adjacent failure mode exists — worth watching over further real incidents
rather than treating as permanently settled.

**Design lesson for any similar guard**: a `before_agent_finalize` (or similar) revise/retry
mechanism is only as good as the instruction it hands back. Asking the model to re-decide
something it already got wrong once in the same turn has no reason to succeed the second time
either — extracting and replaying the actual prior content, turning the retry into mechanical
repetition rather than a fresh judgment call, is what actually closed the gap here.

**Full closure, 2026-08-23**: Olu relocated the plugin to a permanent home
(`~/.openclaw/workspace/plugins/no-reply-guard/`), caught and fixed its own regression during
that move (a full uninstall/reinstall accidentally dropped `plugins.entries.no-reply-guard.
hooks.allowConversationAccess`, silently disabling the hook — caught via `typedHooks` coming
back empty on inspection, before declaring success), and confirmed a live synthetic test passed
post-restart with the actual recovered marker text delivered verbatim, not another silent
`NO_REPLY`. Re-verification was briefly blocked by the model-corruption bug below recurring
rapidly (three synthetic-test subagent attempts in close succession each apparently
re-triggering it) — Olu correctly recognized the known-bug signature via its own investigation
and stopped retrying rather than hammering a known-bad window, deferring to a human decision on
whether to force an out-of-cooldown restart. Good instinct on both counts (self-caught
regression via direct state inspection, not blind retry-until-success).

**Filed upstream**: [openclaw/openclaw#128314](https://github.com/openclaw/openclaw/issues/128314)
— related to, but distinct from, the already-fixed
[#93166](https://github.com/openclaw/openclaw/issues/93166)/[#116006](https://github.com/openclaw/openclaw/pull/116006)
(transcript-isolation fix, merged 2026-07-29, confirmed present in the 2026.7.1-2 install used
here). #116006 fixed the retry pass seeing its own rejected draft in the transcript; the bug
above is that the retry pass can *independently* produce `NO_REPLY` again even without seeing
any prior draft, because the natural retry instruction just re-poses the same judgment call.

### A version upgrade can silently move a lane onto the exact-match-only silence token, leaking real content that used to be safe

Real incident, 2026-09-04 on `dfw`, distinct mechanism from the tool-call-then-`NO_REPLY` bug
above (that one drops a real reply; this one *leaks* one, sentinel included). Will reported
heartbeat/watcher status messages arriving on Telegram with a literal trailing `NO_REPLY` —
e.g. `"All healthy — heartbeat, watcher, and weekly jobs are enabled...\n\nNO_REPLY"` delivered
verbatim, not suppressed.

**Root cause, confirmed by diffing the live 2026.8.2 dist against the prior 2026.6.34 build**
(pulled from local npm cache, integrity-verified) and independently re-verified line-by-line
against the running server: the 2026.8.2 upgrade changed the **default heartbeat prompt**
itself, from `"reply HEARTBEAT_OK"` to `"reply ${SILENT_REPLY_TOKEN}"` (i.e. `NO_REPLY`) —
moving heartbeat turns onto the same exact-match-only silence contract used elsewhere, for the
first time. `normalizeHeartbeatReply` (`heartbeat-runner-jhGs3jbv.js`) has dedicated
edge/punctuation stripping for `HEARTBEAT_OK`, built when that was the only heartbeat token —
`NO_REPLY` never got equivalent treatment when the prompt was switched, so a GLM sign-off habit
(real status content, then `NO_REPLY` appended as a closer) fails the exact-match silence check,
gets classified as real visible output, and is delivered whole. A sibling delivery path (cron/
isolated, `normalizeSilentReplyText` in `delivery-dispatch-policy-CuyV2VD3.js`) has the opposite
bug on the same mixed-text shape: it *does* detect and strip the trailing token, but then
discards the entire stripped remainder instead of delivering it — silent data loss rather than a
leak. Both are one-line-class fixes (strip *and* deliver the remainder), neither shipped.

**General lesson**: an upgrade can silently widen which lanes use a given sentinel/contract
without updating every strip/normalize function that assumes the old contract — the failure
doesn't show up as a crash or error, just previously-safe content leaking or vanishing on the
newly-migrated lane. When a version bump changes default prompts, grep the dist for every
strip/normalize function touching the affected token, not just the ones already known.

**Diagnostic path that worked**: journal (`journalctl -u openclaw.service`) never logs message
*text*, only structural events (`outbound send ok` with a messageId/timestamp, no body) — so
confirming *which* deliveries leaked required a human forwarding the actual Telegram screenshots
with timestamps, then matching those exact timestamps against journal `outbound send`
messageIds. Olu's own transcript search initially came back clean ("zero since the upgrade")
because it only scanned conversational session transcripts — heartbeat/cron deliveries don't
persist through that path, a blind spot Olu had already self-flagged. The real diagnosis needed
both sides: Claude Code's root journal access (timing/structure) plus Olu's dist-source access
(the actual code, which Claude Code can't read — lives under `/home/openclaw`, off-limits per
[[feedback_no_claude_code_home_openclaw_access]]) plus a live npm-cache diff against the prior
release (Olu's own follow-up, not initially requested, that found the real upstream trigger).

**Mitigation live**: Olu adjusted the heartbeat prompt behavior so it stops appending the
sign-off token after real content — confirmed holding via journal cadence (no further leaked
deliveries; message spacing after the fix matches live conversational replies, not the ~25-30min
heartbeat interval). This is a band-aid, not the structural fix.

**Filed upstream**: [openclaw/openclaw#138229](https://github.com/openclaw/openclaw/issues/138229)
— includes the refined dist-diff root cause as a follow-up comment. Distinct from and not a
duplicate of #128314 (this file, above) or #137024 (an *exact-token* heartbeat reply getting
replaced by an unwanted fallback placeholder — the opposite direction: over-eager stripping
causing an unwanted delivery, vs. this bug's no-stripping-at-all).

### `Restart=on-failure` does not cover OpenClaw's own graceful "supervisor restart" exit — the service goes down and stays down

Real outage, 2026-08-23, caused by legitimate OpenClaw behavior, not a misconfiguration on our
side: when OpenClaw's gateway process receives `SIGUSR1`, it performs `[gateway] restart mode:
full process restart (supervisor restart)` — a deliberate, clean self-exit
(`code=exited, status=0/SUCCESS`) that assumes an external process supervisor (systemd, pm2,
etc.) will relaunch it immediately. This is a legitimate, documented-sounding self-restart
mechanism (used here when a plugin config change needed a full reload, e.g. after moving a
plugin to a new install location) — not a crash.

**The trap**: a systemd unit with the seemingly-reasonable `Restart=on-failure` does **not**
restart on this exit — `on-failure` only covers a non-zero exit code or certain fatal signals,
and a clean `status=0` exit is explicitly excluded by that policy's own definition. The service
just goes `inactive (dead)` and stays there indefinitely — no crash loop, no restart attempt,
no alert, nothing in the journal after the clean shutdown lines. Caught here only because a
newly-built watchdog's manual test run happened to overlap with a real SIGUSR1 restart Olu
triggered on its own (relocating a plugin), and a routine post-action status check found the
service dead several minutes after the fact — this could easily have gone unnoticed far longer
in a less actively-monitored moment. Confirmed via `systemctl status`: `Process: ...
(code=exited, status=0/SUCCESS)`, `Deactivated successfully`, with the unit never re-entering
`activating`.

**Fix**: change the unit's `Restart=` from `on-failure` to `always` — the standard policy for
any long-running service that should never intentionally stay down, covering both crashes and
this kind of deliberate clean-exit-expects-relaunch pattern. `systemctl daemon-reload` is
sufficient to apply it (no service restart needed — the policy only governs what happens on
the *next* exit). **Verified by reproducing the exact failure**: sent `SIGUSR1` directly to the
live process after the fix and confirmed systemd auto-relaunched it within seconds with no
manual intervention, vs. the original incident where nothing brought it back at all.

If any other OpenClaw deployment shows the same `Restart=on-failure` in its unit (common
default, looks like the "safe, minimal" choice), check for `restart mode: ... (supervisor
restart)` anywhere in that instance's own history before assuming crash-only coverage is
sufficient — any deployment that installs plugins, changes config needing a full reload, or
otherwise triggers this self-restart path has the same exposure.

## A root-owned dispatch script bypasses `openclaw.service`'s own sandboxing entirely — that's a feature, use it deliberately

Confirmed 2026-09-04: `openclaw.service`'s `ProtectSystem=strict` makes `/usr/lib/node_modules`
(the npm global install root) read-only to the sandboxed gateway process itself — Olu hit a
literal `EROFS` trying to upgrade its own runtime, correctly concluded it structurally could not
do this, and was right. But the existing `npm-global-install` subcommand in
`openclaw-dfw-admin-changes.sh` (see the dispatch-script pattern above) already lets Olu install
*other* packages (`wrangler` is the current allowlisted one) — this works precisely because that
script runs as root via a `NOPASSWD` sudoers grant, entirely outside `openclaw.service`'s own
unit and its `ProtectSystem=strict` scope. The sandbox only ever constrains the confined
process's own writes; a separate root-owned script invoked via sudo was never inside that
boundary to begin with.

**Don't extend that same generic subcommand to let OpenClaw upgrade itself, though.** A
standalone CLI tool like `wrangler` has no runtime state to break — OpenClaw upgrading its own
running gateway is categorically different (see the auto-update-crash incident above: a bare
version bump left the process running fine until the next restart, which then hit a chain of
undocumented legacy-migration gates with a broken `doctor --fix`). If this capability is ever
built, it needs its own subcommand with real structure — a pinned target version rather than
"any version," an automatic pre-upgrade config+session backup (Olu already does this by hand;
should be built into the capability, not a manual habit), and probably no auto-restart, so a bad
upgrade doesn't cascade unattended. Treat it as a real design task (this repo's own "propose
before building" convention), not a same-session manifest edit.

## A revoked/rotated Telegram token crash-loops the channel with a clear signature — and the fix is often outside the `/home/openclaw` access boundary

Real incident, 2026-08-29: a BotFather mix-up during an unrelated credential rotation
accidentally revoked `@dfwclaw_bot`'s own live token. Failure signature in `journalctl -u
openclaw.service` is unambiguous and self-diagnosing — the error names the exact fields to
check:

```
[telegram] [default] Telegram bot token unauthorized for account "default" (getMe returned 401
from Telegram; source: config token). Update channels.telegram.botToken,
channels.telegram.tokenFile, or TELEGRAM_BOT_TOKEN with the current BotFather token.
[telegram] [default] channel exited: ...
[telegram] [default] auto-restart attempt N/10 in <backoff>s
```

Backoff climbs toward 300s over ~10 attempts, then a `[health-monitor]` restart resets the
counter and it repeats — a real outage, not a one-off blip, until the token is actually fixed.

**On this deployment, `TELEGRAM_BOT_TOKEN` resolved to `/root/.config/openclaw-anthropic.env`**
(root-owned, wired into the unit via `EnvironmentFile=` — confirm with `systemctl cat
openclaw.service | grep EnvironmentFile`), alongside the other provider keys — not a plaintext
value inside `~/.openclaw/openclaw.json`. **This file lives outside `/home/openclaw` entirely**,
so it is *not* covered by the harness's `/home/openclaw` access restriction (see
`feedback_no_claude_code_home_openclaw_access` in the homelab planning repo's memory) — Claude
Code can read field names (`cut -d= -f1`, no values) and the systemd unit, and can run the
restart + verification, even though it still can't see or write the actual secret value (the
human writes that directly into the file, standard credential-rotation-protocol pattern). Don't
assume every OpenClaw-token problem is blocked by that boundary — check whether the value is
actually env-sourced via a root-owned `EnvironmentFile` first, since that's a very common pattern
for provider keys per the "Secrets: two valid patterns" section above.

Fix: human edits the `TELEGRAM_BOT_TOKEN=` line in place (`sudo nano <path>`, never a shell
command-line argument — keeps it out of bash history), then `sudo systemctl restart
openclaw.service`. **OpenClaw handles the rotation gracefully on its own** — no extra step
needed for the stale Telegram update offset:

```
[telegram] [default] starting provider (@dfwclaw_bot)
[telegram] Detected token rotation for account "default" (was <id>, now <id>); discarding stale
update offset <N> and starting fresh.
```

Verify clean via `journalctl -u openclaw.service --since <restart-time> | grep -i telegram` —
should show the two lines above and nothing matching `unauthorized|401|exited|auto-restart`.

## Does a release contain a fix? Compare call order in the published `dist`, not a comment grep (2026-09-12)

The upstream fix for a recurring cron error (`Failed to remove unused run continuation … competing work
in flight`) was identified on `main` by a source comment, but **the bundled `dist` strips comments**.
Grepping two published versions for that comment found it in neither, which proves nothing. What
decided it was the code order inside the post-run `finally`:
- 2026.8.2 (`dist/isolated-agent-*.js`): `removeCronRunContinuationSessionIfIdle()` L1552, then
  `sessionWorkAdmission.release()` L1563. It deletes while its own admission is still held, which is
  the race.
- 2026.9.4 (`dist/isolated-agent-*.mjs`): release L1507, then remove L1510. **Fixed.**

Method, with nothing installed:
```bash
T=$(mktemp -d); cd "$T"; npm pack openclaw@<ver> --silent
mkdir <ver> && tar -xzf openclaw-<ver>.tgz -C <ver>
grep -nE "<fnA>\(|<fnB>\(|finally ?\{" <ver>/package/dist/<chunk>
```
Do this in a temp dir outside the service account's home. The error was log noise only (every run
`ok`), which is itself a reason to schedule the upgrade calmly rather than rushing it.

## OpenClaw has a real background auto-updater (`update.auto.enabled`) — check it, but verify before blaming it

Confirmed via the installed dist bundle (`/usr/lib/node_modules/openclaw/dist/update-startup-*.js`,
`schema-*.js`): OpenClaw ships a genuine background auto-update feature, config key
`update.auto.enabled`, **documented default `false`**. Worth checking (`openclaw config get
update.auto.enabled`, run by the account owner — this is inside the service account's config,
off-limits to Claude Code per the access-boundary note below) on any deployment as a matter of
awareness. **But don't assume it's the cause of an unexplained version jump without verifying** —
on the incident below, this was the first theory and it was wrong: the live config and all 7
on-disk config backups had the key unset (default `false`, genuinely off), and the real cause
turned out to be a human running `npm install -g openclaw@<version>` manually in a real
interactive terminal. The tell that separates the two: check `journalctl _COMM=sudo` (not just
`journalctl -u openclaw.service`) for the transition window — a manual update shows up there
with a real `TTY=pts/N`, distinct from anything Claude Code or an internal auto-updater would do.

## A restart can be the moment an already-applied update's migration debt comes due — whether the update was manual or automatic

Real incident, 2026-09-04 (full narrative: `project_openclaw_autoupdate_crash_2026_09_04` memory
in the homelab planning repo). OpenClaw was updated from 2026.7.1-2 to 2026.8.2 (manually, by the
operator, per the correction above) — the version bump alone didn't crash anything, because the
*running* process kept running fine on the old in-memory code. The crash only surfaced ~17
minutes later on the next full process restart (for an unrelated reason), which hit a chain of
three sequential legacy-state migration gates the old version had never needed. Lesson: if
`openclaw.service` needs restarting for any reason, check `openclaw --version` against what you
last confirmed first, and be mentally ready for a chain of migration gates instead of a clean
restart — a version change (deliberate or not) may be sitting there unnoticed since the last
restart.

**`openclaw doctor --fix` itself may be completely non-functional on a hand-authored systemd
unit.** On this deployment (system-level unit with a custom `ExecStart` wrapping the binary
through Agent Vault's MITM proxy — see `agent-vault-credential-broker` skill — not installed via
`openclaw gateway install --system`), every `doctor --fix`/`--fix --force` invocation failed
identically:

```
Doctor could not enter maintenance. Stop the Gateway through its service owner, then run
openclaw doctor --fix. Error: Gateway service ownership or shutdown could not be verified.
Run openclaw gateway status --deep and stop it through its service owner before retrying.
```

This persisted even with the Gateway genuinely, repeatedly verified stopped (`systemctl
is-active` = inactive, no matching process), across multiple retries, with and without an
explicit `XDG_RUNTIME_DIR=/run/user/<uid>` in the invoking environment, and after confirming
(via direct manual `systemctl --user`/`busctl --user` calls, bypassing the CLI entirely) that
the D-Bus session bus for the service account was genuinely up and working. Do not assume this
is the well-documented openclaw/openclaw#137503 (missing `dbus-user-session` package) without
independently verifying — that package can already be installed and the session bus can already
be live, and the generic error persists anyway for a still-unidentified reason. Filed as a fresh
issue: openclaw/openclaw#137888.

**The actual fix: bypass `doctor --fix` entirely and use its narrower, documented sub-commands**
one legacy-state class at a time — each of these worked non-interactively where the umbrella
`--fix`/`--repair` could not (a documented general pattern, see closed issues #134036 and
#134331 — non-TTY/automation contexts silently skip or deadlock the umbrella migrations):

1. **`Legacy workspace setup state requires migration for <workspace>`** — per
   openclaw/openclaw#137866/#134331, the startup guard checks THREE possible legacy source
   markers before it'll proceed, existence-only (it throws on presence, never reads content):
   - `<workspace>/openclaw-workspace-state.json`
   - `<workspace>/.openclaw/workspace-state.json`
   - `~/.openclaw/workspace-attestations/<sha256-of-resolved-workspace-path>.attested` — compute
     the filename with `python3 -c "import hashlib; print(hashlib.sha256(b'/abs/path/to/workspace').hexdigest())"`
   Back up and remove whichever of the three actually exist. The canonical SQLite state usually
   already has the correct data — these are safe, redundant files once superseded, not the only
   copy of anything, unlike the next one.
2. **`Legacy session store requires migration: <path>/sessions/sessions.json`** — this one DOES
   hold real conversation/session history, so don't just delete it. Use the narrow, safe,
   additive sub-command instead (preview first, it's read-only):
   ```
   openclaw doctor --session-sqlite dry-run --session-sqlite-agent <agent-id> --json
   openclaw doctor --session-sqlite import --session-sqlite-agent <agent-id> --json
   ```
   `import` moves legacy JSONL files into an archive directory (not deleted) and reports
   `importedEntries`/`importedTranscriptEvents` counts — verify these match `legacyEntries`
   before trusting it fully migrated.
3. **`Legacy exec approvals exist at <home>/.openclaw/exec-approvals.json`** — move the file
   aside (must stay within the service account's own home directory; it can't write to `/root`
   even under `sudo -u`), then re-register it:
   ```
   sudo -u openclaw mv ~openclaw/.openclaw/exec-approvals.json ~openclaw/.openclaw/exec-approvals.json.moved
   sudo -u openclaw openclaw approvals set --file ~openclaw/.openclaw/exec-approvals.json.moved
   ```
   Verify via `openclaw approvals get` that the full allowlist (target/agent/pattern rows)
   survived intact before considering this done.

After all three are cleared, expect `[gateway] ready` in the log but the crash-loop breaker
(tripped during the earlier failed boots) will likely still be **suppressing channel auto-start**
even on a clean boot — it needs one manual nudge, exactly as its own log line suggests:
```
openclaw gateway call channels.start --params '{"channel":"telegram"}'
```
Messages that arrived during the whole outage are queued/retried by the channel provider and
delivered once it comes back — confirmed zero message loss across a ~75-minute outage in this
incident, no need to worry that queued inbound messages were silently dropped.

**Access-boundary note for Claude Code specifically**: every one of the above commands (the
`cp`/`mv`/`openclaw doctor`/`openclaw approvals` invocations) touches `/home/<service-account>`
directly and must be run by the human operator, not Claude Code — see
`feedback_no_claude_code_home_openclaw_access` in the homelab planning repo's memory. Claude
Code's role in an incident like this is: `systemctl stop/start/restart` (fine, doesn't touch the
home directory), reading `journalctl` output, researching the actual upstream fix commands, and
computing things like the sha256 attestation filename locally — not touching the account's home
directory even read-only (a stray `find` into it mid-incident, just to look for other candidate
legacy files, was a real overstep in this incident — ask the human to run `ls`/`find` themselves
instead, every time, no exceptions for urgency).

## Two structurally different run-timeout mechanisms produce near-identical-looking failures — don't conflate them

Confirmed 2026-09-04 on `dfw`: a user got OpenClaw's generic "Request timed out before a
response was generated. Please try again, or increase agents.defaults.timeoutSeconds in your
config." error on a live chat turn. The journal showed:

```
[agent/embedded] embedded run timeout: runId=<id> sessionId=<id> timeoutMs=300000
[provider-transport-fetch] [model-fetch] error ... elapsedMs=681 name=TimeoutError message=request timed out
```

That second line looks like "the model provider is slow/broken" — it isn't. It's the *symptom*
of the first line: the whole run hit its overall wall-clock budget (`agents.defaults.
timeoutSeconds`, 300s here) and got aborted mid-flight, and the abort surfaces as a spurious
`TimeoutError` on whatever individual call happened to be in progress at that instant — even if
that specific call had only been running well under a second. **Before concluding a model
provider is unhealthy from a `TimeoutError` log line, check whether every OTHER call in the same
run around that timestamp was fast and successful** (`grep` the surrounding window for
`model-fetch] response ... status=200`) — if so, it's the run budget, not the provider.

Separately, a **cron job's own `payload.timeoutSeconds`** is a distinct, per-job budget (default
much shorter — 120s was the value that bit in the confirmed incident) from the interactive/
heartbeat `agents.defaults.timeoutSeconds`. A cron job doing real, legitimate multi-tool-call
work (e.g. reading several files, checking multiple sources) can blow straight through a 120s
budget with zero idle time and zero bug — it looks identical in the journal to a stuck/looping
job (`lane task error: ... durationMs=120145 error="TimeoutError: cron: job execution timed out
(last phase: model-call-started)"`), but the fix is right-sizing the job's own timeout to its
real workload, not debugging the trigger-evaluation logic. In the confirmed incident, throwaway
test jobs with trivial payloads "passed" while the real job with substantive work "failed" — the
differential was workload-vs-budget, not anything structural; don't be misled by a passing
control test into assuming the failing job's *logic* is broken.

**Practical takeaway for diagnosing any "OpenClaw timed out" report**: identify which of the two
budgets fired (`agents.defaults.timeoutSeconds` for live/heartbeat runs vs. a specific cron job's
`payload.timeoutSeconds`) before treating it as a provider-health or trigger-logic bug. Both
manifest as a generic-looking `TimeoutError`, and neither one means the model call that appears
in the error line was actually slow.

## A heartbeat-poll turn can self-extend into an open-ended debugging session with no natural stopping point

Also confirmed 2026-09-04: a routine heartbeat poll found two unrelated cron jobs erroring and
turned into a genuine 72-call, multi-hop investigation (source-tracing through the dist bundles,
then creating throwaway test cron jobs to empirically narrow the cause) that never converged
before hitting the 300s run timeout. Every call did real, distinct work — this is not the same
failure shape as a stuck retry loop or call-fanout bug — but a heartbeat turn has no built-in
concept of "this has gone deep enough, stop and report back," so a legitimately interesting lead
can consume the entire run budget with no final answer produced. If heartbeat runs are expected
to stay lightweight, scope that explicitly in the heartbeat prompt (investigate-and-report only,
defer genuine deep dives to a dedicated follow-up run) or add a per-run tool-call cap as a hard
stop — raising the wall-clock timeout alone doesn't fix this, since a genuinely unbounded
investigation will just consume however much budget it's given.

## Olu cannot restart itself — a restart it "should have done" always needs root

Confirmed 2026-09-04 when Will observed that Olu had built a requested feature without first
performing an approved gateway restart, which read as the agent ignoring an instruction. It
wasn't: `openclaw.service` runs with `NoNewPrivileges`/no-new-privileges sudo and `tools.elevated`
gated off, so **the agent is structurally incapable of restarting its own service.** Investigate
before agreeing that an agent skipped a step — the more common explanation is that it never had
the capability.

Corollary for any change requiring a restart: plan for a human or Claude Code to run it, and say
so explicitly in the task you hand the agent, rather than leaving it as an implied step it will
appear to ignore.

**Before restarting, check whether the on-disk bundle is newer than the running process:**

```bash
sudo systemctl show openclaw -p ExecMainStartTimestamp   # when the running process started
sudo stat -c '%y %n' <installed bundle path>             # when the code on disk last changed
```

If the bundle predates the running process, the restart re-runs an identical version with no
migration debt — boring and safe. If it postdates it, the restart is the moment an already-applied
update's migration debt comes due (see the section above on that). That condition being *false*
is what made the 2026-09-04 crash destructive and a later same-day restart uneventful.

## Delivery monitoring belongs out of process — see the `agent-delivery-canary` skill

OpenClaw's three characteristic failure modes — silent non-delivery (turn dispatch), content leak
(sentinel strings reaching the user), and egress silent drops — **produce no error line at all**,
so every journal-scraping monitor is structurally blind to them. The journal logs delivery but
never message content:

```
[telegram] outbound send ok accountId=default chatId=<id> messageId=<n> deliveryKind=text
```

That asymmetry is what makes the trust split work: a root verifier outside the agent asserts
**delivery** from the journal, while the agent asserts **content**, being the only party that can
see the composed text. Full architecture, escalation model, and the failure-path tests in the
`agent-delivery-canary` skill.

## A root-owned system unit needs `OPENCLAW_SERVICE_REPAIR_POLICY=external` (2026-09-07)

`openclaw onboard --install-daemon` writes a **user** unit (`~/.config/systemd/user/openclaw-gateway.service`);
this project runs a hand-written root-owned **system** unit (`openclaw.service`, `agent-vault run`
wrapper). That difference is the 2026-09-04 `doctor --fix` failure: doctor's maintenance entry
verifies ownership of the *managed* unit via `systemctl --user`, sees a system unit with
`LoadState=loaded`, seals the service definition and refuses ("Gateway service ownership or
shutdown could not be verified"). openclaw/openclaw#140908 (P0, 2026-09-07) is the same chain on
2026.9.2. The docs' answer for a system unit that owns the lifecycle is
`OPENCLAW_SERVICE_REPAIR_POLICY=external`: doctor goes diagnostic-only for the service lifecycle
and repairs state against a gateway *you* stopped. On `dfw` it is set in the unit and in a root
wrapper, `/usr/local/sbin/openclaw-doctor`, which is the one sanctioned way to run doctor by hand
(service user, service `HOME`, the policy exported). Stop the gateway through its owner first for
anything that mutates. **Unverified by execution** on the maintenance gate itself as of writing
(read-only `--lint --json` runs fine through it); the staging twin's first rehearsal settles it.

Related, from the same day (Olu's trace of the 2026.8.2 dist): `openclaw update` classifies a
system unit `foreign`, stops nothing, and refuses to run from inside the gateway process, so the
safe hop on such a host is stop-via-owner → `update --tag <v> --yes --no-restart` → start.
Migrations run inside the update's doctor pass, not at boot (boot only has refusal gates), so a
bare restart after a manual `npm install -g` trips the gates without running the migrations.
`update --dry-run` does not check migrations; `doctor --lint --all --json` does. Freeze knobs:
`update.auto.enabled: false`, `update.checkOnStart: false`, `OPENCLAW_NO_AUTO_UPDATE=1`; there is
no `update.pin` and `--tag` is not persisted, so the declared version lives in
`dfw-ansible`'s `openclaw-gateway-install.yml`, which fails on a mismatch by design.

## Upgrade 2026.8.2 → 2026.9.6 on dfw (2026-10-07, D-28): what actually bit

- **Node first.** 9.3+ needs Node ≥24.16 (<25) or ≥26.1. On dfw: switch `/etc/apt/sources.list.d/nodesource.sources`
  from `node_22.x` to `node_24.x`, `apt-get install nodejs` (24.21.0). Only the gateway uses Node there. The running
  gateway keeps the old binary until its restart. 8.2 also runs on Node 24, so an OpenClaw rollback survives.
- **npm 11 (ships with Node 24) skips install scripts by default.** A plain `npm install -g openclaw@X` "succeeds"
  without OpenClaw's bundled-plugins postinstall. Use
  `npm install -g --allow-scripts=@google/genai,koffi,protobufjs,openclaw openclaw@X`, including for a rollback.
- **`sudo -u openclaw … openclaw doctor` from claude-admin's home fails with `spawn /usr/bin/node EACCES`:**
  the child inherits a cwd openclaw can't enter. Run it as `cd / && sudo -u openclaw -H …`.
- **Preview before `doctor --fix`.** The 9.6 preview wanted to archive TOOLS.md and merge it into AGENTS.md
  (TOOLS.md is Will's call, never Claude Code's) and to move HEARTBEAT.md into the heartbeat job's scratch
  (intersects Olu's Lane B row). Neither was run; both went to Will/Olu. The gateway's own startup runs the
  safe migrations (transcript media, config-audit log → SQLite, Skill Workshop relocation) without them.
- **Capability consent:** non-bundled plugins (admin-changes-gate, no-reply-guard) needed
  `openclaw plugins enable <id> --accept-capabilities` before restart, or they may not load. admin-changes-gate
  is Olu's outbound approval gate, so check it is in the "http server listening (N plugins: …)" line.
- **Version-pinned plugins self-disable:** heartbeat-silent-strip and d24-runaway-loop-guard log "version pin
  mismatch … hook DISABLED (no-op)" until Olu re-validates and bumps the pin. Plan that into the window.
- **Plugin API floors:** brave 2026.7.1 couldn't be updated because its next release needs plugin API ≥2026.9.7.
- Write `/root/state/openclaw-planned-restart` (epoch) before stopping, so the hermes peer watch treats it as planned.
- **Re-pin version-pinned plugins BEFORE the first restart on the new version.** On D-28 they were re-pinned after
  it, so the first boot ran with heartbeat-silent-strip as a no-op for ~70 min, and two raw heartbeat outputs
  reached Will's DM (msgs 3428, 3429). It took a third restart to arm them.
- **Stuck heartbeat after a restart that interrupts a heartbeat run:** the restart-recovery of the interrupted
  heartbeat session collided with the next cron run, which then sat with `state.runningAtMs` set for over an hour,
  and `cron status` showed `nextWakeAtMs` pinned to it. On 9.6 the heartbeat is a **system-owned monitor job**:
  `cron disable/enable/edit` refuse ("system-owned monitor jobs cannot be edited by cron clients"), and there is no
  cancel. A gateway restart clears it (the run is recorded as "interrupted by gateway restart"). Afterwards, check
  that `runningAtMs` goes null between ticks.
- **How lane starvation looks on 9.6:** no 600 s job kill. Instead the heartbeat logs `skipped: requests-in-flight`
  while other turns hold the lane, or runs into `agents.defaults.heartbeat.timeoutSeconds` (1800 s on dfw). Long
  subagents (chat-run timeout ~30–47 min) holding both `maxConcurrent=2` slots also make the 120 s canary time out at
  "last phase: model-call-started", even while model calls themselves return 200 in 1–3 s.
- **Paging run history (2026.9.6):**
  - `--id` needs the full job UUID; a short prefix returns "Automation not found". Get it from `cron list --json`.
  - `--limit` caps at 200 ("must be <= 200"), so page with `--offset 0/200/400…`.
  - Add `--status all` to include skips and errors.
  - Records live under `.entries[]`, with `status` ok/skipped/error, `completionStatus`, `durationMs` and `runAtIso`.
  - A-12 was judged this way on 2026-10-09: 293 runs, no 600 s kill, 2 × 1800 s timeouts and 16 skips. That is
    lane starvation in its 9.6 form, which is a capacity problem, not the old kill.
- **Reading runs:** `cd / && sudo -u openclaw -H openclaw cron runs --id <job> --limit N --json | jq '[.. | objects |
  select(has("runAtIso"))] | sort_by(.runAtIso)'` (the list comes oldest-last). Don't grep the journal for "timed
  out": the agent's own report frames quote old errors into it.

## Stopping or retiring an OpenClaw agent: disable the restarters first (2026-10-17)

A fleet that babysits OpenClaw will fight a plain `systemctl disable --now openclaw`. Order that worked on dfw:

1. Write the planned-restart marker (epoch into `/root/state/openclaw-planned-restart`) so peer/health watchers stand down.
2. `disable --now` every timer that **restarts** it (corruption watchdog, conditional memory restart) — a watchdog's `systemctl restart` starts a disabled unit.
3. `disable --now` every timer that **alerts** on it (health check, provider-error watch, model-drift check), and the **peer** host's watch if its only subject is this agent. Keep watchers whose subject is the *other* agent.
   Include the **delivery canary verifier** (`dfw-canary-verify.timer`): it reads only `journalctl -u openclaw`, so a stopped agent looks like "cannot see the journal" and it pages every 30 min (missed 10-17, 136 alerts by 10-20). Inventory by grepping for the unit, not by timer name: `grep -lE 'openclaw\.service|-u openclaw' /usr/local/bin/* /usr/local/sbin/*`, then check which of those have a live timer.
4. Stop `openclaw` + `openclaw-admin-server`. SIGTERM exits 143, so the unit lands `failed`: `systemctl reset-failed openclaw` or the fleet failed-unit check pages.
5. Off-host: pause dispatch/brief scripts and remove any sweep check that expects the dashboard Serve to answer; dry-run both.
6. Record that these are hand changes: the Ansible role re-enables them until the role is removed.

Leftover `systemd --user`/`dbus-daemon` processes for the service user are the lingering user session, not the agent. Durable removal (vault/keys, egress rules, exchange, fleet access, data archive) is a separate step.
