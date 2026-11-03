---
name: docker-vpn-killswitch-lxc
description: >-
  Route only some Docker containers (downloaders such as yt-dlp, MeTube, Pinchflat) out through a
  commercial WireGuard VPN (ProtonVPN, Mullvad, etc.) from inside an unprivileged Proxmox LXC, with
  a two-layer kill switch so they can never fall back to the ISP: WireGuard `Table = off`, a
  dedicated Docker bridge with a fixed name, source-based ip rules into a routing table whose only
  permanent route is `unreachable`, and an nftables forward-hook drop in its own table. The rest
  of the LXC (Tailscale, Jellyfin, SMB, apt) stays on the LAN. Covers sanitising the provider's
  .conf, unit ordering, DNS, Tailscale's ip rules, and the two drills that prove each layer works
  alone. Trigger phrases include "VPN kill switch", "route docker through wireguard",
  "containers only through the VPN", "ProtonVPN for the downloaders", "no ISP fallback",
  "Table = off", "policy routing for a docker network", "split tunnel docker", "gluetun
  alternative", "wg-quick in an LXC".
---

# VPN-only egress for selected Docker containers in an LXC

Built 2026-10-23 for the offline media server (`media`, CT 143, homelab-ansible
`playbooks/media-install.yml`). Will wanted the downloaders' traffic hidden from the ISP without
TorBox/debrid. The LXC itself had to stay on the LAN and tailnet: Jellyfin is served over
Tailscale Serve, SMB is tailnet-only, and apt and Tailscale must not depend on a third-party VPN.

**Why not gluetun or wg-quick's default routing:**
- Plain `wg-quick` installs a default route plus fwmark rules for *everything* in the namespace.
  That would send Tailscale, apt and Jellyfin through Proton too.
- gluetun works by putting containers into its network namespace with `network_mode:
  service:gluetun`, which couples every downloader's lifecycle and published ports to the VPN
  container's.

The host-level design below keeps each container on an ordinary bridge. The kill switch lives in
kernel routing and nftables, where it can be drilled and audited.

## Design

1. **A dedicated Docker network with a fixed bridge name and subnet.** Only containers attached
   to it are routed through the tunnel.
   ```yaml
   networks:
     dl:
       driver: bridge
       driver_opts: { com.docker.network.bridge.name: br-dl }
       ipam: { config: [ { subnet: 172.30.0.0/24 } ] }
   ```
   Publish their web UIs on `127.0.0.1:<port>` only and front them with Tailscale Serve. Replies
   to the host go back over br-dl into the host itself, never through the forward hook, so the
   UIs keep working while the tunnel is down.

2. **Source-based policy routing into a table that starts out unreachable.** These come from a
   oneshot unit (`media-killswitch.service`) ordered `Before=docker.service
   wg-quick@wg-proton.service`:
   ```
   ip rule add from 172.30.0.0/24 to 172.30.0.0/24 lookup main priority 99   # container ↔ container
   ip rule add from 172.30.0.0/24 lookup 51820 priority 100
   ip route replace unreachable default metric 4278198272 table 51820
   ```
   The `unreachable` route is permanent. While the tunnel is down, packets from the subnet get
   `Network is unreachable`; they never fall through to the main table's LAN default. Keep the
   priorities **below 5210**, where Tailscale's own fwmark rules start, so these rules always win.
   Wrap each `ip rule add` in `ip rule show | grep -q ... ||`, because duplicates stack up on every
   restart.

3. **WireGuard with `Table = off`, adding only the table-51820 default.** Render the provider's
   .conf through a template that:
   - drops any `DNS =` line. Otherwise wg-quick calls resolvconf and rewrites the LXC's DNS.
   - drops any existing `Table =` line.
   - inserts, after `[Interface]`:
     ```
     Table = off
     PostUp = ip route replace default dev %i table 51820
     PreDown = ip route del default dev %i table 51820
     ```
   The tunnel's default route then has the lower metric, and on `wg-quick down` the unreachable
   route takes over again. Store the whole provider .conf as one secret (here Infisical
   `PROTONVPN_WG_CONF`) and render it with `no_log: true` and mode 0600. Skip the tunnel tasks
   cleanly while the secret is absent; until it exists the downloaders just have no route.

