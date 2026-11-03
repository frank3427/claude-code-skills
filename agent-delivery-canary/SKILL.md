---
name: agent-delivery-canary
description: This skill should be used when building monitoring for a self-hosted always-on agent (OpenClaw/Olu, Hermes/Chuka, or a future one) that must catch failures the agent itself cannot report — silent non-delivery of a scheduled turn, a wedged or crash-looping gateway, or a fault already broken at baseline. Covers the delivery-canary pattern (agent-owned cron job + an out-of-process root verifier reading the log), the agent/verifier trust split, mutual liveness via tailnet-only health documents each host publishes and its peer watches, and persistent-state escalation that replaces transition-only alerting. Built and verified on both `dfw` (OpenClaw) and `hermes` (Hermes) on 2026-09-04. Trigger phrases include "delivery canary", "agent monitoring", "silent non-delivery", "turn dispatch bug", "canary verifier", "peer watch", "mutual liveness", "agent health endpoint", "tailscale serve health json", "transition-only alerting", "today > 0 && prev == 0", "persistent state escalation", "agent crash loop unnoticed", "who watches the agent", "canary chat id scoping", "monitor that cries wolf".
---

# Agent delivery canary and mutual liveness

> **2026-11-01:** with Olu and dfw retired, the hermes watcher runs from **ansible-ctrl**
> (homelab-ansible `hermes-peer-watch.yml`; state copied over so restart detection continued). The
> dfw copy sent the bot token in the curl URL, so it showed in `ps`. The port sends it on stdin
> (`--config -`). Do the same in any new watcher. Proven there with a staged stale document
> (alert) and the real one (silent), in `APW_TELEGRAM_STUB=1` mode.

Built 2026-09-04 across both of Will's agent hosts after he asked *"how have olu and chuka been
running? things have been quiet thankfully"* — and the check found one MCP server broken for two
days and, earlier the same week, a Home Assistant auth failure standing 2.5 days and an MCP
server that had **never once connected**. None of it had produced a single alert.

The lesson that shaped everything here: **things WERE watching and could not surface what they
saw.** Monitoring existed, ran on schedule, and was structurally incapable of reporting these
faults. Adding more of the same monitoring would have changed nothing.

## The four defects that make agent monitoring silently useless

Check any existing agent monitor against these before adding to it.

1. **Transition-only alerting.** Firing on `today > 0 && prev == 0` means anything already broken
   when the baseline was taken can *never* trigger. A fault present on day 0 is invisible
   forever. This is the single highest-value thing to fix, and it is extremely common because
   "only alert on change" sounds like good hygiene.
2. **Nobody consumes the self-reported signal.** The agent logged `NEEDS_ATTENTION` every two
   hours for a real fault. Detection worked perfectly; no pipeline read it.
3. **Config status mistaken for runtime status.** `hermes mcp list` showed a server `✓ enabled`
   while it was parked and unusable. "Enabled" is a statement about a config file.
4. **Counting log lines is a proxy, not a probe.** It misled in *both* directions on the same
   day: 37 "failures" that were benign self-healing flaps, and a fatal fault that produced
   silence. Only invoking the thing resolves this.

**Escalation model that replaces (1):** per-category consecutive-day counters; alert on new, on
worsened (>1.5×), and on days 1/2/3 then every 7th day while a fault stands. Never permanently
silent, never a daily nag. "Silent on no change" must never mean "silent while broken."

Make the state paths and time window env-overridable (`HSC_*`, `DAH_*`, `CANARY_*`) — multi-run
escalation logic **cannot be verified by running the script once**, and replaying it against
synthetic state is the only practical test.

## The canary: the only thing that catches silent non-delivery

An agent that drops a scheduled turn produces **no error line at all**. A dropped turn looks
exactly like an idle one. Every error-counting monitor is structurally blind to it, so only
*"a message was supposed to arrive and did not"* detects that class.

**The trust split is the whole design. Do not collapse it.**

| Party | Asserts | Why it must be that party |
|---|---|---|
| The agent | message **content** | It is the only one that can see the composed text |
| A root verifier, out of process | **delivery** | A wedged agent cannot report its own silence |

The verifier must **never** read an agent-written status file. That collapses the split and
turns the canary into the agent grading its own homework. The concrete reason: on 2026-09-01 an
agent reported an approval gate working when it was not — caught only via log timestamps.

**A canary whose only witness is the thing being tested is not a canary.**

### Implementation shape

- **Agent side:** an agent-owned cron job on a known schedule, sending *inside a turn* via the
  message tool — not a bare send — so the real dispatch path is exercised. The agent owns this
  because its cron config typically lives in a directory Claude Code should not touch.
- **Verifier side:** root systemd timer, separate process, reads only the log.

