#!/usr/bin/env bash
# web-render.sh -- read a JavaScript-built web page through Cloudflare Browser Run's REST
# "quick actions". Claude Code's one canonical path for pages WebFetch sees as an empty shell.
#
# Built 2026-10-27 (Will: "go ahead and build it", homelab repo agent-browser-image-skills-
# research.md). Rules borrowed from a friend's agent (Alex): one canonical path, key read at
# runtime and never in argv or the conversation, structured output, dry-run first, a usage
# ledger checked before every run, and one exit code per failure so nothing blind-retries.
# Read-only by construction: quick actions load a page and return it; they cannot click or type.
#
# Usage:
#   web-render.sh [--dry-run] [--wait <css-selector>] [--full-page] <markdown|content|links|screenshot> <url>
#   web-render.sh --usage
#
# Output (stdout): one JSON object {status, exit, action, url, path, bytes, ms_used, today_ms, note}.
# The page itself goes to a file under ~/.claude/state/web-render/ (path in the JSON).
#
# Exit codes (each maps to ONE action -- see SKILL.md):
#   0 ok              3 empty shell (page didn't render content)    4 bot wall / CAPTCHA
#   5 budget/quota    6 auth (token missing, wrong, or API 401/403) 7 network / API error
#   8 internal URL refused (never sent to Cloudflare)               2 usage error
#
# Credentials: CF_BROWSER_RUN_TOKEN and CF_ACCOUNT_ID live in Infisical (homelab-fleet). This
# host has no Infisical identity, so they are read over SSH from ansible-ctrl's infisical-get.sh
# at run time, held in shell variables only, and handed to curl on stdin (--config -), never argv.

set -euo pipefail

STATE_DIR="${WEB_RENDER_STATE_DIR:-$HOME/.claude/state/web-render}"
LEDGER="$STATE_DIR/ledger.tsv"
ANSIBLE_CTRL="${WEB_RENDER_SECRETS_HOST:-root@192.168.50.71}"
API_BASE="https://api.cloudflare.com/client/v4/accounts"
# Workers Free: 10 browser-minutes a day. Stop at 95% so a run never dies half-way on a 429.
DAILY_LIMIT_MS="${WEB_RENDER_DAILY_LIMIT_MS:-600000}"
STOP_AT_MS=$(( DAILY_LIMIT_MS * 95 / 100 ))

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

today_ms() {
  local d; d=$(date -u +%F)
  [[ -f "$LEDGER" ]] || { echo 0; return; }
  awk -F'\t' -v d="$d" '$1 == d { s += $6 } END { print s + 0 }' "$LEDGER"
}

emit() {  # status exit action url path bytes ms note
  python3 -I -c 'import json,sys
a=sys.argv[1:]
print(json.dumps({"status":a[0],"exit":int(a[1]),"action":a[2],"url":a[3],"path":a[4] or None,
  "bytes":int(a[5] or 0),"ms_used":int(a[6] or 0),"today_ms":int(a[7]),"daily_limit_ms":int(a[8]),"note":a[9]}))' \
    "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$(today_ms)" "$DAILY_LIMIT_MS" "$8"
}

ledger() {  # action host http ms exit
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%F)" "$(date -u +%T)" "$1" "$2" "$3" "$4" "$5" >> "$LEDGER"
}

finish() {  # exit status action url path bytes ms note
  emit "$2" "$1" "$3" "$4" "$5" "$6" "$7" "$8"
  exit "$1"
}

# ---- arguments ----
DRY=0; WAIT=""; FULL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --wait) WAIT="${2:-}"; shift 2 ;;
    --full-page) FULL=1; shift ;;
    --usage)
      echo "today (UTC $(date -u +%F)): $(today_ms) ms of ${DAILY_LIMIT_MS} ms browser time"
      [[ -f "$LEDGER" ]] && tail -n 10 "$LEDGER" | column -t -s $'\t'
      exit 0 ;;
    -h|--help) sed -n 2,24p "$0"; exit 0 ;;
    --*) echo "unknown option: $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
