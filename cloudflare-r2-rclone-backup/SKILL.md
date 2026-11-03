---
name: cloudflare-r2-rclone-backup
description: This skill should be used when setting up a nightly/periodic offsite backup of a directory or archive (Proxmox Backup Server datastore, database dumps, photo libraries, any local directory) to a Cloudflare R2 bucket via rclone's S3-compatible API, or when debugging an existing rclone-to-R2 sync job — including a sync that's slow/stalled on listing, needs recoverable soft-deletes, or hits unexpected 403s on a new destination path. Trigger phrases include "offsite backup to R2", "rclone sync to Cloudflare", "back up to R2", "R2 rclone", "unknown flag: --delete" (rclone), "Can't set -v and --log-level", "501 NotImplemented" from an S3/R2 sync, "create R2 access key", "rclone --stats-one-line format", "parse rclone transfer stats", "how many files did rclone sync", "rclone --fast-list", "sync stuck at 0 bytes", "R2 object versioning", "R2 bucket lifecycle rule", "rclone --backup-dir", "R2 token 403 new prefix", "AllAccessDisabled R2".
---

# Cloudflare R2 + rclone offsite backups

Use rclone to mirror a local directory (backup archive, datastore, photo library, anything) to a
Cloudflare R2 bucket on a schedule. This is a **host-side** pattern — the sync runs as a systemd
timer on the machine that already has the data, not as a Cloudflare Worker. Workers have
per-invocation subrequest/CPU-time limits that make them a poor fit for pushing GBs of binary data
through; R2's role here is just the storage destination + a scoped credential, not compute.

## 0. Install a real, current rclone — never the distro package

**Don't `apt install rclone` (or the equivalent on any distro).** Debian/Ubuntu package
repositories lag upstream by years — this is exactly how a 2022-era `v1.60.1-DEV` build ended up
running an active production job, missing the `--s3-no-check-bucket` flag this skill depends on
(see the gotcha in §3) and giving unhelpfully vague errors for other R2-specific quirks. Install a
pinned, current release directly instead:

```bash
RCLONE_VERSION="1.74.4"  # check https://downloads.rclone.org/version.txt for current stable
curl -sO "https://downloads.rclone.org/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-amd64.zip"
unzip -q -o "rclone-v${RCLONE_VERSION}-linux-amd64.zip"
cp "rclone-v${RCLONE_VERSION}-linux-amd64/rclone" /usr/bin/rclone
chmod 755 /usr/bin/rclone
```

If deploying via Ansible, pin the version as a var and guard the download with a check against
`rclone version`'s current output so re-runs are idempotent (skip if already current) — see the
homelab `r2-backup-install.yml` playbook for a working reference. `rclone selfupdate` is not a
reliable escape hatch once already on a very old version — it can fail with `invalid hashsum
signature` (its own signing-key verification logic is itself outdated).

## 1. Create the bucket and a scoped credential

- **Bucket**: create via the Cloudflare dashboard, `wrangler`, or an R2-bucket-creation MCP/API
  tool if one is available. Pick a bucket name distinct from any existing buckets in the account
  (don't collide with an unrelated bucket's namespace).
