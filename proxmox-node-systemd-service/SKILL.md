---
name: proxmox-node-systemd-service
description: This skill should be used when deploying a Node.js application (Next.js, n8n, or any pnpm/npm-based app) as a native systemd service inside an unprivileged Proxmox LXC, instead of Docker — installing Node via NodeSource, running a dedicated non-root service user, building with pnpm, and exposing it only over Tailscale Serve. Also covers debugging an Ansible playbook for this pattern that never reports `changed=0` on a repeat run, a "detected dubious ownership in repository" git error, a service that's unexpectedly reachable on the plain LAN IP instead of only over Tailscale, or an app that fails to write scratch/upload files under `/tmp` despite the service showing active. Trigger phrases include "run Node app as systemd service", "NodeSource install Ansible", "pnpm build systemd", "next start binds 0.0.0.0", "HOSTNAME env var not working Next.js", "ansible git dubious ownership", "git module changed every run", "recursive chown always changed ansible", "Docker-in-LXC alternative for Node app", "ProtectSystem strict /tmp ENOENT", "PrivateTmp systemd Node app", "npm install -g version bump not applying", "creates guard blocks upgrade", "bumping n8n_version does nothing", "ansible pinned npm package upgrade".
---

# Native Node.js app as a systemd service in a Proxmox LXC

Use this instead of Docker when deploying a Node.js app (dashboard, bot, small internal tool) in
an unprivileged Proxmox LXC. It avoids the Docker-in-unprivileged-LXC cgroup quirks that pushed
other services (Immich) to a VM, and matches the "native packages, not Docker" precedent already
used for Grafana/Prometheus in this homelab. Built and verified end-to-end deploying the
Homepage dashboard (`gethomepage/homepage`, VMID 140) — every gotcha below was hit for real, not
theoretical.

## Install sequence

1. **Node.js via NodeSource, not the Debian repo** (Debian's `nodejs` package lags upstream
   releases). NodeSource's current repo format is `nodistro`-based and does *not* gate on the
   distro codename, so it works on Debian releases newer than NodeSource's own compatibility
   table lists (confirmed working on Debian 13/trixie, which isn't in their published table):

   ```yaml
   - name: Install curl, git, and gnupg
     ansible.builtin.apt:
       name: [curl, git, gnupg]
       state: present
       update_cache: true

   - name: Download NodeSource GPG key
     ansible.builtin.get_url:
       url: https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key
       dest: /tmp/nodesource-repo.gpg.key
       mode: '0644'

   - name: Dearmor NodeSource GPG key
     ansible.builtin.command: gpg --dearmor -o /usr/share/keyrings/nodesource.gpg /tmp/nodesource-repo.gpg.key
     args:
       creates: /usr/share/keyrings/nodesource.gpg

   - name: Add NodeSource apt repository (nodistro, version-agnostic)
     ansible.builtin.copy:
       content: |
         Types: deb
         URIs: https://deb.nodesource.com/node_{{ node_major }}.x
         Suites: nodistro
         Components: main
         Architectures: amd64
         Signed-By: /usr/share/keyrings/nodesource.gpg
       dest: /etc/apt/sources.list.d/nodesource.sources
       mode: '0644'
     register: nodesource_repo

   - name: Install Node.js
     ansible.builtin.apt:
       name: nodejs
       state: present
       update_cache: "{{ nodesource_repo.changed }}"
   ```

   `gnupg` is not present on a fresh Debian 13 template — omitting it fails the dearmor step with
   `[Errno 2] No such file or directory: b'gpg'`.

2. **pnpm globally via npm** — simplest reliable path, no corepack edge cases:
   ```yaml
   - name: Install pnpm globally
     ansible.builtin.command: npm install -g pnpm
     args:
       creates: /usr/bin/pnpm
   ```

3. **Dedicated non-root service user**, no login shell:
   ```yaml
   - name: Create dedicated system user
     ansible.builtin.user:
       name: "{{ app_user }}"
       system: true
       shell: /usr/sbin/nologin
       home: "/opt/{{ app_user }}"
       create_home: true
   ```

## Gotcha 1 — `ansible.builtin.git` breaks idempotency once the checkout is owned by a non-root user

The natural sequence is: clone as root → `pnpm install`/`pnpm build` as root → `chown -R` the
whole tree to the dedicated service user at the end. Problem: on every *subsequent* playbook run,
`ansible.builtin.git` still re-verifies the checkout (effectively a `git remote`/`git fetch`
check) as root, which writes to `.git/index` — flipping that one file back to root ownership
every time and making a real idempotency check (`changed=0` on repeat) impossible to achieve.

Symptom if you instead try to fix the ownership check itself: `fatal: detected dubious ownership
in repository at '/opt/.../app'` — root refusing to operate in a directory it doesn't own,
because git's post-2022 CVE mitigation applies even to root.

**Fix: don't use the `git` module for a clone that will be chowned away from root.** Use a plain
clone with a `creates:` guard so nothing ever touches the directory again after the first run:

```yaml
# Bumping the pinned version later requires manually removing the dest dir first --
# same tradeoff as the build step below (deliberate, keeps repeat runs idempotent).
- name: Clone app source at pinned release tag
  ansible.builtin.command: >
    git clone --branch {{ app_version }} --depth 1
    https://github.com/<org>/<repo>.git /opt/{{ app_user }}/app
  args:
    creates: /opt/{{ app_user }}/app/.git
```

## Gotcha 2 — build steps need `creates:` guards too, or every run "changes"

`pnpm install` and `pnpm build` are not naturally idempotent from Ansible's point of view (a raw
`command` task always reports changed). Guard both on a marker file so a clean repeat run
reports `ok`, not `changed`:

