---
name: cloudflare-pages-gotchas
description: This skill should be used when working on a Cloudflare Pages project with Pages Functions — debugging on-the-fly image resizing that won't work, a wrangler.toml with named [env.*] blocks where bindings mysteriously go missing in one environment, a crypto.subtle PBKDF2 call that throws in production but works locally, or a _redirects rule that silently never fires on a path a Function also handles. Trigger phrases include "pages images binding", "env.IMAGES", "wrangler.toml env production", "bindings missing in production", "PBKDF2 iterations error", "NotSupportedError iteration counts", "_redirects not working", "redirect skipped by functions", "pages function precedence".
version: 0.1.0
---

# Cloudflare Pages + Wrangler Gotchas

Four real, non-obvious platform behaviors hit while building and deploying a
Cloudflare Pages site with Functions, KV, and R2. Each looked like a bug in
the project's own code at first; each was actually a documented (but easy to
miss) platform constraint.

## Pages Functions have NO Images binding — at all, ever

`env.IMAGES` (the on-the-fly image transform API) is unsupported on
Cloudflare Pages, full stop:

- `wrangler.toml`: an `[images]` block fails config validation on a Pages
  project.
- Dashboard: Images isn't in the Pages bindings list at all (it exists for
  Workers, not Pages).

This is a hard platform limit, not a config mistake to debug around.
**Solution: pre-generate the responsive/derivative images you need (WebP,
AVIF, thumbnails, etc.) at build or ingest time and serve them as plain R2
objects** — don't design around an on-the-fly resize step for Pages.
(Workers *do* support the Images binding; only Pages doesn't. `keep_vars` is
similarly Workers-only and will fail on a Pages project.)

## Empty `[env.production]` / `[env.preview]` blocks silently drop top-level bindings

In `wrangler.toml`, declaring *any* named environment block — even an empty
one — stops Wrangler from inheriting top-level `kv_namespaces` / `r2_buckets`
/ other bindings into that environment. The result: `pages deploy` (or a
branch deploy) ships with **no bindings at all**, and every Function that
touches one 500s in production while working fine locally.

```toml
# BAD — this empty block silently drops top-level bindings from prod:
[env.production]

# GOOD — no named env blocks at all; top-level bindings apply to every deploy
[[kv_namespaces]]
binding = "MY_KV"
id = "..."
```

Wrangler does print a warning about this during deploy, but still deploys
successfully — easy to miss in CI logs. Fix is simply deleting the empty
`[env.*]` blocks so the top-level config applies to all deploys (production
and preview alike).

## Workers' `crypto.subtle` caps PBKDF2 at 100,000 iterations

`crypto.subtle.deriveBits`/`deriveKey` with PBKDF2 throws
`NotSupportedError: iteration counts above 100000 are not supported` on
real Workers/Pages Functions — but **not** in `wrangler dev` or Miniflare,
which use Node's crypto implementation with no such cap. Code hashing at a
higher iteration count (210,000, matching some published bcrypt/PBKDF2
guidance) will pass every local test and then 500 on every request in
production.

**Lesson: PBKDF2/crypto.subtle behavior must be verified against a real
deploy, not just local dev** — Node-vs-workerd crypto differences hide this
kind of bug completely locally. If you store the iteration count alongside
each hash (e.g. `iterations` field in the stored credential), fixing a
too-high count is just re-hashing existing values, not a schema migration.

## `_redirects` is silently skipped for any path a Pages Functions route matches

Cloudflare's own docs: *"Redirects defined in the `_redirects` file are not
applied to requests served by Pages Functions, even if the Function route
matches the URL pattern."* This applies even when the matching function's
only job for that path is to call `next()` and pass through — the mere
existence of a matching Functions route is enough to disable `_redirects`
for that path.

**Practical impact: a root `functions/_middleware.ts` (which matches every
request) means `_redirects` never fires anywhere on that project, for any
path.** If you need a redirect (e.g. a renamed page/slug) on a Pages project
that has a catch-all middleware, implement the redirect *inside* the
middleware itself — checking `url.pathname` and returning
`Response.redirect(...)` — rather than relying on `_redirects` at all.

## `wrangler pages project create` now makes a *Workers* project (wrangler 4.149, 2026-10)

Seen 2026-10-23: `wrangler pages project create <name>` printed "Delegating to the latest version of
Cloudflare Pages, now part of Cloudflare Workers", **wrote a `wrangler.jsonc` (Worker + assets) into the
repo, rewrote `package.json` (added `deploy`/`preview` scripts and wrangler as a dependency), appended to
`.gitignore` and grew `package-lock.json` by ~1,500 lines**, then failed with "Pages project does not
exist". No Pages project was created. Every edit was local and uncommitted (`git checkout --` + delete the
jsonc to undo).

**To make a real Pages project, use the API, then deploy with wrangler as before**:
`POST /accounts/{id}/pages/projects {"name": "...", "production_branch": "main"}` (Pages Write token), then
`wrangler pages deploy _site --project-name <name> --branch main`. Deploying to an existing Pages project
is unaffected. Long-lived sites still go through dashboard Git integration (website-building-preferences §12).

## A custom domain on a proxied zone: what the headers really mean (2026-11-01, williejackson.com)

- **`cf-cache-status: DYNAMIC` on Pages HTML is normal.** That label describes the zone's CDN cache,
  which by default stores only static extensions (`.css`, `.jpg`…), never HTML. Pages serves the HTML
  from its own edge storage anyway: TTFB measured 0.12–0.16 s, no origin. Don't "fix" it with a Cache
  Everything rule: deploys don't purge the zone cache, so edits would stay invisible until the TTL ran
  out.
- **`cache-control: public, max-age=0, must-revalidate`** is Pages' default for HTML, so a new deploy
  shows at once (browsers revalidate by ETag).
- **Zone settings override `_headers` on the custom domain.** The same file served
  `max-age=86400` (from `_headers`) on `*.pages.dev` but `max-age=2678400` (31 days, the zone's
  Browser Cache TTL) on the custom domain. Compare the two hostnames before blaming `_headers`.
- **`! Header-Name` in `_headers` detaches a default header.** `! Access-Control-Allow-Origin` under
  `/*` drops Pages' default open CORS.
- **Cloudflare Fonts** (zone setting) rewrites a page's Google Fonts `<link>` at the edge into inline
  `@font-face` from `/cf-fonts/…`, so the browser never contacts Google. The `<link>` in the source
  is load-bearing; a `dns-prefetch` for `fonts.googleapis.com` is dead weight.
- **Moving a domain from an origin to Pages.** Add the custom domain in the dashboard; it offers to
  replace the existing proxied A record. A `www` → root redirect the old server did needs a zone
  Redirect Rule (template "Redirect from WWW to root") plus `www` as a second custom domain.
- **A zone-scoped token's reach.** The homelab's `CF_ZONE_TOKEN` reads DNS, custom firewall rules and
  page rules, but gets "not authorized" for redirect/cache/transform rulesets and "Authentication
  error" for zone settings.

## Related

- `wordpress-static-export`: a WordPress site exported to a Git-integrated Pages project.

For Workers Cron Trigger gotchas (day-of-week numbering, testing
`scheduled()` against real bindings, subrequest-limit sizing) and R2
delete/rename verification, see the `cloudflare-workers-cron-email` skill —
distinct topic area, same "the platform did something non-obvious" theme.
