---
name: grafana-prometheus-alerting
description: This skill should be used when a Prometheus + Grafana stack has metrics being scraped but no real alerting configured, when adding a new Grafana alert rule via provisioning-as-code (not the UI), when checking whether Prometheus alert rules actually exist versus assuming a monitoring stack alerts on its own, when detecting individual systemd service failures across a fleet without building a custom OnFailure-to-webhook mechanism, or when a Grafana alert rule needs testing end-to-end before trusting it. Also use it when a disk/filesystem alert rule is green over something that is actually filling up, when a mounted volume has no `node_filesystem_*` series at all, or when a scrape target goes DOWN after a host changes address. Trigger phrases include "prometheus has no alert rules", "grafana provisioning alert rules", "node_systemd_unit_state", "grafana rules.yaml", "alert on systemd unit failure", "grafana noDataState", "test grafana alert rule firing", "prometheus /api/v1/rules empty", "node_exporter systemd collector", "node_exporter not showing /mnt", "no metrics for mounted volume", "mount-points-exclude", "collector.filesystem.mount-points-exclude", "datastore has no disk metrics", "alert green but disk full", "filesystem collector skipping mount", "disk space rule never fires", "scrape target DOWN after IP change", "pin scrape target to hostname not IP".
---

# Grafana native alerting via provisioning-as-code

Covers discovering that a monitoring stack looks complete but doesn't actually alert, and
closing that gap using Grafana's own alerting engine plus metrics `node_exporter` is already
exposing — without building a separate distributed alerting mechanism.

## First, check whether alert rules actually exist

A Prometheus + Grafana + `node_exporter` stack can look fully monitored (dashboards render,
scrape targets show `up`) while having **zero real alerting** wired up. Don't assume rules
exist just because the stack is deployed — check directly:

```bash
# Prometheus's own rules API -- an empty groups list means no rules at all, regardless of
# how populated the dashboards look.
curl -s http://localhost:9090/api/v1/rules | python3 -m json.tool

# Grafana's OWN unified alerting is a SEPARATE thing from Prometheus rule_files -- check this
# too, via a scoped API token:
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  http://<grafana-host>:3000/api/v1/provisioning/alert-rules | python3 -m json.tool
```

If Grafana has exactly one rule (commonly a generic "Host Down" watching `up{job="..."}`),
that only proves the *notification pipe* (contact point → Telegram/email/etc.) works — it
says nothing about individual service failures on an otherwise-healthy host. Don't conflate
"the alerting pipe is proven" with "the fleet is alerted."

## Detect per-service failures without building new infrastructure

Before designing a custom `OnFailure=`-to-webhook mechanism distributed across every host,
check whether `node_exporter`'s systemd collector is already exposing unit state — it often
already is, even without explicit configuration:

```bash
curl -s localhost:9100/metrics | grep node_systemd_unit_state | grep 'state="failed"'
```

If this data is already being scraped by Prometheus, a **single Grafana alert rule** covers
every host and every service with zero new per-host infrastructure — reusing whatever
contact point/notification policy already works. This is almost always simpler and more
maintainable than a distributed alerting mechanism, and it automatically covers any new host
added to Prometheus's scrape config later with no extra wiring.

## Provisioning-as-code rule format

Grafana provisions alerting from YAML files under
`/etc/grafana/provisioning/alerting/{contactpoints,policies,rules}.yaml` (each independently
`ansible.builtin.copy`/`template`-able, `notify`-handler-restarts `grafana-server` on
change). A rule combines a data query (`refId: A`, actual PromQL) with a threshold
expression (`refId: C`, `datasourceUid: __expr__`) evaluating that query:

```yaml
- uid: systemd-unit-failed
  title: Systemd Unit Failed
  condition: C
  data:
    - refId: A
      datasourceUid: prometheus
      relativeTimeRange: { from: 600, to: 0 }
      model:
        expr: node_systemd_unit_state{state="failed"}
        instant: true
        refId: A
    - refId: C
      datasourceUid: __expr__
      relativeTimeRange: { from: 600, to: 0 }
      model:
        type: threshold
        expression: A
        conditions:
          - evaluator: { type: gt, params: [0] }
        refId: C
  noDataState: OK
  execErrState: Alerting
  for: 1m
  labels: {}
  annotations:
    summary: "{{ $labels.name }} failed on {{ $labels.instance }}"
```

**`noDataState` choice matters and is easy to get wrong.** For a rule layered alongside an
existing host-liveness rule (e.g. a generic `up{job="..."} < 1` "Host Down" rule already
covers total scrape failure), set `noDataState: OK` on the new rule rather than the default
`NoData` — otherwise a Prometheus restart blip or a metric that's legitimately absent
double-fires both the specific rule *and* the host-down rule for the same underlying cause.
Reserve `NoData` for a rule that's the *only* thing watching a given failure mode.

If the notification policy (`policies.yaml`) has no label matchers (a single default route),
any new rule automatically inherits the existing contact point with zero additional routing
config — confirm this before assuming a new rule needs its own policy entry.

