---
name: home-assistant
description: This skill should be used when configuring, troubleshooting, or extending a Home Assistant OS (HAOS) instance — installing add-ons/apps, editing configuration.yaml, setting up Tailscale/remote access, or troubleshooting onboarding, the Supervisor, or backups. Trigger phrases include "Home Assistant add-on", "Home Assistant apps", "configuration.yaml", "HAOS", "Home Assistant Tailscale", "Supervisor", "HACS".
---

# Home Assistant OS (HAOS)

Operational notes for a Home Assistant OS appliance VM specifically (not a plain Home Assistant
Container/Docker install) — first built in this homelab 2026-07-13 as VMID 150 on Proxmox. For
the Proxmox/Terraform side of provisioning this kind of VM (UEFI, no cloud-init, appliance image
import), see the `proxmox-terraform-provisioning` skill instead — this skill covers the guest
OS/application layer once it's already running.

## "Add-ons" is now "Apps"

Home Assistant renamed **Settings → Add-ons** to **Settings → Apps** in the 2026.2 release —
purely cosmetic (still the same Supervisor-managed Docker containers underneath), done to reduce
confusion between "Add-ons" and "Integrations" for new users. Any guide, screenshot, or memory
referencing "Add-ons" on a current install means **Apps**. Individual app detail pages keep their
existing tab names (Info / Log / Configuration / Documentation) — only the top-level menu label
changed, not the per-app navigation.

## Installing a non-default app

