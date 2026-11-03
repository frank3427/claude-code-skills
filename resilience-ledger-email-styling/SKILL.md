---
name: resilience-ledger-email-styling
description: This skill should be used when sending or styling any transactional/notification email for Will (dfw, Olu, WordPress, or any future homelab automation) and it should carry the resilience-ledger design system look, when a new HTML email needs light+dark mode that actually works, or when debugging an email where dark mode text is invisible/low-contrast. Also load this before touching render-ledger-email.py, ledger-email-style.php, render-terminal-report.py's HTML output, or render-correspondence-email.py (Claude Code's own prose emails to Will, markdown-in/HTML-out, entities distinguished by shape not colour). Trigger phrases include "ledger styled email", "resilience ledger design system email", "make this email look like the other ones", "dark mode email text invisible", "email dark mode not working", "wp_mail styled", "render-ledger-email.py", "status pill email", "callout box email html".
---

# Resilience-ledger email styling

A shared visual language for every outbound email in this environment — `dfw`/Olu's own sends,
WordPress's `wp_mail()` notifications, the homelab-wide weekly report system on `ansible-ctrl`,
and (since 2026-09-05) Claude Code's own correspondence to Will. Built 2026-08-17 from the `resilience-ledger-design-system` Artifact Will liked
(warm-paper/dark-ink "systems report" look — status pills, tinted callout boxes, IBM Plex
Mono/Sans). This is a **different, separate visual language** from anything else in this
environment named "Kanagawa" — don't confuse it with Ghostty's terminal theme.

## Source of truth for the palette

**`~/Desktop/resilience-ledger-design-system/tokens.css` is GONE as of 2026-09-05** — the
directory no longer exists on Will's Mac (he moves files between machines; this is not a
mystery to investigate). The surviving authority is now
`/root/bin/render-terminal-report.py` on `ansible-ctrl`, whose light and dark blocks carry the
full palette. Re-derive from there. If Will ever restores the tokens file, it wins again.

Historically: every hex value used anywhere in this pattern was hand-copied from that file —
**re-derive from the surviving source, not from memory or from any of the implementations
below**, if the palette ever needs to change.
There is no shared stylesheet these implementations `@import` (email clients strip external
CSS), so a palette change means editing all five by hand. In every one of them, light values
live in the bare selectors and dark values in the `@media (prefers-color-scheme: dark)` block.
The retired tokens file also carried a third `[data-theme="dark"]` block for a web toggle — if
it resurfaces, ignore that block; it is irrelevant to email.

## The one rule that matters most: theme color goes through CSS classes, never inline

**Real bug hit and fixed while building this**: an early version set text color inline on
prose paragraphs (`style="...color:#21201C;"`, the light-mode ink color). A `<style>` block's
`@media (prefers-color-scheme: dark)` override for that same element does **not** win against
a plain inline style — inline styles beat embedded stylesheet rules regardless of media query,
unless the stylesheet rule uses `!important`. Result: in dark mode, the *background* correctly
switched to dark (that was set via a class) but the *text* stayed the light-mode dark-ink
color — dark text on a dark background, functionally invisible. Caught only by actually
screenshotting the rendered output (see Verification below), not by reading the CSS.

**The fix, and the rule going forward**: every element whose color needs to differ between
light and dark gets a class name (`ledger-p`, `ledger-title`, `ledger-heading`, `ledger-pill-
ok`, etc.), and *only* the class rules in the embedded `<style>` block set `color`/`background`/
`border-color`. Inline `style=` attributes are reserved for properties that never change by
theme — `padding`, `margin`, `border-radius`, `font-family`, `font-size`, `letter-spacing`.
If you're about to write `style="color:#..."` directly on an element inside one of these
templates, stop — that color belongs in a class rule instead.

## Font reality — don't oversell fidelity

IBM Plex Mono/Sans are **not** embedded as web fonts in any of these emails — `@font-face`
loading is unreliable across email clients (Gmail generally ignores it entirely, Apple Mail
partial, Outlook desktop none). Every font-family stack lists the real typeface first but
falls back honestly: `'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace` and
`'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif`. The "systems report" register comes
through via the fallback stack even where the exact typeface doesn't load. Don't promise
pixel-identical rendering to the web Artifact version in every client — it isn't, and that's an
accepted, deliberate tradeoff, not a bug to chase.