## Extending coverage to a host outside the normal scrape/inventory pattern

A host added to Prometheus scraping (`job="node"`) is automatically covered by any rule
written against that job label — no per-host rule authoring needed. Confirm a specific host
is actually a scrape target before assuming coverage:

```bash
curl -s http://localhost:9090/api/v1/targets | python3 -c "
import json,sys
for t in json.load(sys.stdin)['data']['activeTargets']:
    print(t['labels'].get('job'), t['labels'].get('instance'), t['health'])
"
```

**Address a scrape target by a stable name, not a LAN IP, if the host's address can move.** A
target pinned to an IP has no fallback: when the host moves subnet the target simply goes DOWN,
and if the same stale IP is also in inventory and a reverse-proxy config, one address change
breaks config management and a published vhost at the same time. Seen 2026-09-06: a host moved to
a bench subnet and its scrape target, Ansible `ansible_host`, and a Caddy vhost were all pinned
to the old IP — `Host Down` fired correctly for 6 days while the vhost 502'd. A tailnet/MagicDNS
name spanned every state, including a second address change two weeks later. Note this failure
mode is *loud* — the alert worked — which makes it a different class of problem from the silent
gap above, and worth distinguishing when reporting.

A stale DNS record can also mask this during diagnosis: with both a dead LAN A record and a live
tailnet one, `ssh <host>` succeeds by silently failing over to the second address while
`getent hosts <host>` shows only the first. Test the specific address you care about, not the
name.

## A green rule can mean the series doesn't exist, not that the thing is healthy

Three independent faults stack into the same symptom: a rule sitting `Normal` over a volume that
is genuinely filling. Each one hides the others, so check all three — finding one is not finding
the cause. Hit for real 2026-09-12: a PBS chunk store at 80% had **no disk monitoring whatsoever**,
on a fleet whose Grafana looked fully provisioned.

**1. The exporter may be dropping the filesystem entirely.** Debian's
`prometheus-node-exporter` package patches upstream's mount-point exclude regex to also cover
`/mnt` and `/media` — upstream excludes neither. Any data volume under `/mnt` therefore exports
**zero** `node_filesystem_*` series, on every Debian host, with no error anywhere. `ARGS=""` in
`/etc/default/prometheus-node-exporter` reads as "nothing customised", not "two paths silently
dropped" — which is why this survives a config review. Confirmed on Debian 13 / node_exporter
1.9.0.

Don't reason from upstream's documented default. Read what the exporter actually parsed, which
it logs at startup:

```bash
journalctl -u prometheus-node-exporter | grep -o 'mount-points-exclude.*' | tail -1
# Debian:   ^/(dev|proc|run|sys|mnt|media|var/lib/docker/.+|...)($|/)
# upstream: ^/(dev|proc|run/credentials/.+|sys|var/lib/docker/.+|...)($|/)
```

Before blaming the exclusion, rule out a mount-namespace issue — a hardened unit
(`PrivateMounts=yes`, `ProtectSystem=strict`) can freeze the exporter's view of mounts at start
time, which presents identically. Compare the process's own mount table against PID 1's:

```bash
pid=$(systemctl show -p MainPID --value prometheus-node-exporter)
grep <mountpoint> /proc/$pid/mounts   # visible here but absent from /metrics => it's the regex
grep <mountpoint> /proc/1/mounts
```

Restore upstream's behaviour for `/mnt` and `/media` **only**. Keep Debian's broader `run`
exclusion — upstream narrows it to `run/credentials/.+`, and widening it adds a pile of `/run`
tmpfs series nobody wants:

```bash
ARGS="--collector.filesystem.mount-points-exclude=^/(dev|proc|run|sys|var/lib/docker/.+|var/lib/containers/storage/.+)($|/)"
```

The `$` and `|` survive systemd's `EnvironmentFile` parsing unescaped, but confirm via the
parsed-flag log line above rather than trusting that either way. Apply it fleet-wide rather than
only to the host that exposed it, so the next host that gains a data volume is covered by
default instead of repeating the discovery.

**2. The rule may be scoped so it could never match.** A disk rule pinned to `mountpoint="/"`
cannot fire for a data volume even once the series exists — and that pin is a very common
starting point, since it is the obviously-correct scope when every host is just a root disk.
Prefer excluding pseudo-filesystems to enumerating mountpoints:

```promql
(node_filesystem_avail_bytes{fstype!~"tmpfs|vfat|fuse.*|squashfs|overlay|iso9660"}
 / node_filesystem_size_bytes{fstype!~"tmpfs|vfat|fuse.*|squashfs|overlay|iso9660"}) * 100
```

On a Proxmox host also exclude the ZFS dataset mountpoints (`mountpoint!~"/rpool.*"`) — each
container subvol restates the same pool free space, so one pool filling produces a fan of
duplicate alerts for a single condition.

**3. `noDataState: OK` turns an absent series into a pass.** With faults 1 and 2 present this is
what makes the whole thing read healthy rather than unknown. Leaving it `OK` is still usually
right when a separate `Host Down` rule already covers a host going silent — otherwise both fire
for one cause — but know that you are trading a silent gap for less noise, and say so where the
rule is defined.

