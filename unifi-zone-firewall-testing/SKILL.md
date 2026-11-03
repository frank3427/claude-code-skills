---
name: unifi-zone-firewall-testing
description: This skill should be used when testing or verifying UniFi zone-based firewall policies between VLANs, when a ping to a gateway address seems to prove an inter-VLAN policy works, when deciding whether a "blocked" result is a firewall rule or a sleeping device, when a UniFi API write returns HTTP 200 and rc "ok" but the value does not persist, when planning a UniFi cutover and wanting before/after evidence, or when a Guest network appears isolated but has not actually been tested from inside it. Trigger phrases include "test VLAN isolation", "tagged VLAN interface for testing", "SO_BINDTODEVICE no route", "curl --interface blocked", "policy hits counter empty", "last_hit never", "tailscale subnet route breaks my test", "disable the policy to prove it", "index 10000 predefined 2147483647", "test VLAN isolation", "verify firewall policy UniFi", "Trusted to IoT blocked", "guest network isolation test", "UniFi API silently discards", "unifi 200 rc ok not persisted", "inter-VLAN ping works but", "policy matrix before after cutover", "bc_filter_enabled", "mDNS filtering per network", "port_overrides native_networkconf_id", "UniFi zone default block", "deadman revert", "dead man switch network change", "schedule the undo before the change", "renumber the management subnet safely", "locked out of the UniFi controller", "doh state off", "is DNS over HTTPS enabled UniFi", "rest/setting key doh", "secondary WAN DNS leaks around Pi-hole", "failover bypasses DNS filter", "wan_dns_preference per WAN entry", "U5G DNS not manual", "DNS redirect works but clients get no answer", "destination's own firewall blocks redirected VLAN", "Pi-hole local nftables allow-list missing subnet", "DNAT and zone policy pass but service still unreachable", "reorder firewall policies API", "batch-reorder", "move rule above block UniFi", "hit counter moved after reorder", "FirewallPolicyCreateRespondTrafficPolicyNotAllowed", "allow one host through an outbound block", "exception above a block rule", "narrow allow rule port 853".
---

# Testing UniFi zone firewall policies so the results mean something

Verified against **UniFi Network 10.6.101 / UniFi OS 5.1.31** on a UCG-Fiber with a USW Flex
2.5G and a U7-LR, 2026-09-06. Every claim below was produced with packets, not read from docs.

## The three traps that make a test lie

### 1. Never test against a gateway address

`ping <gateway-IP-on-the-other-VLAN>` from one VLAN succeeds even when that VLAN pair is denied.
Traffic addressed **to the gateway** is local/input-chain traffic, evaluated separately from the
forwarded traffic that zone policy governs. UniFi's own behaviour makes this concrete:

- Port 53 to the gateway is **unblockable** by any policy — it answers on UDP and TCP with every
  allow removed. There is a built-in accept that user policy cannot override.
- Trusted → the Guest gateway SVI succeeds while Trusted → a Guest *host* is correctly blocked.

**Only host-to-host results say anything about a policy.** A gateway SVI test that "passes" is
the single easiest way to certify a firewall matrix that does not work.

### 2. Every assertion needs a control that can fail independently

A device that is asleep and a device behind a working deny rule produce identical silence. iOS
devices in particular go quiet, and a randomised (Private Wi-Fi Address) MAC means the address
you are testing may be a stale lease for a device now on a different one.

The control must reach the **same target** from a path known to be allowed. If the control fails,
the row is **UNTESTABLE** — never pass, never fail. A result that cannot be interpreted must not
be recorded as though it could.

This also means **a bench with one general-purpose host cannot test itself**: the control keeps
collapsing into the test. A second real host is the fix, not cleverer scripting.

### 3. HTTP 200 and `rc: "ok"` do not mean the write happened

This API accepts and silently discards values constantly. Always `GET` the object back and
compare fields. Confirmed silent discards on 10.6.101:

| Write | Read-back |
|---|---|
| `setting/mdns` `enabled_for_network_ids` (either mode) | `[]` |
| `networkconf/<id>` `mdns_enabled: false` | unchanged — it is a **read-only mirror** |
| `setting/mdns` `enabled_for: "custom"` | vestigial; accepted, dropped |

Things that *do* persist: `bc_filter_enabled` on a WLAN, `predefined_services` as
`[{"key":"airplay"}]` with `mode: "custom"` (a **string** list returns `InvalidPayload`), and
`port_overrides` on a device.