```bash
# dfw / OpenClaw — delivery is in the systemd journal
journalctl -u openclaw | grep -cE "outbound send ok.*chatId=${CANARY_CHAT_ID}\b"

# hermes / Hermes — delivery is in ~/.hermes/logs/agent.log, NOT the journal
grep -F "Job '${CANARY_JOB_ID}': delivered to telegram:${CANARY_CHAT_ID}" "$AGENT_LOG"
```

### Four rules that each prevent a specific real failure

- **Scope to the canary's own chat id** (and job id where available). Matching "any delivery"
  lets ordinary traffic satisfy the check, and a dead canary then passes silently forever.
- **Rolling `interval + grace` window**, so the verifier never needs to know the cron phase —
  only that the window always contains one healthy tick. Avoids a whole class of alignment bugs.
- **`CANARY_INTERVAL_MIN` must match the job's real schedule.** A mismatch manufactures false
  alarms, and *a monitor that cries wolf gets muted, which leaves you worse off than no canary*.
- **Ship disabled until the parameters are confirmed.** An unconfigured verifier stays silent
  rather than alerting about a canary it cannot measure.

Alert on the **first** miss (a silent drop is high-severity), then every 4th, and send a recovery
notice when delivery resumes.

### Canary message content: make every field able to change

A first attempt shipped `CANARY-DFW-7Q4Z | 2026-09-04T21:07:00Z | turn-dispatch liveness probe`.
Will's verdict: *"comically nonsensical and uninformative."* He was right — of three fields two
were constant and the third duplicated Telegram's own timestamp in unreadable UTC. Zero
information per message.

The marker token was worse than useless: it existed because the verifier was *imagined* to
content-match on it. It never did, because the log records delivery, not message text. Nothing
ever read it.

```
Olu OK · 4:07 PM
up 3h 41m · 0 errors since 3:07 PM · lunaroute glm-5.3-flash
```

Each field earns its place by being able to change: a plain claim, local 12-hour time (spot a
*late* tick without UTC math), uptime (a silent restart is otherwise invisible), errors since the
last canary (makes each message carry news), and active provider/model (catches a silent failover
that nothing else surfaces). Prefix a warning sign when errors > 0 **or uptime < 60 min** — a
fresh-restart tell.

Two constraints on the agent's implementation:

- **A failed status lookup must never suppress the message.** Degrade to
  `Olu OK · 4:07 PM · (status unavailable)` and still send. A canary that dies of its own
  complexity manufactures false alarms and trains everyone to distrust the alarm.
- **Keep gathering cheap** (uptime and an error count are free). A heavier turn is a turn with
  more ways to fail; deep analysis belongs in the daily health check.

Those enriched fields are **self-reported convenience, not evidence**. Delivery remains the only
externally-verified signal, which is exactly why the verifier does not read them.

### When the agent-side sender drifts: an agent-run vs script-only canary (2026-09-12)

The agent-side half is itself exposed to model behaviour:
- **Invented commands:** in one day's fires the model skipped the prompt's real status script and made
  up commands that didn't exist, producing false "status unavailable" lines.
- **Provider 429s** failed several fires outright.
- **A warning emoji tied to benign conditions** (scheduled restarts, stale error counts) fired on 55% of
  messages and stopped carrying information. Tie the warning to the one branch that means "could not
  determine status".

A script-only sender (e.g. `hermes cron … --no-agent`) that runs the status script and formats the line
itself removes the drift and the lane contention. It also gives up what an agent turn adds: proof the
agent's own dispatch path works, and fields the agent composes. Don't switch blind: run both side by side
with a visible prefix (`[script]`) for a week, count false warnings and failed fires, then keep one.
Either way the verifier stays out of process.

**Final pick, 2026-10-20 (Will): script-only.** The trial started 2026-09-12 for a week, but neither canary
was turned off: both ran in parallel for over a month, until a question prompt forced the choice. Put the
end of a side-by-side trial on a dated follow-up, and verify the losing sender is actually disabled (here,
the agent-run `delivery-canary` on hermes, recheck 2026-10-25), not just decided against.

## Mutual liveness: the only layer that survives its subject being dead

Every other check runs *on* the host it monitors. A wedged, crash-looping, or offline host emits
silence — and silence is indistinguishable from health. One agent crash-looped ~75 minutes and
nothing reported it.

Each host publishes a small JSON document and watches its peer's:

```
/var/lib/agent-health/health.json      # host, agent_active, uptime_seconds, failed_units,
                                       # canary_consecutive_failures, generated_epoch
tailscale serve --bg --https=9443 /var/lib/agent-health
```

- **HTTP over the tailnet, never SSH.** Minting cross-host root between two credential-bearing
  VPSes to satisfy a health check is a far worse trade than serving one read-only file. Serve
  (not Funnel) is tailnet-only by construction.
- **Observations only — never actions.** The watcher never restarts, edits config, or SSHes. Both
  agents *and* Claude Code were each confidently wrong about a diagnosis in the week this was
  built; the dumb layers exist to check the smart ones, not to be given hands.