**Always resolve the rule's own expression against live Prometheus before trusting it**, and read
the returned series rather than the count. This is also the pre-flight that keeps a widened rule
from storming on deploy:

```bash
python3 - <<'EOF'
import urllib.request, urllib.parse, json
SEL='fstype!~"tmpfs|vfat|fuse.*|squashfs|overlay|iso9660",mountpoint!~"/rpool.*"'
expr='(node_filesystem_avail_bytes{%s} / node_filesystem_size_bytes{%s}) * 100' % (SEL,SEL)
u="http://localhost:9090/api/v1/query?"+urllib.parse.urlencode({"query":expr})
for s in sorted(json.load(urllib.request.urlopen(u))["data"]["result"],
                key=lambda s: float(s["value"][1])):
    m=s["metric"]
    print("%-12s %-24s %5.1f%% free%s" % (m.get("instance"), m.get("mountpoint"),
          float(s["value"][1]), "  <<< WOULD FIRE" if float(s["value"][1])<10 else ""))
EOF
```

If the volume you are worried about is not in that output, the rule cannot protect it no matter
what the threshold says.

## Verify a new rule actually fires, don't just trust the YAML

Deploy, then prove it live with a throwaway, harmless failure — don't assume the query
syntax and label matching are correct just because `nginx -t`-equivalent validation passed:

```bash
# A disposable oneshot unit that fails on purpose, on a low-risk host
cat > /etc/systemd/system/alert-rule-test.service <<'EOF'
[Unit]
Description=Throwaway unit to verify an alert rule fires end-to-end
[Service]
Type=oneshot
ExecStart=/bin/false
EOF
systemctl daemon-reload && systemctl start alert-rule-test.service
```

Then poll the rule's live state via the Grafana API until it transitions
`inactive` → `pending` → `firing` (respecting the rule's `for:` duration — don't check once
and give up if it's still `pending`):

```bash
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  http://<grafana-host>:3000/api/prometheus/grafana/api/v1/rules | python3 -c "
import json,sys
for g in json.load(sys.stdin)['data']['groups']:
    for r in g['rules']:
        print(r['name'], '->', r['state'])
"
```

Clean up the throwaway unit afterward (`systemctl reset-failed <unit>` before removing the
unit file — otherwise the failed state can linger in systemd's own bookkeeping even after the
unit file is gone).

## Proving the contact point delivers — Grafana 13.x test API (2026-09-12)

To prove the *notification pipe* separately from rule evaluation, fire the contact point's test.
Grafana 13.2 removed the old endpoint: `POST /api/alertmanager/grafana/config/api/v1/receivers/test`
→ **HTTP 410**. The replacement is k8s-style:

```bash
B=http://<grafana>:3000/apis/notifications.alerting.grafana.app/v1beta1/namespaces/default/receivers
NAME=$(curl -s -u "admin:$PW" "$B" | python3 -c 'import json,sys
for i in json.load(sys.stdin)["items"]:
    if i["spec"]["title"]=="<contact-point-title>": print(i["metadata"]["name"])')
curl -s -u "admin:$PW" -H 'Content-Type: application/json' -X POST "$B/$NAME/test" -d '{
  "integration": {"uid":"<integration-uid>","type":"telegram","version":"v1",
    "settings": {"chatid":"<chat id>","parse_mode":""},
    "secureFields": {"bottoken": true}},
  "alert": {"labels":{"alertname":"delivery test","instance":"grafana"},
            "annotations":{"summary":"Test, no action needed."}}}'
```

- **`metadata.name`** is a base64-ish encoding of the title, not the title and not the integration uid.
- **`secureFields.bottoken: true`** reuses the stored token, so it never travels. Non-secret required
  settings **must** be sent: leaving out `chatid` → 400 "could not find Chat Id in settings". Read it
  from the provisioning file into a variable; don't print it.
- **Auth:** a Viewer-role API token can't run the test; use admin credentials.
- **`{"status":"success"}` means Grafana sent it, not that it arrived.** Confirm with the recipient.

**Log trap:** `logger=ngalert.sender.router … "Sending alerts to local notifier"` means Grafana's
**built-in Alertmanager**, which then routes per `policies.yaml`. It does *not* mean local-only
delivery. Read the notification policy's root receiver before concluding an alert never reaches the
contact point.

## The Grafana package resets `/etc/grafana` permissions on every upgrade

`/var/lib/dpkg/info/grafana.postinst` runs `chown -Rh root:grafana /etc/grafana` and
`find /etc/grafana -type f -exec chmod 640 {} ';'`. A playbook that writes provisioning files `0644`
flip-flops with it: after each upgrade the weekly `ansible_check` shows drift, and a real run restarts
grafana-server only to loosen permissions. Write them `owner: root, group: grafana, mode: '0640'`
(`grafana-alerting.yml`, fixed 2026-10-06 after the 13.2.3 upgrade on 10-01). That is also right for
`contactpoints.yaml`, which carries the bot token.
