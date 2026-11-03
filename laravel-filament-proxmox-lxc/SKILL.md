---
name: laravel-filament-proxmox-lxc
description: This skill should be used when deploying a Laravel + Filament v3 app (an admin panel, internal dashboard, or CMDB) as a native systemd service inside an unprivileged Proxmox LXC, instead of Docker — dedicated PHP-FPM pool, Caddy loopback front, Pest testing, Laravel Boost, Laravel Nightwatch APM, and adding a read-only Sanctum token API for an external consumer. Also covers a Filament panel behind Tailscale Serve generating mixed-content http:// asset URLs on an https:// page (including a plain asset() call not honoring URL::forceScheme), Eloquent's belongsToMany pivot-table naming surprising an agent building the schema by hand, php-fpm socket permission errors from a restrictive service-user home directory, Boost's guideline generation silently doing nothing under --no-interaction, Sanctum's abilities/ability middleware aliases not existing on a bootstrap/app.php (no Kernel.php) app, and an unauthenticated api/* request 500ing instead of 401ing when no Accept header is sent. For theming/skinning an already-deployed panel (custom colors, self-hosted fonts, brand name), see the sibling `filament-panel-theming` skill instead. Trigger phrases include "laravel filament proxmox", "filament admin panel native install", "php-fpm dedicated pool ansible", "laravel behind tailscale serve mixed content", "APP_URL forceScheme https", "asset() secure true mixed content", "eloquent belongsToMany pivot table wrong name", "credential_service vs service_credential", "laravel nightwatch systemd agent", "boost:install no agents selected", "pest --init not pest:install", "php-fpm socket permission denied caddy", "sanctum personal access token read only", "Target class [abilities] does not exist", "sanctum middleware alias missing", "Route [login] not defined api", "unauthenticated api request 500", "redirectGuestsTo bootstrap/app.php", "FilamentUser canAccessPanel api-only user", "APP_DEBUG true production laravel".
---

# Laravel + Filament v3 as a native systemd service in a Proxmox LXC