The one place it errors honestly is an empty services list under `mode: custom`
(`MdnsSettingInvalidServicesListException`).

## What is actually reachable through the API

- **Zone default is BLOCK.** A pair with no policy is denied, so a matrix that looks complete on
  paper can be missing pairs it needs — an absent `Trusted → IoT` presents on cutover night as
  the entire smart home going unresponsive behind green policies.
- **Per-network mDNS scoping is not reachable via the API.** The feature exists in the UI under
  the name **"mDNS Filtering"** — *not* "Multicast DNS Proxy", which is the gateway reflector and
  the wrong thing to search for. It is **AP-enforced**; the UI bundle carries the strings
  "mDNS Filtering is set to Custom, but some of the selected networks don't exist" and
  "mDNS Filtering isn't supported by any Access Points on this site".
- **Wired VLAN assignment lives in `port_overrides`** on the device object
  (`{"port_idx": N, "native_networkconf_id": "<id>"}`), not in `portconf` profiles.

## Two operational gotchas that cost real time

**A gateway's WAN interface correctly refuses ICMP and HTTPS.** "Cannot ping the WAN address" is
not evidence the gateway lost its lease — check `stat/device` for what the controller says it
holds. Reading "does not answer" as "is not there" sent an afternoon down the wrong path.

**Guest → WAN is unrestricted, and "WAN" means whatever sits upstream.** On a bench where the
house LAN is upstream, a Guest client reaches every host on it, SSH banners included. That closes
when the gateway becomes the edge — but if an ISP router with a management interface sits in
front, Guest reaches it. Add a `Guest → WAN` policy denying RFC1918 destinations.

**Corollary:** a carve-out that appears to work because its target sits on the WAN side has not
been tested at all. A Pi-hole DNS carve-out "passed" from Guest purely because Pi-hole was
upstream and `Guest → WAN` is open; the policy never participated.

## Testing from inside a VLAN you have no device on

A dual-homed laptop can be moved onto the SSID under test. Read the passphrase from
`rest/wlanconf` (`x_passphrase`) and pipe it straight into the join command so it never touches
disk. **Arm an auto-revert before switching**, because the VLAN under test may block the path you
are managing the machine through:

```bash
ssh host "nohup bash -c 'sleep 600; networksetup -setairportnetwork en1 <known-SSID>' &"
```

A wired host changing VLAN keeps its old lease forever under `ifupdown` — arm a DHCP renew loop
before moving the port, or the box strands itself on a network nobody can reach.

## Make the answer discriminate when observation is impossible

Where no observer exists, stop trying to watch packets and design a test whose **answer** differs
by outcome. "Does the gateway resolver use the per-network DHCP DNS?" was settled by pointing one
network's DNS at Quad9 and asking for domains Pi-hole blocks: still `0.0.0.0` meant still
Pi-hole. No capture, no control, no ambiguity.

Watch for caching — use domains never queried through that resolver before, and verify they are
blocked by asking the blocking resolver directly so the cache under test is never primed.

## Give one host every VLAN at once, instead of moving it between SSIDs

Moving a laptop onto the SSID under test works but costs the interface you were using and needs
an auto-revert. If any wired host sits on a **trunked** switch port, a far better instrument
exists — tagged sub-interfaces, several VLANs at once, no gateway or port change to revert:

```bash
ip link add link enp3s0f0 name vl30 type vlan id 30
ip link set vl30 up
dhclient -1 vl30                       # a real lease from the real DHCP server
```

If the port does not carry the VLAN you simply get no lease — a harmless no-op, so this is cheap
to try before assuming you need a port reconfiguration. On UniFi, a default port profile passes
every VLAN tagged with the native one untagged, so this often just works.

**But binding a test to that interface is not enough, and the failure looks exactly like a
policy block.** `curl --interface vlXX` (and anything else using `SO_BINDTODEVICE`) forces egress
on the device — **it does not invent a route**. With the default route still on the physical NIC,
every bound probe fails to connect, and *cannot connect* is indistinguishable from *policy denied
it*. Give each leg its own table:

```bash
ip route add default via 192.168.30.1 dev vl30 table 130
ip rule  add oif vl30 table 130 priority 130
```

**Then assert internet reachability per leg before any interesting row.** `curl --interface vl30
https://1.1.1.1/` must succeed. That single line is the control that discriminates, because it
fails when the plumbing is broken and succeeds when it is healthy.

