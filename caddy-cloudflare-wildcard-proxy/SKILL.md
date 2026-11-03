---
name: caddy-cloudflare-wildcard-proxy
description: This skill should be used when standing up Caddy as a reverse proxy for internal/homelab domains with a wildcard TLS certificate via Cloudflare DNS-01, when a Caddyfile needs one certificate to cover many internal hostnames, when routing Caddy to a backend that's deliberately bound to loopback only and reachable via an existing Tailscale Serve endpoint, when a Caddy instance itself needs to be loopback-only and a request returns an empty 200 response or `ss -tlnp` shows it listening on `*:port` despite the site address looking like `127.0.0.1:port`, or when debugging a fresh unprivileged LXC where tailscaled fails with "/dev/net/tun does not exist" or MagicDNS doesn't register into systemd-resolved. Trigger phrases include "caddy wildcard cert", "caddy dns-01 cloudflare", "caddy custom build dns plugin", "reverse proxy to tailscale serve backend", "loopback-bound service reverse proxy", "tun device does not exist unprivileged lxc", "tailscale magicdns not registering systemd-resolved", "split-horizon internal domain caddy", "caddy empty 200 response", "caddy content-length 0", "caddy site address host matcher not bind", "caddy listening on wildcard despite 127.0.0.1", "tailscale serve empty response from caddy backend".
---

# Caddy + Cloudflare DNS-01 wildcard proxy for internal domains

Pattern for fronting several internal/homelab services with friendly hostnames
(`service.example.dev`) under one real, trusted wildcard certificate, without any public DNS
record — Cloudflare is used purely as the ACME DNS-01 challenge provider.

## Custom Caddy build for DNS plugins

Stock Caddy packages (apt, official binary releases) do **not** include DNS provider modules —
DNS-01 wildcard certs need `caddy-dns/cloudflare` (or the equivalent for another provider), which
isn't in the default build. Rather than requiring a Go toolchain + `xcaddy` on the target host,
fetch a prebuilt custom binary from Caddy's official build server:

```
https://caddyserver.com/api/download?os=linux&arch=amd64&p=github.com%2Fcaddy-dns%2Fcloudflare
```

Verified live: returns HTTP 200, `content-disposition: attachment; filename="caddy_linux_amd64_custom"`.
Swap `p=` for a different DNS provider module path, or chain multiple `&p=` params for more than
one plugin. Use `ansible.builtin.get_url` (or plain `curl`) straight to `/usr/local/bin/caddy`,
mode `0755` — no build step needed on the target.

**`get_url` with `force: true` re-downloads on every playbook run**, and the build server can
return a different binary (a newer plugin, or a new Caddy release) with no version change on your
side. `--check` always reports that task as changed. When a run is meant to change only the
Caddyfile, compare `caddy version` with the latest release and use `--start-at-task "Deploy
Caddyfile"`, then confirm the binary's checksum didn't move. Make upgrades a deliberate run.

## One wildcard cert covering many hostnames

Put every internal hostname in a **single site block** keyed on the apex + wildcard, and route
by `Host` header inside it with `@matcher`/`handle` pairs — not one site block per hostname (that
issues a separate cert per name):

```caddyfile
{
    email you@example.com
}

example.dev, *.example.dev {
    tls {
        dns cloudflare {env.CF_API_TOKEN}
    }

    @service1 host service1.example.dev
    handle @service1 {
        reverse_proxy 192.168.1.10:8080
    }

    @service2 host service2.example.dev
    handle @service2 {
        reverse_proxy https://192.168.1.20:8443 {
            transport http {
                tls_insecure_skip_verify
            }
        }
    }

    handle {
        respond "Not found" 404
    }
}
```

Confirm it actually issued one cert, not N: `openssl x509 -noout -ext subjectAltName` against
any hostname should show a single `DNS:*.example.dev` SAN. New internal hostnames later are a
`@matcher`/`handle` pair plus one DNS record — zero new cert work, since the wildcard already
covers them.

`tls_insecure_skip_verify` on a specific backend's `transport http` block is the right tool when
that backend serves a self-signed cert (e.g. Proxmox VE/PBS web UIs on 8006/8007) — the Caddy
*edge* still presents the real trusted cert to clients, so this is a contained backend-leg
tradeoff, not a user-facing warning. Confirm which backends actually need it by checking with
`ss -tlnp` on the real host — don't assume; some are already directly reachable, others aren't.

## Routing to a backend that's deliberately loopback-bound

A common pattern in a Tailscale-first homelab: a service binds `127.0.0.1` only on its own host,
reachable exclusively through an existing `tailscale serve` mapping — done deliberately to
minimize exposure. **Don't widen that bind address** just to make it reachable from the new Caddy
host; that changes an already-deployed service's security posture for no real gain.

Instead:
1. Join the Caddy host to the tailnet as a **plain client** (`tailscale up --hostname=<name>`,
   no subnet routes, no exit node — needs one-time interactive browser auth at the URL it prints).
2. Point `reverse_proxy` at the backend's existing Serve URL instead of its raw port:
   ```caddyfile
   reverse_proxy https://backend.tailnet-name.ts.net {
       header_up Host backend.tailnet-name.ts.net
   }
   ```
