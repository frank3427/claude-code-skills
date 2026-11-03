---
name: pihole-dot-upstream-failover
description: This skill should be used when adding DNS-over-TLS (DoT) as a Pi-hole upstream resolver, when evaluating cloudflared for DoT/DoH proxying, when a "no fallback DNS" or "DNS failures should surface" constraint needs to coexist with wanting resilience against a recursive resolver (e.g. Unbound) going down, when pihole-FTL --config dns.upstreams rejects an unquoted value as invalid JSON, or when designing an alerted (not silent) failover watcher for infrastructure that must not silently mask its own failures. Trigger phrases include "cloudflared proxy-dns", "cloudflared DoT deprecated", "pihole DNS over TLS", "stubby DoT", "pihole-FTL --config dns.upstreams", "dns.upstreams invalid JSON", "Unbound fallback resolver", "no fallback DNS constraint", "alerted failover watcher", "silent fallback DNS", "pihole upstream failover", "Quad9", "Unbound forward-zone DoT", "forward-tls-upstream", "switch Unbound from recursive to forwarding", "tls-cert-bundle certificate verify failed", "unbound reload vs restart", "serve-expired hides an upstream outage", "FTLCONF_dns_upstreams read-only", "docker Pi-hole upstream".
---

# Pi-hole DoT upstream resolvers: tool choice, config gotchas, and failover design

## `cloudflared proxy-dns` is the wrong tool — don't reach for it

`cloudflared proxy-dns` was deprecated by Cloudflare in November 2025; Cloudflare stopped
shipping it in new `cloudflared` releases as of February 2026 (confirmed via Pi-hole's own docs,
which now carry an explicit deprecation warning on the guide). Existing installs kept working for
roughly 12 months post-deprecation, but it's not safe to stand up fresh.

Independent of the deprecation: `cloudflared proxy-dns`'s `--upstream` flag only ever supported
DoH endpoints (`https://1.1.1.1/dns-query`), **never DoT** (`tls://`). If the goal is specifically
DoT (not DoH), this tool was never the right choice, at any point in its history.

**Use `stubby` instead** — a purpose-built DoT stub resolver, packaged directly in Debian's own
apt repo (confirmed: `stubby` 1.6.0-3.2 on Debian 13/trixie, no third-party repo or GPG key
needed). It's the standard community pattern for "forward only to a specific DoT upstream."

## stubby config gotchas

- **Packaged default listens on `127.0.0.1:53`** (and `::1:53`) — will silently coexist with a
  wildcard `0.0.0.0:53` bind from something else (e.g. pihole-FTL) on Linux, since a
  more-specific bind doesn't conflict with a wildcard one. This is a coincidence of bind
  ordering, not something to rely on — always pin an explicit non-conflicting port.
- **Port syntax on `listen_addresses` is `IP@port`**, e.g. `127.0.0.1@5054` — not `IP#port`
  (that's Pi-hole/Unbound's own convention, easy to cross-contaminate by habit) and not a
  separate config key.
- **Packaged default `upstream_recursive_servers` is a demo/test list** (Sinodun, getdnsapi.net)
  with `tls_pubkey_pinset` entries — replace it entirely for a real deployment. For Cloudflare:
  ```yaml
  upstream_recursive_servers:
    - address_data: 1.1.1.1
      tls_auth_name: "cloudflare-dns.com"
    - address_data: 1.0.0.1
      tls_auth_name: "cloudflare-dns.com"
  ```
  Skip `tls_pubkey_pinset` (hostname validation via `tls_auth_name` is sufficient) — pinning is
  brittle across the upstream's own cert rotations and will silently break resolution when they
  rotate.
- **A broken/invalid `stubby.yml` produces a real crash-loop** (`Could not parse config file:
  ...`), and an Ansible run that only checks for task success (`ok`/`changed`, no failures) will
  look completely clean while the service is actually down. Always verify with `systemctl
  status`/`journalctl -u stubby` after templating a new config, not just the playbook's exit
  code. See the `ansible_managed` gotcha in the global CLAUDE.md's Ansible section for one
  concrete way this happens (a template header silently rendering invalid content while Ansible
  reports success).

## `pihole-FTL --config dns.upstreams` has asymmetric quoting

Setting the value requires quoted JSON strings:
```bash
pihole-FTL --config dns.upstreams '[ "127.0.0.1#5335" ]'
```
An unquoted value (`'[ 127.0.0.1#5335 ]'`) is rejected outright: `not valid JSON`.

But a bare **read** of the same key prints the value **unquoted**:
```bash
$ pihole-FTL --config dns.upstreams
[ 127.0.0.1#5335 ]
```