## Components

- **Status pill**: color + a small dot + text label (`OK`/`WARN`/`FAIL`), never color alone.
  Semantic colors only — green/amber/red mean fine/needs-attention/broken, not
  unimportant/important.
- **Callout/BLUF box**: tinted background (12-14% opacity of the status color) + a colored
  eyebrow label. **Deliberately no colored left border** — a thick side-accent on a card is
  one of the most recognizable AI-generated-UI tells, per the source design system's own
  README; don't reintroduce it here even though it would be an easy way to show status.
- **Mono block**: a light/dark-toned card, monospace, `white-space:pre-wrap`, for anything
  list/data-like (IP counts, pasteable prompts) — as opposed to prose, which uses the sans
  stack in plain `<p>` tags split on blank lines.
- **No numbered section markers** unless content is a genuine sequence — a numbered marker on
  non-sequential content is decoration pretending to be information (same README guidance).
- **Footer report-link line**: omit entirely when there's no link, never show a placeholder
  string.

## Required `<head>` boilerplate

Every implementation needs both of these, or clients may auto-invert an unstyled body instead
of rendering the authored dark palette:
```html
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
```

## The five implementations — no shared renderer across runtimes

Same design language, five separate hand-written implementations, because nothing here can
share code across the runtimes/hosts involved:

1. **`/usr/local/bin/render-ledger-email.py`** on `dfw` (Python, world-readable/executable —
   both root-run systemd services and the `openclaw` user call it). JSON-in
   (`title`/`eyebrow`/`status`/`summary`/`sections[]`/`footer`), HTML-out on stdout. Used by
   `fail2ban-weekly-digest.sh` and `dfw-package-check.sh` (added 2026-08-20, part of
   `dfw-ansible`'s graduated `package-check-install.yml` — see `project_dfw_vultr_buildout`
   memory), and documented as the default in Olu's `email` skill
   (`/home/openclaw/.openclaw/workspace/skills/email/SKILL.md`) for anything substantive.