A cautionary detail: an assertion written *specifically* to catch this can still miss it. A
control requiring "Guest → a Trusted host is blocked, Trusted → same host reaches" is satisfied
perfectly by a **total routing failure** — the physical NIC has an on-link route and the VLAN
legs have none. The control shared the defect it was meant to detect. What exposed it was an
unrelated row claiming Guest could not reach `1.1.1.1:443`, which is plainly false.

Also arm a dead-man's switch before touching routing on a host you reach over that network:

```bash
systemd-run --on-active=480 --unit=revert /bin/sh -c \
  "ip link del vl30; ip route replace default via 192.168.1.1 dev enp3s0f0"
```

## Any host on a tailnet may not be a valid instrument at all

Before trusting any reachability result, check where the packet would actually go:

```bash
ip route get <target>          # Linux
route -n get <target>          # macOS  → look for utunN
```

If a peer advertises the target range as a **Tailscale subnet route**, every probe to it leaves
through the tunnel and never reaches the gateway. Both arms agree, the test looks clean, and it
measured nothing. On one bench this invalidated an entire class of tests from one Mac — while a
second machine on the same bench routed via the gateway and was a perfectly good instrument.

**The instrument was wrong, not the environment.** Concluding "the bench cannot test this" from
one host's defect is the same over-generalisation in reverse. Check the other hosts.

This also threatens **cutover-night verification**: a technician checking inter-VLAN isolation
from a Tailscale-connected laptop gets tunnel answers, so a working block reads as reachable and
an allow passes without the policy participating. Verify from a device with Tailscale off.

## Read `hits`, but never read its absence

Every policy object carries `hits` and `last_hit`, and the populated counters are the cheapest
real evidence available — they exposed a claim filed as "untested, zone empty by design" while
five of its policies had matched thousands of packets.

**An absent `hits` field proves nothing.** Note the distinction: these policies do not report
`hits: 0`, the field is *missing*. A Guest DoT block reporting no counter was demonstrably
matching packets at that moment — proven by toggling it. Missing instrumentation, not missing
traffic.

`last_hit` is worse: several policies report a real `hits` count alongside `last_hit: never`.
Read `hits`; treat `last_hit` as decorative.

## The strongest test of a policy is to turn it off

Behaviour shows a port is shut. It does not show **what shut it** — and the hit counters may not
tell you either. Toggle the rule:

| policy state | `Guest → 1.1.1.1:853` |
|---|---|
| enabled | BLOCKED |
| **disabled** | **REACHED** |
| re-enabled | BLOCKED |

Three data points, ~15 s of propagation each, and the causal claim is closed. Believing a rule
works because its twin on another zone pair works is argument by symmetry — the exact thing
per-zone testing exists to avoid.

## Reordering existing rules, and what it does to `hits`

The API ignores `index` on create (new rules append to their zone pair), but existing rules *can*
be reordered: `PUT /proxy/network/v2/api/site/default/firewall-policies/batch-reorder` with
`{"source_zone_id", "destination_zone_id", "before_predefined_ids": [...], "after_predefined_ids":
[...]}` — the full list of the pair's custom rule ids in the order wanted. Found 2026-09-28 in the
Network UI's own bundle (`swai.<hash>.js`, served from `/proxy/network/manage/react/js/`, fetched
with the `X-API-KEY` header), after guessed `ordering` URLs 404'd as policy ids. Proven on
production the same day: create, then batch-reorder, then read the order back.

**Hit counters follow the position, not the rule.** After moving a new allow above an existing
block, the block's `hits=3` appeared on the allow and the block showed none. Counts are not
comparable across a reorder — the "Read `hits`" advice above holds only for a pair whose order
hasn't changed since the counts accrued.

## Custom policies always precede the predefined allow

A custom policy is created at `index: 10000`; the predefined `Allow All Traffic` for the same
zone pair sits at `2147483647`. So a new custom rule is evaluated **ahead of** that baseline with
no ordering work. The creation-order warning applies **between customs in the same zone pair** —
create the ALLOW before the BLOCK — not against the predefined rules.

Useful corollary when counting: the API returned 144 policies where only 19 were ours. The rest
are predefined plus auto-created `(Return)` companions. When recording a count, record what was
counted.

## Reference implementation

`scripts/unifi-policy-matrix.sh` and `scripts/cutover-capture.sh` in the homelab repo encode all
of the above, plus `scripts/unifi-private-macs.sh` for finding devices whose randomised MAC has
silently broken their DHCP reservation.