```yaml
- name: Install Node dependencies
  ansible.builtin.command: pnpm install --frozen-lockfile
  args:
    chdir: /opt/{{ app_user }}/app
    creates: /opt/{{ app_user }}/app/node_modules/.pnpm

- name: Build the app
  ansible.builtin.command: pnpm run build
  args:
    chdir: /opt/{{ app_user }}/app
    creates: /opt/{{ app_user }}/app/.next/BUILD_ID   # Next.js-specific; adjust per framework
```

Same tradeoff as Gotcha 1: a version bump needs the guard-file's directory cleared manually
before the next run will pick it up. Acceptable for a pinned-release deployment model; not a fit
for anything tracking a moving branch.

## Gotcha 3 — a recursive `ansible.builtin.file` ownership fix always reports `changed`

```yaml
# BAD -- always "changed", even when nothing needed fixing (breaks idempotency checks)
- ansible.builtin.file:
    path: /opt/{{ app_user }}
    owner: "{{ app_user }}"
    group: "{{ app_user }}"
    recurse: true
```

The `file` module can't cheaply diff an entire tree, so `recurse: true` re-applies
unconditionally every run. Check first, fix only when something's actually wrong:

```yaml
- name: Check for files not owned by the service user
  ansible.builtin.shell: >
    find /opt/{{ app_user }} \( ! -user {{ app_user }} -o ! -group {{ app_user }} \) -print -quit
  register: bad_owner
  changed_when: false

- name: Fix ownership
  ansible.builtin.command: chown -R {{ app_user }}:{{ app_user }} /opt/{{ app_user }}
  when: bad_owner.stdout != ""
```

## Gotcha 4 — Next.js (and many Node frameworks) bind `0.0.0.0` by default; `HOSTNAME` env var does nothing

`next start` binds all interfaces unless told otherwise. A `HOSTNAME` environment variable in the
systemd unit looks like it should restrict this — it doesn't; that name is just the generic Linux
"what's my hostname" variable some docs confusingly reuse. The actual control is the `-H` /
`--hostname` **CLI flag**:

```ini
# systemd unit -- WRONG (still binds 0.0.0.0, HOSTNAME env var is a no-op here)
Environment=HOSTNAME=127.0.0.1
ExecStart=/usr/bin/pnpm start

# RIGHT
ExecStart=/usr/bin/pnpm start --hostname 127.0.0.1 --port 3000
```

Note: `pnpm start -- --hostname ...` (with an explicit `--` separator) double-inserts the
separator and breaks argument parsing (`Invalid project directory provided, no such directory:
.../--hostname`) — pass the flags directly after `pnpm start` with no `--`.

