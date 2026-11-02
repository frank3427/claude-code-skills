---
name: wordpress-static-export
description: This skill should be used when turning a WordPress site into a static copy served from Cloudflare Pages (or any static host) while WordPress stays as a private editor, when building or debugging a crawl-based export (wget mirror) of WordPress, a publish pipeline that commits an export to a Git-integrated Pages project, or when an export "passes" but ships without images/CSS. Built 2026-11-01 for williejackson.com (private WordPress on homelab CT 144, homelab-ansible wordpress-install.yml). Trigger phrases include "static WordPress", "WordPress to Pages", "export WordPress to static", "headless WordPress static copy", "Simply Static", "Simply Static WP-CLI", "wget mirror WordPress", "wp-static-export", "wp-static-publish", "publish to williejackson.com button", "static export missing page", "static export missing images", "export passed but no CSS", "WordPress private editor Tailscale", "WP_HOME two hostnames", "unix_socket WordPress database", "pages.dev preview compare", "retire WordPress server keep editing".
---

# WordPress → static copy on Pages, WordPress kept as a private editor

Will's website rules (`website-building-preferences` §11–13) prefer a clean WordPress → 11ty
migration with **no headless WordPress**. This pattern is the sanctioned **interim**: it gets a
site off a public WordPress server now, keeping the editor Will already knows, until the rebuild.
Check those rules first, and say "interim" out loud when proposing it. In 2026-11 a plan was
proposed without checking them, and it was caught only at build time.

## Shape

```
private WordPress (LXC, loopback only)        control node (holds all credentials)        GitHub → Pages
  wp-admin via Tailscale Serve           ───>   timer: ssh "export --if-needed"     ───>   repo public/
  export = wget crawl of the PUBLIC             tar the tree back, git commit, push         Git-integrated,
  hostname served by its own nginx                                                          output dir "public"
```

- **The WordPress box holds no cloud or Git credential.** The control node pulls the files and
  pushes them. WordPress is the attack surface, so it should have nothing to steal.
- **Use Pages Git integration, not Direct Upload.** A Direct Upload project can never be switched to
  Git later. Will creates the project in the dashboard (Connect to Git, no build command, output
  `public`) and attaches the custom domains there.
- **Use two hostnames for one WordPress.** wp-config picks `WP_HOME`/`WP_SITEURL` from `HTTP_HOST`:
  the tailnet name for editing, the public name for everything else (WP-CLI, the crawl). Set
  `$_SERVER['HTTPS']='on'` for both.
- **For the crawl, the public name resolves to 127.0.0.1** through `/etc/hosts`, with a self-signed
  vhost on 127.0.0.1:443. On Proxmox LXCs, `touch /etc/.pve-ignore.hosts` or the line vanishes at
  the next start.
- **The database user is `IDENTIFIED VIA unix_socket`**, with the same name as the PHP-FPM pool user
  and `DB_PASSWORD ''`. No DB password exists to store or leak.
- **Media uploaded while editing over Tailscale embeds the private hostname.** Handle it twice: a
  `wp_insert_post_data` filter rewrites it, and the export also seds it and refuses to publish if
  any remains.

## Why wget, not Simply Static

The free Simply Static has **no WP-CLI export** (Pro only; checked 2026-11-01), so it can't be
scripted. A crawl of the real rendered site also has an advantage: you can check it against the
live site directly.

The crawl command: `wget -r -l inf -p -nH -i seeds.txt --no-check-certificate -e robots=off
--domains=<host> --reject-regex '(/wp-admin/|/wp-login\.php|/wp-json/|xmlrpc\.php|/feed/[^/]+/|[?&](replytocom|share|s)=|/trackback/|/embed/)'`.

Seed it with:
- the home page;
- every published post and page (`wp post list ... --field=url`);
- the category and tag URLs (`wp term list ... --field=url`);
- `/feed/`, `wp-sitemap.xml` and `robots.txt`.

Sub-sitemaps are XML, which wget doesn't follow, so fetch them separately.

## The checks are the product

The export goes into a temporary folder and replaces the published tree **only if every check
passes**. Each check below exists because a real export got past the earlier ones:

| Check | What it caught (2026-11-01) |
|---|---|
| Every published post/page **and every URL in the site's own sitemaps** exists | `/author/<user>/` was missing. Seeding from the sitemap covers new page types automatically |
| Missing required URLs are re-fetched directly before checking | wget **skips a page reached through a redirect** (`/consulting` → `/consulting/`): the child pages saved, the parent didn't |
| Every `wp-content`/`wp-includes` asset referenced in `src`/`href`/`srcset` exists | A permission bug made nginx 404 **every** image, CSS and JS file. The export was 1.3 MB and **still passed the page checks** |
| Assets named in **`data-*` attributes** are collected, fetched, and required too | The theme's YouTube embeds keep their custom preview image in `data-thumb` (a script swaps it in). wget never follows it and the first asset check never read it: 4 thumbnails 404ed on 11 live pages (2026-11-02) |
| Feed exists and contains `<rss`; a 404 page exists | — |
| No private hostname, `127.0.0.1` or tailnet suffix appears anywhere | — |

Also:
- **Rename** `style.css?ver=1.2` → `style.css`. Pages ignores the query string when it looks up a file.
- **Fetch the 404 page from a fixed path** (`/wj-static-404/`). A timestamped probe URL lands in
  `og:url` and changes `404.html` on every publish.
- **Write `_headers`:** RSS `Content-Type` for `/feed/*` and `/*/feed/*`, XML for `/wp-sitemap*`, a
  security header block, and `! Access-Control-Allow-Origin` to detach Pages' default open CORS.
- **Prove the refusal.** Hide one stylesheet (`chmod 000`), export, and expect `FAILED` while the
  last good tree stays in place.

## Publishing semantics

- **Fingerprint:** post count and max `post_modified_gmt`, an MD5 of non-volatile options (exclude
  transients, `cron`, `wpo_*`, `*_last_checked`), terms and term relationships, and the file list
  with mtimes for themes, plugins and mu-plugins.
- **When it exports:** if the fingerprint changed, or the Publish button's flag file exists.
- **The export writes `pending-fp`.** The control node promotes it to `last-export-fp` **only after
  a successful push**, so a failed publish is retried rather than read as "unchanged" forever.
- **An unpushed local commit** (from a failed push) is pushed first on the next run.
- **Alerting:** silent when unchanged and on success. One Telegram on the first failure of a
  streak, and one on recovery.
- **Publish button:** an admin-bar item (`manage_options`, nonce) that writes the flag file. Its
  tooltip shows when the site last published.

## Gotchas

- **The copied site tree was 2750/0640, owned by the site user.** nginx (`www-data`) needs to be in
  that group, or every static file returns 404 (`stat() ... Permission denied` in the nginx
  error log).
- **The control node SSHes by name**, so its known_hosts needs the *name*, not just the IP. Missing
  that, the first timer run failed and sent a real failure alert.
- **Before the cutover, compare the `pages.dev` preview with the live site, URL by URL.** Normalize
  the text (strip scripts, styles and tags). Expect one class of false difference: Cloudflare
  Email Obfuscation turns addresses into `[email protected]` at the edge on the proxied site.
- **Before cutting over, check where forms post.** External ones (Kit/ConvertKit, Wufoo) keep
  working. Check their post-submit redirect pages too: Kit's `/success/` was already a 404.
- **`www` → root:** the old server did that redirect. On Pages it needs a zone Redirect Rule (the
  dashboard template "Redirect from WWW to root"), plus `www` as a second custom domain.
- **The Thesis theme prints its own `<head>` tags with no hooks.** To remove them, use an output
  buffer on `template_redirect` that rewrites only the part before `</head>`, front end only (skip
  admin, feeds, AJAX and REST).
- **Thesis accessibility fixes (Lighthouse a11y + Agentic Browsing to 100, 2026-11-02).** Thesis
  containers can't be `<main>`; put `role="main"` in the Content container's attributes field. The
  Social Profiles box prints unnamed icon links with no filter, so add `aria-label` in the mu-plugin
  output buffer. Section `<h4>`s styled by the skin get `aria-level="2"` instead of becoming `<h2>`,
  which the skin renders 14 px larger and centers in focus mode. Iframes from embed scripts (Wufoo)
  need `title` set in the script after `display()`. Running Lighthouse here: memory
  `reference_lighthouse_on_claude_code_host`.
- **Restore-test checks that pipe `curl | grep -q`** fail under `set -o pipefail`: grep exits
  early and curl gets SIGPIPE. Save to a file, then grep.

See also `cloudflare-pages-gotchas` (cache labels, `_headers` overrides, Cloudflare Fonts) and
`wordpress-nginx-cloudflare` (the public-WordPress stack this replaces).
