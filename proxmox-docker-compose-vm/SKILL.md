---
name: proxmox-docker-compose-vm
description: This skill should be used when deploying an application that only ships via Docker Compose (no native/bare-metal install path — e.g. Immich, and similar multi-container stacks with a custom database extension baked into a maintained image) inside a Proxmox VM, managing its Docker Compose file and secrets as code via Ansible, debugging a Compose service that's unexpectedly reachable on the plain LAN IP instead of only over Tailscale Serve, wiring up a hardware-acceleration `extends:` stanza (hwaccel.yml, OpenVINO/VAAPI image tags) that ships commented-out in the upstream Compose file, or exposing one feature of an otherwise tailnet-only app (e.g. Immich share links) to people outside the tailnet via a purpose-built proxy sidecar + narrow Funnel rather than punching a hole in the app's own API. Also covers verifying an async first-run job (ML indexing, search embedding, etc.) actually processed something rather than just checking container health, and a shared Ansible `file` loop silently drifting a sensitive directory's mode. Trigger phrases include "tailscale serve nftables allowlist not working", "restrict tailnet peers serve", "docker compose in a proxmox vm", "immich docker deployment", "no bare-metal install path", "docker compose ports binds 0.0.0.0", "docker-proxy 0.0.0.0", "ansible deploy docker-compose.yml", "verify smart search indexed", "async job queued but not verified", "second disk for docker volumes proxmox", "hwaccel.yml extends", "immich openvino image tag", "docker compose hardware acceleration", "share immich link outside tailnet", "immich public proxy", "expose one path publicly without exposing the app", "funnel to a proxy not the app".
---

# Docker Compose stack in a Proxmox VM (not an LXC)

Use this when an app's *only* supported deployment path is Docker Compose — no native
package, no bare-metal tarball (unlike e.g. Paperless-ngx, which has one). This homelab
otherwise avoids Docker everywhere (Grafana, Homepage, n8n, Jellyfin, Paperless-ngx all run
as native systemd services specifically to dodge Docker-in-unprivileged-LXC cgroup quirks —
see the `proxmox-node-systemd-service` skill). When Docker is genuinely unavoidable, run it
in a **VM**, not an LXC, and contain the exception there rather than fighting cgroups. Built
and verified end-to-end deploying Immich (`immich-app/immich`, VMID 145, v3.0.3) — every
gotcha below was hit for real, not theoretical.

**VM creation itself** (cloud-init staleness, `qemu-guest-agent` needed before
`generate-config-out`, cleaning up the generated Terraform config) is covered by the
`proxmox-terraform-provisioning` skill, not repeated here — this skill picks up once the VM
exists and boots with working networking.

## Install sequence

1. **Docker CE + Compose plugin from Docker's official apt repo**, not the Debian repo
   (`docker.io` package) or a distro-bundled `docker-compose` — Compose v2 (the `docker
   compose` subcommand, not the legacy hyphenated `docker-compose` binary) is what modern
   Compose files assume:

   ```yaml
   - name: Add Docker GPG key
     ansible.builtin.get_url:
       url: https://download.docker.com/linux/debian/gpg
       dest: /etc/apt/keyrings/docker.asc
       mode: '0644'

   - name: Add Docker apt repository (deb822)
     ansible.builtin.copy:
       content: |
         Types: deb
         URIs: https://download.docker.com/linux/debian
         Suites: {{ ansible_distribution_release }}
         Components: stable
         Architectures: amd64
         Signed-By: /etc/apt/keyrings/docker.asc
       dest: /etc/apt/sources.list.d/docker.sources
       mode: '0644'
     register: docker_repo

   - name: Install Docker CE + Compose plugin
     ansible.builtin.apt:
       name: [docker-ce, docker-ce-cli, containerd.io, docker-buildx-plugin, docker-compose-plugin]
       state: present
       update_cache: "{{ docker_repo.changed }}"
   ```

2. **A dedicated second disk for Docker volumes, not the OS disk**, if the app stores real
   data (photo library, database). Format and mount it, then point the app's data paths at
   it:

   ```yaml
   - name: Check if data disk is already formatted
     ansible.builtin.command: "blkid {{ data_disk }}"   # e.g. /dev/sdb
     register: data_disk_blkid
     failed_when: false
     changed_when: false

   - name: Format data disk (ext4)
     community.general.filesystem:
       fstype: ext4
       dev: "{{ data_disk }}"
     when: data_disk_blkid.rc != 0

   - name: Mount data disk (persistent via fstab)
     ansible.posix.mount:
       path: "{{ data_mount }}"
       src: "{{ data_disk }}"
       fstype: ext4
       state: mounted
   ```

   Confirm the disk device name from inside the guest first (`lsblk`) rather than assuming
   `/dev/sdb` — it follows creation order of the VM's SCSI disks (`scsi0` → `sda`, `scsi1` →
   `sdb`, etc.), which is predictable but worth a direct check, not an assumption.