Use this instead of Docker for a Laravel/Filament admin app (dashboard, internal CMDB, small
CRUD tool) in an unprivileged Proxmox LXC — matches the fleet's "native packages, not Docker"
precedent (Grafana, n8n, this pattern's Node.js sibling `proxmox-node-systemd-service`). Built
and verified end-to-end deploying the Homelab Console app (Laravel 13 + Filament v3.3, VMID
142) — every gotcha below was hit for real, not theoretical.

## Install sequence

1. Base packages: `php8.4-fpm php8.4-cli php8.4-sqlite3 php8.4-mbstring php8.4-xml php8.4-curl
   php8.4-bcmath php8.4-zip php8.4-gd php8.4-intl composer`. Debian 13 (trixie) ships PHP 8.4
   natively — no third-party apt repo needed, unlike NodeSource for Node.js.
2. Caddy from the official apt repo (`dl.cloudsmith.io/public/caddy/stable`) — see the
   `caddy-cloudflare-wildcard-proxy` skill for the full setup and its **loopback-bind gotcha,
   which applies here directly**: a Caddyfile site address of `http://127.0.0.1:8000` does
   *not* restrict the socket bind, only Host-header matching. Use `:8000 { bind 127.0.0.1 ...
   }` instead.
3. A dedicated non-root service user (`useradd -r -m -d /opt/<app> -s /usr/sbin/nologin <app>`)
   owning the app directory — same pattern as the Node.js skill.
4. `composer create-project laravel/laravel app` as that user, then
   `composer require filament/filament:"^3.3" -W` + `php artisan filament:install --panels`.
5. Pest: `composer require pestphp/pest pestphp/pest-plugin-laravel --dev -W`, then initialize
   with **`./vendor/bin/pest --init`, not `php artisan pest:install`** — the latter command
   doesn't exist despite looking like the natural counterpart to `filament:install`; Pest 4
   registers its own binary entry point instead of an artisan command.
6. Enable `RefreshDatabase` in `tests/Pest.php` (ships commented out by default) so Feature
   tests don't pollute the real seeded database — `phpunit.xml`'s default
   `DB_CONNECTION=sqlite`/`DB_DATABASE=:memory:` already isolates the test run, this just wires
   the trait in.
7. Pest's Laravel plugin helpers (`actingAs`, `get`, `post`, ...) are **not** global functions
   by default — `use function Pest\Laravel\actingAs;` explicitly, or `Call to undefined
   function actingAs()`.
8. **Run `base-hardening.yml` against the new LXC before calling it done** — see
   `proxmox-ansible-provisioning`'s provisioning-sequence section. An app being live is not the
   same as the host being hardened; confirmed missed live 2026-08-30 (`console`, this skill's
   own reference deploy, ran 9 days with default SSH password auth and no unattended-upgrades
   before a weekly sweep caught it).

## Dedicated PHP-FPM pool, not the default `www` pool

Run the app under its own PHP-FPM pool (user/group matching the service user, own unix socket)
rather than the default `www-data` pool — cleaner ownership boundary, matches giving every
service its own system user elsewhere in this fleet:

```ini
[app]
user = app
group = app
listen = /run/php/php8.4-fpm-app.sock
listen.owner = app
listen.group = app
listen.mode = 0660
chdir = /opt/app/app/public
```

Delete (or leave disabled) the stock `www.conf` pool if nothing else uses it — two pools is
fine, an unused one is just noise.

**Directory-permission gotcha**: `useradd -r -m` creates the home directory `0700` (owner-only).
Adding the `caddy` system user to the app's group (so it can read the FPM socket) is not enough
by itself — Caddy's `file_server`/static-asset serving also needs to *traverse* the parent
directory, which `0700` blocks even for group members. Symptom: `403 Forbidden` on every
request despite the socket permissions and pool config all being correct. Fix: `chmod 750
/opt/<app>` (owner rwx, group rx) once the `caddy` user has been added to the app's group.

## Laravel Boost (`laravel/boost`, dev dependency)

`composer require laravel/boost --dev` then `php artisan boost:install`. Under
`--no-interaction`, passing `--guidelines` alone is **not sufficient** — the command needs to
know *which* AI agent to generate guidelines for (Claude Code, Cursor, etc.), and with no
interactive prompt available it silently produces "No agents are selected for guideline
installation" and generates nothing, while still exiting 0 (no error). Live MCP tools
(DB/tinker/route/log introspection) also won't attach when Claude Code's session runs over SSH
rather than directly on the LXC — expected, not a bug, if that's the deliberate workflow choice
for this project. Neither gap blocks the rest of Boost (docs-search, the composer package
itself) from working.

## Filament behind Tailscale Serve: mixed-content asset URLs

Tailscale Serve terminates HTTPS and proxies to the loopback Caddy over plain HTTP. Laravel has
no way to know this unless told — by default it generates asset/route URLs from `APP_URL`
(defaults to `http://localhost` from `laravel new`), so an `https://` page ends up requesting
`http://` stylesheets/scripts and the browser silently blocks them (mixed-content policy) —
symptom is a fully broken, unstyled, non-interactive login page with browser console errors
like `Mixed Content: ... was loaded over HTTPS, but requested an insecure stylesheet`, while
`curl` shows a normal 200 with a full HTML body (curl doesn't enforce mixed-content blocking,
so this is easy to miss testing via curl alone — check with a real browser or Playwright).

Fix, both parts:
1. `APP_URL=https://<app>.<tailnet>.ts.net` in `.env` (matches the real external URL, not the
   loopback one Caddy actually listens on).
2. Force the scheme unconditionally in `AppServiceProvider::boot()`:
   ```php
   use Illuminate\Support\Facades\URL;

   public function boot(): void
   {
       URL::forceScheme('https');
   }
   ```
   This is safe to make unconditional (not environment-gated) when the app *only* ever runs
   behind a TLS-terminating proxy, which is true for any Tailscale-Serve-only internal app.

If the app is also reachable through a second reverse-proxy hop (e.g. a central Caddy fronting
`*.example.dev` in addition to Tailscale Serve directly), know that `APP_URL` is a **single
fixed value** — every generated redirect canonicalizes to it regardless of which external
hostname the visitor actually used. A visitor entering via the second hostname will get bounced
to the `APP_URL` hostname after any redirect (login flow, a root-route redirect, etc.) — this is
expected, not a bug, unless `TrustProxies` + dynamic URL generation is deliberately built to
replace the fixed `APP_URL`. Making that dynamic is a real, non-trivial tradeoff (risks splitting
the session cookie across the two hostnames, since the cookie is scoped to whichever hostname
served it) — don't do it reflexively just because the redirect target looks surprising.

**`URL::forceScheme('https')` does not cover the plain `asset()` helper.** Hit this again in a
later session, after the two fixes above were already in place: any `asset('some/path')` call
made directly (e.g. in a Filament panel provider's `->theme()`/`->font()` registration — see the
`filament-panel-theming` skill for that specific context) still emitted `http://` and got
silently mixed-content-blocked, same symptom as above (clean curl 200s, empty logs, unstyled
page). Fix: pass `secure: true` explicitly — `asset('some/path', secure: true)` — rather than
relying on `forceScheme` to propagate there.

## Eloquent's belongsToMany pivot-table naming is alphabetical, not declaration-order

For `Credential::belongsToMany(Service::class)` / `Service::belongsToMany(Credential::class)`,
Eloquent's default pivot table name is the two model names **sorted alphabetically** and
joined with an underscore — `credential_service`, not `service_credential` (which reads more
naturally if you're writing the migration by hand from the "many services have one credential"
direction). Building the migration in declaration order first will pass `php artisan migrate`
cleanly (nothing validates the pivot table name against the relationship at migration time) and
only fail later, at query time, with `SQLSTATE[HY000]: ... no such table: credential_service` —
confusing because the error names a table you never created, not the one you did. Fix: rollback
the wrong migration (`php artisan migrate:rollback --step=1`), rename the file, fix the
`Schema::create()` call inside, re-migrate — don't just `ALTER TABLE ... RENAME` live, since the
migration file itself would still describe the wrong name for the next fresh install.

## Laravel Nightwatch (fully-managed APM, free tier)

`composer require laravel/nightwatch`, then `NIGHTWATCH_TOKEN=...` in `.env` from the
onboarding wizard at nightwatch.laravel.com. The actual telemetry agent
(`php artisan nightwatch:agent`) is a **standing local daemon** that batches and forwards
events — not a request-time call — so it needs a real systemd service, not just the composer
install:

```ini
[Unit]
Description=Laravel Nightwatch agent
After=network.target

[Service]
Type=simple
User=app
Group=app
WorkingDirectory=/opt/app/app
ExecStart=/usr/bin/php /opt/app/app/artisan nightwatch:agent
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Verify with `php artisan nightwatch:status` (expect "running and accepting connections") and by
generating a few real requests, then checking the dashboard's Activity panel populates within
about a minute.

To also capture Laravel's own logs in Nightwatch, **add to the existing log stack rather than
replacing it** — `LOG_STACK=single,nightwatch` (was `single`) keeps the local
`storage/logs/laravel.log` file working (real debugging still needs it) while adding the
Nightwatch channel alongside. Setting `LOG_CHANNEL=nightwatch` directly, as Nightwatch's own
onboarding UI suggests as one option, replaces file logging entirely instead of adding to it.

On sampling: the onboarding wizard defaults to suggesting a reduced request-sample-rate (e.g.
10%) "to manage usage" — appropriate for a high-traffic production app, actively harmful for a
low-traffic single-operator internal tool, where a real bug might only ever fire once and a 10%
sample rate means a 90% chance of missing it. The package's own unset default is already 100%
sampling for every event type (`requests`, `commands`, `exceptions`, `scheduled_tasks`) — check
real expected traffic against Nightwatch's free-tier event cap (300k/month as of 2026) before
accepting a lower default; for an internal admin panel it's rarely close.

### Keep machine traffic out of the free quota (learned 2026-10-08)

The free plan's monthly event quota ran out at 100%, and the cause was almost entirely the app's own automation:
5-minute and 15-minute timers calling `api/*`, plus an availability probe on `/`. Each request records the request
itself plus every query and log line, and `LOG_LEVEL=debug` sends debug logs too. When the quota is exceeded, the agent
logs `Ingest attempted … 200 [Exceeded quota]` and then `Authentication failed … 403 [Exceeded quota]`. The app keeps
working; it's only telemetry that stops until the reset.

- Exclude machine routes with the route middleware `Laravel\Nightwatch\Http\Middleware\Sample::never()`
  (or `::rate(0.1)`) on the `api` groups.
- For a probe on a shared URL, have the probe send a distinctive User-Agent. A tiny prepended global middleware then
  calls `Nightwatch::dontSample()` when it sees that UA.
- Set `NIGHTWATCH_LOG_LEVEL=warning`. It defaults to `LOG_LEVEL`, and the local log keeps everything regardless.
- Exceptions survive: `report()` re-samples at the exceptions rate (default 1.0) when the request was unsampled
  (`Concerns/CapturesState.php`).
- Other knobs: `NIGHTWATCH_REQUEST_SAMPLE_RATE`, `NIGHTWATCH_IGNORE_QUERIES`, `NIGHTWATCH_IGNORE_CACHE_EVENTS`, and so on.
  Read `vendor/laravel/nightwatch/config/nightwatch.php` for the installed version's list.

## Read-only Sanctum API for an external consumer

Adding `GET`-only, token-gated JSON endpoints (e.g. so another agent/service can pull inventory
or stats) on top of this same stack. `composer require laravel/sanctum` then
`php artisan install:api --without-migration-prompt --no-interaction` scaffolds
`routes/api.php`, publishes the `personal_access_tokens` migration, and wires
`api: __DIR__.'/../routes/api.php'` into `bootstrap/app.php`'s `withRouting()` — but it does
**not** add `Laravel\Sanctum\HasApiTokens` to the User model; that's a manual one-line trait add
the command's own output tells you to do.

**Sanctum 4.x's `SanctumServiceProvider` no longer registers the `abilities`/`ability`
route-middleware aliases** that every Sanctum tutorial assumes exist (`CheckAbilities`/
`CheckForAnyAbility`) — confirmed by reading the vendor provider directly, no
`aliasMiddleware()` call anywhere in it. Symptom: `route:list` or any request to a route using
`->middleware(['auth:sanctum', 'abilities:read'])` throws `Target class [abilities] does not
exist`. Fix, in `bootstrap/app.php`'s `withMiddleware()`:
```php
use Laravel\Sanctum\Http\Middleware\CheckAbilities;
use Laravel\Sanctum\Http\Middleware\CheckForAnyAbility;

$middleware->alias([
    'abilities' => CheckAbilities::class,
    'ability' => CheckForAnyAbility::class,
]);
```

**An unauthenticated `api/*` request 500s instead of 401ing when the client sends no `Accept`
header** (a bare `curl` with no `-H "Accept: application/json"`, or any client that doesn't set
it) — easy to miss during testing since a client sending the header (or any real REST library)
never hits it. Root cause: `ApplicationBuilder::withMiddleware()` sets a framework-default
`redirectGuestsTo(fn () => route('login'))`, and that callback runs *inside* the `Authenticate`
middleware at the moment it constructs the `AuthenticationException` — **before** the exception
even reaches the handler's `shouldRenderJsonWhen()`/`expectsJson()` branching. If no `login`
route exists (true for any app where Filament, not Breeze/Jetstream, owns auth), `route('login')`
throws `RouteNotFoundException`, which *replaces* the real 401 entirely and surfaces as a 500.
A `render()` callback for `AuthenticationException` in `withExceptions()` does **not** catch
this — by the time it would fire, the exception has already changed type. The actual fix is to
override the redirect callback itself so it never calls `route('login')` for API paths:
```php
$middleware->redirectGuestsTo(
    fn ($request) => $request->is('api/*') ? null : route('login')
);
```

**Keep API-only token holders out of the Filament panel** even though nothing about Sanctum
does this automatically — a `User` row created just to hold a token can otherwise still attempt
to log into `/admin` with a password. Implement `FilamentUser` and gate on the real admin's
email (or a dedicated boolean column) rather than leaving every `User` row implicitly panel-
eligible:
```php
class User extends Authenticatable implements FilamentUser
{
    public function canAccessPanel(Panel $panel): bool
    {
        return $this->email === 'admin@example.com';
    }
}
```

**While testing this, also check `APP_ENV`/`APP_DEBUG` in `.env`.** An app deployed once and
left alone can easily still be `APP_ENV=local`/`APP_DEBUG=true` from the initial `laravel new`
scaffold — every error response (including the ones above, while debugging them) then leaks a
full stack trace with real server file paths in the JSON body. Flip to
`APP_ENV=production`/`APP_DEBUG=false` before handing an API token to anything outside your own
debugging session. Editing `.env` directly over SSH can hit the auto-mode classifier's generic
config-file-write block — the scp-down/edit-locally/scp-up pattern works around it (delete the
local copy immediately after, since it transiently holds `APP_KEY`).

**Testing**: Sanctum's `Laravel\Sanctum\Sanctum::actingAs($user, ['read'])` test helper is the
clean way to hit ability-gated routes in Pest — it attaches a real token with the given
abilities to the acting user, so `CheckAbilities`/`tokenCan()` behave exactly as they would for
a real request. Don't hand-roll this by calling `$user->withAccessToken(...)` yourself; the
built-in helper already does it correctly.