## A DNAT rewrites the destination; it does not grant passage

The sharpest trap in a zone-firewall build with DNS redirection, and it survived a bench that
tested everything else with packets.

A `:53` redirect on a VLAN's ingress rewrites the destination to the internal resolver. **The
resulting flow then crosses zones** — IoT-zone to Trusted-zone — **and this platform's inter-zone
default is block.** Ubiquiti documents that adding a DNAT rule to a **WAN** interface auto-creates
a matching firewall rule; whether that extends into the zone policy table for a **vlan-ingress**
DNAT is undocumented and, as of Network 10.6, unestablished.

**The bench cannot test it if the resolver lives on the WAN side.** `Guest -> WAN` is open, so the
query succeeds and the redirect looks correct while the policy never participates at all — the
same false pass that hid the Pi-hole carve-out. A green result here is evidence about the WAN
allow, not about the redirect.

**Failure mode:** a silent DNS blackhole for every client on the redirected VLANs simultaneously,
presenting as "the internet is broken" and pointing nowhere near DNS.

**Gate it in two parts.** Read the policy table back and confirm an explicit allow exists — do not
assume the DNAT created one. Then check that the query **answers** *and* **appears in the
resolver's log attributed to the client's own IP**. An answer alone can be a leak to an upstream
resolver, which is the failure the redirect existed to prevent.

**Residual to hold to:** keep every DNS DNAT vlan-ingress-only. NAT here is interface-egress-scoped,
so once the resolver's subnet is a LAN subnet the masquerade rule stops matching and attribution is
correct. But a DNS DNAT anchored on the **WAN IP** — the shape you would reach for to catch a
hardcoded `8.8.8.8` — has hairpin semantics whose SNAT half rewrites sources, reintroducing exactly
the mis-attribution you removed.

## The gateway's own resolver follows WAN DNS — test it with an answer that identifies the responder

On UniFi OS 5.1.31 / Network 10.6.101 the client-facing resolver (dnsmasq on every VLAN SVI)
forwards to **whatever Internet 1's DNS is**, not to the per-network DHCP DNS setting and not to
anything policy can reach. Proven 2026-09-07 after an earlier read said the opposite: that
reading was taken inside the ~10–90 s propagation window, the third wrong conclusion that window
produced in one build.

Method that settles it in five minutes, reusable for any gateway resolver question:

1. Pick domains that are **gravity-blocked yet resolve publicly** (`sqlite3 gravity.db "select
   domain from vw_gravity where domain like 'ads.%' order by random() limit 12"`, then keep the
   ones where `dig @1.1.1.1` returns an A record and `dig @<pihole>` returns `0.0.0.0`). The
   answer then names the responder; a plain `example.com` looks identical from either.
2. Baseline `dig @<gateway> <domain-1>`; confirm it shows in Pi-hole's **live** API
   (`/api/queries`), not `pihole-FTL.db`, which lags.
3. Change the lever (here: `PUT rest/networkconf/<wan id>` with `wan_dns_preference: manual`,
   `wan_dns1: 1.1.1.1`), **wait 90 s**, query a never-used domain-2 — a real address means the
   lever moved the resolver; `0.0.0.0` means it did not.
4. Revert, wait, query domain-3, confirm `0.0.0.0` returns and Pi-hole logs it. Never leave a
   bench in a changed state on the strength of the change's HTTP status.

Consequence for a Pi-hole network: **set the gateway's WAN DNS manually to Pi-hole**, or every
client that asks its gateway bypasses the filter. Zone policy cannot block `:53` to the gateway
and a vlan-ingress DNAT excludes gateway-destined traffic, so this is the only lever. Boot order
is not a failover risk: the WAN SLA probes `1.1.1.1`/`8.8.8.8` by address, so Pi-hole being down
fails one probe of three and WAN stays up.

## Every WAN entry has its own DNS lever, and a secondary one only gets tested by an actual failover

The lever above (`wan_dns_preference`/`wan_dns1` on `rest/networkconf`) exists **per WAN entry**,
not once per gateway. Confirmed on cutover night, 2026-09-28, production hardware (UniFi OS
5.1.31): `Internet 1` had been set to `manual`/Pi-hole correctly, but the U5G cellular backup
entry (`UniFi 5G A`) was still `auto` — silently following the carrier's own DNS. Nothing on the
bench or in the pre-cutover build exercised this, because nothing forced a real failover: the
primary WAN was always up, so the backup entry's DNS setting was configuration nobody had ever
asked to prove.

