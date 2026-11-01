# claude-code-skills

Willie Jackson's Claude Code skills — infrastructure, Cloudflare development, and web/design
utilities. Distinct from [`claude-skills`](https://github.com/jackson2w/claude-skills), which
holds a separate catalog (11ty sites, document formats, presentation/spreadsheet tooling) used
with Cowork and Claude Code.

Drop any of these directories into `~/.claude/skills/` (or a project's `.claude/skills/`) and
Claude Code auto-discovers them — no install step beyond having the `SKILL.md` on disk.

## Proxmox / homelab infrastructure

- **proxmox-ansible-provisioning** — creating a new Proxmox LXC/VM and writing Ansible playbooks
  against Proxmox/Debian hosts (Debian 13/trixie locale and `apt_repository` gotchas, `lineinfile`
  idempotency traps, TUN passthrough for Tailscale in unprivileged LXCs).
- **proxmox-terraform-provisioning** — the `bpg/proxmox` Terraform provider: scoped API tokens,
  importing existing LXCs/VMs as a no-op baseline, and VM-specific gotchas (`SDN.Use`, disk
  import needing host SSH, appliance images like Home Assistant OS/pfSense with no cloud-init).
- **proxmox-node-systemd-service** — running a Node.js/pnpm app as a native systemd service in an
  unprivileged LXC instead of Docker: NodeSource install, Ansible git-module idempotency traps,
  and the "binds 0.0.0.0 by default" gotcha common to Next.js and similar frameworks.
- **proxmox-pbs-backup-job** — adding a new host to an existing Proxmox Backup Server nightly
  schedule via `pvesh`, and the `Datastore.Prune` permission gotcha that fails silently per-job.
- **home-assistant** — configuring/troubleshooting a Home Assistant OS (HAOS) instance: add-ons
  (now "Apps"), `configuration.yaml`, Tailscale remote access, Supervisor, backups.
- **paperless-ngx-bare-metal** — installing Paperless-ngx from its release tarball instead of
  Docker Compose: the tarball's real directory layout, the `mysqlclient` build dependency needed
  even for SQLite, Granian (not Gunicorn) as the ASGI server, and verifying OCR actually ran
  rather than just "upload succeeded."
- **jellyfin-media-permissions** — diagnosing "fatal player error" / empty-metadata library
  items caused by a macOS `rsync` pipeline leaving files unreadable by Jellyfin's service
  account (openrsync has no `--chown`/`--no-owner` flags).
- **pihole-local-dns-records** — getting Pi-hole's dashboard/Query Log to show device names
  instead of raw IPs, identifying unlabeled devices via mDNS/DHCP without router access, and
  why the dashboard label can lag a correct `dns.hosts` record.
- **proxmox-no-subscription-nag** — suppressing the "No valid subscription" login popup on a
  free/no-subscription PVE or PBS install.
- **proxmox-vzdump-notifications** — customizing Proxmox's Handlebars backup-notification
  templates and testing them without waiting for (or triggering) a real backup job.
- **proxmox-zfs-root-mirror** — converting a single-disk ZFS root pool (`rpool`) into a live
  mirror, swapping a drive out, and growing the mirror to full capacity — all via `zpool
  attach`/`detach`/`online -e`, no Proxmox reinstall or guest restore-from-backup needed.
- **tailscale-pihole-dns-routing** — the interaction between Tailscale's tailnet-wide DNS
  override, MagicDNS, and Pi-hole — why a host can silently bypass Pi-hole even though DNS
  still resolves, and the systemd-resolved split-DNS fix.
- **n8n-workflow-api-authoring** — authoring n8n workflow JSON for import via its REST API
  instead of the editor UI: credential/expression/Code-node gotchas that don't show up until
  a workflow actually runs.
- **proxmox-docker-compose-vm** — running an app that only ships as Docker Compose (Immich and
  similar multi-container stacks) inside a VM, with the Compose file and its secrets managed as
  code by Ansible, and the short-form `ports:` trap that publishes to `0.0.0.0`.
- **proxmox-vm-igpu-passthrough** — passing an Intel iGPU through to a VM via `vfio-pci` (as
  opposed to an LXC's device bind-mount): IOMMU group isolation, host-side binding, the Terraform
  `hostpci` block, and guest-side missing drivers/firmware.
- **proxmox-vm-crash-diagnosis** — a VM `stopped` with no shutdown task, or `running` but
  answering nothing: telling a slow boot from a hang, and confirming an OOM kill of the qemu
  process.
- **jellyfin-proxmox-deployment** — Jellyfin as an unprivileged LXC with QuickSync passthrough:
  the VM-vs-LXC call for a shared iGPU, the passthrough steps Terraform can't express, and
  excluding the media volume from backups.
- **laravel-filament-proxmox-lxc** — a Laravel + Filament v3 app as native PHP-FPM + Caddy in an
  LXC instead of Docker, plus a read-only Sanctum API for an external consumer and the
  mixed-content `asset()` trap behind Tailscale Serve.
- **forgejo-deployment** — self-hosted Forgejo as a native binary + systemd unit: the three
  required secrets, the permission-denied crash-loop from a locked-down config, and why its
  git-SSH server needs firewall scoping rather than an app-level bind address.
- **vaultwarden-deployment** — Vaultwarden via Docker on a bare VPS: loopback binding, Tailscale
  Serve exposure, the admin-token hashing tool's TTY requirement, and locking signups after the
  first account.
- **immich-sdcard-sync-prune** — a macOS launchd job that uploads a camera card to Immich on
  insert, and prunes assets deleted from the source: the CLI's non-obvious API key scopes and
  launchd's missing-Homebrew-PATH gotcha.
- **pihole-dot-upstream-failover** — adding DoT as a Pi-hole upstream while keeping a "DNS
  failures must surface" constraint intact: an alerted, non-silent failover watcher rather than
  a standing secondary resolver.
- **debian-kernel-reboot-check** — whether a host actually needs a reboot for a kernel update,
  including when `apt` reports nothing upgradable, and auditing a mixed LXC/VM/bare-metal fleet
  at once.

## Fleet operations

Monitoring, reporting, access, and secrets across the whole fleet rather than any one host.

- **grafana-prometheus-alerting** — turning a scrape-only Prometheus/Grafana stack into one that
  actually alerts: provisioned rules as code, fleet-wide systemd failure detection without a
  custom webhook, and testing a rule end-to-end before trusting it.
- **grafana-api-token-provisioning** — a least-privilege Grafana service account for a script,
  querying real alert-rule health via the API, and why a `fixed:alerting.rules:reader` role may
  not be assignable.
- **homelab-terminal-report-delivery** — the shared report system behind the weekly sweep and
  nightly backup digest: ledger-styled HTML email, Telegram, and a markdown archive, plus when to
  make Telegram primary to stay inside Postmark's free tier.
- **standalone-ansible-repo** — bringing a single hardened non-fleet host under Ansible via
  `ansible_connection=local`, without granting an existing controller a new privileged SSH path,
  and retrofitting a live hand-built host incrementally.
- **termius-fleet-ssh-setup** — Termius across a mixed LXC/VM/bare-metal/VPS fleet: hosts,
  snippets, startup snippets, and the SFTP session that silently lands in the home directory.
- **claude-code-headless-tool-restriction** — restricting tools in an unattended `claude -p`
  invocation as a real boundary: `--disallowedTools` is the one that enforces; `--allowedTools`
  alone does not.
- **infisical-secrets-manager** — migrating a credential off a plaintext `.env` onto self-hosted
  Infisical, provisioning a host machine identity, and auditing what still lives in plaintext.
- **credential-rotation-protocol** — rotating, replacing, or *removing* a live credential without
  leaking it while verifying: the consumer inventory, and the safe probes that confirm a value
  works without printing it.

- **forced-outage-drill** — simulating a dependency outage on a live host so a watcher/failover
  test means something: prove the block bites (counters + a control), container egress needs a
  forward-hook chain, defeat caches that hide the fault, dead-man revert, stubbed alerts, and
  old-vs-new watcher comparisons on a throwaway instance.

## Cloudflare

The skills from `cloudflare/skills` (cloudflare, wrangler, workers-best-practices, agents-sdk,
durable-objects, sandbox-stable, workers-profiling, turnstile-spin, web-perf, cloudflare-email-service,
cloudflare-one, cloudflare-one-migrations) are plain copies of upstream `1a33048` (2026-10-31), reviewed
2026-11-01: markdown only, no scripts. Update by re-copying each `skills/<name>/` directory. Left out on
purpose: `cf-cli` (the `cf` CLI is not adopted; Will's projects use Wrangler), and basin, k2,
gateway-workers, nextjs-on-cloudflare and sandbox-next/-migrate-to-next (no current use).

- **cloudflare** — general-purpose Cloudflare platform skill: Workers, Pages, KV/D1/R2, Workers
  AI, networking, security, infra-as-code.
- **cloudflare-r2-rclone-backup** — nightly offsite backups to R2 via rclone's S3-compatible API
  (the `--delete` flag trap, `-v`/`--log-level` conflict, R2's `501 NotImplemented` on modtime
  fixups).
- **cloudflare-cron-telegram-alert** — scaffolding a cron-triggered Worker that checks something
  external and alerts to Telegram only on failure (uptime monitors, dead-man's-switches).
- **cloudflare-workers-cron-email** — debugging Cron Triggers that don't fire (or fire on the
  wrong day), `send_email` binding setup, subrequest limits, R2 rename/delete verification.
- **cloudflare-pages-gotchas** — Pages Functions platform quirks: no Images binding, empty
  `[env.*]` blocks dropping bindings, PBKDF2's 100k-iteration cap, `_redirects` precedence.
- **cloudflare-email-service** — transactional email via Cloudflare Email Service (sending +
  routing), SPF/DKIM/DMARC, any runtime (Workers, Node, Python, Go).
- **cloudflare-one** / **cloudflare-one-migrations** — Zero Trust/SASE design and migrations from
  Zscaler/Palo Alto/legacy VPN stacks.
- **agents-sdk** — stateful agents, Durable Workflows, MCP servers, and voice/chat apps on the
  Cloudflare Agents SDK.
- **durable-objects** — stateful coordination (chat rooms, booking systems), RPC methods, SQLite
  storage, alarms.
- **sandbox-stable** — sandboxed code execution on stable `@cloudflare/sandbox` (interpreters, CI/CD,
  untrusted code). Upstream renamed it from `sandbox-sdk`.
- **workers-profiling** — CPU and memory profiling of deployed Workers and Durable Objects.
- **turnstile-spin** — end-to-end Cloudflare Turnstile setup: widget creation, siteverify Worker,
  frontend snippets.
- **workers-best-practices** — production best practices for Worker code and `wrangler.jsonc`.
- **wrangler** — the Workers CLI: KV, R2, D1, Vectorize, Hyperdrive, Queues, Workflows, Secrets
  Store.
- **cloudflare-worker-tailscale-shield** — putting a Worker in front of a Tailscale-Funnel-exposed
  homelab service (edge auth/rate-limit + Queue retry-on-failure): why Workers can't reach
  tailnet-private addresses, forwarding the origin's own auth header through, and a `wrangler
  secret put` misuse that leaks a secret's value as its *name*.
- **cloudflare-r2-restic-backup** — encrypted, deduplicated, snapshotted backups to R2 via
  restic on a systemd timer. Pick this over the rclone skill above whenever the source is app
  state rather than a tree you want mirrored as-is.
- **backblaze-b2-rclone-backup** — the same rclone-to-S3-compatible pattern pointed at Backblaze
  B2, for second-provider redundancy: Object Lock/WORM, and the `NoSuchBucket` and mid-job `403`
  that mean a transaction cap rather than a missing bucket.
- **caddy-cloudflare-wildcard-proxy** — Caddy fronting internal hostnames with one wildcard cert
  via Cloudflare DNS-01, routing to loopback-bound backends already exposed by Tailscale Serve,
  and the empty-200 symptom of a Caddy listening on `*:port`.
- **wordpress-nginx-cloudflare** — WordPress on native nginx + PHP-FPM + MariaDB, hardened behind
  an Origin CA cert and Authenticated Origin Pulls, plus a real WP-Cron heartbeat when
  `DISABLE_WP_CRON` is set.

## Web / design / verification

- **frontend-design** — distinctive, production-grade frontend interfaces that avoid generic AI
  aesthetics.
- **web-perf** — Core Web Vitals auditing via Chrome DevTools MCP (LCP/INP/CLS, render-blocking
  resources, layout shifts).
- **cdp-layout-verification** — verifying precise CSS layout/spacing/alignment via direct DOM
  measurement, not just an eyeballed screenshot.
- **artifact-font-embedding** — sourcing real Google/Fontsource fonts and embedding them as
  base64 `@font-face` data URIs inside a Claude Artifact (works around CSP blocking external
  fonts).
- **image-crop-focal-point** — picking a normalized focal point / CSS `background-position` so a
  subject stays in frame across aspect-ratio crops.
- **filament-panel-theming** — taking a Filament v3 admin panel off stock gray/Inter/amber:
  which surfaces `FilamentColor` actually reaches versus the `fi-*` classes needing direct CSS,
  self-hosted fonts, and the Tailwind v3-CLI-vs-Vite fork in `make:filament-theme`.
- **resilience-ledger-email-styling** — the shared design system for transactional and
  notification email, and light/dark that genuinely works — including why dark-mode text goes
  invisible when it doesn't.

## Self-hosted agent fleet

Two always-on agents — Olu (OpenClaw, on `dfw`) and Chuka (Hermes, on `hermes`) — plus the
plumbing that keeps them honest.

- **openclaw-deployment** — deploying/debugging an OpenClaw gateway: secure baseline config, the
  two config traps that silently break things (`tools.exec.security` vs `ask`, model vs API key),
  Telegram lockdown, memory indexing, and handing the agent a new capability it will trust.
- **hermes-agent-deployment** — the Hermes equivalent: gateway install, `EnvironmentFile`
  credentials, MCP servers, `DANGEROUS_PATTERNS` and why `approvals.mode` never fires without a
  pattern match.
- **agent-command-approval-gate** — deciding *which* commands need human approval: substring vs
  anchored regex vs command-position tokenizer, the wrapper bypasses that defeat the middle one,
  the heredoc/backtick false positive the tokenizer introduces, and the live-fire protocol.
- **agent-delivery-canary** — monitoring that catches what an agent cannot report about itself:
  silent non-delivery, a crash-looping gateway, and faults already broken at baseline.
- **agent-vault-credential-broker** — brokering real API keys into an agent's outbound calls so
  the agent process never holds them.
- **cross-agent-filesystem-exchange** — the two-inbox filesystem channel agents and Claude Code
  use to hand work to each other without routing every message through a human.

## Other

- **postmark** — transactional email via Postmark's SMTP relay or HTTP API, including from
  non-Workers systems (Proxmox, cron jobs, backend services).
- **skill-development** — guidance for creating/improving Claude Code skills (structure,
  progressive disclosure, description quality).
- **anthropic-admin-cost-api** — Anthropic Admin API access and the Usage & Cost API: minting an
  admin key or `org:admin` token, why the Console's admin-keys page can 404, and reading cost by
  workspace or model. Its `amount` field is in **cents** — check the unit before reporting a
  figure.
- **better-documents** — communication principles applied while generating a document, deck,
  memo, or proposal rather than reviewed in afterwards.
- **clarity** — Addy Osmani's prose skill (`addyosmani/clarity`, MIT): review, rewrite, interview
  (co-write from the author's own words) and lint modes, never inventing facts or anecdotes.
  Vendored as a plain copy of upstream `e27ceef` (2026-10-25) after review, not via `npx skills`
  (its `-g` install leaves a symlink into `~/.agents`, which dangles once synced). Update by
  re-copying `SKILL.md`, `references/` and the two lint scripts.

## Hooks (not skills)

`_hooks/` holds Claude Code `PreToolUse` guard scripts, version-controlled here so they survive a
machine rebuild and reach every machine with the skills. Unlike skills they are **not**
auto-discovered: run `_hooks/install.sh` once per machine (idempotent; symlinks into
`~/.claude/hooks/` and reports whether `~/.claude/settings.json` wires each hook). See
`_hooks/README.md`.

- **block-credential-dump.sh** — denies Bash commands that would print a secret into the
  transcript: dump verbs against credential-shaped paths, and any command that prints a
  `*_PROXY` value (Agent Vault embeds the agent token in `HTTPS_PROXY`). Both rules come from real
  leaks that each cost a rotation.