If the intended access path is Tailscale Serve only (this homelab's standard pattern), binding
to `0.0.0.0` silently exposes the app on the plain LAN too — see the verification step below,
which is the only reliable way to catch this class of bug.

## Gotcha 5 — `ProtectSystem=strict` blocks `/tmp` writes; add `PrivateTmp=true` if the app writes scratch files there

`ProtectSystem=strict` (Gotcha 4's unit template, below) makes the *entire* filesystem read-only
except `ReadWritePaths=` — including the real `/tmp`, which is easy to overlook since `/tmp` is
normally writable by everyone. Any app that writes scratch/upload files to `/tmp` at startup or
per-request (seen concretely with n8n 2.x's Data Table feature, which does `mkdir
/tmp/<app>Uploads` unconditionally on boot) throws an `ENOENT` on that `mkdir` — easy to miss in
logs since the service still reports `active (running)`, it just fails the first real write.

**Fix: add `PrivateTmp=true` alongside `ProtectSystem=strict`.** This gives the service its own
isolated, writable `/tmp` namespace rather than needing to open up the real one (which would also
leak scratch files to every other service on the host):

```ini
[Service]
...
ProtectSystem=strict
PrivateTmp=true
ReadWritePaths=/opt/{{ app_user }}/app
```

Don't reach for adding `/tmp` to `ReadWritePaths=` instead — that shares the real `/tmp` across
every service on the host, which `PrivateTmp` is specifically designed to avoid.

## Gotcha 6 — a `creates:`-guarded `npm install -g <pkg>@{{ version }}` silently does NOT apply a version bump on re-run

Gotcha 2 above covers `creates:`-guarded build steps (git clone, pnpm build) where the fix is
"clear the guard file/directory, then re-run the playbook." A **globally npm-installed pinned
binary** (n8n's actual install pattern, not Homepage's git-clone pattern) is a different flavor
of the same trap, confirmed live 2026-07-31 bumping n8n 2.29.10 → 2.32.7:

```yaml
- name: Install n8n globally (pinned version)
  ansible.builtin.command: npm install -g n8n@{{ n8n_version }}
  args:
    creates: /usr/bin/n8n
```

Bumping `n8n_version` in the var and re-running the playbook does **nothing** — the `creates:`
guard sees `/usr/bin/n8n` already exists (from the *previous* version's install) and skips the
task entirely, regardless of what version the var now says. Unlike Gotcha 2's git-clone case,
there's no directory to clear here that would make sense to clear — `/usr/bin/n8n` is the
real, working binary a live service depends on.

**The underlying tool itself is NOT the problem, though** — `npm install -g <pkg>@<version>`
run directly (outside Ansible entirely) genuinely does upgrade an already-installed global
package in place; npm has no equivalent idempotency guard of its own. The fix for an in-place
version bump is therefore: bypass Ansible for the actual upgrade, then update the var afterward
purely so a future from-scratch rebuild lands on the right version:

```bash
npm install -g n8n@2.32.7        # upgrades in place, no Ansible involved
systemctl restart n8n            # the env-file-change restart handler won't fire for this,
                                  # since nothing Ansible-managed actually changed
n8n --version                    # confirm before considering it done
```

**Also note**: `npm install -g n8n@<version>` routinely exceeds a 2-minute default shell-tool
timeout (n8n's dependency tree is large) — confirmed both 2026-07-31 (2.29.10→2.32.7) and
2026-08-16 (2.34.5→2.34.6). Run it backgrounded/with a longer timeout up front rather than
letting the first attempt time out.

Then bump the `n8n_version` var in the playbook and commit — it won't retroactively apply
anything, it only affects what a fresh host build installs. Document this asymmetry in a
comment next to the `creates:` guard itself, since it's easy for a future edit to assume
(reasonably, but wrongly) that the var is the single source of truth for what's actually
running.

## systemd unit template

```ini
[Unit]
Description={{ app_description }}
After=network.target

[Service]
Type=simple
User={{ app_user }}
Group={{ app_user }}
WorkingDirectory=/opt/{{ app_user }}/app
Environment=HOMEPAGE_ALLOWED_HOSTS={{ tailscale_hostname }},localhost:3000
ExecStart=/usr/bin/pnpm start --hostname 127.0.0.1 --port 3000
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
PrivateTmp=true
ReadWritePaths=/opt/{{ app_user }}/app

[Install]
WantedBy=multi-user.target
```

`ProtectSystem=strict` makes the whole filesystem read-only except `ReadWritePaths` — needed
since the app writes its own cache/build artifacts at runtime.

## Verification: positive AND negative reachability

A clean `systemctl status` plus a working Tailscale Serve URL is not proof the LAN-binding bug
(Gotcha 4) is absent — it only proves the intended path works. Confirm the *unintended* path is
actually closed too, from a different host on the LAN:

```bash
# From another LAN host (not the LXC itself, not over Tailscale):
curl -s -m 3 -o /dev/null -w '%{http_code}\n' http://<lxc-lan-ip>:<port>/
# Expect: connection refused / timeout, NOT a 200
```

Only after confirming both the positive (Tailscale HTTPS works) and negative (plain LAN IP
refused) cases is the deployment actually done. Skipping the negative check would have shipped
an unauthenticated dashboard reachable by anything on the LAN, not just the tailnet.

## Gotcha 6 addendum (2026-11-01) — n8n now warns that non-container installs are deprecated

Bumping n8n 2.37.10 -> 2.45.7 (in-place `npm install -g n8n@2.45.7`, same bypass-Ansible procedure as above; data folder copied to `/root/n8n-data-pre-2.45.7-20261101` first, migrations ran clean, both active workflows and the krisp-transcript webhook still registered) now logs on startup that running outside a container is deprecated and a future version will require Docker. This directly threatens this skill's whole pattern for n8n specifically (native systemd service, no Docker) — when n8n forces the issue, it'll need its own Docker-based deployment note rather than following this skill. Back up the data directory before any in-place version bump; migrations are one-way.