2. **`/var/www/williejackson.com/wp-content/mu-plugins/ledger-email-style.php`** on `dfw`
   (native PHP — can't shell out to the Python renderer per-email from a WP process). Hooks
   `wp_mail_content_type` → `text/html` and a `wp_mail` filter (priority 20) that wraps the
   plain-text message body in the same visual shell. Guards against double-wrapping if a
   message already looks like real HTML (`stripos($message, '<html')`).
3. **`/root/ansible/scripts/render-terminal-report.py`** on `ansible-ctrl` (git-tracked in the
   `homelab-ansible` repo, deployed to `/root/bin/` — **only ever via the
   `homelab-report-timers.yml` playbook, never hand-copied over SSH**, or a future
   `ansible-ctrl` rebuild silently loses the change). A richer schema than #1
   (`overall_status`/`bluf`/`categories[].items[]`/`claude_code_prompts[]`) for the shared
   weekly-housekeeping/nightly-backup-summary/R2-B2-sync report system — see the
   `homelab-terminal-report-delivery` skill for that schema's full contract.
   `render_markdown()` in this same file is untouched by any of this — markdown has no visual
   style to change, verify any future edit here doesn't touch it (diff before/after).
4. **`backup-worker/src/render-terminal-report.js`** in the `photo-site` repo (JS, Cloudflare
   Worker). A hand-maintained JS port of #3 — same schema, same visual output, kept in
   lockstep manually since there's no shared code across the Python/JS runtime boundary. Was
   still on the old Kanagawa Wave design until 2026-08-20 (missed by the 2026-08-17 fleet
   restyle since it isn't deployed via `homelab-ansible` and nothing sweeps this repo). If #3's
   markup changes, port the change here too — don't let it drift again.

5. **`/root/bin/render-correspondence-email.py`** on `ansible-ctrl` (git-tracked in
   `homelab-ansible` as `scripts/render-correspondence-email.py`, deployed by
   `claude-email-install.yml` — same versioned-source vs deployed-copy split as #3, so editing
   the script proves nothing until that play runs). Added 2026-09-05. **Markdown in, HTML out**
   — no JSON schema at all, because its content is prose rather than findings. It backs
   `claude-send-email.sh --markdown`, which is Claude Code's own correspondence to Will: pause
   handoffs and anything ad-hoc. Until it existed those went out as `TextBody` and nothing else.

   **It runs on three hosts, byte-identical, and there is no shared filesystem to make it
   anything else** (`ansible-ctrl` at `/root/bin/`, `dfw` and `hermes` at `/usr/local/bin/`,
   each deployed from its own Ansible repo). `ansible-ctrl`'s copy in `homelab-ansible` is
   canonical; a change there must be copied to the other two in the same session. Verify with
   `md5sum` across all three — this is the same lockstep problem #4 lost for three days.

   **On `dfw` and `hermes` it renders in the ROOT DISPATCHER, not in the agent** (added
   2026-09-05 when Will asked for Olu's and Chuka's mail to match). The agent keeps writing
   plain markdown into the spool queue exactly as before, so there is no agent-side change, no
   new flag for an agent to remember, and nothing edited inside either agent's own workspace —
   which matters on `dfw`, where `/home/openclaw` is off-limits and could not have been edited
   anyway. Rendering belongs on the dispatcher side regardless: it already owns how a job
   becomes a message, and a formatting decision has no business inside the confined process.

   Default-on with an opt-out (a job may set `"markdown": false`), and a body that already
   begins `<!doctype`/`<html>` passes through as `HtmlBody` untouched rather than being escaped
   — that guard is what keeps #1's report output working through the same path. The markdown
   still goes out as `TextBody` every time, so a failed render degrades to a plain readable
   message rather than a lost one. The eyebrow and footer derive from the sending address's
   local part, so Olu signs as Olu and Chuka as Chuka with no per-identity table to keep in
   sync. Both dispatchers' audit logs record `html=yes/no`, so a silent fallback to plain text
   is visible from the host rather than only from Will's inbox.

   Its one real departure from #1–#4, chosen by Will from three options: **technical entities
   are distinguished by shape, not colour.** Four inline treatments — command (filled, hairline
   border, semibold), host/device (dotted underline, no fill), network/address (hairline border,
   no fill), everything else (filled, no border). Shape survives greyscale, colour-blindness,
   and a client that recolours text; colour stays reserved for callouts, where it means
   something. Only `$` (command) and `@` (host) need author markup — addresses are regex-
   detected, since tagging every subnet by hand is the friction that ends with a format going
   unused. Callouts are `> [!FLAG|BLOCKED|OK|NOTE|NEXT] text`.

   Prose is set in a **serif** here (`'IBM Plex Serif','Iowan Old Style',Georgia,serif`) rather
   than Plex Sans — the only implementation that does. Iowan Old Style ships on macOS and iOS,
   which is where Will reads mail, so the printed register survives the fact that no web font
   ever loads.

If a *new* consumer needs this styling: reuse #1's schema directly if the content is simple
(a title, maybe a status callout, a few prose/data sections); reuse #3's schema if it needs
categorized findings with per-item status and/or a follow-ups section; reuse #5 if the content
is genuinely a *letter* — prose that happens to contain hosts and commands — rather than a
status report. Don't invent a sixth schema without a real reason.

**Two bugs #5 hit that any future implementation will hit too**, both found by screenshotting
rather than by reading output:
- **A wrapped list item silently leaves its list.** Markdown's lazy continuation (a bullet
  whose source text runs onto the next line without a marker) is easy to omit from a hand-rolled
  block parser; the tail then renders as a stray paragraph below the list, which looks like a
  content mistake rather than a parser one.
- **Code-span padding reads as a word space before punctuation.** At 5px horizontal padding an
  inline entity followed by a comma renders as `UNIFI_API_KEY ,`. 3px keeps the fill legible
  without the gap.

## Sending — Cloudflare Email Sending (dfw/Olu path)

```bash
curl https://api.cloudflare.com/client/v4/accounts/af56d5158a7dab3e67f31efc275ec9f2/email/sending/send \
  -H "Authorization: Bearer $CLOUDFLARE_EMAIL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to":"...", "from":{"address":"homelab@jackson2w.dev","name":"..."}, "subject":"...", "text":"...", "html":"..."}'
```
Always include both `text` and `html` — never `html` alone. **Correction 2026-08-30**: the
prior version of this note said `from` "must stay `olu@jackson2w.dev`, the only domain
onboarded" — that was wrong on two counts, confirmed live: (1) authorization is at the
**domain** level (`jackson2w.dev`'s SPF/DKIM are set up in this Cloudflare account), not the
address level — any `@jackson2w.dev` local-part works immediately with **zero** additional
setup, no per-address verification step exists for this API; tested by sending from a
brand-new address that had never been used before and it succeeded on the first try. (2)
`olu@jackson2w.dev` specifically was the wrong choice for non-Olu automations anyway — using
Olu's own persona address as the sender for `dfw`'s package-check/fail2ban-digest scripts made
those emails read as coming from Olu when they're not Olu's action, which is exactly what
confused Will's own inbox threading. Both scripts now send from `homelab@jackson2w.dev`
instead — use that (or a similarly purpose-named `@jackson2w.dev` address) for any *new*
non-Olu automation on this account, and reserve `olu@jackson2w.dev` for things that are
genuinely Olu's own output. A `success:true` response includes a real `message_id` — that's
the thing to check, not just that the `curl` call didn't error (see Verification below).

`ansible-ctrl`'s reports go out via Postmark instead (`send_postmark_email` in
`homelab-report-lib.sh`) — different transport, same HTML.

## Verification — screenshot before shipping, don't trust the markup alone

The invisible-dark-text bug above was caught by **actually rendering and screenshotting the
output**, not by reading the CSS and reasoning it should work. Before shipping any change to
one of the five implementations (for #4, run the JS renderer under plain `node` against a
sample JSON payload to get an HTML file to screenshot — no Worker deploy needed just to check
rendering):

```js
// shot.js -- npm install playwright (no browser download needed, see below)
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'chrome' });
  for (const scheme of ['light', 'dark']) {
    for (const [label, width] of [['desktop', 700], ['mobile', 390]]) {
      const ctx = await browser.newContext({
        colorScheme: scheme, viewport: { width, height: 900 }, deviceScaleFactor: 2,
      });
      const page = await ctx.newPage();
      await page.goto('file://' + process.argv[2]);
      await page.screenshot({ path: `shot-${scheme}-${label}.png`, fullPage: true });
      await ctx.close();
    }
  }
  await browser.close();
})();
```

**Use Playwright's `colorScheme`, not the old brace-stripping workaround.** An earlier version of
this skill said to delete the `@media (prefers-color-scheme: dark)` block out of a throwaway copy
in order to see light mode, because `--force-prefers-color-scheme` did not work under raw headless
Chrome. That tests *modified* HTML, which is exactly the wrong thing for a bug whose whole nature
is that the shipped file behaves differently than the file reads. Playwright emulates the media
query properly and screenshots the real file, in both schemes, at two widths, in one pass.

**`channel: 'chrome'` matters.** `chromium.launch()` with no options wants the exact browser build
the installed `playwright` package pins, and the cached build on this Mac is usually older —
`Executable doesn't exist at .../chromium_headless_shell-1243/...` while 1234 sits on disk. The
documented fix (`npx playwright install chromium`) downloads a few hundred MB to solve a problem
that does not need solving: `channel: 'chrome'` drives the Google Chrome already installed here,
needs no download, and renders the same engine. `npm install playwright` on its own is enough.

For a real end-to-end check (not just a local screenshot): send one isolated real test through
whichever transport is relevant (`send_postmark_email` for `ansible-ctrl`, the Cloudflare
curl call above for `dfw`) using a realistic sample payload — this doesn't require waiting for
or triggering a real scheduled run, and catches transport-level issues a local screenshot
can't (e.g. confirm the *deployed* file, not just a local copy, actually renders right). Then
ask Will to actually look at it on a real device — client rendering (especially font fallback
and dark mode) can't be fully verified from a screenshot or a `success:true` API response
alone.

## Deployment gotcha: the auto-mode classifier blocks some `/etc` writes, inconsistently

Writing `/etc/fail2ban/jail.local` directly (a plain heredoc, not even base64/piped) was
blocked by Claude Code's own auto-mode classifier and needed Will to run the command himself.
Writing `/etc/systemd/system/*.service`/`*.timer` files the same session was **not** blocked.
Don't assume all of `/etc` is off-limits — just attempt the write, and if it's blocked, ask
Will to run the exact command rather than hunting for an encoding workaround (base64|tee
triggered the identical block as a plain heredoc — it's not about the pipe shape).
`/usr/local/bin/*` and WordPress's `mu-plugins/` directory were never blocked.