3. **Fetch the app's real `docker-compose.yml`/`.env.example` from its release tag**, don't
   hand-write one from memory or an older cached version — Compose file structure and image
   names change between major versions (Immich's v3 line switched its Redis image to Valkey
   and its Postgres image name/tag, for example):

   ```bash
   gh api "repos/<org>/<repo>/contents/docker/docker-compose.yml?ref=v<version>" --jq '.content' | base64 -d
   ```

   Commit the file into the Ansible repo (`files/<app>/docker-compose.yml`) as close to
   verbatim as possible, documenting any deliberate deviation in a comment (see Gotcha 1
   below for the one deviation this skill requires).

4. **Render secrets via a `.env` Jinja2 template, not a committed plaintext file** — same
   pattern as this fleet's other apps (n8n's encryption key, Immich's DB password): generate
   once with `openssl rand -hex <n>` into a root-owned `600` file on the Ansible control node,
   read it via a `lookup('file', ...)` var, template it into `.env` on the target host with
   mode `'0600'`. Never print the generated secret to stdout/chat.

## Gotcha 1 — Compose's short-form `ports:` publishes to `0.0.0.0` by default

```yaml
# WRONG -- reachable on the plain LAN IP too, not just Tailscale
ports:
  - '2283:2283'

# RIGHT
ports:
  - '127.0.0.1:2283:2283'
```

Same "binds everywhere by default" family as Next.js/Jellyfin's LAN-binding gotcha (see
`proxmox-node-systemd-service`), just via Docker's port-publishing syntax instead of an
app-level CLI flag or config value. `docker compose ps`/`docker ps` show the mapping as if
it's fine either way — nothing looks wrong until a negative reachability check from another
LAN host succeeds when it shouldn't (see Verification below). This is the one deliberate
deviation from the upstream Compose file worth noting in a comment when committing it.

Confirm the fix landed with `ss -tlnp | grep <port>` on the host after `docker compose up` —
look for `127.0.0.1:<port>` in the listen address, not `0.0.0.0:<port>` — before trusting the
Compose file diff alone.

## Gotcha 2 — container health does not prove an async first-run job actually worked

`docker compose ps` reporting every container `healthy` only proves the *processes* are up —
it says nothing about whether an app's own background pipeline (ML indexing, search
embedding, thumbnail generation, etc.) has actually run for real data yet. Concretely: an
asset uploaded to Immich via a raw API call got a thumbnail immediately, but its smart-search
(CLIP embedding) job never auto-queued the way it does for uploads through the normal
mobile/web client flow — `GET /api/jobs` showed `waiting: 0, active: 0, completed: 0` for
`smartSearch` indefinitely, with no error anywhere.

**Verify the feature, not just the job queue.** If a job queue shows nothing queued for an
action that should have triggered one, don't assume it's fine — either replicate through the
app's real client flow, or manually trigger the job via its admin API (Immich:
`PUT /api/jobs/<jobName>` with `{"command":"start","force":true}`) and then confirm the
*downstream effect*, not just that the queue drained: e.g. run the actual search query and
check the expected asset comes back, rather than trusting `jobCounts.completed` incrementing
alone (queue "completed" counters are often not retained for long in BullMQ-style queues, so
`completed: 0` after a job clearly ran isn't itself evidence of failure — check the real
output instead).

## Gotcha 3 — hardware acceleration is often already anticipated, just commented out

Before writing custom `devices:`/image-tag config for GPU acceleration from scratch, check
whether the upstream Compose file already anticipates it — Immich's does, via commented-out
`extends:` stanzas referencing separate release-artifact files:

```yaml
services:
  immich-machine-learning:
    image: ghcr.io/immich-app/immich-machine-learning:${IMMICH_VERSION:-release}
    # extends: # uncomment this section for hardware acceleration
    #   file: hwaccel.ml.yml
    #   service: cpu # set to one of [armnn, cuda, rocm, openvino, openvino-wsl, rknn]
```

`hwaccel.ml.yml`/`hwaccel.transcoding.yml` aren't in the repo checkout — they're separate
release-tagged download artifacts (`.../releases/download/<version>/hwaccel.ml.yml`) that
define the actual `devices:`/`deploy:` blocks per backend as named service fragments. To wire
up Intel iGPU acceleration: download both files pinned to the **same version** already in use
(mismatched versions can disagree on service/device shape), uncomment the `extends:` block
targeting `openvino` (ML) / `vaapi` (transcoding), and — separately from the `extends:`, which
only adds `devices: [/dev/dri:/dev/dri]` — switch the ML image tag itself to the accelerated
variant (`immich-machine-learning:<version>-openvino`, not just `<version>`); the `extends:`
block alone doesn't change which image ships, only its runtime device access. Deploy the two
downloaded files as static, version-controlled Ansible files (same pattern as
`docker-compose.yml` itself), not a one-off manual `curl` on the VM.

