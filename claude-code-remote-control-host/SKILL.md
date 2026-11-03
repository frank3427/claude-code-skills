---
name: claude-code-remote-control-host
description: This skill should be used when building, debugging, or extending a persistent Claude Code Remote Control server host — a Linux box (LXC/VM/VPS) that runs `claude remote-control` under systemd as a dedicated service user so sessions can be driven from the Claude mobile app or claude.ai/code and survive the laptop closing — including the login/auth model, per-project systemd template units, the liveness watchdog, and fleet SSH access for the service user. Built once for the homelab (`claude-code`, VMID 112, 2026-09-09). Trigger phrases include "claude remote-control", "remote control server systemd", "claude-rc@", "Remote Control requires a full-scope login token", "You must be logged in to use Remote Control", "setup-token remote control", "CLAUDE_CODE_OAUTH_TOKEN remote control", "refreshTokenExpiresAt", ".credentials.json expiresAt", "remote control journal spam", "claude remote-control --help hangs", "list-unit-files template instance", "systemctl show --value order", "git ls-remote -h HEAD", "Enable Remote Control? (y/n)", "hasTrustDialogAccepted", "workspace trust headless", "claude-rc-watchdog", "claude-code-install.yml", "claude_code_pubkey", "herdr", "agent-aware multiplexer", "terminal client for remote control", "ssh into the claude code host", "claude: command not found in a tmux pane", "RemoteCommand not found", "~/.local/bin not on PATH over ssh", "claude --continue resumed the wrong session", "same session open on phone and terminal", "herdr integration install claude".
---

# Claude Code Remote Control host

A persistent `claude remote-control` server on an always-on Linux host, one server process per
project, each a systemd template instance running as a low-privilege service user. Sessions are
created and driven from the Claude mobile app or claude.ai/code; execution and files stay on the
host. Reference build: `claude-code` (unprivileged Debian 13 LXC, VMID 112, `192.168.50.231`),
Terraform `claude-code.tf`, Ansible `claude-code-install.yml` + `claude-rc-watchdog.sh` in
`homelab-ansible`. Design record: the homelab planning repo's
`archive/claude-code-homelab-architecture-proposal.md`; state in `project_claude_code_rc_host`
memory. This skill is the durable "how" and every trap hit building it.

## 1. Facts that shape the design (verified against the docs and live, 2026-09-09)

- **Auth is a browser login, full stop.** Remote Control needs the full-scope claude.ai
  `/login`. A `claude setup-token` / `CLAUDE_CODE_OAUTH_TOKEN` credential is refused by design
  ("can only make model requests"); `ANTHROPIC_API_KEY` disqualifies it too. So a headless host
  needs **one interactive step by the account owner**, as the service user, over SSH: `claude`,
  `/login` (paste the code the browser shows), finish onboarding, `/exit`. Plan for it; don't
  try to script around it.
- **Two more one-time prompts** exist: the workspace-trust dialog per project directory, and
  "Enable Remote Control? (y/n)" on the first `claude remote-control`. Trust can be pre-seeded
  (§3); the RC confirmation is answered once interactively (`claude remote-control` once, `y`,
  Ctrl+C) and then remembered.
- **The login expires.** In `~/.claude/.credentials.json`, `claudeAiOauth.expiresAt` is the
  ~8-hour *access token* (auto-refreshed while a server runs); `claudeAiOauth.refreshTokenExpiresAt`
  is the real login lifetime (~28 days observed). Alert on the second. A server that outlives
  the login stops making progress silently.
- **The process runs fine without a TTY** — probed: it gets as far as the login check headless.
  Under systemd it works with no pty wrapper.
- **`claude remote-control --help` hangs on a signed-in machine**: it checks eligibility and
  starts the server rather than printing help. Take the flag list from the docs page
  (`https://code.claude.com/docs/en/remote-control`). Flags go *after* `remote-control`;
  the useful ones are `--name`, `--capacity N` (default 32), `--spawn same-dir|worktree|session`,
  `--permission-mode`.
