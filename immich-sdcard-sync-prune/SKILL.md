---
name: immich-sdcard-sync-prune
description: This skill should be used when building or debugging a macOS launchd automation that uploads a camera SD card's contents to Immich on insert (via @immich/cli), or when building a workflow to prune Immich assets that were deleted from their source card/folder after import. Covers the Immich CLI's non-obvious API key permission requirements (album.create vs albumAsset.create, the "Found 0 new files" scoped-key bug), launchd's StartOnMount trigger and its missing-Homebrew-PATH gotcha, parsing `immich upload -j` JSON output, the Immich bulk-delete (trash vs permanent) endpoint, and — critically — why a delete/prune workflow across multiple source cards feeding one album must scope its diff by a per-source manifest rather than diffing the whole album, or a second card mounted alone will make every surviving photo from the first card look deletable. Trigger phrases include "sd card to immich", "immich cli upload", "@immich/cli permissions", "albumAsset.create", "Found 0 new files and 0 duplicates", "launchd StartOnMount", "immich upload -j json output", "immich bulk delete trash", "DELETE /api/assets force", "prune immich assets deleted from card", "multiple sd cards same immich album".
---

# Immich SD card auto-sync + safe prune

Pattern for automatically uploading a camera's SD card to Immich when it's inserted on a Mac, plus
a companion tool to safely prune Immich assets after the user deletes their local originals. Built
for a Canon SD card reader on macOS; the mechanics generalize to any camera/reader that mounts as a
normal volume with a `DCIM` folder.

## Architecture

