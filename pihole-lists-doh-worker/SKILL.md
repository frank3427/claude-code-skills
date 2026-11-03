---
name: pihole-lists-doh-worker
description: This skill should be used when giving phones or tablets Pi-hole-style ad-blocking away from home without depending on a VPN/Tailscale tunnel. It covers serving Pi-hole's own lists as DNS-over-HTTPS from a Cloudflare Worker, iOS/iPadOS DNS-settings profiles (.mobileconfig) with SSID OnDemand rules, and the Worker's upstream (Quad9 over DoT via cloudflare:sockets). Built 2026-11-02 for Will (repo jackson2w/roaming-dns-worker, homelab-ansible roaming-dns.yml). Trigger phrases include "ad blocking on the go", "roaming DNS", "DoH Worker", "DNS over HTTPS cloudflare worker", "pihole lists cloudflare", "mobileconfig DNS profile", "com.apple.dnsSettings.managed", "OnDemandRules SSIDMatch", "iOS DNS profile not working", "Use Tailscale DNS settings", "Quad9 DoH 505", "HTTP Version Not Supported quad9", "cloudflare:sockets DoT", "error code 1010", "Python-urllib 403 workers.dev", "Workers Builds name mismatch", "npm install-scripts approve workerd", "roaming-dns-canary", "roaming-dns-sync".
---

# Pi-hole's lists as a DoH Worker (ad-blocking that survives tunnel stalls)

**Why:** with roaming DNS over Tailscale to a home Pi-hole, any tunnel stall kills all DNS (see
`tailscale-pihole-dns-routing`, the last section). This pattern takes the tunnel out of the DNS path but
keeps **Pi-hole as the only place lists are edited**.

## Shape

```
iPhone/iPad --iOS DNS profile (DoH)--> Cloudflare Worker --DoT 853--> Quad9
                                         lists bundled in the Worker, committed nightly by the control node
home Wi-Fi: profile OFF by SSID rule --> Pi-hole on the LAN as before
```

- **The Worker** (RFC 8484, GET `?dns=` and POST `application/dns-message`) at `/dns-query/<device-token>`.
  - Allow (exact, then regex) wins; then exact deny or gravity; then regex deny. This is Pi-hole's order.
  - A blocked name answers `0.0.0.0` / `::` with TTL 2; any other record type gets an empty NOERROR.
    This is Pi-hole's NULL mode.
  - Homelab names (`*.jackson2w.dev`, `<dev>.<tailnet>.ts.net`) are answered from a synced
    `local.json`, because the device no longer uses Tailscale's DNS.
  - Upstream failure answers **SERVFAIL, never a fallback** (hard constraint #1).
- **Lists ship in the bundle**, not KV: 77k domains is about 1.6 MB, and the size limit is 64 MiB.
  - The control node commits `lists/` to the repo, and Workers Builds (Git-integrated) deploys the push.
  - **There's no Cloudflare API token anywhere.** Same pattern as the williejackson static site.
- **Tokens:** generated on the control node with `openssl rand ... | infisical-set.sh`. The repo holds only
  `sha256(token) -> device`. Rotate one by changing Infisical; the next sync locks the old token out.
- **Logging:** counts only (device, outcome, query type) in Analytics Engine.
  **Observability off:** request logs would store the URL, and the URL carries the token.
- **Guards in the sync:** refuse a blocklist under 10k entries or one that shrank more than 20%.
  `meta.generated_at` changes only when the content changes, so an unchanged night makes no commit.
- **Monitoring:** a 5-minute canary queries a blocked name, a normal name (this proves the upstream)
  and `/health` list age. Telegram after 2 consecutive failures, once per streak, plus on recovery.

## Gotchas (each one hit for real)

| Symptom | Cause / fix |
|---|---|
| Quad9 DoH returns **505 HTTP Version Not Supported** | Quad9 has been **HTTP/2-only** for DoH since 2025-12-15 (port 5053 retired in May 2025). Worker `fetch()` to an outside server can't be relied on for h2. **Use DoT through `connect()` from `cloudflare:sockets`** (`secureTransport:"on"`, 2-byte length framing). Same upstream and protocol as Unbound. |
| Upstream fails in `wrangler dev` but production is fine | The home LAN blocks outbound **853** for everything but Pi-hole (UniFi §6a). Prove forwarding against the deployed Worker. |
| Every request returns **403, "error code: 1010"** from a script, but curl works | Cloudflare's bot check rejects **Python-urllib's default User-Agent**. Set your own User-Agent in tests and the canary. iOS clients are unaffected. |
| `wrangler dev` won't start after `npm install` | npm 11 holds install scripts. Run `npm install-scripts approve workerd` then `npm rebuild workerd`. Pin wrangler to an exact version at least 2 weeks old. |
| Builds might fail after the dashboard connect | The dashboard named the Worker after the repo (`roaming-dns-worker`). Make `wrangler.jsonc` `name` match. |
| "Protect with Cloudflare Access?" | **No.** An iOS DNS profile holds only a URL: no login, no headers. Access would redirect every query and kill DNS. The path token is the access control. |
| Profile installed, but the device still queries Pi-hole over 100.x | (1) On an unsupervised device the profile must be **selected under Settings > General > VPN & Device Management > DNS**. (2) Tailscale's DNS overrides it, so turn off **Tailscale > Settings > "Use Tailscale DNS settings"** on that device only. Proof: the device's 100.x queries disappear from Pi-hole while it's on cellular. |
| `gh repo create` worked but a later `git pull` says "could not read Username" | Run `gh auth setup-git` once on the host. |

## The iOS profile

`com.apple.dnsSettings.managed`, `DNSProtocol: HTTPS`, `ServerURL: <worker>/dns-query/<token>`.
`OnDemandRules` are `[{Action: Disconnect, SSIDMatch: [home SSIDs]}, {Action: Connect}]`. Use every
SSID that gets Pi-hole: here AMPJ5, AMPJ4712 and AMPJ-IoT.

**Delivery without the token touching chat:**
- `infisical-wrapper.sh roaming-dns-profile.sh <device>` on ansible-ctrl writes it with plistlib.
- It serves the profile through a loopback Python server with
  `Content-Type: application/x-apple-aspen-config` (Safari then offers to install it).
  The server serves only that one file.
- Exposure is `tailscale serve --https=8443` (tailnet only), switched off by a 2-hour systemd timer.
- The first request may take a few seconds while Serve gets its certificate.

**Acceptance test:** on cellular with **Tailscale fully off**, sites load and ads are blocked.
`test/doh-test.py` in the repo has 19 positive and negative checks; the token goes in `DOH_TOKEN`
(env), never argv.

**Known differences from Pi-hole:** no CNAME deep inspection, and groups are ignored.

## Answer cache (added 2026-11-02): build it, it pays

**Don't skip the cache on the theory that the client already caches by TTL.** On this fleet, Pi-hole
answered about 78% of an iPhone's lookups from cache, and half of those were *stale* hits (Pi-hole's
optimistic serving). A Worker without a cache pays the upstream round trip (+20-50 ms) on every one.
Check the resolver's own data first: FTL `query_storage.status` 3 = cache, 17 = stale cache,
`reply_time` per query.

