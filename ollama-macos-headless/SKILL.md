---
name: ollama-macos-headless
description: This skill should be used when running Ollama headless on a Mac as an always-on service, when Ollama returns HTTP 403 to requests arriving through a reverse proxy or Tailscale Serve, when deciding whether to enable macOS auto-login for a headless box, when choosing a model size for an 8GB Apple Silicon machine, or when a Caddy reverse proxy returns HTTP 200 with an empty body. Trigger phrases include "ollama headless mac", "ollama 403 proxy", "ollama Host header", "OLLAMA_ORIGINS not working", "brew services doesn't start until login", "LaunchDaemon vs LaunchAgent", "mac mini always on service", "ollama tailscale serve", "8GB unified memory model size", "caddy 200 empty body", "caddy site matcher Host".
---

# Ollama headless on Apple Silicon, exposed safely

Built and measured on a **2020 M1 Mac mini, 8 GB, macOS 26.6, Ollama 0.33.3**, 2026-09-06.

## `brew services` cannot make a headless box always-on

`brew services start ollama` installs a **per-user LaunchAgent**, which does not run until
somebody logs in. On a headless machine a power blip therefore leaves it awake, networked, and
running nothing — and the usual proposed fix is to enable **auto-login**, which weakens the box
for a problem it does not actually solve well.

Use a **system LaunchDaemon** in `/Library/LaunchDaemons/` instead. It starts at boot with no
session, so the login screen stays. Pair it with:

```bash
sudo pmset -a sleep 0 disksleep 0 autorestart 1 womp 1
```

`autorestart 1` is the half people forget — it powers the machine back on after an outage.

Two things that bite when writing the plist:

- **`StandardOutPath` must be writable by the `UserName` the daemon runs as.** Pointing it at
  `/var/log/...` for a non-root user gives `last exit code = 78: EX_CONFIG` and **no log file at
  all**, which reads as a mysterious failure. Use `~/Library/Logs/`.
- `launchctl bootstrap` on an already-loaded service fails with **`Bootstrap failed: 5:
  Input/output error`**. That means "already loaded", not a real fault. `bootout` first.

## Ollama returns 403 to any proxied Host, and the popular fix is dangerous

Ollama 0.33 validates the `Host` header against its own bind address to prevent DNS rebinding. A
request arriving through Tailscale Serve as `Host: <name>.ts.net` gets **403**.

**Tested and confirmed not to help:** `OLLAMA_ORIGINS=*`, an explicit
`OLLAMA_ORIGINS=https://<name>.ts.net`, `OLLAMA_ORIGINS=<name>.ts.net`, and binding to the
Tailscale IP. `OLLAMA_ORIGINS` governs CORS, not this check.

**Only `OLLAMA_HOST=0.0.0.0` works** — and on a multi-homed machine that is the wrong answer.
Ollama has **no authentication of any kind**, so its bind address is the entire security
boundary. A Mac on Wi-Fi and Ethernet may sit on several networks at once; `0.0.0.0` publishes
the API onto all of them, including any untrusted segment.

Keep Ollama on `127.0.0.1` and put a Host-rewriting proxy in front:

```caddyfile
{ admin off
  auto_https off }

:11435 {
	bind 127.0.0.1
	reverse_proxy 127.0.0.1:11434 {
		header_up Host {upstream_hostport}
	}
}
```

Then `tailscale serve --bg --https=443 http://localhost:11435`.

### The Caddy trap inside the fix

**Caddy matches sites by Host.** Writing the site address as `http://127.0.0.1:11435` means it
only matches requests whose Host *is* `127.0.0.1` — so every proxied request matches **no site**
and receives Caddy's default **empty 200**. A version check and a full model generation both
"passed" with HTTP 200 and a **zero-byte body**.

Use a **port-only site address** (`:11435`) so it matches any Host, plus an explicit
`bind 127.0.0.1` for the interface. And **check bytes, not status** — a status code proves
nothing about whether a proxy proxied anything.

Caddy also binds the IPv6 any-address for a hostname-only site (`lsof` shows `*:11435`), which is
unreachable over IPv4 but opens up the moment the host gets a routable IPv6 address. `bind` fixes
that too.

## Model sizing on 8 GB: measure, do not reason from the file size

Ollama reported **5.3 GiB usable VRAM** on an 8 GB M1. A 4.9 GB model "fits" arithmetically and
thrashes in practice:

| Model | tok/s | Wall | Swap during the run |
|---|---|---|---|
| `llama3.2:3b` (2.0 GB) | **27.1** | 6.1 s | **fell** |
| `llama3.1:8b` (4.9 GB) | 8.1 | 24.2 s | **rose**; macOS grew the swap file 3 → 6 GB mid-request |

**On 8 GB, a ~3B model is the working default** and an 8B is a deliberate trade for one-off
quality. Measure with a real request through the real path — `eval_count / eval_duration` from
the API response, plus `vm_stat` and `sysctl -n vm.swapusage` before and after. Idle memory
readings tell you nothing.

Useful daemon environment for a small box: `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_KEEP_ALIVE=5m`
so a second model cannot page the machine.

## Verify positive *and* negative

Because there is no auth, confirm from another host that the LAN address is **refused** on 11434
and 11435, not merely that localhost works. Do it behaviourally from a second machine —
`lsof` output is easy to misread, and a listener bound to an IPv6 wildcard looks different from
how it behaves.
