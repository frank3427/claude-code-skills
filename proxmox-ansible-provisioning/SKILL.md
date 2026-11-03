---
name: proxmox-ansible-provisioning
description: This skill should be used when creating a new Proxmox LXC (pct create) or VM, writing or debugging Ansible playbooks that target Proxmox/Debian hosts (including Debian 13/trixie), or troubleshooting a Proxmox+Ansible workflow — a "storage 'local-lvm' does not exist" error, a "Systemd 257 detected" nesting warning, Ansible failing with a locale error inside a fresh LXC, an Ansible lineinfile task that keeps reporting changed on every run, writing multi-line config/YAML files to a remote host over SSH, an "apt-key or gpg binary is required" error from Ansible's apt_repository module, a Proxmox-family product (PVE/PBS/PMG) apt install failing with a 401 against enterprise.proxmox.com, Tailscale/anything needing `/dev/net/tun` stuck crash-looping inside an unprivileged LXC, any host device (GPU render node, USB dongle) bind-mounted into an unprivileged LXC showing up owned by `nobody:nogroup`, or an LXC's own dashboard/monitoring reporting a suspiciously high load average that doesn't match its actual workload. Trigger phrases include "pct create", "pvesm status", "local-lvm", "local-zfs", "unprivileged LXC", "nesting=1", "Ansible could not initialize the preferred locale", "lineinfile idempotency", "ansible-playbook --check failing", "pct exec", "apt-key deprecated", "apt_repository module failed", "enterprise repo 401 unauthorized", "pbs-enterprise.sources", "/dev/net/tun does not exist", "tailscaled activating auto-restart", "TUN passthrough LXC", "device passthrough nobody nogroup", "renderD128 permission denied LXC", "GPU passthrough unprivileged LXC", "chmod 666 dev dri", "loadavg LXC host contamination", "/proc/loadavg not namespaced", "LXC excessive load false alarm", "Jinja Syntax error Missing end of comment tag", "ansible template array length bash", "${#array[@]} jinja", "ansible --start-at-task check diff", "template drifted from live script".
version: 0.3.0
---

# Proxmox + Ansible Provisioning

A repeatable sequence and five real gotchas hit while building a Proxmox LXC and Ansible control
node from scratch. Each looked like a one-off problem at first; all five recur on every future
Proxmox/Ansible build unless checked for up front.

## Provisioning sequence — check reality before writing commands

Don't guess storage/template names from memory or generic Proxmox examples — verify against the
actual host first, every time:

```bash
pvesm status                    # real storage identifiers — NOT always "local-lvm"
pveam update && pveam available | grep debian-13
pveam list local | grep debian-13   # real template filename, exact version string
```

A ZFS-based Proxmox install uses something like `local-zfs`, not the LVM-thin default
(`local-lvm`) most tutorials assume. Guessing wrong here fails the `pct create` outright — cheap
to avoid by checking first.

Create unprivileged, DHCP-addressed (not a hardcoded IP — add a router DHCP reservation instead,
once you have the MAC from `ip a` inside the container):

```bash
pct create <vmid> local:vztmpl/<exact-template-filename> \
  --hostname <name> \
  --unprivileged 1 \
  --cores 1 --memory 1024 --swap 512 \
  --rootfs <real-storage-name>:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --onboot 1 \
  --ssh-public-keys /path/to/pubkey-file-on-the-host
```

