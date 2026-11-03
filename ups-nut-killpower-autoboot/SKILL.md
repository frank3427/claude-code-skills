---
name: ups-nut-killpower-autoboot
description: >-
  Make a single always-on Linux host (Proxmox or bare metal) shut down cleanly on a UPS outage
  and boot again by itself when power returns, including when mains comes back before the battery
  is flat. Covers NUT (usbhid-ups, upsmon, POWERDOWNFLAG + the systemd system-shutdown hook), the
  BIOS "State After G3 = S0" half, picking the low-battery thresholds, log-only drills, and the
  forced-shutdown drill that proves the whole loop. Built and proven on an APC BE600M1 + Beelink
  N150 Proxmox host 2026-10-25..30. Trigger phrases include "nut ups", "upsmon", "usbhid-ups",
  "kill power", "killpower", "POWERDOWNFLAG", "nutshutdown", "upsmon -c fsd", "ups drill",
  "power on after power loss", "State After G3", "Restore on AC power loss", "ups auto restart",
  "back-ups usb data port", "insufficient permissions on everything", "offdelay ondelay".
---

# UPS → clean shutdown → automatic boot (NUT kill-power + BIOS S0)

Two halves, and both must work. Either half alone leaves someone pressing a power button:
- **NUT kill-power:** after the host halts, it tells the UPS to switch its outlets off
  (`offdelay`) and on again when mains is present. Without this, a host that shut down early
  and saw the mains come back before the battery ran out stays off forever, because the PSU never
  lost power.
- **BIOS "State After G3" = S0 / "Restore on AC Power Loss" = Power On:** without it, the
  outlets come back and the host stays off.

## Hardware gotchas (check the unit, not the spec)
- APC Back-UPS BE600M1's data port is a **USB-B** socket on the rear, labelled "USB Data Port",
  next to the Building Wiring Fault light. It is not RJ50. The side USB-A port is charge-only.
  Use a **USB 2.0** A-to-B printer cable: a USB 3.0 B plug is taller and does not fit.
- Read the rear-panel labels or ask for a photo before writing wiring steps.
- `lsusb -d 051d:` (APC) should show the UPS before you apply anything. If NUT was installed
  *after* the UPS was plugged in, its udev rule never ran and the device node stays root:root,
  so the driver says `insufficient permissions on everything`. Fix: `udevadm control --reload &&
  udevadm trigger --subsystem-match=usb`, then restart the driver.

## NUT config that matters
- `ups.conf`: `driver = usbhid-ups`, `vendorid = 051d`, `offdelay = 60`, `ondelay = 120`. Also
  `ignorelb` with `override.battery.charge.low` / `override.battery.runtime.low`, so *your*
  thresholds trigger the shutdown rather than the UPS's own late LB flag.
- Thresholds: measure the real clean-shutdown time first, from journal boot boundaries over
  several reboots. Allow for one guest that ignores ACPI and runs into Proxmox's 180 s stop timeout.
  We used 40 % / 600 s against a ~3.5 min worst case.
- `upsmon.conf`: `POWERDOWNFLAG /etc/killpower` and `SHUTDOWNCMD "/sbin/shutdown -h +0"`. On
  Debian the kill-power step is `/usr/lib/systemd/system-shutdown/nutshutdown`, which runs at the
  very end of shutdown when the flag exists. Assert that the hook exists in the playbook.
- Some Back-UPS models don't expose `ups.delay.start`. **BE600M1 ignored `ondelay`:** it cut the
  outlets about 60 s after halt and restored them within about 20 s. That's fine for auto-boot.
  Only a drill shows what your model does.

## Alerts and drills
- Use a `NOTIFYCMD` script that sends ONBATT / ONLINE / SHUTDOWN / COMMBAD to Telegram, with a
  **test-mode file** (`/var/lib/nut-notify/test-mode`) that diverts it to a log, so drills never
  page anyone. Remove the file when you're done.
- **Drill 1, short outage:** pull the UPS's wall plug for 30 s. Expect OB DISCHRG → OL CHRG, an
  ONBATT and an ONLINE alert in the drill log, no shutdown, and no `/etc/killpower`.
- **Drill 2, the loop:** run `systemd-run --on-active=15 /usr/sbin/upsmon -c fsd` with mains on.
  The delay lets the ssh session return. The host shuts down, sets the flag, the hook kills
  power, the outlets cut and come back, and the host self-boots. Proof:
  - `journalctl --list-boots` shows a new boot shortly after the old one ends.
  - The network gear's uptime, from the controller API, shows it power-cycled too.
  - Afterwards, check that every guest and client got DHCP and DNS again: the switch and gateway
    cold-boot along with the host.
- A plain `reboot` doesn't test the BIOS setting; only a power cut does. Drill 2 is that cut.
- If the session runs on the host itself, write the post-drill checklist somewhere durable first,
  and expect your own DNS to fail until the gateway is up.

## What we saw, 2026-10-30 (APC BE600M1, Beelink N150, 12 guests)
- FSD at 16:55:30, halt at 16:58:51, boot at 17:00:10. The gateway, switch, AP and U5G all
  rebooted at about 17:00:20.
- Shutdown took 3 min 20 s because the Home Assistant VM never answered ACPI and was killed at
  its 180 s timeout. It had no guest agent. Every other guest stopped in under 5 s.
  Fix: enable the QEMU guest agent (`agent: 1`; HAOS ships qemu-ga). Apply it while the VM is
  stopped: shut down from the guest UI, since the setting needs a full stop/start. `qm shutdown` then took 25 s.
- Before trusting the shutdown budget, check every VM for an `agent:` line or a proven ACPI response.