4. **An nftables forward-hook drop, in its own table.** This layer catches routing mistakes, such
   as a lost ip rule or a hand-added route:
   ```
   table inet media_ks
   delete table inet media_ks
   table inet media_ks {
     chain forward {
       type filter hook forward priority filter - 1; policy accept;
       iifname "br-dl" oifname != { "wg-proton", "br-dl" } counter drop
     }
   }
   ```
   - The `table` / `delete table` / `table {}` sequence makes the file idempotent.
   - **Never `flush ruleset`** in this file: Docker's own rules live in the same nftables.
   - `priority filter - 1` runs the drop before Docker's accept rules.
   - Docker's MASQUERADE already covers any non-bridge exit interface, so traffic leaving through
     wg-proton is NATed to the tunnel address with no extra rule.

## LXC prerequisites

- WireGuard is a kernel module, so it has to be loaded on the **Proxmox host** (`lsmod | grep
  wireguard`). Inside an unprivileged LXC, `ip link add type wireguard` then works with the
  container's own CAP_NET_ADMIN.
- The `/dev/net/tun` passthrough (`lxc.cgroup2.devices.allow: c 10:200 rwm` plus the
  `lxc.mount.entry`) is needed for **Tailscale** in the same LXC, not for WireGuard.
- `features: nesting=1` is needed for Docker (and for Debian 13 systemd anyway).

## DNS

Containers use Docker's embedded resolver (`127.0.0.11`), which forwards through the **host's**
resolver, here Pi-hole, which forwards to Quad9 over DoT. DNS therefore does not go through the
VPN, by design: Pi-hole filtering still applies and the ISP still sees no plaintext names. If a
provider must also do DNS, set `dns:` on the containers to the provider's in-tunnel resolver
(Proton: 10.2.0.1). That address is only reachable via table 51820, so name lookups also fail
closed when the tunnel is down.

## Drills: prove each layer on its own

Run these from inside a container on the `dl` network (`docker exec <c> curl -sS -m 8
https://ifconfig.me`). Each drill needs a control: the LXC host itself must still reach the
internet, or the drill proves nothing (see the `forced-outage-drill` skill).

1. **Exit IP.** The container shows the VPN exit, and the host shows the ISP address. On
   2026-10-23: 149.88.100.198 (Proton, Dallas) vs. 66.169.192.156.
2. **Route layer.** Run `wg-quick down wg-proton`, then the container gets `Network is
   unreachable` while the host's control request still succeeds. Bring the tunnel back up.
3. **nft layer alone.** With the tunnel down, temporarily delete the priority-100 ip rule, so
   routing would now leak via the LAN. The request must still fail, and `nft list chain inet
   media_ks forward` must show the drop counter rising (6 packets on 2026-10-23). Re-add the rule
   by restarting `media-killswitch.service`, and check that `ip rule` matches the baseline.
4. **Site check.** With the tunnel up, the actual target (e.g. YouTube) returns 200 through it.
   Some VPN exits are blocked by sites, so pick another server if not.

Re-run the playbook afterwards and expect `changed=0`. Compare `ip rule` and the table-51820
routes against the baseline, so no drill state lingers.

## Monitoring: the kill switch fails silently

Failing closed means a dead tunnel looks like nothing at all: downloads stop and no unit fails.
`wg-quick@` is a oneshot that stays "active (exited)" whatever the peer does, and handshake age is
no use either, because WireGuard stops handshaking when idle. Probe the egress itself from a
container on the `dl` network instead, on a schedule that alerts:
```
docker exec pinchflat curl -sS -m 10 https://1.1.1.1/cdn-cgi/trace | sed -n 's/^ip=//p'
```
Fail if nothing comes back (tunnel down), or if the result equals the host's own trace IP (a leak).
Using the IP avoids DNS. Here this is `media_vpn_egress` in the homelab sweep's service category
(daily drift check), drilled 2026-10-24 by stopping `wg-quick@wg-proton`.

Also check that any yt-dlp bundled in an image is fresh. MeTube's sat 63 days old after the build;
YouTube breaks old yt-dlp within weeks. Pinchflat updates its own.

## Gotchas

- **Rules added by hand don't survive a restart.** Everything has to come from the unit, which
  must run before docker and wg-quick at boot.
- **Recreating the Docker network can change the bridge name** unless
  `com.docker.network.bridge.name` is pinned. The nft rule matches on `br-dl` by name.
- **Changing the subnet means changing it in three places:** the ip rules, the compose IPAM and
  any monitoring that greps for it.
- **Tailscale Serve traffic bypasses nftables input rules** (it arrives from the tailscaled
  process, not the tailscale0 interface; see the `reference_tailscale_serve_bypasses_nftables`
  memory). Restrict Serve ports with ACLs or app auth, not the nft input chain. The
  `iifname != { lo, tailscale0 }` drops here only keep SMB and discovery off the LAN.