Pattern (`roaming-dns-worker/src/cache.js`, 17 node:test cases with a fake clock, upstream and edge):

- **Key:** `name|qtype|qclass|DO bit|CD bit`. The DO bit lives in the OPT record's TTL field.
- **Cache only NOERROR and NXDOMAIN without TC.** Negative TTL = min(SOA TTL, SOA MINIMUM). Clamp to
  1 day. TTL 0 means don't cache.
- **Serving:** copy the bytes, set the asker's ID, copy the asker's question bytes (mixed case), and
  rewrite every non-OPT TTL (age-decremented, or 30 when stale).
- **Serve-stale for up to a day,** with one background refresh per key via `ctx.waitUntil`. A failed
  refresh keeps the old entry.
- **Two layers:** the isolate's Map (LRU, 10k entries), then `caches.default`.
- **The Cache API works on `*.workers.dev`** (verified 2026-11-02 with a real put then match, reported
  by `/health` as `edge_cache`), even though the docs only promise it on custom domains. Measure it;
  don't move to a custom domain on the docs' word.
- **Add an `x-cache: hit|stale|miss` response header.** It's the only cheap way to see the cache
  working from outside when Analytics Engine has no reader.
- **Live stale test:** find a name with a TTL of a few seconds (www.microsoft.com was 2 s), ask once,
  sleep past its TTL, then ask three times. You should see hit, then stale with TTL 30, then hit.
- **Benchmark interleaved** (blocked, cached, unique names, round-robin) over one kept-alive
  connection. Back-to-back batches pick up network drift: one run showed blocked names at 57 ms
  against 31 ms interleaved.

## Per-device rollout and proof (iPad and iPhone, 2026-11-02)

Steps on each device, after installing the profile from the temporary tailnet-only link:
1. Under Settings > General > VPN & Device Management > DNS, **select** the profile. iOS shows it as
   "Unknown"; that's normal.
2. In the Tailscale app, turn off **Use Tailscale DNS settings**. The app then shows an
   "Advanced DNS Settings" page (None / Automatic / Custom). Leave it on **Automatic**; that page
   only appears when Tailscale DNS is off.
3. **Prove it on cellular with two Safari loads:** a blocked name (`doubleclick.net`) should fail with
   "can't connect", and a homelab name only the Worker knows (`grafana.jackson2w.dev`) should load
   over the tunnel. "No more Pi-hole queries from the device's 100.x address" proves only where
   lookups stopped going. It can't tell the Worker apart from a silent fallback to carrier DNS.
4. Take the profile link down (`roaming-dns-profile.sh --stop`). Pi-hole's per-minute counts for the
   device's 100.x address should stop at the moment Tailscale DNS was turned off.

## Blocked-answer TTL: 300 s, not Pi-hole's 2 s

Pi-hole uses 2 s so allowlist edits apply instantly. The Worker's lists only change at the nightly
sync, so 2 s just makes apps re-ask for blocked trackers (more requests, more radio wake-ups). The
DoH test asserts the 300. Keep the sync **nightly** even though blocklists change weekly: it only
deploys on a content-hash change, and it's what makes the owner's own allow/deny edits follow the
device by the next morning.