3. Verify the backend's actual Serve config first with `tailscale serve status` on that host —
   don't assume a port or path; read the real mapping.

The `header_up Host` override matters: Caddy forwards the original inbound Host header
(`service.example.dev`) by default, but some backends validate Host against an allowlist (e.g. a
Next.js app's `ALLOWED_HOSTS`-style env var checking for the tailnet hostname) and will reject
anything else. Override it to whatever the backend actually expects. Tailscale-issued certs are
already publicly trusted (Let's Encrypt via Tailscale), so no `tls_insecure_skip_verify` needed
for this path.

**The Host override breaks CSRF origin checks.** The browser still sends `Origin:
https://service.example.dev`, which no longer matches the Host the backend sees. Grafana rejects
every logged-in write with 403 `origin not allowed`; fix it with `csrf_trusted_origins =
service.example.dev` under `[security]` *before* the switch. A plain login test won't show this,
because Grafana skips the check when there is no session cookie. Test with a dummy one:
`curl -X POST -H 'Origin: https://service.example.dev' -H 'Cookie: grafana_session=x'
https://backend.ts.net/api/dashboards/db` should give 401, not 403, and a foreign Origin should
still give 403 (found 2026-10-25 moving Grafana off a plain-HTTP LAN upstream).

## Split-horizon internal DNS

No public A/CNAME record needs to exist. Cloudflare's role is solely the DNS-01 challenge — a
token scoped to `Zone:DNS:Edit` on the one zone is enough; Caddy creates/deletes its own
`_acme-challenge` TXT records automatically. Resolve the hostnames internally instead (e.g.
Pi-hole Local DNS Records, `dns.hosts`) pointing each name at the Caddy host's LAN IP.

Pi-hole's TOML-based Local DNS Records do **not** support wildcard/glob entries — each new
subdomain needs one explicit line. The wildcard/automatic part is the *certificate*, not the DNS
record.

Verify split-horizon actually holds by querying a public resolver directly and confirming it
returns nothing: `dig +short <hostname> @1.1.1.1`.

## A loopback-only site address is a Host *matcher*, not a socket bind restriction

When a small app-fronting Caddy instance itself needs to be loopback-only (e.g. it sits behind
Tailscale Serve on the same host, matching the "loopback-bound backend" pattern above but for
Caddy itself, not the app behind it), writing the site address as `http://127.0.0.1:8000 { }`
does **not** restrict the actual socket bind — Caddy still listens on `*:8000` (verify with
`ss -tlnp`), and `127.0.0.1` in the site address instead becomes a **Host-header matcher**.
Confirmed live 2026-08-21: a request whose Host header didn't literally match fell through to
an empty automatic-HTTPS redirect handler — `200 OK`, `content-length: 0`, no error anywhere —
which broke both a direct curl to the Tailscale IP *and*, more surprisingly, Tailscale Serve's
own reverse-proxy hop (it doesn't send a Host header matching `127.0.0.1:8000`/`localhost:8000`
either). This masquerades as a Tailscale Serve or DNS problem; it's neither.

Fix: use a **bare port** as the site address plus an explicit `bind` directive, which actually
restricts the socket:

```caddyfile
:8000 {
    bind 127.0.0.1
    reverse_proxy unix//run/php/php-app.sock
}
```

Verify both directions after the fix, not just the happy path: `ss -tlnp` shows `127.0.0.1:8000`
(never `*:8000` or `0.0.0.0:8000`), a direct connection to the host's Tailscale IP on that port
is refused (`curl -m5 http://<tailscale-ip>:8000/` should time out or connection-refuse), and
the real Tailscale Serve URL still works.

## Fresh unprivileged LXC + Tailscale gotchas

- **TUN passthrough**: `tailscaled` needs `/dev/net/tun` explicitly passed through on an
  unprivileged LXC. Append to the host-side `/etc/pve/lxc/<vmid>.conf` (or equivalent for other
  LXC hypervisors):
  ```
  lxc.cgroup2.devices.allow: c 10:200 rwm
  lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file
  ```
  Then a **full stop/start cycle of the container itself** — restarting `tailscaled` from inside
  isn't enough. Symptom without the fix: `journalctl -u tailscaled` shows
  `CreateTUN("tailscale0") failed; /dev/net/tun does not exist`.

- **MagicDNS not registering into systemd-resolved on first pass**: after `tailscale up` +
  `tailscale set --accept-dns=true` + a delayed `tailscaled` restart (common in a DNS-routing
  playbook that avoids severing the SSH session mid-run), `resolvectl status` can still show the
  `tailscale0` link with no DNS scope at all — just LLMNR, no `*.ts.net` split. A direct,
  synchronous `systemctl restart tailscaled` right after (safe once the playbook run itself has
  finished) fixes it. Verify with `resolvectl status tailscale0`: correct output shows
  `Current Scopes: DNS`, `Current DNS Server: 100.100.100.100`, and
  `DNS Domain: <tailnet-name>.ts.net ~.` — compare against a known-good host if unsure.

- **Locale**: fresh Debian LXC templates have no locale generated, which breaks Ansible
  (`could not initialize the preferred locale`) before any of the above even runs — generate
  `en_US.UTF-8` first.