**Falsified live, not assumed:** `dig @<gateway> <domain>` while failed-over answered a real
public IP (`151.101.114.189`) instead of Pi-hole's `0.0.0.0` — every device on every VLAN would
have resolved straight past the filter for the duration of any failover, with no error, no log
entry pointing at DNS, and a gateway that reported the failover itself as fully healthy.

**The check every WAN-redundant Pi-hole deployment needs, and the bench cannot give you:** for
each WAN entry beyond the first, either force a real failover and repeat the domain-that-
identifies-the-responder test above against it specifically, or at minimum read back
`wan_dns_preference`/`wan_dns1` on that entry's `networkconf` object before trusting it. A second
WAN entry's DNS setting is exactly as easy to leave on `auto` as the first one was to fix — it is
just harder to notice, because it only matters during an outage.

## A DNAT + zone-policy pass on the gateway proves nothing about the destination's own firewall

The `IoT/Guest → Pi-hole DNS` carve-out in this build was verified structurally (`networkconf`
zone membership, DNAT rule, matching allow policy — see the DNAT section above) and then
behaviourally on cutover night: the redirect worked, the zone policy passed traffic, Pi-hole was
reachable on `:53` from every VLAN **exactly as designed** — and IoT and Guest clients still got
no DNS answers at all, for hours, before anyone thought to look at Pi-hole itself.

**Root cause: Pi-hole's own host firewall (`/etc/nftables.conf`, unrelated to UniFi, predating
the VLAN migration by months) allow-listed query sources by subnet** — `{192.168.50.0/24,
100.64.0.0/10}` only. Every UniFi-side check (DNAT rule enabled, zone policy allowing the flow,
packets actually arriving at `192.168.50.53:53`) is blind to this: from the gateway's perspective
the traffic was delivered correctly. The drop happened one layer further in, at the destination
host's own packet filter, which the entire zone-firewall test suite in this skill has no way to
see.

