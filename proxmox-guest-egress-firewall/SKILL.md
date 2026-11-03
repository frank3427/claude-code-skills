---
name: proxmox-guest-egress-firewall
description: This skill should be used when restricting a single Proxmox guest's outbound traffic with the Proxmox VE firewall — especially the first time the datacenter (cluster) firewall is enabled on a host where it has never been on. Covers the safe enable order (off files for the host and for any guest whose NIC already has firewall=1, ACCEPT defaults), a per-VM egress allowlist (DNS, NTP, HTTPS, Tailscale, RFC1918 drop), what breaks under it (apt over HTTP, NTP to the internet, direct tailnet paths), and positive/negative verification. Trigger phrases include "proxmox firewall egress", "restrict outbound for one vm", "pve firewall enable cluster", "cluster.fw", "vmid.fw", "policy_out DROP", "firewall=1 nic", "proxmox firewall lock out", "egress allowlist proxmox", "agentic service outbound restriction".
---

# Proxmox guest egress firewall (enable it without collateral damage)

Built 2026-10-03 for the Hindsight memory VM (VMID 113), the first time the PVE firewall was ever
enabled on `pve`. That's the homelab's hard constraint #7: Proxmox-level outbound restriction for
agentic/AI services. A rule enforced on the host can't be undone from inside the guest, which is
the point; in-guest nftables can be.

## The trap: per-guest rules do nothing until the datacenter switch is on, and the switch is global

- `/etc/pve/firewall/<vmid>.fw` takes effect only when `/etc/pve/firewall/cluster.fw` has
  `enable: 1`. Until then every guest firewall setting is inert, and `pve-firewall status` says
  `disabled/running`.
- Turning the cluster switch on also activates **host** filtering and every guest whose NIC has
  `firewall=1`. Check for those first. On `pve`, Pi-hole's NIC (CT 100) already had
  `firewall=1`, so enabling the cluster firewall carelessly would have put the house's only DNS
  server under guest filtering.

```bash
for id in $(qm list | awk 'NR>1{print $1}'); do echo "VM $id: $(qm config $id | grep -E '^net[0-9]' | grep -o 'firewall=[01]')"; done
for id in $(pct list | awk 'NR>1{print $1}'); do echo "CT $id: $(pct config $id | grep -E '^net[0-9]' | grep -o 'firewall=[01]')"; done
ls /etc/pve/firewall/ /etc/pve/nodes/*/host.fw 2>&1
```

## Safe enable order (write the off files BEFORE the switch)

1. For every existing guest with `firewall=1` that you are **not** restricting, create
   `/etc/pve/firewall/<vmid>.fw` with `[OPTIONS]\nenable: 0`.
2. `/etc/pve/nodes/<node>/host.fw` with `[OPTIONS]\nenable: 0`, so the host's own SSH/8006 stay
   unfiltered.
3. The target guest's `<vmid>.fw` (below). The NIC needs `firewall=1`, set at `qm create`/`qm set`.
4. Last: `cluster.fw` = `[OPTIONS]\nenable: 1\npolicy_in: ACCEPT\npolicy_out: ACCEPT`. Refuse
   to proceed if `cluster.fw` already exists, because then you're editing someone's policy, not
   creating one.
5. Immediately verify from another host: DNS still answers (both a local name and an internet
   name), `pve:8006` and `pve:22` open, SSH to the guests whose off files you wrote. `pve-firewall
   compile` should print no errors.

**Rollback** for the whole thing is `enable: 0` in `cluster.fw`. The off files are harmless to
leave.

## The per-VM egress allowlist that worked

```
[OPTIONS]
enable: 1
dhcp: 1              # default 0 -- without it the guest can't renew its lease
policy_in: ACCEPT    # inbound handled in-guest / by app auth; conntrack replies are allowed anyway
policy_out: DROP

[IPSET private]
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16

[RULES]
OUT ACCEPT -dest 192.168.50.53 -p udp -dport 53   # DNS to Pi-hole only
OUT ACCEPT -dest 192.168.50.53 -p tcp -dport 53
OUT ACCEPT -dest 192.168.50.1 -p udp -dport 123   # NTP from the gateway only
OUT DROP -dest +private                           # nothing else on the LAN/homelab
OUT ACCEPT -p tcp -dport 443                      # HTTPS out (by port; PVE can't filter by name)
OUT ACCEPT -p udp -dport 41641                    # Tailscale
OUT ACCEPT -p udp -dport 3478                     # Tailscale STUN
```

Rules are evaluated in order; the specific `.53`/`.1` accepts must come before the `+private` drop.

## What the allowlist breaks, and the fixes

- **apt:** Debian cloud images use `http://` mirrors (`/etc/apt/mirrors/debian*.list`), and port
  80 is dropped. `sed -i 's#^http://#https://#'` both files before the first `apt-get update`.
- **Time:** timesyncd's default pool is internet NTP. Use a drop-in
  `/etc/systemd/timesyncd.conf.d/gateway.conf` with `[Time]\nNTP=192.168.50.1`.
- **Tailscale to LAN peers:** the direct path to a LAN peer's `192.168.50.x:41641` is dropped by
  the private ipset, so those peers go through DERP over 443. That still works; it's just relayed.
  Replies to peer-initiated sessions are fine (conntrack).
- **Agent Vault / other tailnet services:** reached over `tailscale0`, which isn't filtered by
  this host rule. Fine.

## Verify both directions from inside the guest (with controls)

```bash
getent hosts deb.debian.org                                             # DNS via Pi-hole: works
curl -s -o /dev/null -w '%{http_code}\n' --max-time 8 https://deb.debian.org/debian/   # 200
curl -s -o /dev/null -w '%{http_code}\n' --max-time 6 http://deb.debian.org/debian/    # 000 (blocked)
timeout 5 bash -c '</dev/tcp/192.168.50.71/22'   && echo OPEN || echo BLOCKED   # LAN host: BLOCKED
timeout 5 bash -c '</dev/tcp/192.168.50.53/80'   && echo OPEN || echo BLOCKED   # Pi-hole non-DNS: BLOCKED
timeout 5 bash -c '</dev/tcp/1.1.1.1/53'         && echo OPEN || echo BLOCKED   # public DNS: BLOCKED
```

Inbound SSH from ansible-ctrl still works (inbound ACCEPT plus conntrack replies); test it too.

## Not managed by IaC, and its current state

These files live only in `/etc/pve` (covered by pve's config backup). A copy of the exact contents
is in the planning repo's `hindsight-pilot-plan.md`. **On `pve` the switch was turned back OFF 2026-10-05** when Hindsight (VM 113, its only filtered guest)
was decommissioned: `cluster.fw` is `enable: 0`, `113.fw` is deleted, and the host and Pi-hole off files
remain. Re-enabling means following the order above again. The homelab memory
`reference_pve_firewall_enabled` tracks the current state.
