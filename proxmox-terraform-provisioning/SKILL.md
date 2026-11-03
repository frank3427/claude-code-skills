---
name: proxmox-terraform-provisioning
description: This skill should be used when setting up the bpg/proxmox Terraform provider against a Proxmox host, creating a least-privilege Proxmox API token for Terraform, importing existing LXCs/VMs into Terraform state as a no-op baseline, creating a brand-new VM (proxmox_virtual_environment_vm) via Terraform, or configuring an LXC's device_passthrough or mount_point blocks, or a VM's hostpci block — including a "403 ... SDN.Use" error on network_device creation, a download_file resource failing with a permissions/Sys.Modify error, the provider needing SSH access for disk import, importing an appliance-image VM (UEFI/OVMF, no cloud-init — e.g. Home Assistant OS, pfSense/OPNsense) rather than a Debian cloud image, a device_passthrough block 403ing with "only allowed for root@pam", a mount_point's backup=false attribute not actually excluding that volume from vzdump, a new cloud-init VM booting with no network config at all, `terraform plan -generate-config-out` hanging for many minutes with no error, or declaring a VM's PCI/GPU passthrough (hostpci) block, or a cloud-init VM whose SSH host key
changed and triggered an unplanned apt dist-upgrade after a Proxmox host reboot with no VM
config change of its own. Trigger phrases include "instance-id changed", "cloud-init new
instance re-run", "REMOTE HOST IDENTIFICATION HAS CHANGED after pve reboot", "unexpected dist-upgrade after reboot", "initialization dns block terraform", "pbs.tf immich.tf dns pin", "bpg/proxmox", "terraform import proxmox", "pveum token add", "terraform plan -generate-config-out", "PVEVMAdmin", "proxmox_virtual_environment_container", "proxmox_virtual_environment_vm", "Terraform Proxmox provider", "import existing LXC into terraform", "SDN.Use", "qm importdisk terraform", "proxmox_download_file", "ovmf", "efidisk0", "appliance image proxmox", "haos qcow2", "device_passthrough", "only allowed for root@pam", "mount_point backup", "GPU passthrough terraform LXC", "renderD128 terraform", "cloud-init ISO stale", "qm set ide2 cloudinit", "no DHCP after cloud-init boot", "generate-config-out hangs", "qemu guest agent not running terraform", "mac_addresses drift docker", "hostpci terraform", "VM PCI passthrough terraform", "rombar drift", "grow VM disk terraform", "terraform disk resize proxmox", "resize scsi0",
"systemd-growfs proxmox vm", "growpart not needed terraform", "terraform plan -target disk
resize".
version: 0.7.0
---

# Proxmox + Terraform Provisioning (bpg/proxmox)

A repeatable sequence for bringing a Proxmox host under Terraform management with the
`bpg/proxmox` provider, plus gotchas hit importing already-running LXCs as a no-op baseline and,
separately, creating brand-new VMs from scratch.

## 1. Create a scoped API token, not root

Proxmox's built-in roles cover VM/LXC lifecycle management without granting host shell access —
use them instead of `root@pam` or a custom role from scratch:

```bash
pveum user add terraform@pve --comment "Terraform (bpg/proxmox provider)"
pveum aclmod / -user terraform@pve -role PVEVMAdmin       # VM.Allocate, VM.Config.*, VM.PowerMgmt, etc.
pveum aclmod / -user terraform@pve -role PVEAuditor        # Sys.Audit, VM.Audit, Datastore.Audit
pveum aclmod /storage -user terraform@pve -role PVEDatastoreUser  # Datastore.AllocateSpace/.Audit
pveum user token add terraform@pve terraform-token --privsep 0 --output-format json
```

None of these roles include `Sys.Modify` or `Sys.Console` — confirm with
`pveum user permissions terraform@pve` before trusting it; the token should never be able to open
a host-level shell.

**Never let the token secret land in your own shell output, a chat transcript, or a log.** Pipe
it directly from creation to its destination instead of echoing it at any point — e.g. parse the
`pveum ... --output-format json` output in a script and `subprocess`/`ssh` it straight into a
gitignored, `600`-permission env file on the box that will actually run Terraform. If a step
requires printing something to confirm success, print the token *ID*, never the secret value.

Provider config then just reads from environment variables — no secrets in `.tf` files:

```bash
PROXMOX_VE_ENDPOINT=https://<pve-ip>:8006/
PROXMOX_VE_API_TOKEN=terraform@pve!terraform-token=<secret>
PROXMOX_VE_INSECURE=true   # pve's default self-signed cert; fine for LAN-only traffic
```

## 2. Import existing resources as a no-op baseline, don't hand-write the config

For LXCs/VMs that already exist and already work, use Terraform's `import` block +
config-generation rather than writing `resource` blocks from memory and hoping they match:

```hcl
import {
  to = proxmox_virtual_environment_container.pihole
  id = "pve/100"   # "<node_name>/<vmid>"
}
```

```bash
terraform plan -generate-config-out=generated.tf   # writes real attribute values Terraform read back
# review generated.tf, clean it up (see gotchas below), fold into version control
terraform apply
terraform plan   # MUST show "No changes" — this is the actual proof the import was a no-op
```

That last `terraform plan` showing zero drift is the only real verification that bringing a
resource under Terraform didn't silently change anything about the running container.

## Gotcha 1 — `operating_system.template_file_id` wants `""`, not `null`

The generated config emits `template_file_id = ""` for containers with no template reference.
Changing it to `null` (which looks more idiomatic and matches what `terraform show` reports for
the imported state) fails apply with `Error: Missing required argument` — the schema treats this
attribute as required-but-emptyable, not optional. Leave it as the generator wrote it.

## Gotcha 2 — `timeout_*` fields showing up as additions are harmless

A first `terraform plan` after import typically shows `+ timeout_clone = 1800`,
`+ timeout_create = 1800`, etc. as in-place updates. These are client-side provider operation
timeouts, not attributes stored on the Proxmox container itself — applying them doesn't touch the
running guest (confirms as `Modifications complete after 0s` with no real API side effects). Don't
mistake this for the import being non-clean; the `terraform plan` *after* apply is the real check.

## Gotcha 3 — `unprivileged` is `ForceNew`: changing it destroys and recreates the container

Proxmox has no live conversion between privileged and unprivileged LXCs. If a container was
created privileged by mistake (e.g. a `pct create` that dropped `--unprivileged 1`) and you flip
`unprivileged = true` in Terraform config expecting an in-place fix, `terraform plan` will show a
**destroy + recreate**, which wipes the container's rootfs disk. Before applying that:

- Back up the container's actual application config/data first (Terraform only manages the LXC
  shell — network, disk size, resource limits — not what's installed inside it).
- Any host-side passthrough config on the Proxmox node (e.g. TUN device passthrough for
  unprivileged LXCs — see the `proxmox-ansible-provisioning` skill) has to be redone after
  recreation, since it's tied to the container's `.conf` file, not preserved across destroy.
- If the container has its own identity in another system (VPN mesh node key, etc.), recreating
  it will register as a new device there too — plan for re-authentication, not just DNS/network
  config.
- Flag this to the human before applying — it's a real outage window for whatever the container
  serves, not a quiet config change.

## Creating a new VM (not just an LXC) hits gaps the scoped token doesn't cover

Building a `proxmox_virtual_environment_vm` from scratch (as opposed to importing an existing
LXC) surfaces problems the LXC-import workflow above never hits. Found building a Proxmox Backup
Server VM:

**Gotcha 4 — attaching a NIC to a bridge needs `SDN.Use`, which `PVEVMAdmin` doesn't grant.**
PVE 9 wraps legacy bridges (`vmbr0`) as SDN zones under the hood; creating a `network_device` on
one fails with `403 ... SDN.Use` even though `PVEVMAdmin` covers every other VM operation. Fix by
granting the scoped token `PVESDNUser` (SDN.Audit + SDN.Use only, no Allocate) at the specific
zone path: `pveum acl modify /sdn/zones/localnetwork/vmbr0 --users terraform@pve --roles
PVESDNUser`.

**Gotcha 5 — `proxmox_download_file`/`proxmox_virtual_environment_download_file` needs
`Sys.Modify`, which this token deliberately doesn't have.** Downloading an arbitrary URL
server-side is exactly the privilege the scoped token was designed to exclude — don't widen the
token for it. Stage cloud images manually instead, once, as root over SSH, into local storage's
`import` content type:
```bash
curl -sL -o /var/lib/vz/import/<name>.qcow2 <url>
```
then reference the file directly: `disk { file_id = "local:import/<name>.qcow2" }`. Skip the
download resource entirely.