1. **`immich upload` via `@immich/cli`** (`npm install -g @immich/cli`) — not `immich-go`, not the
   deprecated Docker-based CLI. Auth via `immich login-key <server-url> <api-key>`, which writes
   `~/.config/immich/auth.yml`. That file is created world-readable by the CLI —
   [immich#6911](https://github.com/immich-app/immich/issues/6911) — `chmod 600` it immediately.
2. **A macOS `launchd` LaunchAgent with `StartOnMount`** fires the sync script on *any* volume
   mount. The script itself filters for volumes with a top-level `DCIM` folder rather than matching
   a specific volume name/label — camera-formatted cards often mount with a generic name like
   `Untitled`, and the name isn't stable across reformats anyway.
3. **Dedup two different ways for two different purposes:**
   - A `synced.log` state file keyed by **Volume UUID** (`diskutil info "$vol" | grep "Volume UUID"`)
     stops the same already-fully-synced card from re-triggering a full re-upload on every
     incidental `/Volumes` change while it sits mounted.
   - Immich's own upload does checksum-based dedup server-side — re-running `upload` against a
     partially-imported card is always safe and cheap (reports `duplicates`, doesn't re-transfer).

## The permission set — and its sharp edges

Minimum working set for `upload -r -A <album>`: `asset.read`, `asset.upload`, `album.read`,
`album.create`, `user.read`. Two things aren't obvious and aren't documented together anywhere:

- **A too-narrow key doesn't error — it silently no-ops.** [immich#21456](https://github.com/immich-app/immich/issues/21456)
  and [immich#22543](https://github.com/immich-app/immich/issues/22543): a scoped key can make the
  CLI report `Found 0 new files and 0 duplicates` instead of uploading, with no error. If that
  happens, it's a permissions problem, not a "nothing to upload" result — don't reach for
  `--skip-hash` as a workaround, since that disables the checksum dedup that makes the whole
  workflow safe to re-run. Widen the key's scope instead.
- **Adding an asset to an album needs `albumAsset.create` — a separate permission from
  `album.create`.** Creating the album and uploading the asset both succeed with just
  `album.create`; the CLI then throws `403: Missing required permission: albumAsset.create` when it
  tries to link the two. Not mentioned in Immich's own docs as of this writing — found by running
  a real (non-dry-run) upload and reading the actual error, which `--dry-run` alone won't surface
  since dry-run doesn't exercise the album-link call.
- **The CLI matches albums by exact name string.** If a human renames the album in the Immich UI
  after the script has been using a different name, the next sync creates a *new*, separate album
  instead of finding the renamed one. Keep the album name in the script and the album's actual name
  in Immich in sync deliberately.

## launchd's PATH doesn't include Homebrew

`launchd`'s default environment is `PATH=/usr/bin:/bin:/usr/sbin:/sbin` — no `/opt/homebrew/bin`.
Since `immich` is a Node shebang script (`#!/usr/bin/env node`), a script invoked via `StartOnMount`
fails with `env: node: No such file or directory` even though the same command works fine typed
into a normal Terminal (which inherits your shell's PATH). Fix: `export PATH="/opt/homebrew/bin:$PATH"`
explicitly at the top of any script launchd will run, and hardcode the binary's absolute path
(`/opt/homebrew/bin/immich`) rather than relying on `which`/bare `immich` resolving.

```xml
<key>StartOnMount</key>
<true/>
```
is the whole trigger — no volume-name filtering at the launchd level, no `WatchPaths` needed. Load
with `launchctl bootstrap gui/$(id -u) <path-to-plist>`. Test the whole trigger chain without a
real card using a disk image: `hdiutil create -volname TEST -srcfolder <dir-with-DCIM> -format UDZO
test.dmg && hdiutil attach test.dmg` — this fires `StartOnMount` for real, end to end.

## Building a manifest from `upload -j`

`immich upload -r -j -A "<album>" <path>` prints normal progress text to stdout, then a single JSON
object, then more status lines — the JSON is sandwiched in the middle, not cleanly at the end. Parse
it by finding the first `{` and using `json.JSONDecoder().raw_decode(text[idx:])`, which correctly
consumes just the object and ignores trailing garbage. Shape:

```json
{
  "newFiles": ["/local/path/IMG_0001.JPG"],
  "duplicates": [{"id": "<asset-uuid>", "filepath": "/local/path/IMG_0002.JPG"}],
  "newAssets": [{"id": "<asset-uuid>", "filepath": "/local/path/IMG_0001.JPG"}]
}
```

Both `newAssets` and `duplicates` give `{id, filepath}` — record both into a persistent manifest
(asset ID + filename + **source identity**, see below). Both cases legitimately "belong" to this
sync: a duplicate still means this card is a valid source for the album-membership that upload run
established.

## The core safety issue: scope prune diffs by source, not by album

The tempting naive prune approach: list everything in the Immich album, list what's still on the
currently-mounted card, delete anything in the album but not on the card. **This is only safe if
exactly one source (one card) has ever fed that album.** The moment a second card contributes to
the same album — a spare/replacement card, a different camera — mounting card #2 alone and running
that diff makes every surviving photo from card #1 (sitting in a drawer, not mounted) look "not on
the card" and flags the *entire first card's kept photos* for deletion. This is a real, silent
data-loss risk if the diff's output is trusted without a full manual review of every filename.

The fix: maintain a manifest (`volume_uuid, asset_id, filename, synced_at` — TSV is fine) written by
the sync script on every run, and have the prune tool scope its diff to **only the rows matching the
currently-mounted card's own Volume UUID**. A second card's prune run then structurally cannot see,
and cannot touch, the first card's manifest rows — verified by directly calling the manifest-lookup
function with a fabricated UUID and confirming it returns zero rows, rather than trusting the logic
by inspection alone.

If a prune tool like this is being retrofitted onto assets that predate the manifest, backfill it:
compute `(all current album assets) − (assets already confirmed absent from the card)` = the set
that's demonstrably still present under a matching filename right now, and write those in as
manifest rows for the currently-mounted card's UUID before relying on the tool going forward.

## Deleting: trash vs. permanent

`DELETE /api/assets` with body `{"ids": [...], "force": false}` → soft delete (moves to trash,
recoverable within Immich's retention window). `force: true` → permanent, immediate. **Always use
`force: false`** for anything automation-driven; a human can empty the trash themselves later if
they're sure. Requires the `asset.delete` permission on the API key (deliberately not included in
the baseline upload-only key — add it as a separate, explicit step only when building the prune
capability, and tell the user exactly what permission is being added and why).

## Listing album contents needs the search endpoint, not the album endpoint

`GET /api/albums/{id}` does **not** return the member assets by default in current Immich versions
(no `assets` key in the response, and `?withoutAssets=false` doesn't change that as of this
writing). To list an album's assets with filenames, use `POST /api/search/metadata` with
`{"albumIds": ["<id>"], "size": 1000, "page": N}` and follow `assets.nextPage` until it's null.

## Testing without waiting on a real large upload

A multi-GB real card upload can take an hour+; don't block iteration on it. Validate the trigger
chain and script logic with a small synthetic disk image first (see above), and validate a real API
key's permissions with a tiny real (non-dry-run) upload of a throwaway generated image
(`sips -s format jpeg <any .heic> --out test.jpg`) into a clearly-named disposable test album —
delete it via the trash endpoint once confirmed. Watch for checksum collisions between multiple
test files generated the same way from the same source image — Immich dedups by content, so two
"different" test files with identical bytes will silently resolve to the same underlying asset,
which can leak a test asset into the wrong album as a side effect (harmless, but confusing until
traced back to the matching checksum).

## Successor (2026-10-07): SD card → R2 directly, and the macOS privacy trap it hit

Immich was decommissioned; the camera backup now goes straight to R2 (`mac-tools/sdcard-r2-sync/` in the homelab
planning repo: per-file single-part upload, R2 MD5 verified before the manifest row, no deletes, Keychain credentials).

**A launchd job can't read a removable volume.** A LaunchAgent running `/bin/bash` on `StartOnMount` can list
`/Volumes`, but `find /Volumes/<card>/DCIM` fails with `Operation not permitted` (Removable Volumes privacy). A
background process gets no "Allow?" prompt, so it is refused silently. Fix without granting Full Disk Access to bash:
wrap the script in a tiny app (`osacompile -o "~/Applications/SD Card Backup.app" -e 'do shell script "…"'`, ad-hoc
`codesign`, `LSUIElement`), have the LaunchAgent `open -g -j` the app, and open it once interactively so macOS asks
the app for removable-volume access. **Also:** a run that examined zero files must never report success. The first
version said "0 backed up, 0 already safe. Safe to wipe" on a card it couldn't read.
