---
name: ssh-exposure-audit
description: >-
  Audit and harden SSH exposure on a host — especially an internet-facing VPS — and build a
  check that would have caught it. Covers the sshd first-obtained-wins drop-in trap (a 99-
  file silently loses to 50-cloud-init.conf, and reading sshd_config lies about effective
  state), proving it is safe to disable password auth before doing it, scoping :22 to a
  Tailscale interface behind a deadman revert, and why an external port probe beats a config
  read as a monitoring check. Trigger phrases include "PermitRootLogin", "PasswordAuthentication
  no", "root login refused", "ROOT LOGIN REFUSED FROM", "sshd -T", "sshd_config.d", "50-cloud-init.conf",
  "ufw allow 22 anywhere", "scope ssh to tailscale0", "fail2ban sshd jail", "is ssh open to the
  internet", "harden ssh vps", "ssh exposure check", "lock myself out ssh", "deadman revert
  firewall".
---

# SSH exposure audit and hardening

Built 2026-09-11 after `hermes` (a Vultr VPS holding a live agent's API credentials) was found
accepting **root login with a password from the entire internet**, open for 11 days. It was
found by accident, while adding an unrelated account. Its sibling `dfw` — same role, same
provider — was hardened. The asymmetry was drift, not a decision.

## 1. The trap that makes config-reading useless

`sshd` takes the **first** value it sees for a keyword, and Debian/Ubuntu's stock
`sshd_config` puts `Include /etc/ssh/sshd_config.d/*.conf` near the **top** (line 12 observed).

Consequences, both seen live on the same day:

- A drop-in named `99-hardening.conf` **loses** to `50-cloud-init.conf`. It applies cleanly,
  reports `changed`, and does nothing. **Name hardening drop-ins `10-`.**
- `dfw`'s main `sshd_config` said `PasswordAuthentication no` at line 57 and was overridden to
  `yes` by cloud-init's drop-in. **Auditing by reading the main file would have called that host
  clean while sshd did the opposite.**

So: `sshd -T` is the only truth. Never conclude posture from a file, and never conclude a change
worked because the file was written — assert on `sshd -T` afterwards.

## 2. Earn the password-auth change before making it

Do not disable password auth on a host you cannot console into without first proving nothing
uses it:

```bash
journalctl -u ssh --since "30 days ago" | grep -oE "Accepted [a-z]+" | sort | uniq -c
```

All `publickey` and zero `password` means you are removing attack surface and no working path.
If there are password logins, find out whose before proceeding.

## 3. Earn the firewall change too

Scoping `:22` to a tailnet interface is the only genuinely lockout-capable step. Establish, don't
assume:

```bash
# every successful login, with source, over a long window
journalctl -u ssh --since "30 days ago" \
  | grep -oE "Accepted [a-z]+ for [a-zA-Z0-9_-]+ from [0-9.]+" \
  | awk '{print $4, $6}' | sort | uniq -c | sort -rn
```

Field offsets matter (`$4` user, `$6` IP) — a wrong offset produces confident nonsense like
`2596 for from`, which is obviously broken only if you read the output.

Then classify every source. On the real run this surfaced one non-tailnet IP with 10 root logins
that would have been cut off. It turned out to be the owner's own key during the host's build
window (tailscaled started partway through it, visible in `journalctl -u tailscaled | head`), so
it was historical — but that had to be *checked*, not assumed, and the owner's "I only connect
over the tailnet" was sincere and still incomplete.

Also confirm which interface your own session actually arrives on, since name resolution may be
sending you over the tailnet already:

```bash
ss -tnp state established '( sport = :22 )'
```

## 4. Apply in stages, with a deadman

Order matters: additive first, lockout-capable last, each verified before the next.

1. **fail2ban** — pure addition. Put the whole tailnet in `ignoreip` (`100.64.0.0/10`) so fleet
   automation can never ban itself out of a host it is trying to repair.
2. **sshd** — `PasswordAuthentication no`, `PermitRootLogin prohibit-password`. Wrap in
   `block`/`rescue` around a full `sshd -t`, so a bad config removes itself rather than leaving
   sshd unable to start on next boot. **`reload`, not `restart`** — established sessions survive.
3. **ufw** — add the scoped rule *before* deleting the open one, so `:22` is never momentarily
   unreachable.

Arm a deadman around step 3:

```bash
sudo systemd-run --on-active=10min --unit=ufw-ssh-deadman /usr/sbin/ufw allow 22/tcp
# ... apply the change, then verify a NEW connection (-o ControlPath=none, so you are not
# riding a multiplexed socket that was already open) ...
sudo systemctl stop ufw-ssh-deadman.timer
```

Verify every consumer before disarming, not just your own shell: other automation accounts, a
controller's dispatch path, any monitoring user. Then confirm the public side is actually closed.

## 5. The check that would have caught it

The reason this sat open for 11 days is that nothing looked. When adding the check:

- **For hosts you do not have root on** (an un-inventoried VPS), probe `:22` from the public
  internet instead of reading config. Reachability is what matters, and unlike config-reading it
  cannot be fooled by §1's ordering trap.
- **For hosts you do have root on**, read `sshd -T`. Report unreachable hosts as *not assessed*,
  never `ok` — a sleeping host must not read as hardened.
- **Give the probe a control.** This test's failure mode is silence: lose the WAN path and every
  `:22` reads "closed", producing a clean report describing an exposure never measured. A port
  open by design must read open, or withhold the per-host results as "could not assess".
- **Prove the check can fail** before trusting it — point the probe at a known-open port and
  confirm it reports `fail`. An `ok` from a check that has never failed is not evidence.
- Put it in a category your *daily* job runs, not only the weekly one.

## 6. Small things that bit

- A dedicated sudo-capable account beats flipping `PermitRootLogin` to admit one key: revocable
  and attributable on its own, and it leaves a host-wide policy alone. If root SSH is refused,
  the journal says `ROOT LOGIN REFUSED FROM <ip>` — that means the key matched and policy
  declined, i.e. the key install was fine.
- `/etc/ssh/sshd_config` is often `0600`, so a non-root audit account reading it gets an empty
  grep — indistinguishable from "the setting isn't there". Check readability before believing an
  empty result.
- Validate sudoers with `visudo -c` while you still have a working session.
