---
name: proxmox-pbs-backup-job
description: This skill should be used when adding a new host (LXC or VM) to an existing Proxmox Backup Server nightly backup schedule, creating a vzdump job via `pvesh`, debugging a backup job that succeeds but the prune step fails with a permission error, excluding one specific mount point (e.g. a bulky media/data volume) from an LXC's backup while still backing up its rootfs, setting up PBS-to-PBS replication via a Remote + Sync Job (a second physical PBS instance holding a pulled copy of another datastore), a PBS API token that returns `{}` from `/access/permissions` despite a correct-looking ACL grant, `apt update` failing with `401 Unauthorized` against `enterprise.proxmox.com` on a no-subscription PBS install, or restore-testing a PBS datastore/replica by restoring to a throwaway VMID/CTID. Trigger phrases include "add backup job pvesh", "vzdump schedule new host", "pbs prune permission denied", "Datastore.Modify Datastore.Prune missing", "backup job finished with errors", "proxmox-backup-client prune permission check failed", "exclude mount point from backup", "mp0 backup=0", "vzdump exclude volume", "pbs remote sync job", "proxmox-backup-manager sync-job create", "pbs replica second instance", "pbs api token permissions empty", "access/permissions returns empty object", "pbs enterprise repo 401 unauthorized", "pbs-enterprise.sources", "restore test throwaway ctid", "pct restore verify backup", "querying namespaces failed permission check", "pbs sync job remove-vanished".
---

# Adding a host to an existing PBS nightly backup schedule

Use this when a new LXC/VM needs to join an existing Proxmox Backup Server datastore's nightly
backup rotation (as opposed to setting up PBS or a datastore from scratch — that's a bigger,
one-time task). Verified end-to-end adding the Homepage dashboard (VMID 140) to an existing
`pihole-and-friends` datastore already backing up Pi-hole and Home Assistant.

## Create the job via `pvesh`, not by hand-editing `/etc/pve/jobs.cfg`

`pvesh` is available directly on the Proxmox host (`pve`) even though it isn't installed on the
PBS host itself — backup jobs are configured cluster-side (`/etc/pve/jobs.cfg`), not on PBS.
Match whatever schedule offset and retention the existing jobs already use rather than
inventing new values:

```bash
# Check what's already scheduled first, so the new job doesn't collide:
pvesh get /cluster/backup --output-format json

pvesh create /cluster/backup \
  --vmid <new-vmid> \
  --storage <existing-pbs-storage-name> \
  --mode snapshot \
  --schedule 'sun..sat HH:MM' \
  --enabled 1 \
  --comment '<Host> nightly backup to PBS' \
  --prune-backups keep-daily=7,keep-weekly=4
```

Stagger the schedule time a few minutes after the last existing job in the same datastore (e.g.
`03:00`, `03:15`, `03:20`) rather than running them concurrently.

## Always manually trigger the new job once — don't just wait for the cron schedule

A scheduled job succeeding tonight doesn't confirm the *prune* step works (see the gotcha below;
prune can fail silently in a way that only shows up in the task log, not as a missing backup).
Trigger it for real and read the full output:

```bash
vzdump <vmid> --storage <storage> --mode snapshot --prune-backups keep-daily=7,keep-weekly=4
```

Look for `Backup job finished successfully` at the end, not just `Duration: ...` after the
upload — a failed prune still uploads the backup fine and only fails on the line after.

## Gotcha — the backup service account can lack `Datastore.Prune`, and this fails silently per-job, not fleet-wide

A PBS service account scoped with only `DatastoreReader` + `DatastoreBackup` (a reasonable-looking
least-privilege choice) can successfully upload backups indefinitely while **every prune step
fails**:

```
ERROR: prune 'ct/<vmid>': proxmox-backup-client failed: Error: permission check failed - missing Datastore.Modify|Datastore.Prune on /datastore/<name>
INFO: Backup job finished with errors
```