If you're writing an idempotency check (only write when the live value differs from the target,
to avoid touching FTL on every poll), the read-comparison string and the write-argument string
are **not the same string** — compare against the unquoted read form, but pass the quoted form
when actually setting. Verify this round-trip live with a throwaway set/read before wiring it
into a script; don't assume the two forms match (this is the same quoting idiom used for
`dns.hosts` — see the `pihole-local-dns-records` skill — but that key's *values* are themselves
`"IP HOSTNAME"` strings, so its round-trip masked the same underlying asymmetry differently).

## Every `dns.upstreams` change restarts pihole-FTL

Changing `dns.upstreams` doesn't hot-reload. FTL logs `Restarting FTL due to change of
dns.upstreams`, then does a full internal restart, which means **~0.6s with no DNS at all, plus a
flushed cache**. In FTL v6.7 the key is defined with `FLAG_RESTART_FTL` (`src/config/config.c`), a
property of the key itself, so the CLI (`pihole-FTL --config`), the API and a direct TOML edit all
behave the same. There's no supported no-restart path.

What follows for a failover design:
- A failover and its recovery each cost one short total outage. Measured in the homelab's forced
  test on 2026-09-12: ~7.7s of failed uncached lookups before the switch, then ~0.6s dark at each
  restart.
- Never write the key unless the value actually changes (the idempotency check above).
- Don't "fix" it by keeping two upstreams configured permanently. That's exactly the standing
  silent fallback the constraint forbids.
- Make the probe resistant to false positives, since every false failover is a real outage.

## Designing resilience without violating a "no silent fallback" constraint

If the environment has a standing rule like "DNS failures should surface, not be silently
patched with a secondary resolver" (or any analogous "no silent fallback" infra constraint), an
always-live second upstream (Pi-hole picks whichever responds) violates it even if the intent
was just resilience — a failing primary resolver gets silently absorbed by the fallback with no
signal that anything is wrong.

**Pattern that satisfies both goals** (resilience *and* "failures surface"): an **actively
health-checked, alerted, actuated failover**, not a standing blend:

1. Steady state: primary resolver only, single upstream, unchanged from a no-fallback baseline.
2. A watcher (systemd timer, ~15s interval, with a `flock` so runs can't overlap) runs a **real
   query** against the primary, not just `systemctl is-active`, which misses a wedged-but-running
   resolver. Three traps, all found in the homelab's own watcher on 2026-09-12:
   - **Require an actual answer, not a zero exit code.** `dig` exits 0 on SERVFAIL, so an
     exit-code-only probe reads the broken-root-hints case as healthy. Pipe `+short` output through
     `grep -q .`.
   - **Probe TCP as well as UDP** (`dig +tcp`). FTL talks to its upstream over TCP too, and a
     UDP-only probe was blind to a real 2026-07-22 failure where TCP connections were reset while
     UDP still answered.
   - **Two attempts per protocol within a run** (2s each), so one dropped packet doesn't fail over.
     A failover restarts FTL (below), so false positives cost real outages. Keep the worst-case
     probe time inside the interval; the homelab measured 8.1s against a blackholed host.
   - **If the primary forwards to an upstream** (the homelab's Unbound → Quad9 DoT since
     2026-10-23), a fixed-name probe only tests the cache. With `serve-expired` a stale answer
     survives for a day, so a dead upstream reads healthy while every uncached name SERVFAILs
     (reproduced with a test Unbound behind an nft drop). Add a probe for a **never-seen random
     name** (`pdf-probe-<ns>-<rand>.cloudflare.com`) that must return NOERROR/NXDOMAIN.
     `unbound-control flush <name>` is NOT a fix: it marks entries expired, which serve-expired
     then serves. Pick a zone with NSEC "black lies" (cloudflare.com) so `aggressive-nsec` can't
     synthesize the answer locally.
3. On a genuine health-check failure: **clean cutover** (replace the upstream entirely, don't
   blend) to the secondary, plus an **immediate alert** (Telegram, PagerDuty, whatever's already
   wired up) — the human is told the instant the fallback engages, not after the fact via a
   dashboard someone has to remember to check.
4. On recovery: revert, and alert again.
5. State for detecting *transitions* (so you only alert on the edge, not every 30s tick) lives
   on tmpfs (e.g. `/run/<name>/state`), not disk — a reboot always re-verifies live rather than
   trusting stale state across a restart. Default a missing state file to "healthy" so a normal
   boot doesn't fire a spurious recovery alert, while a real ongoing outage at boot still alerts
   correctly (the health check itself is live, not the default assumption).
6. Route the alert directly from the watcher (a raw API call), not through a monitoring stack
   dependency (Prometheus/Grafana alerting) — the failover mechanism and its alert shouldn't
   depend on the monitoring stack being up, especially for infrastructure the monitoring stack
   itself might depend on (e.g. DNS).
7. If this is managed by the same Ansible/config-management tooling that also asserts a baseline
   state, make sure the baseline-assertion task doesn't fight a legitimate in-progress failover —
   only correct the config if it's in neither of the two *recognized* managed states, not
   unconditionally reset to the steady-state default.

Verify this kind of design with a **live** test, not just a config review: actually stop the
primary, confirm an uncached query genuinely fails in the gap before the watcher reacts (proves
the failure really surfaces), confirm the cutover and alert both fire, confirm real traffic gets
served during the outage (check the actual query/access log, not just synthetic test queries),
confirm the secondary path is doing what it claims (e.g. packet-capture the failover traffic and
check for a real TLS record header if it's supposed to be encrypted — `17 03 03` at the start of
the payload, not just "port 853 is being used"), then restore the primary and confirm a clean
revert. If the underlying host can reboot, do that too and confirm both services and the
watcher's own state come back correctly rather than trusting a stale assumption.

For a steady-state "is anything still in plaintext" check, capture egress for `port 53 and not net
<LAN> and not net 100.64.0.0/10` for ~30 s. The control is a second capture of `dst port 853` on
the same interface, which must show packets to the provider, or an empty first capture proves
nothing. On 2026-10-25 both Pi-holes gave 0 plain packets against ~40 DoT packets to Quad9.

## Diagnosing a "DNSSEC validation looks broken" false alarm

A health check that queries a deliberately-broken-signature test domain (`dnssec-failed.org`,
`sigfail.verteiltesysteme.net`) and expects `SERVFAIL` can false-alarm for a reason that has
nothing to do with Unbound's own validator: those domains are rarely cached anywhere (Unbound's
`val-bogus-ttl` default is 60s), so almost every check is a cold query, and their own external
authoritative nameservers occasionally take 20-60s+ to respond — a single bare `dig` with
default retry behavior (~15s total) has no margin for that. Confirmed live 2026-08-30 on the
homelab's Pi-hole: a weekly sweep's `pihole_dnssec_validation` check FAILed, but the validator
was genuinely correct and fast the whole time.

**How to tell "really broken" from "cold query to a slow external test domain" without
guessing:**

1. Bypass Pi-hole-FTL and query Unbound directly on its own port, not through the resolver
   chain: `dig +tries=1 +timeout=20 @127.0.0.1 -p 5335 dnssec-failed.org` (adjust the port to
   whatever the local `unbound.conf.d/*.conf` sets — `5335` here). This isolates "is Unbound
   itself slow/wrong" from "is something upstream of Unbound (FTL, the LAN path) the problem."
2. Force a genuinely cold query rather than trusting an ambient cache state:
   `unbound-control flush_zone dnssec-failed.org` right before the test query.
3. Raise verbosity to watch the validator's own reasoning in real time:
   `unbound-control verbosity 3`, then `journalctl -u unbound -f` (or `--since`) while the query
   runs. Look for `Did not match a DS to a DNSKEY, thus bogus` / `Could not establish a chain of
   trust` — if that line appears (even if the client-side `dig` timed out before ever seeing a
   reply), the validator concluded correctly and quickly; the delay is downstream of validation
   logic, in getting a reply back to the client at all. **Set verbosity back to 1 when done** —
   verbosity 3 is chatty and not meant to run steady-state.
4. Cross-check with a working control query in the same breath:
   `sigok.verteiltesysteme.net` (should resolve `NOERROR`) and a real-world uncached domain
   (should resolve in well under a second) — if those are fine, general connectivity/root-server
   reachability isn't the cause, narrowing it further to that one test domain's own external
   reachability at that moment.
5. Retry a few times, spaced a minute+ apart. This kind of slowness is usually transient and
   self-resolving within minutes (external nameserver hiccup, not a local config problem) —
   confirmed by 4 consecutive fast/correct results minutes after reproducing the slow case live.

If a health-check script needs to encode this distinction itself (not just a one-off manual
diagnosis), don't just lengthen a single `dig`'s timeout — retry a few times with a moderate
per-try timeout, and treat "never got any response" as a `warn` (worth a glance) rather than a
`fail` (confirmed broken), reserving `fail` for an actual non-`SERVFAIL` answer. See the
homelab's `weekly-housekeeping-checks.sh` `pihole_dnssec_validation` check (fixed
2026-08-30, `homelab-ansible` commit `bd8bfc7`) for a working example of this shape.

## Unbound DoT forwarding gotchas (2026-10-23)

- **A HUP reload does not load `tls-cert-bundle`.** Adding a `forward-tls-upstream` zone plus the
  bundle by `systemctl reload unbound` left every handshake failing `certificate verify failed /
  unable to get local issuer certificate` until a full restart. Restart on any TLS-related config
  change. A fresh test instance on another port won't show it, because it starts cold.
- **Check the network allows :853 from that host before switching.** A gateway "block DoT except
  the Pi-hole" rule made the iMac replica SERVFAIL everything. `timeout 4 bash -c '</dev/tcp/9.9.9.9/853'`
  from the host first, with `:443` as a control.
- Never set `forward-first: yes` under a no-silent-fallback constraint: it falls back to recursion
  when the forwarders fail.
- Verify with `dig proto.on.quad9.net TXT` (returns `"dot"` over DoT), `dnssec-failed.org` →
  SERVFAIL, and Google's `o-o.myaddr.l.google.com TXT` (no `edns0-client-subnet` line = no ECS).
- Quad9-blocked domains that are DNSSEC-signed come back **SERVFAIL** through a validating Unbound
  (Quad9's NXDOMAIN has no proof), not NXDOMAIN. Still blocked; just don't read it as an outage.
- **Containerized Pi-hole (docker):** an `FTLCONF_dns_upstreams` env var makes `dns.upstreams`
  read-only, so a watcher can't flip it — unpin it. But removing the var does NOT keep the old value:
  FTL falls back to the image default (`8.8.8.8, 8.8.4.4`, plaintext) on recreate. Set the value with
  `docker exec pihole pihole-FTL --config dns.upstreams '[ "127.0.0.1#5335" ]'` in the same breath
  (better: have Ansible set it before the recreate is even possible to observe). The in-container FTL
  restart a change triggers is fine — the container doesn't restart.
- **Simulating an upstream outage for a containerized Unbound:** its egress goes through the host's
  FORWARD path, so an nft `output` drop alone doesn't block it — add a `forward`-hook chain too. And
  don't name the chain `fwd`: it's a reserved word in nft ("syntax error, unexpected fwd").


## Forwarding mode: a leak-test burst trips the provider's per-IP block (2026-10-25)

A DNS leak test (dnsleaktest.org) sends ~1,000+ random, mostly failing names in seconds. **Quad9
blocks the whole public IP for ~30-60 s** when it sees that, which was proven from a second LAN host
that sent none of the burst. Unbound makes it about 10x worse by default: on every SERVFAIL it
re-asks each forwarder up to `outbound-msg-retry` (5) times, and the provider gives the same
answer each time. The forwarders get benched (`tA 3`, `rto 120000` in `dump_infra`), every
uncached name SERVFAILs in 0 ms, and the watcher fails over. Set, on every Unbound:
```
outbound-msg-retry: 0   # 1 absorbed single-resolver bursts; 0 needed when a client hits both Pi-holes at once
infra-host-ttl: 60      # backstop: a bench clears in ~1 min, not 15+ (the iMac was stuck 18 min)
infra-keep-probing: yes # host-down case only; does not fix this on its own
```
Even on 0, a two-resolver leak test (~2,300 names in 16 s) still trips about a 10 s block: what
Quad9 reacts to is the failing-random-name pattern, not raw rate (the house's normal peaks reach
118/s without any block). `unbound-control set_option` rejects 0, so set it in the config.
**Every leak test still trips the block and fails both watchers over for ~1 min** (one alert pair
per Pi-hole, recovery unaided). Whether the *report* shows Cloudflare is a race. The test sends
waves over ~15 s, and the watcher's 15 s timer flips the upstream partway through. Any wave after
that goes to Cloudflare. Four tests on 10/25: Cloudflare 145 (retry 1, primary flipped 2 s before
the last wave), 0 (retry 0, burst ended 5 s before the flip), 158 (retry 0, a final wave of 112
landed 2 s after the flip). retry 0 did not change the outcome; the clean run was timing. Expect
Quad9 plus sometimes Cloudflare, never the ISP, and treat either as a pass, not an incident. Don't add a "ignore failovers under a minute" debounce: it
would also hide the first minute of a real outage.
Ruled out: `infra-cache-min-rtt` (no help), a Pi-hole per-client rate limit (real devices burst to
700-1,365/min), and an Unbound rate cap (normal peaks are above a leak test's per-resolver rate). Testing: a lab Unbound on another port isolates Unbound state, *not* the
provider's per-IP block, so each burst still briefly affects the house. Pause BOTH watchers (pihole's and
imac's `pihole-dot-failover.timer`) before any DNS burst test: the per-IP block covers the shared
public IP, so a burst against either resolver benches both. Resume each only after its own
UDP+TCP+random-name probes pass 3x in a row, and check both Pi-holes' `change of dns.upstreams`
log lines before reporting how many pages went out. Use an external probe from another host as the
control. Detail: the `reference_unbound_forwarder_benching` memory.
