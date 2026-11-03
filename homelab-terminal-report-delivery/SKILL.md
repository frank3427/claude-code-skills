---
name: homelab-terminal-report-delivery
description: This skill should be used when building or modifying a homelab automation that needs to deliver a status report via email + Telegram + (optionally) a GitHub-hosted markdown archive — the shared report system (resilience-ledger-styled HTML as of 2026-08-17, previously Kanagawa-Wave-terminal-styled) already used by the weekly housekeeping sweep, the nightly backup summary, and the R2/B2 offsite sync emails. Also covers choosing between a minimal-link Telegram ping and a rich bulleted Telegram-as-primary-channel with conditional email (added 2026-08-20 to cut Postmark's 100/month free-tier quota). Trigger phrases include "homelab status report", "ledger styled email", "kanagawa wave email", "render-terminal-report", "homelab-report-lib", "consolidate emails into a digest", "add a new homelab report automation", "resilience-ledger design system", "claude_code_prompts schema", "push report to obsidian-vault", "deploy report script to a host other than ansible-ctrl", "raw ISO timestamp in email/telegram", "human readable local time in report", "send_rich_telegram_report", "postmark quota", "postmark free tier limit", "telegram primary channel", "bulleted telegram summary", "only email on warn or fail".
---

# Homelab terminal-report delivery system

A shared, reusable pattern for any homelab automation that needs to tell Will "here's the status"
via email, a Telegram ping, and (optionally) a durable GitHub-hosted record — instead of each
automation inventing its own formatting and delivery plumbing. Built 2026-07-18/19 for the weekly
housekeeping sweep, extended 2026-07-19 for the nightly backup summary and 2026-07-20 for the R2
offsite sync's email; reach for it again before writing a new bespoke report/notification flow.
The first two run from `ansible-ctrl`; the R2 sync report runs locally on `pbs` instead (see
"Deploying to a host other than ansible-ctrl" below) — the pattern isn't tied to any one host.

## What it looks like

**Updated 2026-08-17**: the email HTML is now styled with the **resilience-ledger design
system** (warm-paper/dark-ink "systems report" look — see
`~/Desktop/resilience-ledger-design-system/` and `project_dfw_vultr_buildout` memory for the
full design-token detail), not the earlier Kanagawa Wave terminal-window chrome. This was a
**visual-only swap of `render_html()`** in `render-terminal-report.py` — the JSON schema below,
the CLI interface, `render_markdown()`, and every calling orchestrator are all byte-for-byte
unchanged (verified via diff before/after deploying). A colored callout box carries the BLUF
(`OK`/`WARN`/`FAIL` label + tinted background, not emoji), each category renders as a list of
status-pill + headline + optional detail rows, and a "Follow-ups" section at the bottom has one
numbered, pasteable Claude Code prompt per actionable issue in a monospace card. Light mode is
now the default with a proper dark media-query companion (the old version was dark-only).
Subject line reads `❯ <report-name> MM/DD/YY`, mirroring the email's own opening prompt line
(an earlier version read `❯ <report-name> --date MM/DD/YY` — the `--date` was dropped
2026-07-20 as pure noise, Will found it confusing rather than informative; don't reintroduce
it) — that convention lives in each orchestrator script, not in the renderer, and was
deliberately left untouched by the 2026-08-17 restyle. **Any timestamp shown to Will (BLUF
text, Telegram, follow-up prompts) must be a human-readable local time**
(`TZ='America/Chicago' date -d "@$EPOCH" '+%-I:%M %p %Z'` → `6:27 AM CDT`), never a raw UTC
ISO-8601 string (`2026-07-20T11:13:56Z`) — Will explicitly called this out as unreadable when
the R2 sync report first shipped with it. Keep the epoch/ISO value around internally for
duration math or log-grepping if needed, but never surface it directly.

**Telegram: minimal-link vs. rich-primary, pick one per report (updated 2026-08-20).**
Two established patterns now, not one:
- **Minimal-link** (weekly housekeeping, and the default for anything new): just the subject
  line + the GitHub archive link (`send_telegram`), full detail lives in the email. Right fit
  when the report is low-frequency and/or dense enough that email is genuinely the primary
  read — the whole point is not duplicating a big report into a phone notification.
- **Rich-primary** (`nightly-backups`, `r2-offsite-backup`, `b2-offsite-backup`, all switched
  2026-08-20): `send_rich_telegram_report <json_file> <subject> <report_url>` (new in the shared
  lib) builds a scannable message straight from the JSON — see "The Four-Line Standard" below for
  the exact shape (this replaced an earlier bullet-per-category-item dump 2026-08-29, which broke
  the standard's own ≤4-section rule on any report with more than a couple of items). Paired with
  making Postmark **conditional** — only call `send_postmark_email` when `overall_status != "ok"` —
  since this was driven by Postmark's 100/month free-tier cap (see
  `project_postmark_telegram_quota_shift` memory for the real numbers that motivated it). Right
  fit for daily-cadence, usually-`ok`, no-action-needed-on-a-good-day reports. On `warn`/`fail`
  both channels still fire, same as before this change. Don't reach for rich-primary by default
  — it only makes sense once Postmark volume (or phone-notification noise) is an actual
  problem; minimal-link is still the right starting point for a brand-new report.

## The Four-Line Standard (2026-08-29)

Every Telegram message sent through this system — `send_rich_telegram_report` and
`send_telegram_failure` alike — follows one shape: **one status glyph from a closed set (✅ ok/
recovered, ⚠️ warn/degraded, 🔴 fail/needs attention, 🔧 auto-fixed), then up to 3 more optional
sections (impact, action — pick one, never both — link), each separated by a blank line**, never
packed onto consecutive lines. Hard bans in the body: raw HTTP codes/JSON/stack traces/systemd
unit lines/ZFS-or-bucket paths (say the plain-English equivalent), ISO-8601 timestamps, raw
comma-joined lists past two entries (cap at 2 + "+N more" — see `backup-status-checks.sh`'s
`NOT_OK_NAMES` construction for the pattern, and use `awk`, never `paste -sd`, to join them —
`paste -d` only honors the first character of a multi-char delimiter per join position, the exact
same gotcha as bash `IFS`, confirmed live: it silently produced `"immich,pbs-vm-snapshot"` with no
space). Target ≤4 sections / ~400 characters total — if it doesn't fit, it belongs in the linked
report, not the message. This grew out of a fleet-wide audit that found the pre-2026-08-29
`send_rich_telegram_report` (a bullet per category item, no length cap) and several ad-hoc scripts
outside this system violating all of the above; this skill's schema/functions are the standard's
canonical implementation going forward — any *new* Telegram-sending code in this environment
should match this shape even if it doesn't use `render-terminal-report.py`/this JSON schema at
all.

`send_rich_telegram_report` gets its impact/action line from a new optional `telegram_summary`
JSON field (see schema below) — **not** derived from `bluf` via truncation, since `bluf` is
allowed to carry raw paths/bucket names/technical detail for the email/vault copy of the same
report, and no generic string transform can reliably strip an embedded bucket name out of prose.
If a producer omits `telegram_summary`, the function falls back to a generic, name-free count
synthesized from `categories[].items[].status` (`"All N checks ok."` / `"N of M checks need
attention."`) rather than parsing any per-item `headline`/`detail` text, which isn't guaranteed
Telegram-safe either. **Any new rich-primary automation should populate `telegram_summary`
explicitly** rather than relying on the fallback, the same way `backup-status-checks.sh` and the
two sync `.j2` templates do.

`send_telegram_failure <subject> <detail> [<link_or_path>]` is for orchestrator-internal failure
paths that fire before a report JSON exists (so `send_rich_telegram_report` can't be used yet) —
always the fail glyph, same blank-line shape. Every ad-hoc raw-string `send_telegram "🔴 ..."` call
across `weekly-housekeeping-run.sh`/`backup-summary-run.sh` was converted to this 2026-08-29;
reach for it instead of hand-building a failure string in any new orchestrator.

A subject passed into `send_rich_telegram_report` should be **plain** — no `❯`/`[FAILED]`
decoration — since the function prepends its own status glyph now and a decorated subject just
doubles up with it (e.g. `✅ ❯ nightly-backups ...`). That decoration is still fine, and expected,
for the separate Postmark email subject line (`send_postmark_email` doesn't render a glyph the
same way) — see `backup-summary-run.sh`'s `SUBJECT` vs. `EMAIL_SUBJECT` split for the pattern if
a report needs both.

**Using the standard without a JSON report object.** Not every Telegram-sending script has (or
needs) a `render-terminal-report.py`-shaped report — a simple event/status notifier (a watchdog,
a fail2ban hook, a health-check poller) just calls `send_telegram "$(echo "..." | html_escape)"`
directly with a hand-built glyph + blank-line-separated message, or `send_telegram_failure` for
its failure paths, same as above — no `overall_status`/`categories`/`telegram_summary` involved.
This is how Round 2 (2026-08-29) migrated `dns-symlink-watchdog`, `boot-watchdog`,
`post-reboot-bounce`, `pbs-vm-os-disk-snapshot`, `pihole-dot-failover`, `restic-backup`,
`openclaw-model-corruption-watchdog`, and the fail2ban ban/unban notifier — all previously
hand-rolled `curl`/local-`send_telegram()` clones, none of them JSON-report producers. Existing
cooldown/debounce/state-machine logic in a script like this is unrelated to the standard and
should stay untouched — only the message text and glyph choice change.

**Deploying the lib to a host that isn't `ansible-ctrl`/`pbs`.** Per-consumer `/opt/<name>/lib/`
(mirroring the R2/B2 precedent), not a shared `/root/bin/lib/` — that path is a special case
unique to `ansible-ctrl` as the control node. Round 2 added first-time lib deploys to `pve`
(`/opt/boot-watchdog/lib/`, `/opt/pbs-vm-os-disk-snapshot/lib/`) and `pihole`
(`/opt/pihole-dot-failover/lib/`) this way. **A separate git repo with no automated sync to
`homelab-ansible`** (e.g. `dfw-ansible` on host `dfw`) needs the lib file copied in as a second,
manually-maintained copy (`playbooks/scripts/lib/homelab-report-lib.sh` there) — a future change
to the standard has to be applied in both repos by hand until/unless that gets automated.

## The pieces

Versioned in `homelab-ansible/scripts/`; deployed to `ansible-ctrl:/root/bin/` for automations
that run from `ansible-ctrl` itself, or to wherever the automation actually runs otherwise (see
"Deploying to a host other than ansible-ctrl" below).

- **`render-terminal-report.py`** — turns a JSON report object into either the HTML email
  (`--format html`, default) or a plain markdown archive copy (`--format md`). Both formats read
  the exact same JSON, so nothing about the visual design can drift between what gets emailed and
  what gets archived. Takes `--report-name <name>` (e.g. `weekly-housekeeping`, `nightly-backups`)
  which becomes both the titlebar suffix and the `❯ <name> ...` prompt line — this is the
  one parameter that makes the script reusable across automations rather than forked per use.
  Usage: `render-terminal-report.py <json_file> <date YYYY-MM-DD> <report_url> --format html|md
  --report-name NAME` (`report_url` may be `""` when rendering markdown before the GitHub push
  that produces it, **or when this report has no GitHub archive at all** — the "# full report →"
  footer line is omitted entirely when `report_url` is empty, rather than showing a misleading
  fallback string; don't reintroduce placeholder text there).
- **`lib/homelab-report-lib.sh`** — shared bash functions, sourced by every orchestrator script:
  `send_telegram`, `html_escape` (Telegram `parse_mode=HTML` needs `&`/`<`/`>` escaped),
  `send_rich_telegram_report <json_file> <subject> <report_url>` (builds the rich-primary message
  per the Four-Line Standard above from the JSON's `telegram_summary`/`overall_status`; see that
  section for the shape and when to use it vs. plain `send_telegram`), `send_telegram_failure
  <subject> <detail> [<link>]` (added 2026-08-29 — for pre-JSON orchestrator failure paths, see
  the Four-Line Standard section), `send_postmark_email` (builds the `HtmlBody`+`TextBody` JSON
  payload via `jq`, posts to Postmark's API), and `push_report_to_vault <local_md_file> <slug.md>
  <commit_message>` (commits+pushes into the `obsidian-vault` repo root, prints the GitHub blob
  URL to stdout, or an empty string on failure — treat empty as "no link available," never as a
  hard error, matching the report-only never-block-a-delivery-channel posture).
  **Deployed to three destinations from this one canonical source** — `ansible-ctrl:/root/bin/lib/`
  via `homelab-report-timers.yml`, plus `pbs:/opt/r2-backup/lib/` and `pbs:/opt/b2-backup/lib/` via
  `r2-backup-install.yml`/`b2-backup-install.yml`. The `ansible-ctrl` deploy task didn't actually
  exist until 2026-08-29 (the copy sitting there matched the repo by coincidence, not by any
  playbook managing it) — if a future change to this file doesn't seem to be taking effect on
  `weekly-housekeeping-run.sh`/`backup-summary-run.sh`, confirm the deploy task in
  `homelab-report-timers.yml` is still there before assuming something else is wrong.
- **The JSON schema** every report is built from:
  ```json
  {
    "overall_status": "ok" | "warn" | "fail",
    "bluf": "2-4 short paragraphs separated by a blank line (\n\n) -- each one scannable idea, not one dense block. Allowed to carry raw paths/bucket names/technical detail -- this is the email/vault copy, not Telegram.",
    "telegram_summary": "OPTIONAL, rich-primary reports only. One Telegram-safe sentence for send_rich_telegram_report's impact/action line -- no raw paths/bucket names/host lists past two. Producer-owned, not derived from bluf. See 'The Four-Line Standard' above.",
    "claude_code_prompts": [
      {"title": "short label, e.g. 'Investigate pbs SSH host-key change'",
       "prompt": "a TIGHT, self-contained prompt: the specific finding (host/VMID/file/error) and the decision to make -- do NOT tell it to read CLAUDE.md first or restate hard constraints/confirm-before-acting, see below"}
    ],
    "categories": [
      {"name": "Category Name",
       "items": [{"status": "ok"|"warn"|"fail", "headline": "short headline", "detail": "one line, optional `code` spans"}]}
    ]
  }
  ```
  `claude_code_prompts` is one entry **per distinct actionable issue**, not one combined prompt —
  the whole point is letting Will paste them into separate Claude Code sessions one at a time.
  Empty array renders no Follow-ups section at all.
- **Don't repeat standing-context boilerplate inside every prompt** (fixed 2026-08-30, was
  costing real reading time at 12 prompts/week): telling each prompt to "read CLAUDE.md first"
  and "confirm before risky actions" is redundant — any Claude Code session opened in the
  project directory loads its `CLAUDE.md` (hard constraints included) automatically, and
  "confirm before risky/destructive actions" is already a standing constraint there. Say it
  **once**, as a static line rendered above the whole Follow-ups section by
  `render-terminal-report.py` itself (zero LLM cost, always consistent — see
  `render_html()`/`render_markdown()`), not per-prompt by the judgment-generation instructions.
  Each individual prompt should carry only what's actually specific to that finding.
- **The weekly housekeeping sweep additionally cross-run-diffs its checks JSON** (own state
  file, `first_seen`/`recurring`/`status_changed` per item, `resolved_since_last_run` array —
  see [[project_weekly_housekeeping_sweep]] and `weekly-housekeeping-run.sh`) **before** handing
  it to the judgment step, so a finding that's unchanged since last run gets folded into its
  `categories[]` item as a compact "(recurring since \<date\>, still pending)" note instead of
  generating a fresh full `claude_code_prompts[]` entry every week. This state-diff step and its
  metadata fields are internal to the weekly sweep's own checks-JSON input — not part of this
  shared `claude_code_prompts`/`categories` output schema itself — but the pattern (don't
  re-litigate an already-known, unchanged finding at full ceremony every run) is reusable by any
  other automation built on this skill that runs frequently enough for the same problem to
  recur.

## The delivery path has to be able to fail (2026-09-06)

For most of this system's life `send_telegram()` could not report its own failure:

```bash
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" -d parse_mode="HTML" \
  --data-urlencode text="$text" >/dev/null
```

No `-f`, no result check. **`curl` exits 0 on an HTTP 401**, so this returned success for a revoked
bot credential, a wrong chat id, or the bot being removed from the chat — across all fifteen
message types, every caller believing it had notified.

What made it survivable indefinitely is the property this whole skill is built around: **the
healthy state of these alerts is silence.** `daily-drift-check` pings only on new-or-worsened
findings; the sweep only on warn/fail. So a permanently dead channel and a good week produce the
identical observation, and nothing in the fleet could ever have surfaced the difference.

**Both halves of the fix are load-bearing.**

1. **The sender checks its own result.** HTTP code **and** the body's own `ok` field — Telegram
   answers `200` with `{"ok":false}`, so either test alone is insufficient. Every attempt is
   appended to `/root/state/telegram-sends.log`, and the function returns non-zero on failure.
   **Never log the URL or the response body**: the URL carries the credential and the body echoes
   the message. Before tightening the return value, confirm the callers' shell flags — all twelve
   here use `set -uo pipefail` without `-e`, so a failed send cannot abort a report mid-run.

2. **The channel gets a scheduled reason to speak.** `telegram-path-check.sh`, daily at 05:25
   America/Chicago, five minutes ahead of `daily-drift-check` so the path is known good before the
   day's alerting. It validates the credential (`getMe`) and the destination (`getChat`) rather
   than sending anything, so it is **zero-noise** — it never messages Will when healthy. It alarms
   **by email**, deliberately: *a channel cannot report its own death through itself.*

**Testing this needs a failing control, because the broken code passes every happy path.** The
suite that matters is four arms, not one:

```
send_telegram, bogus credential -> http=401 ok=false, returns non-zero   PASS
send_telegram, real credential  -> delivered, returns zero               PASS
path check, healthy             -> silent, exit 0, no email              PASS
path check, bogus credential    -> both checks fail, would email, exit 1 PASS
```

The path check takes `--dry-run` so the failing arm can be exercised without mailing Will.

**Generalises past Telegram.** Any delivery whose healthy state is silence — a webhook, a push API,
a health POST — needs the same two properties: a sender that can distinguish refusal from success,
and a scheduled proof of life that alarms somewhere else.

**Two follow-ups found 2026-09-12:**
- **A host can run a stale copy of the shared lib.** Pi-hole's failover watcher had a pre-9/06 copy of
  the lib, so its pages were still unchecked and unlogged months after the fix. Any host that sources
  the lib needs the lib *in its own playbook's deploy list*. Grep a host's deployed copy for the
  result-check before trusting its alerts.
- **Bound the send itself:** `curl --connect-timeout 10 --max-time 20-30` on Telegram, Postmark and
  webhook calls. A send with no timeout against a server that accepts and never replies hangs the
  whole report job. Verified: rc 28 at 30 s with the flags, still hanging at 45 s without.

**Verify sends without messaging anyone:** put a stub `curl` first on `PATH` that records each request
(URL with the token redacted, and the body) and returns a canned response. Include a failing canned
response to prove the non-zero path. The real send functions then run unchanged, which is stronger
than an `if --dry-run; then echo` branch that skips them. **Install the stub only at the delivery
step.** One dry run had it active during the checks too, so every HTTP health check "passed" against
the stub.

## Wiring up a new automation

1. Write (or reuse) a checks script that gathers raw data and decide: does turning that into the
   JSON above need **judgment** (noisy/ambiguous signals that need triage against project
   history — reach for a locked-down headless Claude Code step, see
   [[feedback_claude_cli_disallowedtools_not_allowedtools]] and the weekly housekeeping
   orchestrator for the `--allowedTools`/`--disallowedTools` pattern) or is it **deterministic**
   (a clear pass/fail fact, like "did this vzdump task exit OK" — just build the JSON directly
   with `jq`, no LLM, no API cost, no non-determinism). The nightly backup summary is the
   deterministic template to copy; the weekly sweep is the judgment-step template to copy.
2. Write an orchestrator script (`source` the lib, run the checks, build/receive the JSON,
   validate it with `jq empty`, render markdown → push to vault → get URL → render HTML with that
   URL → send Telegram (minimal `send_telegram` + link, or rich `send_rich_telegram_report` —
   see "Telegram: minimal-link vs. rich-primary" above) → send Postmark (`HtmlBody`+`TextBody`,
   subject `❯ <name> MM/DD/YY`, unconditionally for minimal-link reports or gated on
   `overall_status != "ok"` for rich-primary ones)). `set -uo pipefail`, **not** `-e` — a failed
   delivery channel must not block the others. **Not every report needs the vault push** — the R2 offsite
   sync report (2026-07-20) skips `push_report_to_vault` entirely and renders HTML straight from
   the JSON with `report_url=""`; a nightly per-run email isn't worth a GitHub commit every night
   the way the weekly/daily digests are. Skip steps that don't earn their keep for a given report
   rather than including vault-push by default.
3. Deploy: versioned copy in `homelab-ansible/scripts/`, live copy in `ansible-ctrl:/root/bin/`
   (or elsewhere — see "Deploying to a host other than ansible-ctrl" below).
   An orchestrator that embeds a headless-Claude `--disallowedTools` invocation stays
   **uncommitted**, matching the weekly wrapper's convention; one with no LLM step (like the
   backup summary) is fine to version normally.
4. **Manage the script deployment and the systemd `oneshot` service + `.timer` via the shared
   `homelab-ansible/playbooks/homelab-report-timers.yml` playbook — add a new task block there,
   don't hand-create units on `ansible-ctrl` directly.** Both existing automations
   (weekly-housekeeping, nightly-backup-summary) had their units hand-created initially and it
   took a dedicated fix 2026-07-19 to bring them under Ansible (see
   [[project_nightly_backup_summary]] / [[project_weekly_housekeeping_sweep]] for the incident) —
   a hand-created unit is invisible to a rebuilt `ansible-ctrl` and silently doesn't come back.
   An orchestrator kept uncommitted (the `--disallowedTools` case) still gets its **unit**
   templated by the playbook — only the script copy step is skipped for that one file, referencing
   it in place. `OnCalendar=... America/Chicago` — the host's system timezone is UTC, so the zone
   must be explicit in the calendar expression or it fires at the wrong local hour. Re-run the
   playbook (or `--check --diff` it first) after any future schedule change instead of editing the
   live unit over SSH. **`render-terminal-report.py` itself must be in that playbook's copy
   loop too**, not just each automation's own script — it was missing from
   `homelab-report-timers.yml` from 2026-07-18 until a 2026-07-20 fix, meaning
   `ansible-ctrl:/root/bin/render-terminal-report.py` had been hand-deployed outside Ansible the
   whole time (the exact "invisible to a rebuilt host" gap this step exists to prevent, just on
   the shared renderer instead of a per-automation script). Check it's actually in the loop, not
   just present on disk, before trusting a fresh `ansible-ctrl` rebuild would restore it.
5. If pushing to a **different** GitHub repo than `obsidian-vault`, mint a new dedicated deploy
   key first — GitHub deploy keys are strictly one-key-per-repo (see the homelab CLAUDE.md
   gotcha); reusing `obsidian-vault`'s existing key/alias is fine if the target repo is the same.

## Deploying to a host other than ansible-ctrl

Not every report-generating automation runs from `ansible-ctrl` — the R2 offsite sync report
(2026-07-20) runs from `sync.sh` on `pbs` itself, since that's where the actual `rclone sync`
happens. In that case, deploy `render-terminal-report.py` + `lib/homelab-report-lib.sh` alongside
the automation's own script (e.g. `/opt/r2-backup/render-terminal-report.py` and
`/opt/r2-backup/lib/homelab-report-lib.sh`, via a `copy` task in that automation's own install
playbook — `r2-backup-install.yml` — reading `src: "{{ playbook_dir }}/../scripts/{{ item }}"`
the same way `homelab-report-timers.yml` does for `ansible-ctrl`) rather than trying to reach back
into `ansible-ctrl:/root/bin/` over SSH at runtime. `homelab-report-lib.sh`'s `VAULT_DIR`/
`push_report_to_vault` still default-reference `/root/obsidian-vault`, but that's harmless as
long as the caller never invokes `push_report_to_vault` — no `obsidian-vault` clone or `git` is
needed on a host that only sends email + Telegram. Credentials: reuse `ansible-ctrl`'s existing
Postmark/Telegram creds via `lookup('file', ...)` in the target automation's own install
playbook (reading `ansible-ctrl`'s local files at playbook-compile time, same as how R2/Telegram
creds are already sourced there) and write them into that automation's own credentials env file
on the *target* host — don't invent a second Postmark account.

## Adding a new check to an existing automation

`categories[]` is freely extensible — a checks script isn't limited to one category. Build the
new check's status/headline/detail the same way as existing ones, add it as its own
`{name: "...", items: [...]}` entry in `categories`, and fold its status into the existing
`overall_status`/`claude_code_prompts[]` logic (fail if any category has a fail, warn if any has
a warn, generate a prompt for anything not `ok`). Verified this works end-to-end 2026-07-19 adding
a "Datastore Capacity" category to the nightly backup summary alongside its existing "Nightly
Backups" category — rendered correctly through `render-terminal-report.py` with no changes needed
to the renderer itself. Always run the checks script standalone first (`| python3 -m json.tool`)
to confirm valid JSON, then push the output through the real renderer before trusting it, rather
than assuming a new category "just works" from reading the schema.

## Dynamic discovery, not hardcoded lists

When a report should automatically pick up new services without editing the checks script (e.g.
"add every configured backup job" rather than "add Pi-hole, n8n, Homepage, Immich by name"),
query Proxmox's own live config as the source of truth — `pvesh get /cluster/backup` for vzdump
jobs, not a maintained list. **`pvesh get /nodes/<node>/tasks` defaults to the 50 most recent
tasks across *all* task types, not just the one you're filtering for** — enough unrelated node
activity between two nights' backup runs silently truncates older-but-still-relevant entries out
of the response before your `jq` filter ever sees them. Always pass an explicit `--limit` (e.g.
300) when cross-referencing task history against a job list you expect to span more than a
handful of the node's most recent tasks.

**Separately, with no `--since` at all the endpoint has no time bound either** — `--limit 300`
fixes the truncation above but a "failed task" check with only `--limit` and no `--since` will
keep matching a resolved failure from weeks or months ago for as long as it stays within the
limit window, re-flagging a fixed incident as current on every run indefinitely. Hit this for
real 2026-07-22: a `recent_vzdump_jobs` check with no `--since` kept reporting the already-fixed
2026-07-19 PBS-datastore-full failures (`homelab-incidents.md`) as current, three days after they
were resolved. Fix: pass both — `--since $(date -d '8 days ago' +%s) --limit 300 --typefilter
vzdump` — sized to the report's own cadence plus a one-day buffer (weekly report → 8 days), so a
real failure gets exactly one cycle of visibility and then genuinely ages out.

## Suppressing a per-event notification Proxmox already sends natively

If a new automation is meant to *replace* Proxmox's own built-in notifications for something
(the nightly backup summary replaces the individual per-guest vzdump emails), don't fight the
matcher system with a second decoy matcher — narrow the existing one. Notification matchers'
`match-field` supports `exact:type=<value>` (see `/usr/share/pve-docs/notifications-plain.html`
"Field Matching Rules" locally on the node for the authoritative live syntax — verify against
that file, not memory, since exact CLI flag names have shifted across PVE releases); combined
with `invert-match: true` on the matcher, `match-field exact:type=vzdump` + `invert-match`
means "match everything *except* vzdump" — the single existing catch-all matcher keeps routing
package-updates/replication/system-mail exactly as before, only vzdump stops being delivered
anywhere (an unmatched notification is simply dropped, not queued or retried).
```
pvesh set /cluster/notifications/matchers/<name> --match-field 'exact:type=vzdump' --invert-match 1 --digest <current-digest>
```
Always re-fetch the current `digest` immediately before the `set` call (concurrent-edit guard).
**Verify the suppression actually took effect**, don't trust the API call succeeding: fire a
synthetic notification of the now-excluded type through the *real* config (not a real
backup/replication job — see the `proxmox-vzdump-notifications` skill's `PVE::Notify::notify()`
technique) and confirm via the delivery target's own API (e.g. Postmark's `/messages/outbound`)
that no new message landed, while a different (still-matched) notification type still does.

## Palette

**Superseded 2026-08-17** — the email is now the resilience-ledger design system, not Kanagawa
Wave/Ghostty-derived. Hex values are hardcoded in `render-terminal-report.py`'s `LEDGER_STYLE`
block, sourced from `~/Desktop/resilience-ledger-design-system/tokens.css` on Will's Mac —
re-derive from that file (not from memory) if the palette ever needs to change, the same
"don't hand-tune hex values here" discipline as before, just pointed at a different source of
truth now. `<meta name="color-scheme" content="light dark">` + `supported-color-schemes` cover
both modes now (previously dark-only) so mail clients render the correct authored palette
either way instead of auto-inverting an unstyled body.

Original Kanagawa Wave/Ghostty derivation note, preserved for history (the live email HTML no
longer uses these values): hex values were read directly from Ghostty's own bundled theme file
(`/Applications/Ghostty.app/Contents/Resources/ghostty/themes/Kanagawa Wave` on Will's Mac).
Status colors used the *bright* ANSI variants (green `#98bb6c`, yellow `#e6c384`, red
`#e82424`); decorative-only chrome (the titlebar traffic lights) deliberately used the *dim*
variants so it was never visually confused with real status.