This is easy to miss because the backup itself (the part anyone actually checks — "did last
night's backup run?") succeeds every time; only the prune line fails, silently accumulating
backups past the configured retention. **This is a shared-account permission, so if it's missing
it's missing for every job on that datastore, not just the new one** — check by manually
triggering an *existing* job (e.g. the oldest one) after the fix, not just the new one, to
confirm the fix actually resolved a fleet-wide gap rather than something scoped to the new host.

Fix: grant `DatastorePowerUser` (read + backup + prune + verify — the PBS role designed
specifically for an automated backup account that also manages its own retention) on the
datastore path:

```bash
proxmox-backup-manager acl update /datastore/<name> DatastorePowerUser --auth-id <backup-user>@pbs
```

`acl update` is additive — it doesn't need the old narrower roles removed first, though they
become redundant once `DatastorePowerUser` is in place.

**This is a permission escalation on a shared credential, not a scoped fix for one job** — it
affects every existing backup job using that account. Flag it and get explicit confirmation
before applying, don't fix it silently as a side effect of an unrelated task.

## Excluding one mount point from backup (e.g. a bulky media/data volume)

A container with a separate large data mount (media library, scratch data, anything bulky and
reproducible from elsewhere) usually shouldn't have that volume backed up nightly alongside the
small rootfs — it wastes datastore space backing up content that isn't actually irreplaceable.
Proxmox supports this per-mount-point, not just per-container:

```bash
pct set <vmid> -mp0 local-zfs:subvol-<vmid>-disk-1,mp=/mnt/media,size=500G,backup=0
```

Proxmox's default for a *volume* mount point (as opposed to a bind-mount of an existing host
directory) is backed-up-by-default when the `backup` flag is absent — you have to set
`backup=0` explicitly to exclude it. If provisioning this container via Terraform's
`bpg/proxmox` provider, **don't trust `mount_point.backup = false` in the `.tf` config alone** —
see that skill's Gotcha 11: the attribute can be recorded in Terraform state without the real
`backup=0` flag landing in `/etc/pve/lxc/<vmid>.conf`. Always verify directly:

```bash
grep ^mp0 /etc/pve/lxc/<vmid>.conf   # must show `,backup=0` explicitly
```

Confirm the exclusion actually works by triggering a real backup and reading the log, not just
the config file — the log line makes it unambiguous:

```
INFO: including mount point rootfs ('/') in backup
INFO: excluding volume mount point mp0 ('/mnt/media') from backup (disabled)
```

If a mount point isn't irreplaceable (e.g. it holds the only copy of something), don't exclude it
from backup without a separate backup plan for that content — flag this explicitly rather than
silently trading data safety for datastore space.

## A datastore needs a `gc-schedule` set explicitly — it is not on by default

Creating a PBS datastore (`proxmox-backup-manager datastore create`) does **not** set up
automatic garbage collection. Per-job `--prune-backups` only updates snapshot *metadata*
(marks old snapshots for removal per retention) — it does not reclaim the underlying chunk-store
disk space. Without a scheduled GC, deleted/superseded chunks accumulate forever and the
datastore can silently fill to 100%, causing every subsequent backup job to fail with `No space
left on device`, even though retention/pruning has been "working" the whole time. Check with:

```bash
proxmox-backup-manager datastore show <name>   # look for a gc-schedule row; if absent, none is set
```

Fix — set one at datastore creation time, not as an afterthought:

```bash
proxmox-backup-manager datastore update <name> --gc-schedule 'sun 04:00'
```