Not every app is in the default store. Community-maintained ones (e.g. the Tailscale app) need
their repository added first: **Settings → Apps → ⋮ (store view) → Repositories** → paste the
repo URL (e.g. `https://github.com/hassio-addons/repository` for the widely-used "Home Assistant
Community Add-ons" set). It then appears in the store under that repo, installs like any other app.

## No normal shell, no cloud-init (guest agent: off until you enable it)

HAOS is a locked-down appliance OS, not a general Debian box:
- No SSH/root shell by default (advanced users can enable an SSH add-on, but treat this as
  intentionally locked down, not a bug).
- Ignores Proxmox cloud-init entirely — onboarding (creating the first admin account) happens
  through HA's own first-boot web wizard, not via injected SSH keys/config.
- **The web UI's port is no longer reliably 8123.** Confirmed on a fresh HAOS 18.2 build
  (2026-08-22): the LAN-facing UI is served on **port 80** by Supervisor's own proxy, while 8123
  itself returns connection-refused from outside the guest (Core is presumably still bound to it
  internally, just not exposed). Symptom if you assume 8123: ICMP ping succeeds, TCP to 8123 is
  refused, but plain `http://<ip>` (port 80) serves the real HA frontend fine — don't read the
  refused 8123 as the guest being down. Check both ports (`nc -zv <ip> 80 8123`) rather than
  assuming one.
- **HAOS ships qemu-guest-agent, but the VM needs `agent: 1`** (Terraform `agent { enabled = true }`).
  Corrected 2026-10-30: the "no working agent" note here was only ever true because the VM was built
  without that flag. Without it, **HAOS ignores ACPI shutdown**: every `qm shutdown` and every pve
  shutdown waited the full 180 s and then SIGTERMed HA, a hard kill that risks its database. With
  it, `qm shutdown 150` took 25 s and `qm agent 150 ping` answers (HAOS 18.4). The flag takes effect
  only after a full VM stop and start, not a guest reboot. Stop it cleanly from HA itself
  (Settings → System → power icon → Advanced → Shut down system), then apply. Without the agent,
  find the IP via `ip neigh` on the Proxmox node, matched by MAC.

## Editing configuration.yaml

Needs a text-editing app first — install one from the default store (no extra repo needed):
- **File editor** — simplest, opens directly into `/config`, `configuration.yaml` is at the top
  level (created by default on first boot).
- **Studio Code Server** — full VS Code in-browser if doing more than a one-line edit.

Always restart Home Assistant (Settings → System → Restart) after editing — changes to
`configuration.yaml` don't take effect live.

## Tailscale access — add-on-based, not raw CLI

Because there's no normal shell, exposing HA over Tailscale goes through the **Tailscale app**
(`hassio-addons/addon-tailscale`, needs the community add-on repo above), not a hand-run
`tailscale serve` command the way every other Debian LXC/VM in this homelab is exposed:

1. Install + start the Tailscale app, authenticate via the login URL shown in its **Log** tab.
   Originally noted as Chrome-only (other browsers reportedly misbehaving with this flow) — not
   reproduced on a 2026-08-22 build, where the same auth link worked fine in Safari. Try whatever
   browser is handy; only fall back to Chrome if the link actually misbehaves.
2. In its **Configuration** tab, show "unused optional configuration options" to reveal:
   - `share_homeassistant`: `disabled` / `serve` / `funnel` — use **`serve`** for tailnet-only
     access (this homelab's standing default — see constraint #3 in `homelab/CLAUDE.md`); only
     use `funnel` if there's a genuine public-ingress need.
   - `share_on_port`: `443` / `8443` / `10000` — `443` matches every other tailnet-only service
     in this homelab.
3. Restart the Tailscale app itself (not just HA) after changing its config.
4. **Trusted proxies must be configured or HA rejects requests coming through the add-on's
   reverse proxy with a plain `400: Bad Request`** (confirmed live 2026-08-22 — direct IP access
   still returned `200` the whole time, only the proxied path 400'd, which is the tell that this
   is what's wrong rather than HA actually being down). Two different mechanisms depending on
   version:
   - **Older versions / still on YAML**: add to `configuration.yaml` via the File Editor app,
     then restart HA:
     ```yaml
     http:
       use_x_forwarded_for: true
       trusted_proxies:
         - 127.0.0.1
     ```
   - **Newer versions (confirmed on the 2026-08-22 HAOS 18.2 build)**: the `http:` YAML key is
     **silently ignored** post-migration — editing it does nothing, no error, and HA shows a
     dedicated warning ("HTTP YAML configuration is ignored after migration ... stops working in
     2027.2.0") the next time you open Settings if you still have a stale block in the file.
     Configure it via **Settings → System → Network → HTTP server → Reverse proxy** instead:
     toggle **Trust X-Forwarded-For** on, add each proxy IP under **Trusted proxies** (as a bare
     IP, e.g. `127.0.0.1` and `192.168.50.181` for a LAN Caddy instance — not a CIDR, despite the
     field's own hint text). Clicking **Save** on that card *is* the restart — no separate
     Settings → System → Restart needed. HA then shows a "Confirm new HTTP server configuration"
     dialog with a ~5-minute auto-revert countdown (a lockout safety net) — click **Confirm** once
     you've verified you can still reach it, or it silently reverts on its own.
   - If proxying through more than one hop (e.g. both a local Tailscale Serve add-on *and* a
     separate Caddy host), list every hop's source IP in trusted proxies — `127.0.0.1` alone
     covers the Tailscale/HAOS-local add-on, but a LAN reverse proxy on another host needs its
     own real IP added too.

## Mobile app setup

Two separate apps are needed, not one:
1. **Tailscale** app — sign into the same tailnet, VPN toggle **on**. If HA "looks down" from a
   phone, check this first — it's almost always the phone's own Tailscale connection status, not
   the HA server (verify server health independently via `curl` from a known-good host before
   assuming an outage).
2. **Home Assistant** companion app — server URL is the Tailscale hostname
   (`https://<name>.<tailnet>.ts.net`), not a LAN IP (LAN IP only works on home WiFi).

## Backup/restore via Proxmox Backup Server

VM-level PBS backup/restore works the same as any other Proxmox VM (`vzdump`/`qmrestore`) with or
without the guest agent. Snapshot-mode backup completed cleanly before the agent was enabled
(2026-10-30); with it on, vzdump also gets an fs-freeze. One restore-test
gotcha: **a `qmrestore` to a throwaway VMID preserves the original guest's MAC address** — booting
it alongside the still-running original puts two VMs on the same LAN segment with an identical
MAC. Strip it first: `qm set <throwaway-vmid> --net0 virtio,bridge=vmbr0` (omit the MAC) so
Proxmox generates a fresh one before starting the throwaway copy.