- **Outbound-only.** Registers with the Anthropic API and polls; no inbound port, no Tailscale
  Serve endpoint to create — a documented exception to a "Serve is the standard access pattern"
  rule, not a deviation. Direct `api.anthropic.com` only (no `ANTHROPIC_BASE_URL`, no Bedrock).
- **Don't set** `DISABLE_TELEMETRY`, `DO_NOT_TRACK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`,
  or `DISABLE_GROWTHBOOK` for the service user — each silently disqualifies Remote Control.
- **Restarting the unit resumes its relay sessions** (within ~4h of the stop). Verified: a
  restart brought the same session back on the phone. Crashed *sessions* (not the server) are
  re-served when a device sends them a message.
- No crash auto-recovery of the server itself, and the server **exits after ~10 minutes of lost
  API reachability**. systemd `Restart=always` covers both — **but not past the start limit.**
  With `StartLimitBurst=6` in 30 min at `RestartSec=30s`, any network outage longer than ~3.5
  min leaves every server `failed` for good: after the 2026-09-27 UniFi cutover all three sat
  dead for 20 h. Pair the limit with a recovery timer (below). Don't reach for
  `RestartSteps=`/`RestartMaxDelaySec=` backoff instead: its counter (`NRestarts`) resets only on
  a manual start, so weeks of routine relay drops would push every restart to the maximum delay.

## 2. Host shape

- Dedicated service user (`claude`, `/home/claude`, bash shell). Native installer run *as that
  user* (`curl -fsSL https://claude.ai/install.sh | bash`, `creates: ~/.local/bin/claude`).
  Debian 13 LXC template has **no `sudo`** — install it before any `become_user` task.
- `~/projects/<name>` per project; `git clone` needs the service user's own SSH key accepted on
  GitHub (account key = every repo; deploy keys are one-key-per-repo, so that's N keypairs +
  `Host` aliases). Pin GitHub's host key and **assert the scanned fingerprint against the
  published one** (`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`) before writing it.
- Service user's global `~/.claude/CLAUDE.md` carries the session-hygiene rules (resume not
  restart, `/compact` at breakpoints, `/rename`, the env-var bans above) so they re-establish
  every session.
- `~/.ssh/config` for the service user: right login per fleet host, `StrictHostKeyChecking
  accept-new` so a first connection never stalls a phone-driven session.

## 3. Per-project systemd template unit

```ini
[Unit]
Description=Claude Code Remote Control server for project %i
After=network-online.target tailscaled.service systemd-resolved.service
Wants=network-online.target
ConditionPathExists=/home/claude/.claude/.credentials.json
ConditionPathIsDirectory=/home/claude/projects/%i
StartLimitIntervalSec=30min
StartLimitBurst=6

[Service]
User=claude
Group=claude
WorkingDirectory=/home/claude/projects/%i
Environment=HOME=/home/claude
Environment=PATH=/home/claude/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=LANG=en_US.UTF-8
ExecStart=/home/claude/.local/bin/claude remote-control --name %i --capacity 4
StandardOutput=null
StandardError=journal
Restart=always
RestartSec=30s
KillMode=mixed
TimeoutStopSec=30s

[Install]
WantedBy=multi-user.target
```

Recovery for instances that hit the start limit — `claude-rc-recover.service` (oneshot) +
`.timer` (`OnBootSec=10min`, `OnUnitActiveSec=15min`), in `homelab-ansible`'s
`claude-code-install.yml`:

```sh
for u in $(systemctl list-units "claude-rc@*" --state=failed --plain --no-legend | cut -d" " -f1); do
  systemctl is-enabled --quiet "$u" || continue   # a unit stopped by hand is inactive, not failed
  systemctl reset-failed "$u"; systemctl start --no-block "$u"
done
```

A broken state (expired login) then costs one burst of ≤6 attempts per 15 min, not a 30 s loop,
and a transient outage heals within 15 min of the network returning. The watchdog on
`ansible-ctrl` re-alerts a persisting failure every 6 h, so a dead server can't sit unnoticed.

