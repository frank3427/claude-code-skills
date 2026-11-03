---
name: jellyfin-proxmox-deployment
description: This skill should be used when deploying (or redeploying) Jellyfin on a Proxmox host as an unprivileged LXC with Intel QuickSync hardware transcoding passthrough — including the VM-vs-LXC decision for a shared iGPU, the manual device-passthrough steps Terraform can't do declaratively, the media-volume backup-exclusion pattern, and the Tailscale-Serve-only exposure model. Trigger phrases include "deploy jellyfin", "reinstall jellyfin", "jellyfin quicksync passthrough", "jellyfin proxmox LXC", "renderD128 jellyfin", "jellyfin hardware transcoding setup", "redeploy jellyfin from scratch".
---

# Jellyfin on Proxmox — LXC deployment with Intel QuickSync passthrough

Full recipe for deploying Jellyfin as a native (non-Docker) service in an unprivileged Debian 13
LXC on a Proxmox host with a single shared Intel iGPU, exposed only over Tailscale Serve. First
built 2026-07-16 in a homelab with one Proxmox host (Beelink N100, Alder Lake-N iGPU) and a
Terraform+Ansible-managed fleet; the mechanics below generalize to any single-iGPU Proxmox host.
Decommissioned 2026-07-18 at Will's request (a deliberate choice, not a resource-pressure one)
— this skill exists so a future redeploy doesn't have to rediscover any of the following.

**2026-10-23 redeploy (no GPU):** Jellyfin is live again on CT 143 `media` as part of an offline media server
(homelab-ansible `media-install.yml`): native Jellyfin 12.3, library on a quota'd host dataset bind mount
(`pct set 143 -mp0 /rpool/media,mp=/srv/media`, never in vzdump), first-run wizard + libraries + scan schedule
done via the HTTP API (`/Startup/*`, `/Library/VirtualFolders`, `/ScheduledTasks/{id}/Triggers`) so no browser
step is needed. Clients direct-play, so the iGPU was left alone. **The iGPU is still bound to `vfio-pci`** even
though the Immich VM it served was destroyed 2026-10-07: releasing it needs the modprobe change + a pve reboot.

**⚠️ The iGPU is currently claimed by something else.** The same day Jellyfin was decommissioned,
its freed iGPU was passed through **exclusively** to the Immich VM via `vfio-pci` (full PCI
passthrough — this hardware has no GVT-g/mdev support, so it can't be split). A future Jellyfin
LXC redeploy **cannot** get `/dev/dri` back without first reverting that passthrough (see the
homelab CLAUDE.md item 17 entry, "iGPU passthrough added 2026-07-18", for the exact revert
steps) — check whether the GPU is still exclusively bound to a VM before assuming the simple
LXC bind-mount path below will just work.

## The core architectural decision: LXC, not VM, despite the general rule

This homelab's standing rule is "GPU passthrough need → VM" (hardware passthrough generally
wants a VM for clean device isolation). **Deliberately override that rule for Jellyfin** when
the host has only one iGPU and other guests might want it too: a VM would hand Jellyfin
*exclusive* ownership of the only GPU on the box, permanently taking it away from Proxmox itself
and everything else. An **unprivileged LXC with device passthrough** shares the iGPU instead
(the host and the container both see the same `/dev/dri/renderD128`) — this is current
Proxmox/Jellyfin community best practice for Intel QuickSync specifically, because Intel iGPUs
in this class (no GVT-g/SR-IOV support, e.g. Alder Lake-N) can't be split between multiple VMs
the way a real virtualization-capable GPU can. Confirm this trade-off with whoever owns the box
before building — it's a real, named exception to a general rule, not an oversight.

## Terraform: what it can and can't do here

Bring the LXC up via the `bpg/proxmox` provider (`proxmox_virtual_environment_container`) same
as any other host in the fleet — but **device passthrough itself cannot be expressed in
Terraform if using a scoped, non-root API token**. `device_passthrough` blocks (and any LXC
`features` flag other than `nesting`) are hardcoded server-side to `root@pam` only; a scoped
token gets a real 403. Don't try to work around this by widening the token's privileges for one
resource. Instead:

```hcl
resource "proxmox_virtual_environment_container" "jellyfin" {
  node_name     = "pve"
  vm_id         = 142
  unprivileged  = true
  started       = true
  start_on_boot = true

  operating_system {
    template_file_id = "local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst"
    type             = "debian"
  }

  disk {
    datastore_id = "local-zfs"
    size         = 20
  }

  # Separate media volume -- see "Backup exclusion" section below.
  mount_point {
    volume = "local-zfs"
    size   = "500G"
    path   = "/mnt/media"
    backup = false
  }

  cpu    { cores = 2 }
  memory { dedicated = 4096; swap = 512 }

  features { nesting = true }   # nesting alone is fine for a scoped token

  network_interface { name = "eth0"; bridge = "vmbr0" }

  initialization {
    hostname = "jellyfin"
    ip_config { ipv4 { address = "dhcp" } }
    user_account { keys = [ /* ansible + personal pubkeys */ ] }
  }
}
```