This assumes the GPU device is actually present in the VM in the first place — see the
`proxmox-vm-igpu-passthrough` skill for getting `/dev/dri` to exist at all inside a VM guest
(materially more involved than an LXC, which gets it for free via the host's kernel).

## Gotcha 4 — public sharing: use a purpose-built proxy sidecar, not a partial-path Funnel to the app itself

If an app needs to expose *one specific feature* to people outside the tailnet (Immich's
"share a link with someone who's not on my tailnet") while staying otherwise tailnet-only,
the instinct is to Tailscale-Funnel just that one path on the app's own port (the pattern
that works fine for a pure-API endpoint like n8n's `/webhook`). **This doesn't work for a
page that's part of a real frontend app**: Immich's `/share/:key` page is a SvelteKit route
that needs `/api/*` calls to load thumbnails/metadata client-side, so Funneling only
`/share` still leaves the page broken, and Funneling `/api/*` too punches a hole to the
*entire* authenticated API surface — confirmed via Immich's own reverse-proxy docs and a
GitHub discussion before building anything, not assumed.

**Fix: deploy a dedicated, purpose-built proxy sidecar as its own Compose service**, and
Funnel *that*, not the app. For Immich specifically:
[`alangrainger/immich-public-proxy`](https://github.com/alangrainger/immich-public-proxy)
(Docker Hub, pin a version tag e.g. `3.0.2`, not `:latest`) — it needs no Immich API key,
calls Immich read-only over the Docker network, and its entire route surface (confirmed by
reading its actual `src/index.ts`, not the README) is a closed set: `/share/:key`, `/s/:key`
(short alias), its own static assets, and a catch-all 404. Because that surface is
self-contained and safe by construction, it's fine to Funnel the *whole proxy app* rather
than trying to sub-scope it further:

```yaml
# Added alongside immich-server etc. in the same docker-compose.yml / network
immich-public-proxy:
  container_name: immich_public_proxy
  image: alangrainger/immich-public-proxy:3.0.2
  environment:
    IMMICH_URL: http://immich-server:2283       # reach the app by Compose service name
    PUBLIC_BASE_URL: https://<host>.<tailnet>:8443
  ports:
    - '127.0.0.1:3000:3000'                     # loopback only, same Gotcha 1 rule applies
  depends_on:
    - immich-server
  restart: always
```

```bash
# On the VM itself -- a second, narrow Funnel on its own port, same pattern as
# Grafana's /health and n8n's /webhook proxies elsewhere in this fleet. The app's
# main Serve URL (port 443) is completely untouched by this.
tailscale funnel --bg --https=8443 http://127.0.0.1:3000
```

Then set the app's own "external domain" setting (Immich: Administration → Settings →
Server settings → External Domain — not a guessable UI path, verify live rather than assume;
it moves between versions) to the Funnel URL, so the app's own "Copy Link" button generates
a working public URL directly instead of needing the domain hand-edited after copying.

**Verify from a genuinely external vantage** (not a tailnet member — see the n8n-webhook
precedent for why "this Mac" and the Ansible control node both fail as test vantage points):
the proxy's own healthcheck returns `200`; a direct probe at the app's real API through the
*same* Funnel port 404s (proves the proxy's catch-all, not the app, is what's answering); an
invalid/garbage share key also 404s cleanly rather than leaking anything or crashing.

## Gotcha 5 — a shared Ansible `file` loop can silently drift a security-sensitive directory's mode

Grouping "ensure these directories exist" into one loop with one shared `mode:` is a natural
simplification when scaffolding a data disk's subdirectories (`library/`, `postgres/`, etc.
in Immich's case) — but if the directories have genuinely different sensitivity
requirements, a mode chosen for one silently overwrites the other every time the play re-runs.
Concretely: `mode: '0755'` was fine for Immich's photo-library directory but wrong for its
Postgres data directory (Postgres data dirs must stay `0700`, non-group/world-accessible).
Re-running the install playbook for an unrelated change (adding the proxy sidecar above)
silently flipped the live `postgres/` directory to `0755` on disk — harmless immediately only
because the already-running Postgres container wasn't restarted by that same apply (it only
validates data-directory permissions at startup), but a future restart/reboot would have hit
it. **Split into separate `file` tasks per directory once their required modes diverge**,
even if it means a few more lines — a shared loop is only safe when every item genuinely
wants the same mode. Caught here via a routine `--check --diff` before applying (see the
`dry-run-before-scoped-playbook-test` habit), which is what surfaced the pre-existing drift
in the first place, not something specific to this change.