- **`ConditionPathExists` on the login file** keeps instances *inactive* (a skip, not failed,
  not restart-looping) until the owner's login exists. Enable them in Ansible without
  `state: started`; a separate task starts them `when` the login file exists.
- **Do NOT gate on `projects/%i/.git`.** A server over an empty directory is still a usable
  session; gating on the checkout took a live server down mid-use. Report "no checkout yet"
  from the watchdog instead.
- **`StandardOutput=null` is load-bearing.** With stdout not a TTY the status panel redraws
  continuously — measured ~5 journal lines/second, ~400k/day. Errors (including the
  login-expired message) go to stderr and stay in the journal.
- Pre-seed workspace trust so a TTY-less server can start in each directory: set
  `projects["<abs dir>"].hasTrustDialogAccepted = true` in `~/.claude.json` (a small Python
  script that edits only that key, prints `changed`/`unchanged`). Ansible `changed_when` must
  test the last line *exactly* — `'changed' in stdout` also matches "unchanged".
- Default permission mode is the human backstop: every command a phone-driven session runs
  prompts on the phone. Enable **Push when actions required** in `/config` so the prompt is a
  notification. Changing `--permission-mode` is a deliberate playbook edit, never a session's.

## 4. Watchdog (report-only, diff-alert)

`claude-rc-watchdog.sh` on the controller, every 15 min, one SSH round-trip as root:

- Enabled instances: read the **`/etc/systemd/system/multi-user.target.wants/claude-rc@*.service`
  symlinks**. Enabled template *instances* do not appear in `systemctl list-unit-files`, and
  never-started ones aren't loaded for `list-units`.
- Per unit: `systemctl show -p ActiveState -p SubState -p NRestarts` **without `--value`** and
  parse `Key=Value`. `--value` prints properties in systemd's internal order, not the requested
  order — a positional `read a s n` silently got `NRestarts` in `a`.