**Gotcha 6 — actual VM creation (the disk-import step) needs direct root SSH to the node**, which
conflicts with a token deliberately scoped to exclude host shell access. The bpg/proxmox provider
shells out over SSH for `qm importdisk`-equivalent work when a disk references a `file_id`; there
is no way around this with API-token-only auth. Rather than configuring SSH credentials into the
provider (handing Terraform permanent host shell access), do the one-time create by hand instead:
`qm create` / `qm importdisk` / `qm set` over root SSH (the same access already used for
Ansible/manual admin), then bring it under Terraform with the same
`generate-config-out` + `import {}` no-op-import pattern from section 2 above. Ongoing lifecycle
(resize, destroy, tag changes) goes through `terraform apply` with the scoped token from that
point on — only the one-time create needs host shell.

**Adding `agent { enabled = true }` to an existing VM (2026-10-30, HA VM 150):** it plans as a clean
in-place update, but the virtio-serial device appears only after a full stop and start. Apply it
while the VM is **stopped**: shut it down cleanly first, then `started = true` boots it with the
device. Check every VM for an `agent:` line. Without one, a guest may ignore ACPI, and every host
shutdown then waits Proxmox's 180 s stop timeout and SIGTERMs it, which blows a UPS shutdown
budget.

**Gotcha 7 — `generate-config-out` needs the QEMU guest agent already running** to read back
network config, or it fails with `error waiting for network interfaces from QEMU agent`. Install
and start `qemu-guest-agent` inside the guest *before* running `generate-config-out` — Debian's
`genericcloud` cloud image does not ship it preinstalled (unlike some other distros' images).
**Not universal**, though: an appliance-image guest with no guest agent at all (see Gotcha 9)
generated its config fine anyway — this requirement seems tied specifically to reading back
network config normally supplied via cloud-init, not a hard dependency of config generation itself.

**Update (2026-07-18, building Immich):** without the agent installed, `terraform plan
-generate-config-out` doesn't fail fast with that error — it **hangs silently for the resource's
full `agent.timeout` window** (default `"15m"`) with the process sitting in `futex_do_wait` and
near-zero CPU, giving no indication anything is wrong. It looks exactly like a stuck/broken
Terraform run rather than a clean, documented failure mode. Confirm what's actually happening
before assuming a hang is a bug: check `qm agent <vmid> ping` on the Proxmox host in another
session — if it errors `QEMU guest agent is not running`, that's the cause. The fix works
mid-hang, no need to kill and restart the stuck command: `apt-get install -y qemu-guest-agent &&
systemctl enable --now qemu-guest-agent` inside the guest (reachable via its DHCP IP over SSH even
without the agent — the agent is unrelated to normal networking) lets the already-running
`terraform plan` pick it up and finish within moments.

**Gotcha 8 — the experimental config generator emits some invalid or redundant fields.** Seen
in practice: `cpu.units = 0` (rejected — valid range is 1–262144; both `cpu.units` and top-level
`mac_addresses` are optional+computed, so just delete the lines rather than fixing the value), and
a `network_device.enabled = true` that a deprecation warning says to remove but the schema
currently still requires — keep it despite the warning. Expect to hand-edit generated VM config
before it applies cleanly; treat the warning `Config generation is experimental` as accurate.

If the guest runs Docker (building Immich, 2026-07-18), the generated `mac_addresses` list can
come back with 8-9 entries, not just the real NIC's — the guest agent reports `lo`, `docker0`, and
a MAC per container's `veth` pair, and the generator dumps all of them in. These are ephemeral
(change on every `docker compose up`/container recreate), so keeping them in the committed `.tf`
would cause permanent phantom drift. Same fix as above: delete the `mac_addresses` line entirely
and rely on the real NIC's `mac_address` already captured inside the `network_device` block.

**Gotcha 12 — setting cloud-init fields (`--ciuser`, `--ipconfig0`, `--sshkeys`) via separate `qm
set` calls *after* `qm set --ide2 local-zfs:cloudinit` leaves the VM's cloud-init ISO stale.**
Proxmox only regenerates the NoCloud seed ISO at the moment a cloud-init-relevant flag is set —
each `qm set` prints `generating cloud-init ISO` when it does this. If `--ide2 ...cloudinit` is
attached *before* `--ciuser`/`--ipconfig0`/`--sshkeys` are set, the ISO gets baked with defaults
(no network config, no SSH keys) and never regenerates again from those later calls — the VM then
boots to a normal login prompt (cloud-init's `set_hostname` module still runs fine, since hostname
comes from the VM's `name` field independent of the ISO) but with **no network interface
configured at all**: zero DHCP traffic on the tap interface, not even a failed attempt, indefinitely.
This is easy to misdiagnose as a DHCP/router problem rather than a stale local config file — checked
first via `tcpdump -i tap<vmid>i0 port 67 or port 68` (confirms the guest never even tries) and via
`qm terminal <vmid>` wrapped in `script -qc "... " /dev/null` (a plain `qm terminal` over
non-interactive SSH fails with `tcgetattr: Inappropriate ioctl for device`; wrapping in `script`
gives it a pty so it actually attaches and shows the live console, including full dmesg/cloud-init
boot output if attached right after a `qm reset`).

**Fix: destroy and recreate the VM, setting every cloud-init-relevant flag (`--ciuser`,
`--ipconfig0`, `--sshkeys`) *before* attaching `--ide2 ...cloudinit`, in one pass** — don't rely on
a later `qm set` or a reboot to pick up corrected values, since cloud-init's NoCloud datasource
processes network/user config once per instance and a plain reboot isn't guaranteed to reprocess
it even after the ISO is regenerated. If the VM already has real data on it (not a fresh build),
`qm cloudinit update <vmid>` regenerates the ISO from current config without recreating the VM,
followed by a full guest reboot — but rebuilding fresh is simpler and safer when nothing of value
exists on the disk yet.

## Appliance-image VMs (UEFI, no cloud-init) — a third VM shape

Sections above cover LXC-import and Debian-cloud-image VM creation. A third shape showed up
building a Home Assistant OS VM (2026-07-13): importing an official appliance `.qcow2` image
(HAOS, but the same applies to any prebuilt appliance image — pfSense/OPNsense included, relevant
for a future OPNsense-on-Proxmox build) rather than a generic Linux cloud image.

**Gotcha 9 — appliance images typically need UEFI, not the `seabios` used for Debian cloud
images**, plus no cloud-init block at all:
```hcl
bios    = "ovmf"      # not "seabios"
machine = "q35"
efi_disk {
  datastore_id      = "local-zfs"
  file_format       = "raw"
  pre_enrolled_keys = false   # Secure Boot OFF — appliance images are typically unsigned for this
  type              = "4m"
}
```
Omit the `initialization` (cloud-init) block entirely — a self-contained appliance OS ignores it,
and includes its own first-boot onboarding/setup instead. Also don't assume `qm create` defaults
`ostype`; set it explicitly (`qm set <vmid> --ostype l26` for a Linux-based appliance) before
generating config, or the generated block will show `operating_system { type = null }`, which
technically matches (no drift) but is worth fixing at creation time rather than leaving unset.

Many appliance images (e.g. Home Assistant OS's `_ova-<version>.qcow2.xz` variant) already ship
with the intended virtual disk size baked in — check with `qemu-img info` after decompressing
before assuming a post-import `qm resize` is needed; it may already be sized correctly.

## Gotcha 10 — `device_passthrough` is hardcoded to `root@pam` only, no matter how the token is scoped

Building a container that needs a passed-through host device (a GPU render node for hardware
transcoding, a USB dongle, etc.), the `device_passthrough` block looks like the natural
declarative fit:

```hcl
device_passthrough {
  path = "/dev/dri/renderD128"
  mode = "0666"
}
```

`terraform plan` accepts this fine, but `terraform apply` 403s even for a token holding
`PVEVMAdmin`:

```
Error: Container create
received an HTTP 403 response - Reason: Permission check failed
(configuring device passthrough is only allowed for root@pam)
```

This isn't a missing-privilege gap fillable by granting more roles — Proxmox hardcodes this one
operation to `root@pam` specifically, presumably because arbitrary host-device passthrough is
close enough to a host-boundary escape that it's deliberately kept out of the ACL system
entirely. Don't widen the Terraform token's privileges chasing this (there is no role that grants
it). Instead: drop `device_passthrough` from the Terraform resource, create the container without
it, then pass the device through with a manual `.conf` edit over root SSH — the same escape hatch
already used for TUN passthrough (see the `proxmox-ansible-provisioning` skill's Gotcha 7, which
generalizes to any device, not just TUN):

```bash
pct stop <vmid>
cat >> /etc/pve/lxc/<vmid>.conf << 'EOF'
lxc.cgroup2.devices.allow: c <major>:<minor> rwm
lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file
EOF
pct start <vmid>
```

Document in the `.tf` file's comments *why* the device isn't there declaratively (so a future
`terraform plan -generate-config-out` refresh doesn't lead someone to re-add it and hit the same
403 again).

## Gotcha 11 — `mount_point.backup = false` doesn't necessarily write `backup=0` into the real container config

A `mount_point` block set with `backup = false` shows correctly in `terraform plan`
(`+ backup = false`) and gets recorded in `terraform.tfstate` the same way. But the actual
resulting `mpN` line in `/etc/pve/lxc/<vmid>.conf` after `apply` can come out with **no `backup`
flag at all**:

```
mp0: local-zfs:subvol-142-disk-1,mp=/mnt/media,size=500G
```

Proxmox's own default for a *volume* mount point (as opposed to a bind-mount of an existing host
directory) is **backed-up-by-default** when the flag is absent — so this silently backs up the
full volume nightly despite Terraform state insisting `backup: false` is already in effect. This
is a real drift between what Terraform believes and what vzdump will actually do, and `terraform
plan` won't show it as drift either (state matches what Terraform wrote, it's the provider's
write-to-Proxmox step that didn't fully land).

**Don't trust the state file's `backup` attribute as proof of the real on-disk behavior for this
attribute specifically.** Verify directly after apply:

```bash
grep ^mp0 /etc/pve/lxc/<vmid>.conf   # look for `,backup=0` explicitly present
```

If it's missing, fix with a direct `pct set`, which does write the flag correctly:

```bash
pct set <vmid> -mp0 local-zfs:subvol-<vmid>-disk-1,mp=/mnt/media,size=500G,backup=0
```

Confirm the fix by actually triggering a backup (`vzdump <vmid> --storage <storage>`) and reading
the log for the exclusion line, rather than just re-checking the config file — the log makes the
real behavior unambiguous: `excluding volume mount point mp0 ('/mnt/media') from backup
(disabled)` vs. it silently being included.

## Gotcha 12 — VM `hostpci` (PCI passthrough) is NOT the same root@pam restriction as LXC `device_passthrough`

Don't assume Gotcha 10 above generalizes to VMs. A `proxmox_virtual_environment_vm` resource's
`hostpci` block for full PCI/GPU passthrough works fine with a scoped API token — `terraform
plan`/`apply` both succeed cleanly, zero auth errors, confirmed live 2026-07-18 passing an Intel
iGPU through to a VM:

```hcl
hostpci {
  device = "hostpci0"
  id     = "00:02.0"   # bus:device.function, no domain prefix -- matches `lspci`'s 00:02.0,
                        # not qm's own "0000:00:02.0" long form
  pcie   = true
  rombar = true         # declare explicitly -- Proxmox's live default is `true`; omitting it
                         # shows as permanent drift (`rombar = true -> null`) every plan
}
```

A web search claimed `hostpci` requires root@pam/password auth (same restriction as LXC
`device_passthrough`) — that turned out to be **wrong** for this provider version, confirmed by
just trying it. Don't take a search result's word for a permission boundary when it's this cheap
to verify directly against the real API.

Also set `machine = "q35"` (not left `null`/default i440fx) — recommended for PCIe passthrough
reliability, and cheap to set regardless. A VM with `hostpci` attached needs a full VM reboot to
attach the device (not hot-pluggable) — same operational shape as Gotcha 10's LXC pattern, just
without the Terraform-vs-manual split. See the `proxmox-vm-igpu-passthrough` skill for the full
host-side (`vfio-pci` binding) and guest-side (kernel/firmware) procedure this Terraform block is
only one piece of.

## Gotcha 13 — a cloud-init VM with no explicit `dns` block silently inherits `pve`'s own `/etc/resolv.conf`, and `initialization` changes trigger a live guest reboot

If a `proxmox_virtual_environment_vm`'s `initialization` block has no `dns { servers = [...] }`,
Proxmox's own cloud-init generator (`PVE::QemuServer::Cloudinit.pm`, `get_dns_conf`) falls back
to the **Proxmox host's** `/etc/resolv.conf` when building the guest's cloud-init network-data —
not a guest-level default, the actual hypervisor's own resolver config. This matters because
NoCloud's `instance-id` is computed as `sha1(user-data + network-data)` (`nocloud_gen_metadata`),
so **any future change to the host's `/etc/resolv.conf` silently changes the instance-id of every
cloud-init VM without a pinned `dns` block**, even though nothing about the VM itself changed.

The next time such a VM boots (a `pve` host reboot restarts every guest on a single-node
cluster), cloud-init sees a "new" instance-id and re-runs every once-per-instance module:
**full SSH host-key regeneration** (all key types — this is what breaks `known_hosts` on
whatever host SSHes into it, see the general host-key-verification-failed gotcha elsewhere in
this project) and, if `upgrade = true` is set in `initialization` (as it commonly is, to patch a
freshly-created VM on first boot), **a full unattended `apt-get dist-upgrade`** — a real,
surprising side effect that has nothing to do with why the host actually rebooted.

Confirmed live 2026-07-18/19: `pve`'s `/etc/resolv.conf` changed as part of an unrelated DNS
routing overhaul; the next `pve` reboot (days later, for unrelated iGPU passthrough work)
silently regenerated the SSH host keys and ran a full `dist-upgrade` on two VMs (`pbs`,
`immich`) that both lacked an explicit `dns` block.

**Fix — always pin `dns` explicitly on every cloud-init VM**, even when it happens to match what
the host would currently provide anyway:

```hcl
initialization {
  datastore_id = "local-zfs"
  interface    = "ide2"
  upgrade      = true
  dns {
    domain  = "local"
    servers = ["192.168.50.53"]
  }
  ip_config { ... }
  user_account { ... }
}
```

This makes the network-data (and therefore instance-id) depend only on Terraform-declared
values, never on `pve`'s own resolver state.

**Applying this fix itself triggers exactly one more instance-id change** (the network-data
content is changing, by design) — expect one more SSH-key regen + dist-upgrade cycle on
whichever VM(s) you patch. Also confirmed: unlike most `initialization` sub-block edits, this one
does **not** just update Proxmox-side metadata — `terraform apply` visibly reboots the running
guest live (~20s "Modifying...", uptime resets to 0 immediately after) to make cloud-init re-read
the changed data. Budget for that; it's not a no-op update-in-place the way most attribute
changes in this block are (see Gotcha 2 above for the ones that genuinely are harmless).

**Verify the fix actually stuck** by re-checking `qm cloudinit dump <vmid> network` for the `dns`
section post-apply, and confirming `terraform plan` shows zero drift afterward — don't just trust
that the apply succeeded.

## Gotcha 14 — growing a VM's disk is a one-line `.tf` edit; no `qm resize`, no `growpart`, no reboot needed

Growing an existing `disk` block's `size` (e.g. an OS disk that's run low on space) is
Terraform-native end to end for a Debian cloud-image VM — confirmed live 2026-07-31 growing
Immich's scsi0 disk 20GB → 40GB while the VM stayed running:

```hcl
disk {
  interface         = "scsi0"
  path_in_datastore = "vm-145-disk-0"
  size              = 40   # was 20
  # ...unchanged attributes
}
```

```bash
terraform plan -target='proxmox_virtual_environment_vm.<name>' -out=resize.tfplan  # confirm ONLY size changes
terraform apply resize.tfplan
```

**No manual `qm resize` step is needed** — unlike `hostpci`/`device_passthrough` (Gotchas 10/12
above), a plain disk resize is not a permission gap the scoped API token hits; the provider
applies it directly via API, no root SSH involved.

**No `growpart`/`resize2fs` inside the guest either, and no reboot** — Debian's cloud image
ships `systemd-growfs`, which reacts to the live block-device size change and grows the
partition + filesystem automatically, seemingly triggered by the udev "change" event the
resize generates rather than requiring a fresh boot. Confirmed via `df -h /` before and after
with no guest-side commands run at all: available space jumped from ~800MB to 22GB within
moments of the `terraform apply` completing.

Verify both layers, not just one: `qm config <vmid> | grep scsi0` on the Proxmox host confirms
the real underlying disk grew (not just Terraform state), and `df -h` inside the guest
confirms the filesystem actually grew too (not just the block device). Finish with an
untargeted `terraform plan` — it should show zero drift, confirming the `-target` apply didn't
leave anything else out of sync.

This is specifically about a disk already in active use as a live filesystem on a modern
Debian cloud image (GPT partition table with the growfs auto-resize attribute). A non-root
data disk, an older/non-cloud image, or a non-GPT layout may still need manual
`growpart`/`resize2fs` — don't assume the zero-touch behavior generalizes without checking
`df -h` after the fact regardless of which case applies.