`terraform apply` this first (fresh create, no import needed), then do the passthrough as a
**manual step over root SSH to the Proxmox host** (`pct stop 142`, edit
`/etc/pve/lxc/142.conf`, `pct start 142`):

```
lxc.cgroup2.devices.allow: c 226:128 rwm
lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file
```

(`226:128` is `renderD128`'s major:minor — confirm with `ls -la /dev/dri/renderD128` on the host
if a different card/node shows up.) This is the same established pattern as TUN passthrough
(`/dev/net/tun`, needed if this LXC also runs Tailscale) — always a full `pct stop`/`pct start`
cycle, restarting the service from inside the container is not enough for either device.

## The permissions gotcha device passthrough always hits

A device node bind-mounted from the host keeps the **host's** uid/gid, which does not map into
an unprivileged LXC's shifted uid/gid namespace — `/dev/dri/renderD128` shows up owned by
`nobody:nogroup` inside the container even though the major:minor is correct. Fix on the
**host** (not inside the container):

```bash
chmod 666 /dev/dri/renderD128
```

...and persist it, since Proxmox recreates `/dev/dri` fresh on every host reboot:

```
# /etc/udev/rules.d/70-jellyfin-quicksync.rules on the Proxmox host
KERNEL=="renderD128", GROUP="render", MODE="0666"
```

Inside the container, add the `jellyfin` service user to both `video` and `render` groups (the
Ansible playbook below does this) — belt-and-suspenders alongside the `0666` mode.

## Ansible: package install + VAAPI driver

Native apt-repo install, not Docker — matches this fleet's general Docker-in-unprivileged-LXC
avoidance (cgroup quirks). Two non-obvious package facts, both confirmed live rather than
assumed:

- **Jellyfin's official repo (`repo.jellyfin.org`) already serves Debian 13 (`trixie`)
  packages** directly — don't assume you need a `bookworm` compat fallback.
- Use the **free** `intel-media-va-driver` package (Debian `main` component), not
  `intel-media-va-driver-non-free`. The non-free variant lives in Debian's `non-free`
  component (not enabled by default) and isn't needed anyway — the free iHD driver fully covers
  Gen8+ Intel iGPUs, including Alder Lake-N.

```yaml
- name: Install and configure Jellyfin
  hosts: jellyfin
  become: false
  tasks:
    - name: Install prerequisite packages
      ansible.builtin.apt:
        name: [curl, gnupg, apt-transport-https]
        state: present
        update_cache: true

    - name: Ensure /etc/apt/keyrings exists
      ansible.builtin.file:
        path: /etc/apt/keyrings
        state: directory
        mode: '0755'

    - name: Fetch and dearmor Jellyfin GPG key
      ansible.builtin.shell: |
        curl -fsSL https://repo.jellyfin.org/jellyfin_team.gpg.key | gpg --dearmor -o /etc/apt/keyrings/jellyfin.gpg
      args:
        creates: /etc/apt/keyrings/jellyfin.gpg

    - name: Add Jellyfin apt repository (deb822)
      ansible.builtin.copy:
        content: |
          Types: deb
          URIs: https://repo.jellyfin.org/debian
          Suites: trixie
          Components: main
          Architectures: amd64
          Signed-By: /etc/apt/keyrings/jellyfin.gpg
        dest: /etc/apt/sources.list.d/jellyfin.sources
        mode: '0644'
      register: jellyfin_repo

    - name: Install Jellyfin + Intel VAAPI userspace driver + rsync
      ansible.builtin.apt:
        name: [jellyfin, intel-media-va-driver, rsync, vainfo]
        state: present
        update_cache: "{{ jellyfin_repo.changed }}"

    - name: Add jellyfin service user to video and render groups
      ansible.builtin.user:
        name: jellyfin
        groups: video,render
        append: true
      notify: Restart jellyfin

    - name: Ensure jellyfin service is enabled and running
      ansible.builtin.service:
        name: jellyfin
        enabled: true
        state: started

  handlers:
    - name: Restart jellyfin
      ansible.builtin.service:
        name: jellyfin
        state: restarted
```

Verify hardware transcode capability for real, don't assume from general N100 knowledge:

```bash
vainfo
```

Confirmed live output for an Alder Lake-N iGPU: H.264 and HEVC (8-bit + 10-bit) decode
*and* encode (`EncSliceLP` entrypoints), VP9 decode+encode too. **No AV1 hardware encode** —
not in the profile list at all; don't advertise AV1 hardware support without re-checking
`vainfo` on the actual hardware in use.

## The "binds 0.0.0.0 by default" gotcha, Jellyfin's flavor