- Login: `jq -r .claudeAiOauth.refreshTokenExpiresAt` (only that field — never the tokens);
  fail if past, warn <3 days (matches Claude Code's own warning). `expiresAt` >2h past with a
  server running = refresh failing (warn). Also `journalctl -u 'claude-rc@*' --since '20 min
  ago' | grep -ci 'login expired\|run /login\|must be logged in'` — the most direct signal.
- Restart bursts: `NRestarts` grew since the last snapshot → warn (crash or relay drop).
- Inactive unit: with no login → ok "waiting on login"; with login but no `.git` → warn "no
  checkout"; otherwise fail. Alert only on new/worsened findings; silent on recovery.

## 5. Fleet exec access for the service user (if wanted)

- Grant via the fleet baseline playbook with one `authorized_key` task, a single
  `claude_code_pubkey` var and a `present`/`absent` switch (revocation = one edit, one run).
  Target `user: "{{ ansible_user }}"` so it lands on root for the LXC/VM fleet and the admin
  account on a hand-built host.
- **Exclude the RC host itself** (`when: inventory_hostname != 'claude-code'`) — otherwise the
  unprivileged service user gets root on its own box via `ssh root@localhost`.
- Verify **positive and negative**: `sudo -u claude ssh -n -o BatchMode=yes <host> hostname`
  for granted hosts, and `Permission denied` for its own host and every excluded one. Use
  `ssh -n`; without it a loop of inner `ssh` calls silently swallows the outer script's stdout.
- Root on the controller is already root on the fleet through the controller's deploy key, so
  "controller only" narrows the *path*, not the blast radius. Say so when presenting the option.

### Hosts outside the Ansible inventory (external VPSes)

The baseline-playbook route above only reaches hosts in inventory. For an external box — a VPS
running an agent, holding real credentials — it does not apply, and root is the wrong default.
Settled 2026-09-11 for `dfw`/`hermes`:

- **Expect root SSH to be refused.** A hardened VPS runs `PermitRootLogin no`; the give-away is
  `ROOT LOGIN REFUSED FROM <ip>` in its journal, which means the key matched and *policy*
  declined — the key install was fine. Do not "fix" this by loosening a host-wide policy to
  admit one key.
- **Two accounts, not one.** `claude-admin`: sudo-capable, exists only so the RC host can run
  Ansible there. `claude-diag`: the narrow one for routine reads — **no sudoers grant at all**
  (`systemd-journal` group supplies `journalctl`, so no escalation path exists to widen later),
  `restrict,command="..."` in `authorized_keys`, and a script that allowlists every argument it
  turns into a command argument. Say plainly which one is the boundary: it is the script, not
  the sudoers line.
- **`shell: /usr/sbin/nologin` kills a forced command.** sshd runs `command="..."` *through* the
  login shell, so `nologin` yields "This account is currently not available" and a dead account.
  Use `/bin/bash` with a locked password (`password: '!'`); `restrict,command=` is what prevents
  a shell, not the shell field. This shipped-broken in rehearsal and was only caught because the
  playbook was tried against a throwaway host first — do that.
- **A verification task that only checks `rc` can pass vacuously.** `failed_when: rc != 2` went
  green against a *missing* script, because an absent file also exits 2. Assert on the refusal
  *message* too, and let verification tasks skip under `--check` rather than forcing them to run
  against a copy task that was simulated.
- Both accounts carry a `present`/`absent` var for one-flag revocation, and the `claude-admin`
  play asserts the key stays *out* of root's `authorized_keys`.
- Point the service user's `~/.ssh/config` at the right account per host and backport it into the
  install playbook — that file is Ansible-managed, so a hand edit is drift.

Related: the `ssh-exposure-audit` skill (this work surfaced a real exposure on one of the two
hosts; the account was the errand, the finding was the value).

## 6. Small traps, in the order they bit

1. `git ls-remote --exit-code -h <repo> HEAD` **never matches**: `-h` restricts to
   `refs/heads` and no branch is named HEAD. The reachability probe reported every repo
   unreachable with working auth. Drop `-h`.
2. `ansible.posix.known_hosts` reported `changed` every run with the identical key present;
   an exact-line `lineinfile` is idempotent by construction.
3. A `systemctl start` typed while still inside `sudo -iu claude` fails with
   `Failed to start …: Access denied` plus a `pkttyagent` complaint — it's the wrong user, not a
   broken unit.
4. `ssh -T git@github.com` as the service user is the definitive auth check ("Hi <user>!");
   trust it over any wrapper's verdict.
5. Restore-test coverage for this host should check the binary (`sudo -u claude
   /home/claude/.local/bin/claude --version`), not a unit: a restored clone has no network and
   the units are Condition-gated.
6. The fleet's weekly-sweep exposure arrays (`LOOPBACK_ONLY`/`LAN_OK`) have no entry for a
   host with no listener at all; that's correct, same as the Ansible controller.
7. Pinning GitHub's key from `ssh-keyscan` with `stdout_lines[0]` breaks trap 2's fix. The
   first line is sometimes keyscan's `# github.com:22 SSH-2.0-<banner>` comment, and the banner
   changes. The task then appended a new comment on most runs (9 found) and never re-ran clean,
   which would hide a real host-key change. Select the `github.com ssh-ed25519 …` line itself
   (homelab-ansible `f594983`, 2026-10-29).

## 7. Terminal access alongside Remote Control, and herdr

Remote Control has **no terminal client** — `claude --help` on 2.1.267 lists no subcommand that
attaches to an RC server. The phone and claude.ai/code drive it; a terminal reaches the same work
by **SSHing in and running `claude` there**, over the same `~/.claude` (credentials, memory repo,
CLAUDE.md, skills). Two front-ends, one session store.

- Grant the owner's workstation key directly to the **service user**, not just root
  (`claude_rc_owner_pubkey` + a `present`/`absent` switch in `claude-code-install.yml`). It is not
  a privilege increase where the same key is already on root, and it stops routine work happening
  as root. `ssh <host>` then lands with the right PATH, memory and CLAUDE.md with no `sudo -iu`.
- **Don't resume the same thread on two surfaces at once.** Settle a convention instead — the one
  that holds here is *terminal primary, phone for check-ins and permission prompts.*

### herdr

`herdr` (herdr.dev, Apache-2.0) is a tmux-like multiplexer that is **agent-aware**: every pane is
marked working / blocked / idle, so a session waiting on input is visible without cycling tabs.

- **Install it on the host the agents run on, not the laptop.** Its value is the background server
  that survives a dropped SSH connection (`prefix+q` detaches, `herdr` reattaches). A local
  install with panes SSHing out still loses the remote processes on disconnect.
- **It replaces tmux; it does not layer on it.** Both use the `ctrl+b` prefix — nesting means
  double-prefixing every keystroke.
- Installer is clean for a no-sudo service user: single static binary to `~/.local/bin`, SHA-256
  verified against a manifest, touches no shell rc and no system path. `HERDR_INSTALL_DIR`
  overrides the target.
- **Check the live version, don't trust the README** — the GitHub README said 0.4.0 while the
  installer shipped 0.9.0, and the two differ substantially (0.9.0 has `--remote`, named sessions,
  and a socket API the older write-ups don't mention).
- `herdr integration install claude` **merges** into `~/.claude/settings.json` rather than
  replacing it — existing hooks survive, but diff it anyway. It adds one `SessionStart` hook that
  guards on `HERDR_ENV`/`HERDR_SOCKET_PATH`/`HERDR_PANE_ID` and exits in ~3 ms when absent, so
  **RC sessions driven from the phone are unaffected**. Verify that rather than assuming it: a
  hook on `SessionStart` fires for every server instance on the box, not just terminal ones.
- The integration is optional — herdr detects agent state by screen analysis without it; the hook
  only adds native session restore.
- **Surviving a reboot (2026-09-30/10-01):** a client-launched `herdr` server dies with the host.
  `herdr.service` (system unit, `User=claude`, `ExecStart=herdr server`, in
  `claude-code-install.yml`) brings it back at boot and **restores saved panes headless, before any
  client attaches**, each re-running `claude --resume <id>`. Two traps: Claude Code **never persists
  trust for the home directory**, so a pane in `~` stops at the trust prompt on every restore; and
  herdr saves the cwd a pane was **created** with, so `cd` inside it changes nothing. Create the
  workspace with `herdr workspace create --cwd ~/projects/<name>`.
- `herdr --skill` prints a skill file for driving herdr's own panes/agents via its socket API.

### Two traps that only appear once someone actually uses the terminal surface

1. **`~/.local/bin` is a login-shell-only PATH entry.** `~/.profile` adds it; `~/.bashrc` does
   not, and is guarded against non-interactive shells anyway. So `claude` is **not found** in a
   herdr/tmux pane (interactive, non-login) and **not found** under `ssh` `RemoteCommand`
   (non-interactive, non-login). Fix with a guarded block in `~/.bashrc` for panes, and an
   **absolute path** for `RemoteCommand`. Verify with `bash -ic`, **never `bash -lc`** — a login
   shell is the one kind that was never in play, and checking that way certifies nothing. Put the
   fix in the playbook; a hand-edited `~/.bashrc` dies at the next rebuild.

2. **`claude --continue` will silently grab the session the Remote Control server is serving.**
   It resumes the most recent session *for that directory*, and the RC server's sessions live in
   the same store under the same user. The result is one conversation with two live front-ends —
   exactly what the coexistence convention exists to prevent. **Use `claude --resume`**, which
   lists sessions so a human chooses, and reserve `--continue` for a surface you know owns the
   thread. Observed 2026-09-11 within minutes of the terminal surface existing: the terminal
   resumed the phone's session and printed its own state summary, which read like a person asking
   a question.
