---
name: debian-kernel-reboot-check
description: This skill should be used when checking whether a Debian-based host (Proxmox host, LXC, VM, bare metal, or VPS) needs a reboot to pick up a kernel update, when "apt update" reports no upgradable packages but a reboot is suspected to be pending anyway, when planning a safe reboot of a host running live services, or when auditing an entire fleet of mixed LXC/VM/bare-metal hosts for pending kernel upgrades. Trigger phrases include "kernel upgrade", "check for pending reboot", "reboot-required", "unattended-upgrades installed a new kernel", "does this host need a reboot", "safe reboot checklist", "fleet kernel sweep", "uname -r doesn't match installed kernel", "proxmox-kernel not applied", "LXC kernel version", "does the container share the host kernel".
---

# Debian kernel/reboot check across a mixed fleet

`unattended-upgrades` silently installs newer kernel packages in the background but **never
reboots the host**. This means the running kernel (`uname -r`) can lag the newest *installed*
kernel indefinitely with zero visible symptoms — `apt update`/`apt list --upgradable` will
report nothing pending, because the new kernel package is already installed, just not booted
into. Don't conflate "nothing to `apt upgrade`" with "no kernel action needed."

## Checking a single host

Three checks, cheapest/most authoritative first:

```bash
# 1. The single most reliable signal — presence means a reboot is needed, absence means clean
cat /var/run/reboot-required 2>/dev/null || echo "no reboot pending"

# 2. Compare currently running kernel against what's actually installed
uname -r
dpkg -l 'linux-image-*' | grep ^ii | tail -5   # look for a newer version than uname -r reports

# 3. Confirm apt has nothing further queued unattended (should report nothing found)
sudo unattended-upgrade --dry-run -d 2>&1 | tail -5
```

On a Proxmox host itself, the kernel package family is `proxmox-kernel-*` / the
`proxmox-kernel-7.0` (or current major) meta-package, not `linux-image-*`:

```bash
uname -r
dpkg -l 'proxmox-kernel-*' | grep ^ii
```

If `/var/run/reboot-required` is absent, the host is already running its newest installed
kernel — no action needed regardless of what other packages are upgradable.

## Fleet topology: don't check LXCs individually

**LXC containers share the Proxmox host's kernel.** `uname -r` inside any LXC reports the
*host's* kernel version (e.g. `7.0.14-12-pve`), not something the container can independently
upgrade or reboot into. Checking 6 LXCs one at a time for "kernel updates" wastes time — check
the Proxmox host (`pve`) once, and that answers it for every LXC on that host simultaneously.
A kernel bump on `pve` requires rebooting the *entire physical host*, which restarts every
guest at once — a much bigger operation than a single VM/container reboot, and worth flagging
to the user before doing it rather than treating it the same as a single-service reboot.

Hosts with **independent kernels** that must be checked/rebooted one at a time: Proxmox VMs
(e.g. a backup server VM, a Docker-in-VM host), bare-metal boxes, and any external VPS. Each
of these needs its own `/var/run/reboot-required` check and, if needed, its own reboot.

## Safe-reboot checklist (before actually rebooting a live host)

1. **Check what's enabled/active**, so you know it'll come back:
   ```bash
   systemctl is-enabled <service1> <service2> ...
   systemctl is-active <service1> <service2> ...
   ```
2. **For Docker-based services**, confirm the container restart policy will bring it back
   without manual intervention:
   ```bash
   docker inspect <container> --format '{{.HostConfig.RestartPolicy.Name}}'
   ```
   Want `unless-stopped` or `always` — `no` means it stays down after reboot.
3. **Check upcoming backup/timer windows** so the reboot doesn't collide with a nightly job:
   ```bash
   systemctl list-timers --no-pager
   ```
4. **On a hardened host with fail2ban**, confirm the `sshd` jail's `ignoreip` already covers
   the range you'll reconnect from (e.g. Tailscale's CGNAT `100.64.0.0/10`) — reconnecting
   immediately post-reboot shouldn't risk a self-inflicted lockout.
5. **Firewall/ufw rules**: note the current `ufw status` output if the host has a non-default
   firewall config, so you can spot-check it survived the reboot.

## Executing the reboot

```bash
ssh <host> "sudo reboot"
```

Immediately confirm the host actually went down — a host mid-shutdown can still briefly answer
ping/SSH, producing a false "it's already back" read if you poll too early:

```bash
sleep 15
ssh -o ConnectTimeout=5 -o BatchMode=yes <host> "echo still up" 2>&1 || echo "host is down (expected)"
```

Then poll until it's genuinely back:

```bash
for i in $(seq 1 20); do
  ssh -o ConnectTimeout=5 -o BatchMode=yes <host> "uname -r" 2>/dev/null && break
  sleep 5
done
```

## Post-reboot verification (don't just confirm SSH is back)

```bash
uname -r                                        # matches the expected new kernel?
cat /var/run/reboot-required 2>/dev/null || echo "clean, no reboot pending"
systemctl is-active <every service checked above>
docker ps --filter name=<container> --format '{{.Status}}'   # if Docker-based
sudo ufw status                                 # if firewall rules matter here
```

Only declare the reboot complete once every service from the pre-reboot checklist is
independently confirmed active again — a host answering SSH again is necessary but not
sufficient proof everything came back cleanly.

## Fleet-wide sweep pattern

Loop the single-host check across every host with an independent kernel (skip LXCs, check
their Proxmox host instead):

```bash
for h in <proxmox-host> <vm1> <vm2> <bare-metal-host> <external-vps>; do
  echo "=== $h ==="
  ssh <user>@$h "uname -r; cat /var/run/reboot-required 2>/dev/null || echo 'no reboot pending'"
done
```

Remember each independent-kernel host may need a different SSH user (root vs. a hardened
non-root sudo user vs. a bare-metal account) — don't assume `root@` uniformly across the
fleet.

## Batching a fleet-wide upgrade behind one pve reboot (2026-11-01)

When a report flags many hosts needing updates and reboots at once, don't reboot each guest. LXCs
share the Proxmox host's kernel, so: (1) upgrade every guest with **no reboot**; (2) upgrade `pve`;
(3) reboot `pve` **once** at the end, which restarts every guest and picks up their pending work in
one window. In the homelab this is `homelab-ansible/playbooks/fleet-apt-upgrade.yml` (serial, pihole
canary first, stops at the first unhealthy host; `-e include_pve=true` for step 2; it never reboots).
VMs (Home Assistant, PBS, Infisical) do restart with pve but have their own kernels, so check their
own reboot-required too. Tell the user up front that the pve reboot takes DNS, Home Assistant and
everything on it down for a few minutes, and agree the timing first.