**GC is two-phase and won't reclaim space on its first run after a big deletion.** Phase 1 marks
chunks referenced by *current* backup indices; phase 2 sweeps everything else, but only actually
deletes chunks whose access-time is *older* than a safety cutoff (default ~1 day + 5 min) — chunks
touched more recently are left as "pending removal" to avoid racing a backup that's still
mid-upload. A GC run right after deleting several groups can report `Removed garbage: 0 B` while
also reporting `Pending removals: NN GiB` — this is expected, not a bug; a second GC run once the
cutoff clears (usually within ~24h of the chunks' last real use) actually frees the space. Don't
assume GC "didn't work" from a 0 B removal on the first pass — check `Pending removals` in the
output.

## Monitor datastore disk usage — a full datastore fails every job at once with no advance warning

Nothing about `pvesh get /cluster/backup` or a single job's own history surfaces that the
*datastore itself* is nearly full — every guest's job just starts failing with `No space left on
device` the night it tips over 100%, with no warning the nights before. If a nightly/weekly
backup-status check doesn't already cover this, add a `df -h <datastore-path>` (or the PBS API's
datastore status endpoint) threshold check (e.g. warn at 80%, fail at 90%) — this is the single
highest-leverage check for catching the failure mode below before it happens, rather than
diagnosing it after the fact. Hit this for real 2026-07-19: `pihole-and-friends` hit 100% used
(93GB/98GB) overnight, failing Homepage/n8n/Immich's jobs simultaneously; root cause was two
compounding gaps — no `gc-schedule` (above) plus stale backups for four services decommissioned
days earlier never pruned (see next section) — neither of which any monitoring caught until
backups actually started failing. The homelab project's nightly backup summary
(`backup-status-checks.sh`) now implements exactly this check (added same day) — use it as a
reference implementation (a plain `df --output=pcent`/`--output=avail` SSH call, two thresholds,
feeding into the same overall-status/follow-up-prompt machinery as its per-job checks) rather
than reinventing the shape for a new project.

## When decommissioning a guest, its PBS backups don't disappear with it — decide on them explicitly

Destroying a VM/LXC via Terraform/`pct destroy`/`qm destroy` does **not** touch its existing PBS
backups — they sit in the datastore under their own group (`ct/<vmid>` or `vm/<vmid>`) consuming
real disk space indefinitely, since nothing is left to trigger their retention-based pruning
(that only happens as a side effect of a *new* backup running via `--prune-backups`, which will
never happen again for a destroyed guest). "Let them age out naturally per retention" is not
actually true for a decommissioned guest — there is no more pruning happening, so they simply sit
there consuming datastore capacity forever unless removed explicitly. Delete a decommissioned
guest's backup group via the PBS API (no CLI subcommand exists for this as of this writing):

```bash
# from the PBS host itself, using a scoped API token (create one, grant DatastoreAdmin
# on /datastore/<name>, delete both when done — see below)
curl -sk -X DELETE \
  -H "Authorization: PBSAPIToken=<tokenid>:<secret>" \
  "https://localhost:8007/api2/json/admin/datastore/<name>/groups?backup-type=<ct|vm>&backup-id=<vmid>"
# response: {"data":{"protected-snapshots":0,"removed-groups":1,"removed-snapshots":N}}
```

If you don't already have a token scoped for datastore admin, mint a short-lived one and delete
it again afterward rather than widening a long-lived credential's scope:

```bash
proxmox-backup-manager user generate-token root@pam housekeeping-tmp --comment '<why, and expected deletion>'
proxmox-backup-manager acl update /datastore/<name> DatastoreAdmin --auth-id 'root@pam!housekeeping-tmp'
# ... do the deletes ...
proxmox-backup-manager acl update /datastore/<name> DatastoreAdmin --auth-id 'root@pam!housekeeping-tmp' --delete
proxmox-backup-manager user delete-token root@pam housekeeping-tmp
```

This is a real, deliberate decision point, not a formality — add "prune PBS backups for the
decommissioned guest (or explicitly note you're keeping them and for how long)" to whatever
decommission checklist you're following, alongside the already-standard Prometheus/Homepage/
Pi-hole-DNS/Tailscale-device cleanup steps. Run GC (above) afterward to actually reclaim the
freed chunks.

**Checking whether a group exists at all doesn't need a token.** Before minting a temp
DatastoreAdmin token just to *check*, it's simpler to look at the datastore's own directory
layout directly (root SSH to the PBS host is enough — no API, no token):

```bash
ssh pbs "find /<datastore-path>/vm /<datastore-path>/ct -maxdepth 1 -mindepth 1 -type d"
# e.g. /mnt/pbs-datastore/vm/145, /mnt/pbs-datastore/ct/101 -- the trailing number is the vmid
```

Each backup group is just a `vm/<vmid>` or `ct/<vmid>` directory — `grep` the output for the
vmid you care about. Reserve the token-minting dance above for the actual delete, once you've
confirmed via this read-only check that there's something to delete. Used this in
`homelab-ansible/scripts/decommission-touchpoint-check.sh` (see the homelab's
`project_ansible_graduation_catalog` memory) — also where a variable named `GROUPS` turned out
to silently misbehave (it's a bash built-in special variable, an array of the process's Unix
groups); name it something else.

## Setting up a second, physically separate PBS instance as a pulled replica (Remote + Sync Job)

Full workflow verified end-to-end 2026-08-27 building a resilience-node replica: a fresh PBS
install pulling a copy of an existing datastore from a primary PBS instance, then restore-tested
for real. Applies whether the replica is another Proxmox VM or, as here, bare-metal (any Debian
box `apt install proxmox-backup-server` on).

**Direction matters — the replica runs the Sync Job, not the primary.** PBS Sync Jobs *pull*:
whichever instance holds the destination datastore is the one that must have the Remote (pointing
at the source) and the Sync Job configured on it. Configuring the Remote+Sync Job on the primary
instead (pointing at the replica) pulls data the wrong direction. `--sync-direction` defaults to
`pull`; leave it that way.

```bash
# On the REPLICA (destination) instance:
# 1. Create a dedicated least-privilege user+token on the PRIMARY (source):
proxmox-backup-manager user create sync-replica@pbs --comment "read-only, used by <replica> sync job"
proxmox-backup-manager user generate-token sync-replica@pbs <token-name> --comment "..."
# See the token-permission gotcha below -- grant the ACL to BOTH the user and the token:
proxmox-backup-manager acl update /datastore/<name> DatastoreReader --auth-id 'sync-replica@pbs'
proxmox-backup-manager acl update /datastore/<name> DatastoreReader --auth-id 'sync-replica@pbs!<token-name>'

# 2. Get the primary's cert fingerprint (self-signed, needed to register the Remote):
proxmox-backup-manager cert info | grep -i fingerprint

# 3. On the replica: register the primary as a Remote, then create the Sync Job:
proxmox-backup-manager remote create <remote-name> --host <primary-ip> --port 8007 \
  --auth-id 'sync-replica@pbs!<token-name>' --password '<token-secret>' --fingerprint '<fp>'
proxmox-backup-manager sync-job create <job-id> --store <replica-datastore> \
  --remote <remote-name> --remote-store <primary-datastore> \
  --schedule '06:00' --remove-vanished true
proxmox-backup-manager sync-job run <job-id>   # trigger once manually, don't just wait for cron
```

`--remove-vanished true` keeps the replica's retention actually tracking the primary's pruning
instead of accumulating independently — matches the whole point of it being a *replica*, not a
second, separately-retained archive. Set `gc-schedule` on the new datastore too (see the section
above) — a fresh datastore is exactly as exposed to the "never had a gc-schedule" incident as
the original was.

**Use the primary's LAN IP for the Remote, not its Tailscale hostname**, if the replica's own
DNS resolution doesn't go through something Tailscale-aware (e.g. it points at a plain Pi-hole
that only does recursive resolution, not MagicDNS). `*.ts.net` names don't resolve through a
generic recursive resolver — confirmed 2026-08-27, `Querying namespaces failed - client error
(Connect)` when the remote's `--host` was a `.ts.net` name the replica genuinely couldn't
resolve. Both instances on the same LAN subnet makes this moot anyway; use the IP.

### Gotcha — a PBS API token's permissions are capped by its *parent user's own* ACL, not just the token's

Granting an ACL to the token itself (`user@realm!tokenname`) is not sufficient on its own — if
the owning user (`user@realm`) has zero ACL entries of its own, the token's effective
permissions are also zero, **even though the token's own ACL entry looks completely correct**.
Confirmed 2026-08-27: `sync-job run` failed with `Querying namespaces failed - HTTP error 403
Forbidden - permission check failed`, and `curl`ing `/api2/json/access/permissions` directly with
the token returned `{"data":{}}` — an authenticated (200 OK) but *empty* permission set — despite
`proxmox-backup-manager acl list` clearly showing the token's own `DatastoreReader` grant on the
right path. Fix confirmed: grant the **same role to the plain user**, not just the token
(`proxmox-backup-manager acl update /datastore/<name> DatastoreReader --auth-id 'sync-replica@pbs'`,
no `!tokenname` suffix) — permissions immediately populated correctly afterward. Always grant
both when creating a scoped service token from scratch; a token-only grant that "looks right" in
`acl list` will still silently produce zero access.

### Gotcha — `proxmox-backup-server`'s own postinst adds the paid enterprise repo, which 401s on a no-subscription install

A fresh `apt install proxmox-backup-server` can leave
`/etc/apt/sources.list.d/pbs-enterprise.sources` in place (pointing at
`https://enterprise.proxmox.com/debian/pbs`), which requires a paid subscription — every
subsequent `apt update` fails outright with `401 Unauthorized`, blocking *all* package updates on
the host, not just PBS's own. An existing no-subscription PBS install elsewhere in the same fleet
may never have hit this (e.g. if it was built by a slightly different install sequence) — don't
assume a sibling host's clean `apt update` means this file won't be present on a new one; check
`ls /etc/apt/sources.list.d/` directly. Fix: `rm /etc/apt/sources.list.d/pbs-enterprise.sources`
— the `pbs-no-subscription` repo (set up separately per the standard no-subscription install
steps) is sufficient on its own.

### Restore-testing a replica for real, not just trusting "sync completed"

A sync job reporting success only proves bytes transferred, not that they're restorable. Prove
it with an actual restore to a throwaway VMID/CTID on a real Proxmox host, then tear it down:

```bash
# On a Proxmox VE host (pve), add the PBS replica as a temporary storage backend:
pvesm add pbs <temp-storage-name> --server <replica-ip> --port 8007 \
  --username '<user>@pbs!<token>' --password '<token-secret>' \
  --datastore <replica-datastore> --fingerprint '<replica-cert-fingerprint>'
pvesm list <temp-storage-name>   # confirm real snapshot history is visible

# Restore the most recent snapshot of some small, low-risk guest to an unused VMID:
pct restore 999 '<temp-storage-name>:backup/ct/<vmid>/<timestamp>' \
  --storage local-zfs --unprivileged 1 --hostname restore-test-999
pct set 999 --delete net0   # no network interface at all -- see the gotcha below
pct start 999
pct exec 999 -- systemctl is-active <the-guest's-main-service>   # confirm it's genuinely running, not just booted; pct exec needs no network

# Clean up immediately -- this was a throwaway, not a new permanent guest:
pct stop 999 && pct destroy 999
pvesm remove <temp-storage-name>
proxmox-backup-manager user remove <temp-restore-test-user>@pbs   # if a separate scoped user was minted for this
```

Confirming a real service is `active` inside the restored container (not just that `pct start`
returned success) is what actually proves the backup is usable — a container can boot with a
corrupted or incomplete application config and still show as "running." `pct exec` works purely
through Proxmox's own attach mechanism and needs no network path at all, so there's no reason to
give the restored container one.

**Go one level further than `is-active`: assert the service's *function*** (2026-09-12). A unit can be
active on an empty or broken dataset. Per-guest assertions that work with no network, all via `pct
exec` or loopback inside the guest:

| Guest type | Assertion |
|---|---|
| Pi-hole | resolves a known Local DNS Record via `dig @127.0.0.1` |
| Caddy | :443 on loopback presents the expected wildcard cert CN |
| Grafana | health DB ok, provisioned alert rules > 0 |
| n8n | `/healthz` 200, and the workflow count in its DB is > 0 |
| Laravel app | `/up` 200, and a core table row count is > 0 |
| SQLite-backed services (HA recorder, credential brokers) | `pragma quick_check` = ok and key tables non-empty |
| A service bound only to an address the clone can't have (e.g. a Tailscale IP) | skip the socket and assert its data store instead |

**Prove each assertion can fail.** Run guest A's check inside guest B's restored container, where it must
fail (e.g. rc 4 "no such unit"), while it passes in its own. Without that control, a check that always
returns 0 looks identical to a working one. Run guests one at a time, checking host memory first, and
confirm no throwaway CTID or VMID is left afterwards.

### Gotcha — giving the restored container *any* network path risks a live Tailscale identity collision with the real guest, even with a fresh MAC

A restored container's disk is a byte-for-byte copy of the real guest's, including
`/var/lib/tailscale` — its live Tailscale node key comes along for the ride. Tailscale identifies
a device by node key, not IP or MAC, so giving the restored container *any* route out (even
`pct set --net0 ...,ip=dhcp,type=veth` with no `hwaddr` specified, which correctly avoids a MAC
conflict) still lets its `tailscaled` phone home using the exact same identity as the real, live
guest — a genuine identity collision, not just an IP conflict. Confirmed live 2026-08-29: restore-
testing `ansible-ctrl` this way hijacked the real `ansible-ctrl`'s own MagicDNS entry mid-test,
which broke a restore-test *script running on ansible-ctrl itself*'s route to `pve`, cascading
into false failures on every guest tested after it and leaving the clone orphaned (no automatic
teardown could run once connectivity broke). The real `ansible-ctrl` was unaffected once the
clone was destroyed — but this can silently hit any guest, not just automation hosts, wherever
something else depends on that guest's Tailscale identity being stable during the test window.

**Fix: give the restored container no network interface at all** (`pct set <ctid> --delete net0`
after restore, before start) rather than a freshly-MAC'd one — `pct exec` doesn't need it.
Verified: with no net0, `tailscaled` still starts as a process but reports `unexpected state:
NoState` / "network is down" via `tailscale status` — it has no path to the coordination server,
so the collision becomes structurally impossible rather than just less likely. If a restore-test
genuinely needs real network reachability for some other reason, mask `tailscaled` inside the
guest before starting it (`pct exec <ctid> -- systemctl mask tailscaled`) as a second layer, but
prefer no network path at all when the check doesn't require one.

**If you're automating this** (not just running it by hand once), wrap the whole per-guest cycle
in a `trap ... EXIT`-based cleanup, not just an inline `pct stop && pct destroy` at the end of the
happy path — a mid-run failure (this Tailscale collision itself, or an SSH blip, or anything else)
can skip straight past inline cleanup and leave the throwaway container running indefinitely with
no supervision, which is exactly what compounded the incident above.