This fleet has hit "binds all interfaces by default" three times now (Next.js's `HOSTNAME` env
var doing nothing, Docker's short-form `ports:` syntax, and this one) — Jellyfin's mechanism is
its own XML config, not an env var or CLI flag. `/etc/jellyfin/network.xml`'s
`LocalNetworkAddresses` element controls bind address ("if empty, all interfaces will be used" —
per Jellyfin's own bundled API docs):

```xml
<LocalNetworkAddresses>
  <string>127.0.0.1</string>
</LocalNetworkAddresses>
```

**This file does not exist until Jellyfin's first web-based config write** — it has to be
hand-created *before* the first-run setup wizard runs, not edited after the fact, if the goal is
never letting the wizard bind wide open even briefly. Verify the fix with a **positive and
negative** check, not just "the Tailscale URL works": confirm reachable over
`https://jellyfin.<tailnet>.ts.net`, then confirm the plain LAN IP on Jellyfin's port is refused
from another LAN host.

## Exposure: Tailscale Serve only, no Funnel

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8096
```

Tailnet-only — no public ingress need for a personal media server. Verify both directions (see
above).

## Storage: separate media volume, deliberately excluded from backups

Two Proxmox storage volumes, not one:
- `rootfs` (small, ~20GB) — OS, app, Jellyfin's own metadata DB (posters, `.trickplay` files,
  watch state). **This is what nightly PBS backups actually protect.**
- A dedicated `mp0` mount at `/mnt/media` — the media library itself, sized generously (e.g.
  500GB) but usually mostly empty. Set `backup = false` in Terraform's `mount_point` block.

**Real gotcha found in production**: the `bpg/proxmox` provider's `mount_point.backup = false`
attribute does not reliably write a `backup=0` flag into the actual `/etc/pve/lxc/<vmid>.conf`
`mpN` line — Terraform's state can say `backup: false` while the live container config has no
flag at all, and Proxmox's *default* for a volume-backed mount point (as opposed to a bind-mount
of a host path) is backed-up-by-default when the flag is absent. This would silently vzdump the
entire media library nightly. **Always verify directly after apply**:

```bash
grep mp0 /etc/pve/lxc/<vmid>.conf   # must show ,backup=0
```

If missing, fix with a direct `pct set <vmid> -mp0 <existing-value>,backup=0` and confirm with a
real manual `vzdump <vmid>` run — the log should say *"excluding volume mount point mp0 (...)
from backup (disabled)"* and the resulting archive size should roughly match the rootfs alone,
not the whole library.

**The rationale for excluding media from backup is "presumed reproducible from its original
source."** That's a real assumption, not a guarantee — if any content in the library genuinely
has no other copy (home movies, personal recordings, event footage someone captured
themselves), it needs an explicit, separate preservation plan before relying on this pattern.
Don't let "media is excluded from backup" become "media has no backup at all" without that
being a deliberate, confirmed decision — see the companion decommission note this skill's
project attached this lesson to.

## Ingestion pattern (optional, if using a Mac-side drop folder)

If media arrives via a sync pipeline from a source machine (rather than direct download to the
LXC), that source machine's rsync client matters: macOS's built-in `rsync` is openrsync, which
preserves local uid/gid/mode verbatim with no `--chown` flag — files can land unreadable by the
`jellyfin` service account. See the `jellyfin-media-permissions` skill for the full diagnostic
and fix (a post-transfer `chown`/`chmod` step on the receiving end, not a client-side rsync flag
change).

## Redeploying from scratch (checklist)

1. `terraform apply` the LXC (Terraform block above) — fresh create, no import.
2. Manual device passthrough on the Proxmox host: TUN (if Tailscale needed) + `renderD128`,
   both via `.conf` edit + full `pct stop`/`start`.
3. Host-side `chmod 666` + persistent udev rule for `renderD128`.
4. Run the Ansible install playbook above.
5. Hand-create `/etc/jellyfin/network.xml` with `LocalNetworkAddresses` = `127.0.0.1` *before*
   visiting the web UI for the first time.
6. `tailscale serve --bg --https=443 http://127.0.0.1:8096`.
7. Verify `mp0`'s `backup=0` actually landed in the live `.conf`, not just Terraform state.
8. **Interactive, needs a human at the browser** — the first-run wizard: admin account, add a
   library pointed at `/mnt/media`, then Dashboard → Playback → Hardware Acceleration → Intel
   QuickSync (QSV), device `/dev/dri/renderD128`. HDR tone-mapping needs OpenCL (heavier) —
   skip unless a specific title needs it.
9. Add to Homepage, Pi-hole Local DNS Records, Prometheus scrape targets, and the nightly PBS
   backup schedule — standard closing steps for any new host in this fleet.
10. DHCP reservation on the router — always a manual step if there's no router API access.