- **R2 access key (S3-compatible Access Key ID + Secret Access Key)**: this is **not** the same
  thing as a normal Cloudflare API token, and a normal Cloudflare API token scoped to
  R2/KV/Pages *object* operations generally **cannot mint one** — that requires the separate,
  more sensitive "API Tokens Edit" permission. Don't broaden an existing automation token's
  scope just to bootstrap this. Instead, create it via the dashboard: **R2 → Manage API Tokens
  → Create API token**, scoped to:
  - Permission: **Object Read & Write** (not Admin Read & Write — that's for bucket-level ops
    like CORS/lifecycle rules, which this job doesn't need).
  - Specify bucket: the one bucket this job targets, not "Apply to all buckets."
  - Copy the three values it shows **once**: Access Key ID, Secret Access Key, and the S3
    endpoint (`https://<account-id>.r2.cloudflarestorage.com`).
- Store these three values in a root-owned, mode-`600` env file on whatever host runs the sync
  (or on the Ansible controller if deploying via Ansible — see §4). Never commit them, never put
  them in `--extra-vars` on a CLI (shell history exposure).

## 2. Configure rclone via environment variables (no rclone.conf needed)

rclone supports configuring a remote purely through env vars, which avoids ever writing an
`rclone.conf` file containing secrets. Split these across two places by whether they ever change:

**Constants — set these directly in the wrapper script (`export` at the top), never in the
credentials file:**
```bash
export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
```

**Actual secrets — these belong in the root-owned 600 credentials env file, since they're what
actually rotates:**
```
RCLONE_CONFIG_R2_ACCESS_KEY_ID=<access key id>
RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=<secret access key>
RCLONE_CONFIG_R2_ENDPOINT=<https://account-id.r2.cloudflarestorage.com>
```

**Why split it this way**: a human hand-editing the credentials file during a rotation (pasting
in just the two rotated key lines) can accidentally drop an adjacent, unrelated line without
realizing it — confirmed happening for real *three separate times* in one incident. Keeping
`TYPE`/`PROVIDER` out of that file entirely, `export`ed in the script where they can't be
silently dropped by an edit to a different file, closes the failure class structurally instead
of just making it faster to diagnose. `export` in the script always wins regardless of what the
sourced credentials file does or doesn't contain.

**Do not set `RCLONE_CONFIG_R2_ACL`** (an earlier version of this skill recommended
`RCLONE_CONFIG_R2_ACL=private` — that was wrong, see the gotcha below). R2 has no concept of
per-object ACLs at all; access is controlled entirely at the bucket/API-token level. Leave this
var unset.

This defines a remote named `R2` (rclone lowercases the env var segment to the remote name), so
commands reference it as `r2:bucket-name`.

**If `RCLONE_CONFIG_R2_TYPE` does end up missing** (e.g. an older deployment that hasn't adopted
the split above yet), the symptom is rclone failing *instantly*, before any network call —
`CRITICAL: Failed to create file system for "r2:...": didn't find section in config file ("r2")`
— which looks like a config/credential problem but has nothing to do with whether the new key is
valid. Check `cut -d= -f1 <file>` (field *names* only — safe, no secret values) first whenever a
fresh rotation immediately fails, before assuming the new key itself is bad.

## 3. The rclone command — three real flag gotchas

The correct sync command:

```bash
rclone sync "${SOURCE_DIR}" "r2:${BUCKET}" --checksum --no-update-modtime --s3-no-check-bucket --log-file="${LOG_FILE}" --log-level INFO
```

`--s3-no-check-bucket` is required whenever the token is scoped to Object Read & Write only
(the correct choice per §1) rather than Admin — see the gotcha below for why omitting it fails
almost every write silently.

Gotchas that will bite on the first run if not accounted for:

- **`--delete` is not a valid flag for `rclone sync`** — it's a hard error (`unknown flag`), not
  a no-op. `sync` already deletes destination files absent from source *by default*; `--delete`
  (as `--delete-before/-during/-after`) is a `copy`/`move`-only option for opting *into* deletion
  there. If migrating a command from `copy` to `sync`, drop this flag.
- **`-v` and `--log-level` are mutually exclusive** (`Can't set -v and --log-level`). Use
  `--log-level INFO` (or `DEBUG`) alone when a `--log-file` is already being written to.
- **R2 returns `501 NotImplemented` when rclone tries to fix up an object's modification time
  after transfer via a self-copy** (a metadata-only `CopyObject` to the same key) — R2's S3
  implementation doesn't support that call. Symptom: the sync log shows dozens/hundreds of
  `Failed to copy: NotImplemented` errors on files whose *content* transferred fine, then
  rclone's built-in retry logic (`Attempt 2/3 succeeded`) quietly papers over it into an eventual
  exit 0 — easy to miss since the job technically "succeeds," just noisily and with wasted
  retries on every single run. Fix: add `--no-update-modtime` (skips the modtime-fixup call
  entirely) and `--checksum` (compares files by hash instead of size+modtime, sidestepping the
  need for accurate remote modtimes at all — also just a better comparison strategy when the
  source data is content-addressed, e.g. backup chunk files named by their own hash).
- **`RCLONE_CONFIG_R2_ACL` should still never be set** (R2 has no per-object ACL concept at all;
  see §2) — but don't stop debugging if removing it doesn't fix a persistent failure. It didn't,
  in the incident below; it was a real thing to fix, just not *the* thing.
- **The actual, much larger root cause of persistent `501 NotImplemented` / `AccessDenied` /
  `SignatureDoesNotMatch` errors on real transfers: an old rclone binary plus a least-privilege
  (Object-only, not Admin) API token.** Since some rclone version, the S3 backend issues a
  `CreateBucket` preflight call before writing — intended as a harmless idempotent
  "ensure destination exists" check, since on real AWS S3 calling `CreateBucket` on a bucket you
  already own typically just succeeds. A token scoped to Object Read & Write only (the correct,
  least-privilege choice per §1 — deliberately *not* Admin) has no permission to call
  `CreateBucket` at all, so R2 correctly denies it — and rclone treats that preflight failure as
  fatal, **never even attempting the actual PUT**. Symptom: the sync log fills with `Failed to
  copy` errors (the exact wrapper text varies by rclone version — an ancient `v1.60.1-DEV` gave a
  bare `NotImplemented`/`AccessDenied` with no detail; `v1.74.4` gives the much clearer `failed to
  prepare upload: operation error S3: CreateBucket, ... AccessDenied`), while `rclone lsf`/`rclone
  size` against the same remote work fine (list/read operations don't hit this path at all) —
  don't let read access working convince you the credential itself is broken; it's the preflight
  write-side call. rclone's own retry logic can look like it's "working around" this
  intermittently over many nights (each `sync` run re-attempts every unsynced object, so some
  eventually go through via some other path/order), which is what let this masquerade as an
  eventual-exit-0 job for days in the homelab PBS incident below rather than failing loud and
  immediate.

  **Fix — both parts, don't stop at just one:**
  1. Add **`--s3-no-check-bucket`** to the `rclone sync` command — this is the flag that actually
     skips the `CreateBucket` preflight, and is exactly the intended flag for "the bucket already
     exists and my token can't create one anyway."
  2. **Check the rclone version isn't ancient** (`rclone version`) — a multi-year-old build can
     have different/buggier error handling around this exact path even with the flag present in
     principle. Compare against `curl -s https://downloads.rclone.org/version.txt` for current
     stable; if it's more than a couple major versions behind, download and replace the binary
     directly (`curl -sO https://downloads.rclone.org/v<version>/rclone-v<version>-linux-amd64.zip`,
     unzip, `cp rclone /usr/bin/rclone`) rather than relying on `rclone selfupdate`, which can fail
     with `invalid hashsum signature` on a sufficiently old starting version (its own signing-key
     verification logic is itself outdated).

  Isolate this class of error from a real credential/permissions problem by testing with a second,
  independent S3 client (`apt-get install -y awscli`, then `aws s3api put-object --endpoint-url
  ...`) against the exact same bucket/token — if it gives a *different* error than rclone
  (`SignatureDoesNotMatch` from a modern awscli defaulting to trailer-checksum streaming uploads,
  vs. rclone's `CreateBucket`-preflight `AccessDenied`), that's a strong signal that the several
  tools are each hitting their own distinct R2-compatibility quirk, not that the credential itself
  is bad — `rclone lsf`/`aws s3api list-objects-v2` both succeeding on the same token confirms the
  key pair and its permissions are genuinely fine.

  Caught in the homelab PBS job 2026-07-19: the destination bucket's real size (16GB) didn't match
  the ~93GB source, and 9,325 `Failed to copy` errors were spread across 7 nights of logs once
  actually grepped for. Two credential rotations and the ACL removal above were tried first and
  didn't fix it (worth doing regardless, but they were solving a different, smaller problem);
  isolating with `awscli` and finally reading rclone's own (newer, clearer) error text is what
  actually found it. After the fix: a full sync of the entire backlog completed in ~52 minutes
  with zero errors.
- **Diagnosing a rclone/R2 auth or permissions error with `-vv` prints the resolved access key ID
  and secret access key in plaintext** (`DEBUG : Setting access_key_id="..." ... from environment
  variable`) — there's no flag to suppress just that field. If you need verbose output to debug a
  failing transfer, prefer `-v` over `-vv` and grep the output for the specific error rather than
  dumping full DEBUG-level config resolution; if `-vv` is genuinely needed, treat the credential
  as burned afterward and rotate it (dashboard-only — see §1, a scoped token generally can't mint
  its own replacement) rather than trusting that only you saw the transcript.

## 4. Wiring: systemd oneshot + timer (Ansible-managed example)

Pattern used successfully for a Proxmox Backup Server → R2 job:

- A bash wrapper script (`/opt/<job>/sync.sh`) runs the rclone command, checks the exit code,
  and sends a short success notification or a failure notification with a log tail (see §5).
- A systemd **oneshot service** (`EnvironmentFile=` pointing at the root-owned 600 env file,
  `ExecStart=` the wrapper script) plus a **timer** (`OnCalendar=`) scheduled to run comfortably
  after any upstream job the source data depends on (e.g. 30 min after a nightly backup job
  finishes, not immediately after/concurrent with it).
- If deploying via Ansible from a separate controller host: read the R2 credential file with
  `lookup('file', '/path/on/controller')` in playbook vars (this runs on the controller, not the
  managed host) and extract individual values with `regex_findall('KEY=(.*)')` rather than trying
  to build a dict from parsed pairs — Jinja's `dict()` global is Python's real `dict()` and does
  accept an iterable of pairs, but per-key `regex_findall` extraction is simpler to read and
  debug than constructing an intermediate list-of-tuples.
- Remember to explicitly create the destination config directory (e.g. `/root/.config`) before
  writing the env file into it — a fresh minimal host image may not have it yet, and `copy`
  fails with "Destination directory does not exist" rather than creating it implicitly.
- **Rotate the sync log.** `--log-file` appends forever with no built-in cap — over months this is
  a slow-motion repeat of the exact "silent capacity drain" failure mode this whole skill is
  about, just on the OS disk instead of the datastore. A basic `/etc/logrotate.d/<job>` (`weekly`,
  `rotate 8`, `compress`, `missingok`, `notifempty`) is cheap insurance, not optional polish.
- **A credential rotated by hand directly on the target host will be silently reverted by the
  next Ansible run**, if the playbook writes the env file from a var sourced off a credentials
  file on the *controller* (the `lookup('file', ...)` pattern above) — Ansible has no idea the
  live file was touched out-of-band, and a `copy`/`template` task always treats the controller's
  version as authoritative, overwriting whatever's actually running. Hit this directly rebuilding
  this exact PBS job 2026-07-19: rotated the R2 key by hand on `pbs` mid-incident, then an
  unrelated `ansible-playbook` re-run (testing an idempotency fix) silently reverted it back to
  the old, already-revoked key, breaking the job again. If a credential is ever rotated manually
  as a stopgap, **update the controller's source file in the same breath** — don't treat the
  manual fix as done until the thing Ansible would regenerate from matches it too.

## 5. Verify for real, not just "the job exited 0"

A clean exit code is not proof of a working backup. Prove it:

- **Pull a file back down** (`rclone copyto r2:bucket/path /tmp/check`) and diff/checksum
  (`sha256sum`) it against the source file — confirms round-trip integrity, not just that
  upload requests didn't error.
- **Actually trigger a test notification** and check the provider's API response (e.g.
  Telegram's `sendMessage` returning `{"ok":true,"result":{"message_id":...}}`) rather than just
  trusting a `curl` exit code of 0, which only proves the HTTP request completed, not that the
  message was accepted/delivered.
- **Have the wrapper script itself distrust exit 0.** rclone's own top-level retry logic
  (`--retries`, default 3) can produce a clean `exit 0` on a run that still logged real errors
  along the way — this is precisely what let the `CreateBucket`/ACL incident above run "green"
  for 6 nights straight. Don't gate the success/failure notification on exit code alone: record
  the log's line count before the run, then after, grep only the *new* lines for `ERROR` and send
  a distinct "succeeded but logged N errors, check the log" notification if any are found, rather
  than folding that case into either a false all-clear or the hard-failure path. See the homelab
  `r2-backup-sync.sh.j2` template for a working `LOG_START_LINE`/`tail -n +N` implementation.

## 6. Parsing `--stats-one-line` for a human-readable "what was synced" summary

If a notification/report needs to say *what* actually moved (bytes transferred, objects
copied/deleted) rather than just pass/fail, add `--stats-one-line` to the sync command so each
periodic (and final) progress line collapses to one line instead of a multi-line block — easier
to `grep`/`tail -n 1` reliably.

**The resulting line has no `Transferred:`/`Checks:`/`Elapsed time:` labels** (confirmed live on
rclone `v1.74.4`, 2026-07-20) — despite that being the format of the *unflagged* default
multi-line stats block, which does carry those labels. `--stats-one-line`'s actual format is just
the bare numbers, e.g.:
```
2026/07/20 11:21:20 INFO  :     2.464 GiB / 2.464 GiB, 100%, 364.458 KiB/s, ETA 0s
```
Don't write a parser assuming the labeled format is still there under `--stats-one-line` — it
silently matches nothing and any regex keyed on `Transferred:.*Elapsed time:` will just come back
empty. Build the summary instead from three independent signals in the log, each simple to grep:
- The bare stats line above → `grep -oE '^[0-9.]+ ?[KMGT]?i?B'` after stripping the log's
  date/level prefix, for a total-bytes figure.
- `grep -c 'Copied (new)'` → count of new objects actually written this run.
- `grep -c ': Deleted$'` → count of objects removed this run (propagated upstream pruning).
- **Correction (2026-07-23):** a run with nothing to do does **not** reliably log a distinct
  `There was nothing to transfer` line under `--stats-one-line` — confirmed live, a true no-op
  run still just prints a `0 B / 0 B, -, 0 B/s, ETA -` stats line like any other. Don't gate the
  "no changes" message on that string; judge it from the copied/deleted counts being both zero
  instead.
- **Bash gotcha when joining multiple summary fragments** (e.g. "X of chunks + Y of metadata"
  from a multi-pass sync): `JOINED=$(IFS=' + '; echo "${PARTS[*]}")` looks like it joins on the
  full `' + '` string but bash only honors the **first character** of a multi-char `IFS` when
  expanding `"${array[*]}"` — it silently collapses to a single-space join instead. Build the
  joined string with an explicit loop (`for p in "${PARTS[@]}"; do ...`) instead of relying on
  `IFS`/`[*]` for anything longer than one character.

See the homelab `r2-backup-sync.sh.j2` template (and the `homelab-terminal-report-delivery`
skill, whose report emails this feeds) for a full working implementation, including the
`sed`/`grep -oE` chain that strips the log prefix and extracts just the byte figure.

## 7. Platform gotchas found running this in production (2026-07-23)

- **A source tree sharded into many subdirectories (tens of thousands) needs `--fast-list`, or
  listing alone can take many minutes.** Without it, rclone lists one directory at a time — each
  a separate round-trip LIST call to R2. A PBS datastore's `.chunks/` dir (65,536 subdirs, its
  standard 4-hex-char chunk sharding) stalled a sync at ~0% CPU for 7+ minutes on listing alone
  before `--fast-list` was added (R2's paginated `ListObjectsV2` instead of per-directory calls).
  Low CPU + long wall-clock time with no error is the tell — it's not hung, it's network-latency
  bound on a huge number of small round trips.
- **R2 has no S3-style object versioning.** `PutBucketVersioning` is explicitly unimplemented
  (confirmed via `/r2/api/s3/api/` docs) — don't assume `sync`'s deletes are recoverable via a
  bucket setting the way they would be on real AWS S3. If sync-mode's immediate mirroring of
  local deletes is a concern (a bad local prune propagating straight to the offsite copy with no
  recovery window), the working alternative is rclone's own `--backup-dir <path>`: instead of
  deleting/overwriting at the destination, it moves the prior object into a dated path first.
- **R2 *does* support S3-style bucket lifecycle rules** (age + prefix-based object expiration —
  `PutBucketLifecycleConfiguration` is implemented), which pairs well with `--backup-dir` as a
  server-side, zero-maintenance cleanup for that soft-delete path:
  ```bash
  npx wrangler r2 bucket lifecycle add <bucket> <rule-name> <prefix>/ --expire-days 30 --force
  npx wrangler r2 bucket lifecycle list <bucket>   # verify it took
  ```
  This runs entirely on Cloudflare's infrastructure — no cron job of your own to keep alive or
  silently break. If relying on it, still add a periodic check (don't just assume server-side
  automation can't fail) that the oldest object under the soft-delete prefix stays inside the
  configured window.
- **When the sync host and the source-data host run in different system timezones, a
  same-clock-looking `OnCalendar=` schedule can silently fire *before* the upstream job it's
  supposed to follow.** Caught 2026-07-24: `pbs` (running the sync) is `Etc/UTC`, `pve` (running
  the nightly vzdump jobs the sync depends on) is `America/Chicago`. The vzdump schedule
  (`03:00–03:30` in `pve`'s local time) reads like "early morning," and the sync timer's
  `OnCalendar=*-*-* 03:30:00` (in `pbs`'s UTC clock) *looks* like it lines up — but `03:30 UTC` is
  `22:30 CDT the previous day`, ~4.5h before vzdump even starts. The sync ran "successfully" every
  night for over a week, just always one day stale, because a clean exit code says nothing about
  *which* night's data got copied. Fix: convert the upstream job's schedule to the sync host's
  timezone before picking `OnCalendar=`, not just eyeball the two numbers side by side — and add
  a real buffer (not the minimum gap) since DST changes shift standard-time hosts by an hour
  relative to hosts in a fixed zone like UTC twice a year.
- **R2 API tokens/access keys can be scoped to specific object prefixes**, not just the whole
  bucket. A token that works fine for every path it was originally granted starts throwing
  `403 Forbidden` (on writes/HEAD) or `AllAccessDisabled` (on listing) the moment it touches a
  **new** prefix that didn't exist at token-creation time — this looks exactly like a broken
  credential but isn't; the same token works fine against its originally-granted paths. Before
  adding a new destination path (like a `--backup-dir` target) to an existing sync job, probe it
  with a disposable test write first (`rclone copyto` a throwaway file to the new prefix) rather
  than assuming an existing working credential covers it — confirmed live: writes to `.chunks/`,
  `ct/`, `vm/` (original grant) succeeded while an identical write to a brand-new `.attic/` prefix
  403'd with the *same* credential, same bucket, same command.

## Hold the distro rclone package once a pinned binary shares its path (2026-10-06)

Installing a pinned rclone release straight to `/usr/bin/rclone` (per §0 above) does not protect it from a **later** `apt upgrade` -- if the Debian `rclone` package is or becomes installed, apt owns that same path, and a routine upgrade silently overwrites the pinned binary with the distro's (years-old) build, undoing the whole point of pinning. Run `apt-mark hold rclone` right after installing the pinned binary so apt refuses to touch it. Separately, make sure the read-only task that checks the installed rclone version for drift also runs under `ansible-playbook --check` (`check_mode: false` -- see the ansible-check-mode-verification-tasks pattern); otherwise the weekly `ansible_check` drift sweep is blind to a pin that got silently reverted between real runs. homelab-ansible `db505f1`, `954162e`.

## Env-var-only remotes: silence "Config file not found" (2026-10-11)

A script that defines its remote only through `RCLONE_CONFIG_<NAME>_*` env vars still makes rclone log `NOTICE: Config file "…/rclone.conf" not found - using defaults` on every call, and a per-file loop floods its log with it. Set `RCLONE_CONFIG=/dev/null` (or `--config /dev/null`): rclone keeps the config in memory, the notice disappears and the env remote still resolves. Verified with v1.75.2 (`mac-tools/sdcard-r2-sync` in the homelab repo).