[[ $# -eq 2 ]] || { sed -n 9,12p "$0" >&2; exit 2; }
ACTION="$1"; URL="$2"
case "$ACTION" in markdown|content|links|screenshot) ;; *) echo "action must be markdown, content, links or screenshot" >&2; exit 2 ;; esac
[[ "$URL" =~ ^https?:// ]] || finish 2 usage "$ACTION" "$URL" "" 0 0 "URL must start with http:// or https://"

# ---- internal-address guard (exit 8): never send LAN/tailnet names to a third party ----
INTERNAL=$(python3 -I - "$URL" <<'PY'
import ipaddress, socket, sys
from urllib.parse import urlsplit
host = (urlsplit(sys.argv[1]).hostname or "").lower().rstrip(".")
def internal_ip(t):
    try: ip = ipaddress.ip_address(t.strip("[]"))
    except ValueError: return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified \
        or (ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"))
suffixes = (".ts.net", ".jackson2w.dev", ".local", ".internal", ".lan", ".home.arpa", ".localhost")
if not host: print("no host")
elif host == "localhost" or host.endswith(suffixes): print(f"{host} is an internal name")
elif "." not in host and not internal_ip(host): print(f"{host} is a single-label LAN name")
elif internal_ip(host): print(f"{host} is a private or tailnet address")
else:
    try: addrs = {i[4][0] for i in socket.getaddrinfo(host, None)}
    except OSError: addrs = set()
    bad = sorted(a for a in addrs if internal_ip(a))
    if bad: print(f"{host} resolves to private address {bad[0]}")
PY
)
[[ -z "$INTERNAL" ]] || finish 8 refused "$ACTION" "$URL" "" 0 0 "$INTERNAL; internal pages are never sent to Cloudflare. Use the fleet tools instead."

# ---- budget (exit 5) ----
USED=$(today_ms)
if (( USED >= STOP_AT_MS )); then
  finish 5 budget "$ACTION" "$URL" "" 0 0 "today's browser time is ${USED} ms of ${DAILY_LIMIT_MS}; refusing before the API does (resets 00:00 UTC: 7 PM CDT, 6 PM CST)"
fi

# ---- request body ----
BODY=$(python3 -I - "$ACTION" "$URL" "$WAIT" "$FULL" <<'PY'
import json, sys
action, url, wait, full = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1"
body = {"url": url, "gotoOptions": {"waitUntil": "networkidle2", "timeout": 30000}}
if wait:
    body["waitForSelector"] = {"selector": wait, "timeout": 15000}
if action == "screenshot":
    body["screenshotOptions"] = {"fullPage": full}
    body["viewport"] = {"width": 1280, "height": 900}
print(json.dumps(body))
PY
)

HOST=$(python3 -I -c 'import sys; from urllib.parse import urlsplit; print(urlsplit(sys.argv[1]).hostname or "page")' "$URL")
STAMP=$(date -u +%Y%m%d-%H%M%S)
case "$ACTION" in markdown) EXT=md ;; content) EXT=html ;; links) EXT=txt ;; screenshot) EXT=png ;; esac
OUT="$STATE_DIR/$STAMP-$HOST.$EXT"

if (( DRY )); then
  finish 0 dry-run "$ACTION" "$URL" "$OUT" 0 0 "would POST $API_BASE/<account>/browser-run/$ACTION with body $BODY; no token fetched, no browser time used"
fi

# ---- credentials (exit 6), held in variables only ----
CREDS=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$ANSIBLE_CTRL" \
  't=$(/root/bin/infisical-get.sh CF_BROWSER_RUN_TOKEN) && a=$(/root/bin/infisical-get.sh CF_ACCOUNT_ID) && printf "%s\n%s\n" "$t" "$a"' 2>/dev/null) || CREDS=""
# $(...) strips each value's own trailing newline, so the token is always line 1 and the ID line 2.
TOKEN=$(printf '%s\n' "$CREDS" | sed -n 1p | tr -d '[:space:]')
ACCOUNT=$(printf '%s\n' "$CREDS" | sed -n 2p | tr -d '[:space:]')
unset CREDS
if [[ -z "$TOKEN" || ! "$ACCOUNT" =~ ^[0-9a-f]{32}$ ]]; then
  finish 6 auth "$ACTION" "$URL" "" 0 0 "could not read CF_BROWSER_RUN_TOKEN / CF_ACCOUNT_ID from Infisical via ansible-ctrl"
fi

# ---- the call ----
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
printf '%s' "$BODY" > "$TMP/body.json"
set +e
HTTP=$(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl -sS --config - \
  -X POST "$API_BASE/$ACCOUNT/browser-run/$ACTION" \
  -H 'Content-Type: application/json' --data-binary @"$TMP/body.json" \
  -D "$TMP/headers" -o "$TMP/response" -w '%{http_code}' --max-time 90 2>"$TMP/curl.err")
