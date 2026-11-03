---
name: forced-outage-drill
description: >-
  Simulate a dependency outage on a live host (upstream DNS, an API endpoint, a backup target,
  a peer) to prove a watcher, failover or alert actually works, without paging anyone and
  without the drill passing for the wrong reason. Covers proving the block bites (nft counters
  plus a control) before trusting any result, why container egress needs a forward-hook chain,
  cache and stale-answer layers that hide the outage, a systemd-run dead-man revert, testing a
  new watcher against a throwaway instance on a spare port with stubbed alerting, and the drill
  sequence: baseline, failure surfaces, failover, recovery, cleanup. Trigger phrases include
  "failover drill", "simulate an outage", "force a failover", "test the watcher", "blackhole the
  upstream", "nft drop for a test", "dead-man revert", "does the alert actually fire", "drill
  without paging", "stub telegram", "prove the failover works".
---

# Forced-outage drills that mean something

A drill is only evidence if the outage really happened. The usual failure isn't a crash; it's a
green result because the simulated fault never reached the thing under test. On 2026-10-23 a
single DNS session hit this three times. All three looked like "the system copes fine":

- an nft rule keyed on `meta skuid 0` dropped nothing the test needed, and lookups kept answering;
- `unbound-control flush <name>` didn't empty the cache: with `serve-expired` it only marks entries
  expired, and they keep being served;
- the drill's container chain was named `fwd`, a reserved word in nft, so it was never created;
  the output-only rule left container egress untouched.

## 1. Prove the block bites before reading any result

- Put a `counter` on every drop rule and **print the counters** after the fault window. Zero
  packets means no outage happened, whatever the probes said.
- Pair it with a **control** on the same host that must still work (another port or address on
  the same path, e.g. `:443` to the same IP while `:853` is blocked). A dead host and a working
  block look identical without one.
- Quick reachability probe, no extra tools: `timeout 4 bash -c '</dev/tcp/9.9.9.9/853' && echo
  REACHED || echo BLOCKED`.
- **Expect the failure to surface first.** Before the watcher reacts, an uncached request must
  actually fail. If it succeeds, something (cache, stale answers, a fallback) is masking the
  fault, and the drill is testing that layer, not the watcher.

## 2. Block at the layer the traffic actually takes

- **Host processes:** an `output`-hook chain.
- **Docker containers on a bridge:** egress traverses the host's **forward** path, so an
  `output` drop alone does nothing. Add a `forward`-hook chain too:
  ```
  nft add table inet drill
  nft add chain inet drill out '{ type filter hook output priority 0; }'
  nft add chain inet drill fw  '{ type filter hook forward priority 0; }'
  nft add rule inet drill out ip daddr '{ 9.9.9.9, 149.112.112.112 }' tcp dport 853 counter drop
  nft add rule inet drill fw  ip daddr '{ 9.9.9.9, 149.112.112.112 }' tcp dport 853 counter drop
  ```
  Don't name a chain `fwd` (`syntax error, unexpected fwd`). Keep the drill in its own table so
  cleanup is one `nft delete table inet drill`, and it never touches Docker's own tables.
- Avoid clever matches (`skuid`, cgroup) unless you've confirmed with counters that they match.
  A plain destination plus port match is easier to trust.

## 3. Defeat the layers that hide the outage

Caches, stale answers and connection reuse make a probe succeed through a dead dependency:

- Probe something no cache can hold: a **never-seen random name or path** per run (e.g.
  `probe-$(date +%s%N)-$RANDOM.cloudflare.com`), accepting a real negative answer (NXDOMAIN or 404)
  as success. For DNS, pick a zone with NSEC "black lies" (cloudflare.com) so aggressive-NSEC can't
  synthesize the answer locally.
- "Flush" commands aren't always deletes. Check whether they only expire entries.
- Long-lived TLS/TCP connections can keep working briefly after a new-connection block; a
  stateless drop of all packets to the destination avoids that.

## 4. Always arm a dead-man revert

Anything that can cut the host off, or leave production degraded if your session dies, gets a
timed undo that outlasts the drill, armed **before** the fault:

```
systemd-run --quiet --unit=drill-deadman --on-active=240 /bin/sh -c \
  'nft delete table inet drill; <restore production state>; systemctl start <paused-timer>'
```

Cancel it on a clean finish (`systemctl stop drill-deadman.timer; systemctl reset-failed
drill-deadman.service`) and confirm it's gone. Size the deadline to outlast the whole run: a
revert that fires mid-drill voids the result.

## 5. Never page a human for a designed failure

- Pause the real watcher's timer for the drill, and run the real watcher by hand with its alert
  function stubbed to a log file (`send_telegram(){ echo "$1" >> /run/drill/tg.log; }`). Restart
  the timer at the end, and in the dead-man.
- Point the run's state at a scratch dir, so the production watcher's transition state isn't
  disturbed.
- Verify the real alert path separately without sending: e.g. Telegram `getMe` with the token
  read from the env file via `curl -K <(printf 'url = ...')`, never in argv.
- Design watchers with env overrides for exactly this (`PDF_LIB`, `PDF_STATE_DIR`, `PDF_FTL_BIN`,
  ports, probe host). Production sets none of them.

## 6. Test a new or changed watcher before it ships

Run the **old and new watcher side by side against a throwaway instance** of the dependency on a
spare port (a second Unbound on :5399 with the production config, its own control socket and
pidfile, `chroot: ""`). Feed both the same fault. The result worth keeping is the comparison:
"the old one stayed healthy, the new one failed over in 4 s". Stub the side-effect binaries too
(a fake FTL that records the upstream it was set to), and confirm production state is unchanged
at the end.

A throwaway instance started cold can hide a **reload-path** bug: on 2026-10-23 the test Unbound
was fine, while production, changed by HUP, failed every TLS handshake (HUP doesn't load
`tls-cert-bundle`). If production will be changed by reload, test a reload too.

## 7. The sequence

1. **Baseline:** watcher healthy, real path verified (e.g. `proto.on.quad9.net` → `"dot"`).
2. **Fault:** apply the block; confirm an uncached request genuinely fails before any reaction.
3. **Failover:** time it, then confirm real traffic is served on the fallback and the
   protections stay intact (ad blocking, DNSSEC).
4. **Counters:** print them. Non-zero, or the run is void.
5. **Recovery:** lift the block; time the revert and the recovery alert; re-verify the real path.
   One empty probe right after a service restart is normal. Re-check before calling it a failure.
6. **Cleanup:** drill table gone, dead-man cancelled, real timer active, production state back
   to the steady-state value, the scratch dir removed.

Related: `pihole-dot-upstream-failover` (the DNS watcher these lessons came from),
`ssh-exposure-audit` (dead-man around SSH/firewall changes), `unifi-zone-firewall-testing`
(packet-testing gateway policies with controls).