- **Check staleness first, and treat it as the most important signal.** A reachable-but-frozen
  document keeps serving the last good file forever, so *"reachable and says healthy" can
  describe a host that died an hour ago.* Publish `generated_epoch` and enforce a limit well
  above the publish interval.
- The publisher runs as **root, independent of the agent**, so the document still updates — and
  still reports `agent_active: false` — when the agent is down. That is the entire value.

### Host differences that are real, not cosmetic

Verify each rather than copying the sibling host's playbook:

- **Firewall.** A ufw host needs a rule scoped to the `tailscale0` interface — a bare
  `ufw allow 9443` opens the port on a public VPS interface. A host whose nftables input chain
  already admits Serve ports needs **no rule at all**; confirm by reaching an existing Serve port
  from the peer rather than adding a redundant rule that implies a dependency that isn't real.
- **Credentials.** One host may source a root-owned env file, another inject via a secrets-broker
  wrapper in `ExecStart`. Write the shared script to **prefer the environment and only fall back
  to the file**, and to refuse to run rather than proceed to a silent unauthenticated send.

## Bugs this pattern is prone to — all found live, none by a passing run

- **`pipefail` + an unguarded zero-match `grep`.** A canary that has never delivered is the
  normal zero-match case; the grep returns 1, a trailing `|| echo 0` fires *in addition to*
  awk's output, and the count becomes the two-line string `"0\n0"`, which explodes the next
  numeric comparison. **The guard must sit immediately after the specific grep that can
  legitimately match nothing** — `{ grep ... || true; }` — not at the end of the pipeline, which
  only catches the last command. Add a `[[ "$N" =~ ^[0-9]+$ ]] || N=0` assertion as a backstop.
- **A discarded `curl` result makes a failed alert silent** — a dead monitor that still looks
  alive, the exact failure class the monitor exists to catch. Verify `"ok":true` and log loudly
  on failure. **Never echo the response body**: an error can quote back the request URL, which
  contains the bot token. Extract only `"error_code":[0-9]+`.
- **False-clean guard is mandatory, especially here.** This check's entire signal is an
  *absence*, so "log unreadable / rotated / empty" is trivially confused with "the canary stopped
  delivering." Assert a minimum line count and fail loudly instead of reporting a false miss.
  Same family as `journalctl -u <unit>` returning a clean "No entries" for a non-root user.
- **`mktemp` is mode 600 and `mv` preserves it.** A published health file built via
  `mktemp` → `mv` silently becomes root-only-readable. Copy through `cat` and `chmod` explicitly.
- **Don't copy a sibling script's patterns without checking the runtime.** `Traceback` is right
  for Python and matches *nothing* on Node, which would report a permanently reassuring
  `exceptions=0`.

## Test the paths that must fail, not just the happy one

The original tracker's defect was invisible precisely because nobody tested the not-firing case.
Every one of these was staged deliberately and confirmed:

- canary detects a real delivery and **stays silent**
- canary **alerts on absence**, suppresses misses 2–3, re-alerts on the 4th, sends recovery
- peer-watch reports **unreachable** (point it at a dead port)
- peer-watch reports **stale** (rewind `generated_epoch` by an hour)
- peer-watch reports **agent inactive** (flip `agent_active` to false)
- a full healthy cycle produces **no Telegram traffic at all**

Give every notification script a `--dry-run` that prints instead of sending and writes no state,
so testing never pages the human. Reset any state file the tests dirtied, or the next real run
sends a spurious recovery notice.

**Measure over a window long enough to mean something.** One change looked clean at 7 minutes and
was a 3× regression at 12.

## Verification methodology, which is where most of the real errors came from

Every wrong conclusion in this build came from probing the system the wrong way, not from bad
code. Three separate false diagnoses in one session traced to a single root cause: **a CLI
invoked from a plain SSH shell does not have the credentials systemd injects into the running
service.** It surfaces as `401` from one subcommand and `Not Found` from another — the second
looks like a missing chat rather than a missing token, which is how it fools you.

Rules that follow:

- Verify through the **real execution path** — trigger via the service, or temporarily reschedule
  the job and read the log, then restore. Never a manual CLI run.
- When a probe fails, run a **control** against something known-good before concluding anything
  about the target. `send` to a chat with confirmed deliveries; if that fails too, the probe is
  broken, not the target.
- `journalctl -u <unit>` as a **non-root** user returns a clean "No entries" — not an error — so
  an unprivileged read is indistinguishable from a quiet service, and any derived count is a
  confident zero. Check `whoami`; a habit formed on a host where you log in as root breaks
  silently on one where you don't.
- A **glob** in a remote command expands in the *calling* user's shell — `ls /root/x/agent-*.sh`
  as a non-root user reports "No such file" for files that exist. Not a missing file; a
  permissions artifact.
- Independently verify what the agent tells you, then **say so plainly when it was right**. It
  usually is, and confirming builds the shared record that makes the exceptions legible.