**Last step, not optional: run `base-hardening.yml` against the new host before considering it
provisioned** — `ansible-playbook base-hardening.yml --limit <new-host>` (add it to the
inventory first if it isn't already). A host is not done just because its application stack is
up. Confirmed missed live 2026-08-30: a Laravel/Filament LXC (`console`) ran for 9 days after
build with `PasswordAuthentication`/`PermitRootLogin` still at OpenSSH defaults (sshd on
`*:22`, no scoping firewall) and zero unattended-upgrades, caught only by the next weekly
sweep's `ansible_check` category — a check that only runs weekly, so don't rely on it to catch
this at build time. `dpkg -l unattended-upgrades` and `sshd -T | grep -i passwordauth` are the
two fastest ways to confirm hardening actually landed, not just that the playbook reported
`ok`.

## Gotcha 1 — Debian 13 (trixie) LXCs need `nesting=1` or systemd can leave services degraded

`pct create` prints `WARN: Systemd 257 detected. You may need to enable nesting.` — this is real,
not boilerplate. Systemd 257's sandboxing directives can fail inside an unprivileged LXC without
nesting enabled, leaving services silently failed/degraded on boot. Fix before first boot:

```bash
pct set <vmid> --features nesting=1
pct start <vmid>
pct exec <vmid> -- systemctl --failed   # confirm zero failed units
```

This does **not** compromise the container's unprivileged status — nesting is a separate feature
flag, not a privilege escalation.

## Gotcha 2 — fresh templates have no locale generated; Ansible hard-fails on this (not just warns)

Most commands run via `pct exec` on a bare template only print a harmless
`setlocale: LC_ALL: cannot change locale` warning. Ansible is different — it refuses to run at
all: `ERROR: Ansible could not initialize the preferred locale: unsupported locale setting`. Fix
once, system-wide, before installing Ansible:

```bash
pct exec <vmid> -- apt install -y locales
pct exec <vmid> -- sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
pct exec <vmid> -- locale-gen
pct exec <vmid> -- update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
```

## Gotcha 3 — multi-line file writes over SSH/`pct exec` can get silently corrupted

Pasting a heredoc into a remote shell can pick up extra indentation or lose the terminator
(terminal-dependent bracketed-paste issue, seen with Ghostty specifically). The write "succeeds"
with silently wrong content — easy to miss without checking. **Avoid entirely: base64-encode the
file locally and write it as a single line**, which has no embedded newlines to mangle:

```bash
base64 -i local-file.yml | tr -d '\n'
# then, on the target:
pct exec <vmid> -- bash -c 'echo <base64-blob> | base64 -d > /path/to/file.yml'
```

Always `cat` the written file back afterward to confirm it matches before trusting it — this
silent-corruption failure mode is exactly the kind of thing that looks fine until you check.

## Gotcha 4 — Ansible `lineinfile` regex anchored with `\b` matches more than intended

`\b` (word boundary) fires at *any* word-to-non-word transition, including a hyphen. A regexp like
`'MySetting\b'` also matches `MySetting-WithSuffix` — a real, different config key. Since
`lineinfile` acts on the *last* matching line by default when multiple lines match, this can
silently overwrite the wrong setting, and because the file shape keeps changing, it presents as
persistent non-idempotency (`changed` on every single run) rather than an obvious one-time bug.

Fix: anchor precisely enough to exclude sibling keys — e.g. require trailing whitespace or a
quote character immediately after the setting name, not just `\b`:

```yaml
# BAD — also matches "Automatic-Reboot-WithUsers" and "Automatic-Reboot-Time"
regexp: '^//?\s*Unattended-Upgrade::Automatic-Reboot\b'

# GOOD — requires whitespace right after, which the suffixed variants don't have
regexp: '^//?\s*Unattended-Upgrade::Automatic-Reboot\s'
```

If a `changed=1` won't go away across repeat idempotent runs, read the actual `--diff` output
(not just the recap) — it will show you exactly which line is being touched and usually reveals
this pattern immediately.

## Gotcha 5 — `ansible-playbook --check` will report false failures for dependent tasks

A task that edits a config file created by an *earlier task in the same play* (e.g. editing a
package's shipped config file right after installing that package) will fail in `--check` mode
with something like `Destination ... does not exist`. This isn't a bug — check mode doesn't
actually perform the install, so the file genuinely isn't there yet to edit. Don't chase this as a
real error; either add `create: true` to make the task robust regardless, or just verify by
running for real (against a low-risk target first if the playbook touches anything sensitive).
If you only need to validate a *later* task in the same play (e.g. a `template`/`copy` task
further down whose rendering you want to `--diff`-check without wading through an earlier task's
known false failure), use `--start-at-task="<exact task name>"` to jump straight past it rather
than fighting the earlier task into passing.

## Gotcha 10 — a Jinja2 template containing bash's `${#array[@]}` fails to render at all

`{#` is Jinja2's comment-start delimiter, and it doesn't care that it's sitting inside a `${...}`
bash expansion — the template lexer treats raw text left-to-right regardless of surrounding shell
syntax. Any `.sh.j2` template with bash array-length syntax (`${#PARTS[@]}`, `${#some_array[@]}`)
fails with `Syntax error in template: Missing end of comment tag` the moment Ansible tries to
render it (`ansible.builtin.template`), even though the file is perfectly valid bash on its own
and passes `bash -n` fine as a plain script. This only bites templates, not `ansible.builtin.copy`
of a static file — a script can be deployed unmodified for a long time via `copy` and only surface
this the day it's converted to a `template` (e.g. to parameterize a path that used to be
hardcoded). Fix: wrap just the array-length expression in a raw block so Jinja emits it literally:
```
if [ "{% raw %}${#PARTS[@]}{% endraw %}" -gt 0 ]; then
```
Confirmed live 2026-07-29 reconstructing `r2-backup-sync.sh.j2` in `homelab-ansible` from a live
script that had drifted ahead of its template — the render failed opaquely until this was spotted.

## Gotcha 6 — Ansible's `apt_repository` module fails on Debian 13; and Proxmox-family packages auto-add a paid enterprise repo that 401s

Two related but distinct traps when installing any Proxmox-family package (PVE itself, PBS, PMG)
via Ansible on trixie:

1. `ansible.builtin.apt_repository` shells out to `apt-key`, which trixie removed entirely —
   every call fails with `Either apt-key or gpg binary is required, but neither could be found`,
   even when no `key:` parameter was passed. Don't fight the module; skip it and write the
   sources file directly instead:
   ```yaml
   - name: Add signing key (binary keyring, goes straight in trusted.gpg.d — no apt-key needed)
     ansible.builtin.get_url:
       url: https://enterprise.proxmox.com/debian/proxmox-release-{{ ansible_distribution_release }}.gpg
       dest: /etc/apt/trusted.gpg.d/proxmox-release-{{ ansible_distribution_release }}.gpg
       mode: '0644'

   - name: Add the no-subscription repo
     ansible.builtin.copy:
       content: "deb http://download.proxmox.com/debian/<pbs-or-pve> {{ ansible_distribution_release }} <component>-no-subscription\n"
       dest: /etc/apt/sources.list.d/<name>-install-repo.list
       mode: '0644'
   ```

2. Installing the package itself (`proxmox-backup-server`, etc.) auto-creates a deb822-format
   enterprise repo file (e.g. `/etc/apt/sources.list.d/pbs-enterprise.sources`) pointed at
   `enterprise.proxmox.com`, which requires a paid subscription key and 401s on every
   `apt update` otherwise — this breaks not just this install but every subsequent idempotent
   re-run of the playbook. Disable it explicitly, before the package-install task so the first
   run doesn't fail either:
   ```yaml
   - name: Disable the enterprise repo (needs a paid subscription key, 401s otherwise)
     ansible.builtin.file:
       path: /etc/apt/sources.list.d/pbs-enterprise.sources   # filename varies per product
       state: absent
   ```
   Check `ls /etc/apt/sources.list.d/` for the actual filename if unsure — it's `.sources`
   (deb822), not the older `.list` format, on recent installs.

## Gotcha 7 — unprivileged LXCs need explicit TUN passthrough before Tailscale (or anything else needing `/dev/net/tun`) will start

`nesting=1` alone does not grant `/dev/net/tun` access — an unprivileged LXC without this fix
gets `tailscaled` stuck in an `activating (auto-restart)` crash loop, with the real error buried
in `journalctl -u tailscaled`:

```
getLocalBackend error: createEngine: tstun.New("tailscale0"): CreateTUN("tailscale0") failed; /dev/net/tun does not exist
```

Hit repeatedly across this homelab's builds (Pi-hole, Grafana, Homepage) — it recurs on every new
unprivileged LXC that needs Tailscale, not a one-off. Fix on the Proxmox host, not inside the
container:

```bash
cat >> /etc/pve/lxc/<vmid>.conf << 'EOF'
lxc.cgroup2.devices.allow: c 10:200 rwm
lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file
EOF
pct stop <vmid> && pct start <vmid>   # full stop/start required -- a restart from inside the
                                      # container does not re-read the host-side .conf
```

Verify before moving on: `pct exec <vmid> -- ls -la /dev/net/tun` should show the device, and
`systemctl is-active tailscaled` should report `active`, not `activating`.

## Gotcha 8 — a bind-mounted device keeps the host's uid/gid, which shows as `nobody:nogroup` and blocks access inside an unprivileged LXC

Gotcha 7 above is TUN-specific, but the same `.conf` pattern applies to *any* host device passed
into an unprivileged LXC (a GPU render node for hardware transcoding, a USB dongle, etc.):

```
lxc.cgroup2.devices.allow: c <major>:<minor> rwm
lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file
```

TUN usually doesn't hit a follow-on permission problem because `/dev/net/tun` is already
world-writable on most hosts. Other devices commonly aren't — `/dev/dri/renderD128` is typically
`crw-rw---- root:render` on the host. An unprivileged LXC shifts every uid/gid by a fixed offset
(subuid/subgid mapping), so the host's `render` group GID has no reason to land on anything
meaningful inside the container's namespace. The bind-mounted device shows up like this from
inside the container even though the major:minor and file itself are correct:

```
crw-rw-rw- 1 nobody nogroup 226, 128 ... /dev/dri/renderD128
```

`nobody:nogroup` is the tell — the device is visible but the owning group means nothing inside
the container's shifted namespace, so a non-root process (e.g. a `jellyfin` service user) can't
actually open it despite `ls` showing the device exists. Fix on the **host**, not inside the
container (the device node is a bind mount of the host's real file — permissions live there):

```bash
chmod 666 /dev/dri/renderD128
cat > /etc/udev/rules.d/70-<service>-gpu.rules << 'EOF'
KERNEL=="renderD128", GROUP="render", MODE="0666"
EOF
udevadm control --reload-rules
```

The udev rule is required for persistence — `/dev/dri` is recreated fresh by the kernel on every
host boot, so a one-off `chmod` alone reverts on the next reboot. Verify with `pct exec <vmid> --
ls -la /dev/dri/renderD128` showing `crw-rw-rw-` from inside the container, then confirm the
consuming application actually opens it (e.g. `vainfo` for VAAPI/QuickSync) rather than trusting
the permission bits alone.

## Gotcha 9 — `/proc/loadavg` inside an unprivileged LXC is the *host's* load, not the container's

Unlike cgroup-scoped CPU/memory accounting, Linux's load average is a kernel-wide number — it
isn't namespaced per-container. An unprivileged LXC shares the host's kernel, so any tool reading
`/proc/loadavg` from inside the container (uptime, an app's own health-check log, a dashboard
warning) is actually reporting the host's system-wide load, contaminated by every other guest and
by the host's own QEMU threads for its VMs. A container can look "overloaded" purely because
something unrelated — another guest's backup job, a different VM's CPU-heavy task — is busy on
the *host* at that moment, with the container itself sitting near idle.

Confirmed live 2026-07-23: `pihole` (LXC, 1 vCPU at the time) showed recurring "excessive load"
warnings that tracked a nightly Cloudflare R2 backup sync running as a *different* guest (a VM).
Pulled `node_load15` for both `instance=pve` (the host) and `instance=pihole` from Prometheus —
identical to the decimal, every night, at the same time. Bumping the LXC's core count (a natural
first guess, since the warning says "N > number of processors") does nothing for this, since it's
not the LXC's own demand driving the number in the first place.

Before adding cores/CPU limits to "fix" a load warning on an LXC, check whether the number matches
the **host's** load at the same timestamps (Prometheus `node_load15{instance="<host>"}` vs.
`node_load15{instance="<lxc>"}`, or just `ssh <lxc> uptime` and `ssh <host> uptime` back to back) —
if they match, the fix is on the host side (find and fix what's actually spiking there), not the
container.

**Privileged LXCs too (2026-10-06).** Pi-hole (CT 100, privileged) showed `load average: 2.05, 4.39, 3.46`
and pve showed the same three numbers at the same moment. The cause was fleet-wide Ansible runs, and pve has
4 cores. Judge a service by its own latency (Pi-hole's cached answers stayed at 0.02–0.05 ms), not by `uptime`
inside the guest.

## Verification discipline for anything SSH/auth-related

Before letting a playbook change `PasswordAuthentication`/`PermitRootLogin` or similar, verify
key-based access works *first* — a hypervisor lockout is a severe, hard-to-reverse mistake. After
applying, verify both directions explicitly, not just that the playbook exited 0:

```bash
# new path works
ssh -o PreferredAuthentications=publickey -o PasswordAuthentication=no root@host echo ok

# old path is genuinely closed (force the real code path, don't just omit a flag)
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o BatchMode=yes root@host echo should-fail
```

A clean `ansible-playbook` recap is not proof the security property actually holds — read the
`--diff` output and test both the allowed and blocked path directly.

## Gotcha 10 — never stage a managed file in `/tmp`

`base-hardening.yml` copied its terminfo source to `/tmp` and compiled it with `creates:`. After any
reboot or tmp cleanup the copy reappeared as `changed` on all 13 hosts, so the weekly `ansible_check`
read drift that wasn't there. `creates:` also meant an updated source was never recompiled. Fixed
2026-10-06: a persistent source (`/usr/local/share/homelab-terminfo/`), registered, and the compile step
`when: src.changed or not compiled.stat.exists`. A playbook that is not idempotent across a reboot
trains everyone to ignore the drift check.