**Generalizes beyond Pi-hole:** any DNAT or zone-policy build that redirects traffic to a service
with its own host-level firewall (nftables, iptables, ufw, a cloud security group) needs that
service's own allow-list checked against the **new** set of source subnets a VLAN migration
introduces — a UniFi-side pass is necessary but not sufficient. The bench never caught this
because the bench's own IoT/Guest test devices were, at the time the local firewall was written,
years away from existing; nothing re-audited the destination once new source subnets were added
upstream of it. Fix pattern: `sudo nft list ruleset` (or the host's equivalent) on the actual
destination, not just on the gateway, whenever a redirect's target predates the VLANs now sending
it traffic.

## A WLAN change can silently move your instrument to another SSID

Pinning `AMPJ-IoT-bench` to 2.4 GHz dropped its 5 GHz VAP; the Mac mini's `en1` auto-joined a
*remembered* Guest SSID and the controller kept a stale IoT station entry for it. Every test from
that interface would have measured Guest while labelled IoT. **Check `essid` in `stat/sta` before
trusting any result from a WiFi leg**, and after any WLAN write. `networksetup
-setairportnetwork` may also report "Could not find network" once from scan cache; power-cycle the
radio and retry before concluding the SSID is not broadcasting — the AP's `vap_table` is the
authority for that.

## Testing Apple auto-join: private addresses are per SSID, and iOS picks its own network (2026-09-12)

To test whether an iPhone or iPad rejoins an SSID after a WLAN change (e.g. WPA2 → WPA2/WPA3
transition), you need the device's address **for that SSID**:
- **Private Wi-Fi Address is per network.** A device has a different fixed private MAC on each SSID it
  has joined. A recorded MAC from the Guest or IoT SSID can never match on the main one, so a check
  comparing against it is guaranteed to fail whatever iOS does. Read it from the device (Settings →
  Wi-Fi → ⓘ on *that* SSID → Wi-Fi Address), or from `rest/user` records whose
  `last_connection_network_name` is that network and whose `first_seen` predates the change.
- **With several known SSIDs in range, iOS joins whichever it prefers,** often the most recently used,
  not the one under test. Turn **Auto-Join off on every other known SSID** (home network included), then
  Wi-Fi off/on with no taps. Otherwise the "result" is a join to a different network.
- **Pass criteria:** it associates to the tested SSID with no prompt or tap, `stat/sta` shows the same
  private MAC as that SSID's pre-change `first_seen` record, and the device's own ⓘ page agrees. Check
  `essid` on every observation, and say the SSID name in full when asking a person what they see:
  "bench" and "guest bench" get conflated.
- A watcher polling `stat/sta` should report **new** MACs too, not just the expected ones. A rotated
  address shows up only as a stranger.

## Schedule the undo before a change that can cost you the controller

A network change can take away the path you would use to reverse it. Renumbering the management
subnet is the clearest case: if devices do not re-inform at the new gateway address, the UI you
would fix it from is the thing you just lost. **Snapshot and schedule the revert first, then make
the change, then cancel the revert** — the same shape as the `systemd-run --on-active=` deadman
used before a lockout-capable `ufw`/`sshd` change.

Reference implementation: `scripts/unifi-deadman-revert.py` in the homelab planning repo, run on
the bench observer host. `arm` snapshots the network object and schedules a restore; `disarm`
cancels and wipes; `fire` restores and **verifies by reading back**, never by trusting the PUT's
return code.

Points that make it real rather than theatre:

- **`fire` must not assume the controller is where it was at arm time** — the reason it is firing
  is that addressing went wrong. Try every plausible address, and **authenticate** rather than
  TCP-probe: something else answering on `:443` satisfies a socket test and proves nothing.
- **Retry across a window.** A DHCP lease can take a minute to follow a subnet change.
- **Unreachable is UNKNOWN, not success.** Exit non-zero and say the revert did not happen.
  A deadman that reports success it did not achieve is worse than none.
- **Refuse to arm without a good snapshot.** Armed-with-nothing is the worst state.
- **Key in tmpfs, 0600, never in argv**, removed on disarm.
- **Verify `disarm` against systemd's own view**, not the stop command's exit code.
- **State the shared failure path in the tool's own output.** This host reverts *over the network
  the change affects*; if its lease does not follow, the rescuer is stranded too. Good net for
  "the change applied but the controller moved", no net for "the segment lost DHCP". Write that
  where the operator will read it, or the tool's existence becomes false confidence.

**Test the failure path, not just the happy one.** Point the candidate list at unroutable
addresses and confirm it exits non-zero with an honest message.

### `doh` is a settings row, not a field

`GET /rest/setting` returns ~38 rows, each with a `key`. DNS-over-HTTPS is
`{"key": "doh", "state": "off", "server_names": [...]}` — a **row whose `key` field is `"doh"`**,
not a field named `doh` on some object. A parser scanning key *names* for `doh` finds nothing and
reports "absent", which reads as reassuring and means nothing. `doh` on would bypass Pi-hole for
gateway-originated queries, which a DNAT structurally cannot close, so a false "absent" here is
expensive.

## A one-device exception needs --src-ip, or it silently becomes zone-wide

`unifi-fw add-allow` without `--src-ip` matches **every device in the source zone**, not just the one intended -- a rule meant to carve out a single IoT camera's talk-back path would instead quietly open that path for the entire IoT VLAN. Always pass `--src-ip <device-ip>` to scope an exception to specific sources, and verify by reading the created policy back (its source-IP field), not by trusting the create call's 200/`ok`. First real use: the Nanit talk-back exception, 2026-10-05 (homelab-ansible `39dce16`) -- `192.168.20.109` scoped to only the household phones/iPads on UDP high ports + TCP 4443.

## One host's exception to an outbound block: a narrow allow above it (2026-10-23)

To let one LAN host through a "Trusted → External :853 blocked except the Pi-hole" rule, add a
**separate narrow allow above the block** (`--src-ip` host, `--ip` each permitted destination,
`--port`, `--proto tcp`) rather than widening the block's except-list. Widening exempts that host
for every destination on the port; the narrow allow keeps the rest blocked.

- **Allows toward External can't carry a respond rule.** The controller refuses
  `create_allow_respond: true` toward External (as toward Gateway) with HTTP 400
  `api.err.FirewallPolicyCreateRespondTrafficPolicyNotAllowed`; WAN replies ride connection
  tracking. `unifi-fw` sends `false` for both since homelab-ansible `a7f6eb7`.
- **Packet-test four ways**, with `timeout 4 bash -c '</dev/tcp/<ip>/<port>'`:
  1. allowed host → every allowed destination: REACHED;
  2. allowed host → an unlisted destination on the same port: BLOCKED (the allow is narrow);
  3. another host on the network → an allowed destination: BLOCKED (the block still applies);
  4. a control on the same destinations, e.g. `:443`: REACHED (a BLOCKED in 2–3 is the rule, not
     a dead path).
  Also re-test any host the block's except-list already carved out.
- After inserting above a busy rule, `hits` displayed against the new rule. That's the
  index-shift effect described under reordering above, not real traffic.

## Live WAN failover drill, and AP radio changes (2026-10-09)

**Failover drill:** demote the primary WAN below the cellular WAN with `PUT rest/networkconf/<id>`
(`wan_failover_priority`). Arm the restore first, on a LAN host, with `systemd-run --on-active=600`: the LAN path to
the gateway survives the WAN change, while a remote session may not. API constraints:
- Priorities must be unique, or you get `WanFailOverPriorityAlreadyExists`.
- Valid priorities are only 1–9; 10 and above return `InvalidPayload`.
- So reorder through a parking number: primary to 9, then cellular to 1. The restore parks every WAN on 7/8/9 and then
  writes the snapshot values back.
- Setting the primary to `failover-only` is refused (`MissingWeightedWanNetwork`); the priority swap alone is enough.

Observe four things during the drill:
- the gateway's `stat/device` `uplink.name` (`gre1` = the U5G tunnel);
- egress IP from a LAN host;
- `dig @<gateway> <blocked domain>`, which must still return 0.0.0.0 (DNS stays on Pi-hole over the cellular path);
- throughput.

Finish by diffing the WAN `networkconf` objects against the snapshot. An uplink-change alert
(`wan-failover-watch.sh`) is the natural companion: nothing in UniFi itself notified anyone.

**AP radio change (e.g. 5 GHz to 160 MHz):** `GET rest/device` returned no data on Network 9.x, so snapshot from
`stat/device`, then `PUT rest/device/<id>` with the full `radio_table` modified. A DFS-spanning width forces a 60 s
channel-availability check, during which every 5 GHz client drops. 802.11n devices (HomePods) may settle on 2.4 GHz
afterwards.

## Reading and writing site settings via the API (2026-10-17)

- **Filter by key name, not value length.** `rest/setting` (`mgmt`, `radius`, `magic_site_to_site_vpn`, `connectivity`, `element_adopt`), `rest/wlanconf` and `rest/networkconf` carry short plaintext secrets: device SSH password, API token, RADIUS secret, WireGuard private key, mesh/WLAN PSKs. Drop keys matching `^x_|psk|secret|passw|key|token|private` before printing anything.
- **Writes that persisted with a partial PUT (`X-API-KEY`, UniFi Network 10.6):** `rest/wlanconf/<id>` `{"enabled":false}` and `{"minrate_ng_enabled":true,"minrate_ng_data_rate_kbps":6000}`; `rest/networkconf/<one-click-vpn id>` `{"enabled":false}`; `rest/setting/teleport/<id>` `{"key":"teleport","enabled":false}`; `rest/setting/super_mgmt/<id>` `{"key":"super_mgmt","autobackup_cron_expr":"30 0 * * 0", ...}`. Re-read each: `rc: ok` is not evidence (mDNS writes return ok and are discarded).
- **Raising the 2.4 GHz minimum rate applied without disconnecting clients** and cut the AP's own airtime (`radio_table_stats.cu_self_tx`) from 15% to 4%: beacons go at the minimum rate, so many SSIDs × 1 Mbps beacons is the classic hidden 2.4 GHz cost. Check every client's `tx_rate` is well above the new floor first.
- **Not doable via API:** the built-in `Internet 2` WAN has `attr_no_delete` and no `enabled` field; per-network mDNS scoping is silently dropped.
- `stat/health` `vpn.remote_user_enabled` can still read true right after the One-Click VPN is disabled; trust the networkconf read-back and recheck later.
- Auto-created objects to audit on a new console: a `UniFi Identity` WPA-Enterprise SSID broadcasting on both bands, and a `One-Click VPN` remote-user WireGuard server, both enabled with 0 users.
- **`rest/user?mac=<mac>` ignores the filter** and returns every known client; taking `data[0]` renames whoever is first (it renamed the Mac mini on 10-17, reverted within a minute). Fetch `rest/user`, select by exact `mac` locally, assert exactly one match, then `PUT rest/user/<_id> {"name": ...}` and read back by MAC.
