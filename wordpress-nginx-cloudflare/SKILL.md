---
name: wordpress-nginx-cloudflare
description: This skill should be used when deploying or migrating a WordPress site onto a native nginx + PHP-FPM + MariaDB stack (not Docker, not a managed host like GridPane/WP Engine), when hardening a WordPress origin behind Cloudflare with an Origin CA certificate and Authenticated Origin Pulls, when importing a BackWPup/GridPane export onto a new server, when WP-Cron needs a real heartbeat because DISABLE_WP_CRON is set or the site gets low traffic, when debugging a WordPress 500 error that traces to a GridPane-specific absolute path or a stale object-cache.php drop-in, when a fail2ban jail (e.g. wordpress-login) shows real bans that don't seem to actually stop the traffic, when investigating whether Cloudflare Access/WAF is genuinely blocking a brute-force pattern against wp-login.php or xmlrpc.php, or when a Cloudflare Access self-hosted application seems to protect one hostname but not a variant of it (e.g. apex vs. www). Trigger phrases include "migrate wordpress off gridpane", "wordpress nginx php-fpm deployment", "cloudflare origin ca certificate", "authenticated origin pulls", "wp-cron not running", "DISABLE_WP_CRON", "object-cache.php fatal error", "wordfence auto_prepend_file", "BackWPup import", "wp-config.php DB_HOST socket", "real_ip_header cloudflare nginx", "fail2ban jail full", "wordpress-login jail", "fail2ban ban not blocking", "CF-Connecting-IP ban ineffective", "cloudflare access www bypass", "cloudflare access hostname scoping", "xmlrpc.php brute force", "rotated nginx logs investigation", "cloudflare rate limiting free plan".
---

# WordPress on nginx + PHP-FPM + MariaDB, behind Cloudflare

> **2026-11-01:** williejackson.com no longer runs this stack publicly. It's a static copy on
> Cloudflare Pages, exported from a private WordPress on homelab CT 144 (see
> `wordpress-static-export`). Everything below still describes how a *public* WordPress origin
> behind Cloudflare is built, and dfw ran it until 2026-11-01. A copied 2750/0640 site tree needs
> `www-data` in the site user's group, or nginx 404s every static file.

Covers a from-scratch WordPress deployment (not Docker, not a managed panel) with Cloudflare
as the sole public entry point, plus the specific gotchas hit migrating a real site off
GridPane onto a fresh Debian host.

## Stack setup

Install `nginx php-fpm php-mysql php-curl php-gd php-mbstring php-xml php-zip php-imagick
php-intl php-bcmath php-soap mariadb-server` from the distro repos — verify the actual
available PHP version live (`apt-cache policy php-fpm`) rather than assuming one.

Create a dedicated system user for the site (no login shell) to own the docroot and run its
own PHP-FPM pool — don't share `www-data` across multiple sites/services on the same box.
Give the pool `pm = ondemand` for a low-traffic site (no idle workers sitting around).

Create a dedicated MariaDB database + user scoped to just that database, random password,
written only into `wp-config.php`.

## Dedicated PHP-FPM pool user needs setgid on uploads, or new uploads 403