## Gotcha 6 — a bridge-mode container's `127.0.0.1` is its own loopback, not the host's

A compose stack that mixes `network_mode: host` (for a service that genuinely needs to bind
real host ports, e.g. Pi-hole needing raw port 53) with plain bridge-mode services (the
default, e.g. a monitoring tool like Uptime Kuma with a normal `ports:` mapping) has two
*different* loopback namespaces in play. From inside a bridge-mode container, `127.0.0.1`
resolves to that container's own loopback — never the Docker host's — so a monitor/health-check
configured to hit `127.0.0.1:<port>` for a *different*, host-networked service in the same
compose file will fail to connect, even though both containers are "on the same box" and even
in the same `docker compose` project. Confirmed 2026-08-27: an Uptime Kuma DNS monitor
(bridge-mode, default `ports: - "127.0.0.1:3001:3001"`) targeting Resolver Server `127.0.0.1`
for a host-networked Pi-hole container on the same host failed outright — fixed by pointing the
monitor at the host's real LAN IP instead, which bridge-mode containers *can* reach (Docker's
default bridge networking routes out to the host's real interfaces/LAN fine, it's specifically
the host's loopback-bound services that are unreachable this way). The fix is either point
cross-service checks at a real IP (LAN or the Docker bridge gateway) instead of `127.0.0.1`, or
put every service in the stack on `network_mode: host` if they all need to talk to each other
via true host loopback — don't assume `127.0.0.1` means the same thing everywhere in a mixed
bridge/host compose file.

## Backup: a Docker-Compose VM usually wants a full, unexcluded vzdump

Unlike Jellyfin's bulky, reproducible-from-elsewhere media mount (`backup=false` on that
`mount_point`, see `proxmox-pbs-backup-job`), an app's Docker volumes are typically its *only*
copy of real user data (photo library + database, in Immich's case) — back up the whole VM,
no exclusions, same nightly `pvesh`-scheduled vzdump pattern as everything else in this fleet.
Verify with a real manual `vzdump` and confirm the transferred size is consistent with actual
data present (a mostly-empty data disk will report as heavily "sparse" — that's expected and
fine, not a sign of a broken backup).

## Verification: positive AND negative reachability, plus the real feature

1. `docker compose ps` — every container healthy.
2. Real data test: upload/create something through the actual app (not just a config check),
   confirm it processed (thumbnail, transcode, whatever the app's basic pipeline is).
3. The async-job check from Gotcha 2, if the app has one.
4. Tailscale Serve reachable from a genuine tailnet device.
5. **Negative check**: `nc -zv <lan-ip> <port>` (or `curl` with a timeout) from a different
   LAN host — expect refused/timeout, not a response. This is the only reliable proof Gotcha
   1 didn't slip through.
6. A real manual `vzdump` completes and the backup log doesn't show an unexpected exclusion.

## Gotcha 7 — in-guest nftables cannot restrict who reaches a Tailscale Serve port

Serve accepts the connection inside `tailscaled` (netstack), ahead of the kernel's input hook, so
an `iifname "tailscale0" tcp dport 443 ip saddr {...} accept; ... drop` allowlist filters nothing.
Proven 2026-10-03 on `hindsight` (VM 113): the rule was loaded, yet a non-listed peer got HTTP 200,
while the same table's `eth0` rules (SSH, 9100) worked. To limit tailnet reachability of a Serve
service, use the **app's own auth** (Hindsight: `ApiKeyTenantExtension`, 401 without the key) or
a **Tailscale ACL/grant**. ACLs only allow, so on an allow-all policy that means making the whole
policy explicit, which is Will's call in the admin console. Always test a non-listed peer before
claiming an inbound restriction. If you keep nftables for LAN-side rules, give it its **own table**
and flush only that table. Debian's `/etc/nftables.conf` starts with `flush ruleset`, which would
also wipe Docker's and Tailscale's rules.

## Gotcha 8 — a compose-file edit does not always restart anything; gate post-restart checks on it

`docker compose up -d` recreates a container only when its effective config changes. A comment, or an
edit to another service, leaves it running. A playbook that, on "compose file changed", then requires a
startup log line (e.g. Infisical's "Migrations completed successfully") fails against a container that
correctly did not restart. Found 2026-10-06 on the first exercise of `infisical-server.yml`. Record the
container ID (`docker inspect -f '{{.Id}}'`) before `up -d`, compare after, and run the startup checks
only if it changed. Order for an image bump: validate (`compose config -q`), `pull` while the old
version still serves, back up, `up -d`, wait for health, then check startup logs since the restart time.