CURL_RC=$?
set -e
unset TOKEN
MS=$(awk -F': *' 'tolower($1) == "x-browser-ms-used" { gsub(/\r/, "", $2); print $2 }' "$TMP/headers" 2>/dev/null | tail -1)
MS=${MS:-0}
MS=$(printf '%.0f' "$MS" 2>/dev/null || echo 0)   # Cloudflare sends a decimal, e.g. 7518.09

if (( CURL_RC != 0 )); then
  ledger "$ACTION" "$HOST" "curl$CURL_RC" "$MS" 7
  finish 7 network "$ACTION" "$URL" "" 0 "$MS" "curl failed ($CURL_RC): $(head -c 200 "$TMP/curl.err")"
fi
API_ERR=$(python3 -I -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
    e = d.get("errors") or []
    print("; ".join(str(x.get("message", x)) for x in e)[:300])
except Exception: pass' "$TMP/response" 2>/dev/null || true)
case "$HTTP" in
  200) ;;
  429) ledger "$ACTION" "$HOST" "$HTTP" "$MS" 5; finish 5 quota "$ACTION" "$URL" "" 0 "$MS" "Cloudflare 429: ${API_ERR:-rate or daily browser-time limit}" ;;
  401|403) ledger "$ACTION" "$HOST" "$HTTP" "$MS" 6; finish 6 auth "$ACTION" "$URL" "" 0 "$MS" "Cloudflare $HTTP: ${API_ERR:-token lacks Browser Run - Edit}" ;;
  *) ledger "$ACTION" "$HOST" "$HTTP" "$MS" 7; finish 7 api-error "$ACTION" "$URL" "" 0 "$MS" "Cloudflare HTTP $HTTP: ${API_ERR:-no error message}" ;;
esac

# ---- unpack the result ----
if [[ "$ACTION" == "screenshot" ]]; then
  cp "$TMP/response" "$OUT"
  if ! head -c 8 "$OUT" | od -An -tx1 | tr -d ' \n' | grep -q '^89504e470d0a1a0a'; then
    rm -f "$OUT"; ledger "$ACTION" "$HOST" "$HTTP" "$MS" 7
    finish 7 api-error "$ACTION" "$URL" "" 0 "$MS" "HTTP 200 but the body is not a PNG: ${API_ERR:-unexpected response}"
  fi
  TEXT=""
else
  python3 -I -c 'import json,sys
d = json.load(open(sys.argv[1]))
r = d.get("result")
out = "\n".join(r) if isinstance(r, list) else (r if isinstance(r, str) else json.dumps(r, indent=1))
open(sys.argv[2], "w").write(out or "")' "$TMP/response" "$OUT"
  TEXT=$(cat "$OUT")
fi
BYTES=$(stat -c %s "$OUT")

# ---- classify (exit 4 bot wall before exit 3 empty: a challenge page is also short) ----
if [[ -n "$TEXT" ]] && grep -q -i -E 'just a moment|checking your browser|cf-chl|verify (that )?you are (a )?human|are you a robot|captcha|attention required! \| cloudflare|access denied|enable javascript and cookies to continue|request blocked' <<<"$TEXT"; then
  ledger "$ACTION" "$HOST" "$HTTP" "$MS" 4
  finish 4 bot-wall "$ACTION" "$URL" "$OUT" "$BYTES" "$MS" "page looks like a bot challenge; Browser Run announces itself as a bot and cannot pass these"
fi
if [[ "$ACTION" == "markdown" ]]; then
  VISIBLE=$(tr -s '[:space:]' ' ' <<<"$TEXT" | wc -c)
  if (( VISIBLE < 200 )) || grep -q -i -E 'you need to enable javascript|requires javascript' <<<"$TEXT"; then
    ledger "$ACTION" "$HOST" "$HTTP" "$MS" 3
    finish 3 empty "$ACTION" "$URL" "$OUT" "$BYTES" "$MS" "rendered page has ${VISIBLE} visible chars; retry ONCE with --wait <selector> for the content you need"
  fi
fi

ledger "$ACTION" "$HOST" "$HTTP" "$MS" 0
finish 0 ok "$ACTION" "$URL" "$OUT" "$BYTES" "$MS" ""