The "dedicated system user, own PHP-FPM pool" pattern above (e.g. pool `user = wpwww` /
`group = wpwww`, distinct from nginx's `www-data`) breaks new file uploads unless the upload
directories force group inheritance. Confirmed 2026-08-29 (`williejackson.com` on `dfw`, first
real media upload since a GridPane migration): PHP-FPM creates new files with its own pool
group (`wpwww`) as the file's group, not the parent directory's group (`www-data`) — Unix only
inherits a directory's group onto new children when the directory has the **setgid bit** set,
which a plain `mkdir`/`chmod 750` does not add. Nginx (running as `www-data`) then gets a `403`
trying to serve a file it exists and can see (`ls` on the directory works — that's the
directory's own group-read bit) but can't open (the *file's* mode has no `www-data` read).

**Diagnostic signature**: a nonexistent filename in the same directory correctly 404s (proves
nginx can reach/read the directory), but the real just-uploaded file 403s with nginx's own
stock error page — that combination points at file-level, not directory-level or vhost-level,
permissions. Pre-migration files copied in via rsync/tar (this skill's own import section)
often still work because they kept their *original* host's group, masking the bug until the
first fresh upload happens on the new box.

**Fix** (systemic, doesn't touch the FPM pool's user/group security boundary):
```bash
chown -R <pool-user>:www-data wp-content/uploads/<affected-month>/   # fix existing files
chmod -R u+rwX,g+rX wp-content/uploads/<affected-month>/
find wp-content/uploads/ -type d -exec chmod g+s {} \;              # fix it permanently
```
The `find ... chmod g+s` on the whole `uploads/` tree makes every subdirectory (including ones
WordPress creates automatically for future months) inherit `www-data` group on new files from
then on — no umask tuning, no FPM pool config change needed. Do this once, right after initial
deploy or migration, rather than waiting for the first real upload to surface it.

## Importing a GridPane/BackWPup export

A BackWPup export lands as a `.tar` containing the DB dump (`.sql`), `wp-config.php`, the
full site tree, and a `manifest.json` describing the original `abspath`. Two known traps:

1. **GridPane's docroot convention is `/var/www/<domain>/htdocs/`** — a fresh flat extraction
   (no `htdocs` subdir) breaks any absolute path baked into a config file. The one that bites
   immediately: Wordfence's `.user.ini` has `auto_prepend_file =
   '/var/www/<domain>/htdocs/wordfence-waf.php'` — this fires on *every* PHP request via
   `php.ini`'s per-directory `.user.ini` mechanism, so a wrong path here is an instant 500 on
   the homepage, not a delayed/soft failure. Fix by rewriting the path in `.user.ini` to
   match wherever the new docroot actually is (or by preserving the `htdocs/` layout on
   import to avoid touching it at all).
2. **`wp-content/object-cache.php` is a live drop-in, not inert config.** If the export came
   from a site running the `redis-cache` plugin (or similar), this file is present and WP
   will use it automatically — even though the plugin's own PHP file may be inactive. If the
   new host has no Redis, this produces a **fatal** `Predis\Connection\ConnectionException`
   on every request, not a graceful fallback. Delete `wp-content/object-cache.php` outright
   if the new deployment isn't running the same cache backend; WordPress falls back cleanly
   to its built-in non-persistent object cache.

`wp-config.php`'s `DB_HOST` is often written as `localhost:/var/run/mysqld/mysqld.sock` (a
GridPane convention) — this works unchanged against a standard Debian MariaDB install, which
uses the same socket path. Only `DB_NAME`/`DB_USER`/`DB_PASSWORD` need updating for the new
database.

Check `wp-config.php`'s trailing custom-includes section (GridPane typically adds
`include __DIR__ . '/user-configs.php';` unconditionally near the bottom) — if that file
doesn't exist in the export, it's a soft `PHP Warning`, not fatal, but worth stubbing with an
empty file to keep logs clean.

## Cloudflare Origin CA + Authenticated Origin Pulls

For a Cloudflare-proxied domain, skip Let's Encrypt entirely and use a **Cloudflare Origin
CA certificate**: dashboard → SSL/TLS → Origin Server → Create Certificate (15-year default
is fine, covers apex + wildcard). This cert is only trusted by Cloudflare's edge, never by a
direct client — that's the point.

Pair it with **Authenticated Origin Pulls** so the origin only accepts connections that
actually came through Cloudflare:

1. Check whether "Global" AOP is already enabled account-wide (SSL/TLS → Origin Server →
   Authenticated Origin Pulls tab) — it very often already is, in which case no per-zone
   toggle is needed, just the origin-side nginx config.
2. Fetch Cloudflare's public Origin Pull CA cert (a fixed, non-secret file, safe to `curl`
   directly): `https://developers.cloudflare.com/ssl/static/authenticated_origin_pull_ca.pem`
3. On the origin's nginx vhost: `ssl_client_certificate /path/to/that-ca.pem;` and
   `ssl_verify_client on;`. A request without Cloudflare's client cert gets a clean
   `400 No required SSL certificate was sent` — verify this directly (`curl` straight to the
   origin's public IP) as proof the gate works, separate from verifying the real domain works
   through Cloudflare.

**Verification technique that doesn't touch live DNS**: before cutting over a real domain's
A record, create a throwaway subdomain (e.g. `migration-test.example.com`), proxied, pointed
at the new origin. This exercises the *real* Cloudflare→AOP→origin path end-to-end with zero
risk to the live site, and gets deleted afterward.

## The nginx-vs-tailscaled port conflict

If the same host already runs Tailscale Serve/Funnel for another service, binding nginx to
`listen 443 ssl;` (wildcard `0.0.0.0:443`) can fail with `bind() to 0.0.0.0:443 failed
(98: Address already in use)` even though `tailscaled` is bound to a *different*, specific IP
(its own Tailscale address) on the same port — Linux won't let a wildcard bind coexist with
an existing specific-IP bind on the same port, regardless of which IP the wildcard would
otherwise prefer. Fix: bind nginx explicitly to the host's public IP
(`listen <public-ip>:443 ssl;`) instead of the wildcard. Drop bare `listen [::]:443;` too if
the host has no real public IPv6 (check `ip -6 addr show`, excluding Tailscale's `fd7a::`
ULA range and link-local `fe80::`) — it serves no purpose and can hit the identical conflict
against `tailscaled`'s own IPv6 listener.

## real_ip_header for Cloudflare

Without `set_real_ip_from` + `real_ip_header CF-Connecting-IP;`, nginx logs Cloudflare's edge
IP as the client for every request — not the real visitor. This silently breaks anything that
reads `$remote_addr` downstream, most importantly **fail2ban**: a jail built against
unpatched logs will end up banning Cloudflare's own shared edge IP ranges, taking the site
down for everyone. Fetch Cloudflare's current IP ranges live
(`https://www.cloudflare.com/ips-v4` and `/ips-v6`) rather than hardcoding them — they do
change. Verify the fix by making a real request and confirming the access log shows the
actual originating IP, not a Cloudflare range.

## fail2ban bans are cosmetic against Cloudflare-proxied traffic, even configured correctly

Getting `real_ip_header` right (above) fixes *logging* and jail *matching* — it does not fix
*blocking*. A local `iptables`/`nftables` ban targets whatever IP fail2ban logged, but the
actual TCP peer connecting to the origin is always one of Cloudflare's edge IPs, never the
real visitor — so an OS-level ban on the real visitor's IP never matches the real connection
and blocks nothing. Confirmed directly (2026-08-20): fail2ban banned an attacker within 7
seconds of the first matched line, then logged 893 more successful hits from the same IP over
the next 8+ hours, each with an accompanying `fail2ban.actions WARNING ... already banned`
line — proof the daemon believed it had blocked the traffic while the traffic kept flowing.

To check whether this is happening on a given host: find a `Ban <ip>` line in
`fail2ban.log`, note its timestamp, then `grep <ip>` the nginx access log for any hits *after*
that timestamp. Continued hits post-ban means the ban is inert, not that fail2ban is
malfunctioning — this is the expected, structural outcome for any site behind Cloudflare's
proxy, regardless of jail tuning.

**The real backstop for Cloudflare-fronted traffic lives at Cloudflare's edge, not in
fail2ban**: a WAF Custom Rule (Security → WAF → Custom rules, expression like
`http.request.uri.path eq "/xmlrpc.php"` → Block) for an endpoint that should never be
reachable at all, or a Rate Limiting Rule (Security → WAF → Rate limiting rules) for one that
needs to stay reachable but capped (e.g. `/wp-login.php`, 10 requests per period → Block).
Both enforce by the real visitor IP regardless of proxying, because they run at the edge
before the request is ever proxied to origin. Free plan rate limiting is locked to a fixed
10-second counting period and 10-second mitigation timeout (not a UI bug — confirmed via
Cloudflare's own plan-availability docs) and only 1 rule; Single Redirects get a separate
quota of 10 rules. Write match expressions as **path-only** (`http.request.uri.path eq
"..."`) rather than including the hostname — this makes the rule automatically cover every
hostname in the zone (apex, www, any future subdomain) with no extra configuration, which
matters given the Access gotcha below. Keep fail2ban as a detection/alerting signal for
these hosts (Telegram-notify on ban is genuinely useful for noticing a pattern exists) — just
don't rely on its ban action to actually stop anything.

## Cloudflare Access application hostname scoping — apex and www are not the same protection

A Cloudflare Access self-hosted application's destination (e.g.
`williejackson.com/wp-login.php*`) only matches the exact hostname configured. If nginx
serves both `example.com` and `www.example.com` from the same `server_name` line (a common
default), and the Access app was only ever set up for the apex, **`www.example.com/wp-login.php`
gets zero Access enforcement** — a real `200` straight from WordPress, not the `302` to
`<team>.cloudflareaccess.com` the apex correctly returns. This is easy to miss because it
looks symmetrical from the origin's side (one nginx block, one WordPress install, identical
content either way) and because testing from a personal browser can mask it entirely: an
existing Access session cookie is scoped to the app/hostname and survives an origin move, so
a logged-in visit to the *protected* hostname shows the real WP login form and looks
identical to a *bypassed* hostname unless tested cookie-less.

**Verify with `curl`, not a browser**, from both hostnames:
```bash
curl -sI https://example.com/wp-login.php | head -3      # expect 302 to cloudflareaccess.com
curl -sI https://www.example.com/wp-login.php | head -3  # check independently, don't assume
```
Any `200` here (a real WordPress response) where a `302` is expected means that hostname has
no Access enforcement, full stop — confirmed by the response itself, no dashboard check
needed.

**Fix the whole class of problem, not just the one path.** Adding `www` as a second
destination on the same Access application only closes it for that one app+path — any other
future gap between the two hostnames needs the exact same fix repeated. If the extra
hostname isn't actually wanted (common — `www` is often just a legacy default nobody
intentionally uses), eliminate it entirely instead: a Cloudflare Redirect Rule
(Rules → Redirect Rules → Single Redirects; the built-in "Redirect from WWW to root"
template handles the common case, wildcard match `https://www.*` → `https://${1}`,
`Preserve query string` on) bounces every `www` path to the apex before Access, WAF, or
origin ever see it — closing the entire hostname, not one path on it. Consider a matching
origin-side backstop too: split the shared nginx `server_name` into two blocks, a
content-serving one scoped to the apex only and a redirect-only one for the extra hostname
(`return 301 https://example.com$request_uri;`), so the protection doesn't depend solely on
the Cloudflare-side rule staying enabled.

## Investigating a brute-force incident: use the full log history, not just today's

`fail2ban-client status <jail>` reports lifetime totals (`Total failed`, `Total banned`) —
`/var/log/nginx/access.log` alone only covers the current day. A conclusion drawn from
today's log plus the currently-banned IPs can miss the real incident entirely if it happened
on a rotated day; check `access.log.1` (yesterday, plain) and `access.log.2.gz` /
`fail2ban.log.1` etc. (`zgrep` for the compressed ones) before concluding a jail's history is
benign or fully understood.

If a jail's filter matches multiple endpoints in one pattern (e.g. `wordpress-login` matching
both `POST /wp-login.php` and `POST /xmlrpc.php` at `200`), split them apart before drawing
conclusions — a jail dominated by one endpoint's spam can hide a much smaller but more
serious incident on the other. `xmlrpc.php` spam (fake `Jetpack`/`WordPress.com` user agents
probing for open XML-RPC) is common background noise; a real `wp-login.php` `200` is not.

**Before concluding a `200` at origin means Access/WAF failed to enforce, rule out a raw
origin-IP bypass** — a request could be reaching WordPress directly by hitting the origin's
real IP, never touching Cloudflare's edge at all, which is a completely different problem
(origin IP exposure, not an edge-enforcement gap) needing a different fix. Distinguish the
two with the AOP test from above: attempt the same request directly against the origin IP
with no client cert.
```bash
curl -sk -X POST "https://<origin-ip>/wp-login.php" -H "Host: example.com" -d "log=x&pwd=x" \
  -o /dev/null -w "%{http_code}\n"   # expect 400 if AOP is genuinely enforced
```
If that returns `400`, any `200` found in the real logs necessarily presented a valid
Cloudflare client cert — meaning it really did come through Cloudflare's proxy, confirming an
edge-enforcement gap (Access/WAF/hostname-scoping) rather than an origin exposure. If the
direct-origin test itself returns something other than `400`, AOP isn't actually enforced and
that's the real, more fundamental problem to fix first.

## WP-Cron needs a real heartbeat on a low-traffic site

WordPress's default "cron" is a pseudo-cron that only fires on an incoming page request —
useless for a near-zero-traffic site, and **already broken entirely** (not just unreliable)
if `DISABLE_WP_CRON` is set to `true` in `wp-config.php` (a common managed-host convention,
since panels like GridPane normally run their own external cron driver that doesn't survive
a migration). Check for this constant before assuming pseudo-cron is even a fallback.

Fix with a systemd timer driving `wp cron event run --due-now` via wp-cli, running as the
site's own system user:

```ini
[Service]
Type=oneshot
User=<site-user>
WorkingDirectory=/path/to/site
ExecStart=/usr/local/bin/wp cron event run --due-now
```
```ini
[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true
```

Verify by checking `wp cron event list` shows real hooks (`wp_update_plugins`,
`wp_version_check`, etc.) with sane `next_run_relative` values, and by tailing
`journalctl -u <the service>` after a manual `systemctl start` to confirm events actually
executed (not just that the unit exited 0).

## Verifying auto-update settings and the mail path

`auto_update_core_major`/`_minor`/`_dev` and `auto_update_plugins` live in `wp_options` —
check them directly with `wp option get <name>` rather than assuming WordPress's documented
defaults apply; a managed-host export can carry a more (or less) aggressive setting than
vanilla WordPress ships with.

To verify WordPress's own update-failure email notifications will actually work (the same
`wp_mail()` path they use), don't wait for a real failure — trigger a real send directly:
`wp eval 'var_dump(wp_mail("you@example.com", "test", "body"));'`. A `bool(true)` confirms
the configured mail transport (SMTP plugin, Postmark, etc.) accepted the message; for
stronger proof of actual delivery, check the transport's own delivery log (e.g. Postmark's
Messages API) rather than trusting the boolean alone.

## After a backup-plugin restore, sweep the webroot for the restore's own files (2026-10-17)

BackWPup (and similar) restores drop the archive's DB dump (`<prefix>_<site>.sql`), `manifest.json`, `backwpup_readme.txt` and a plugin-list txt into the **webroot**, and a stock WordPress nginx config serves them with 200. One sat public for two months. After any migration/restore: `find <webroot> -maxdepth 2 \( -iname '*.sql*' -o -name manifest.json -o -iname '*backup*' -o -iname '*.zip' -o -iname '*.tar*' \)`, move hits out, and `curl -sI` each URL to confirm 404. Defence in depth: an nginx `location ~* \.(sql|sql\.gz|bak|zip|tar|tar\.gz|log)$ { deny all; }` and a Cloudflare WAF rule on the same extensions. To judge exposure without reading values, compare sha256 fingerprints of each secret-looking option in the dump against the live `wp_options` row.
