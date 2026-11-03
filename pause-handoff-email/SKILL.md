---
name: pause-handoff-email
description: This skill should be used whenever a working session pauses rather than completes — when Will says "good pause point", "let's pause here", "I'll pick this up later", "that's enough for today", "wrapping up", "done for now", or hands work back while something is still mid-flight. It defines the pause-handoff email sent to Will covering unverified claims, owed work, phrases to resume each thread, and steps only he can run. Also applies when he asks to "email me the flags", "send me what's outstanding", "what do I need to do", or "how do I pick this up later".
---

# Pause handoff email

A terminal summary scrolls away and cannot be read from a phone. When a session pauses, anything
still outstanding — an unverified claim, a decision only Will can make, a command only he can run
— otherwise survives only in a transcript he would have to reopen a laptop to find. This skill
sends that state to his inbox instead.

Standing convention from Will, 2026-09-05: *"whenever we pause, email me the flags and gaps and
things that need my attention, along with guidance on how to resume the topic with you and any
steps i need to run myself."*

## When to fire

Fire on **any pause**, not only on an explicit end-of-session signal. A pause is any point where
Will stops driving and work remains: a stated pause, a handoff, a blocked step waiting on him, or
a session ending with items open.

This is a broader trigger than the homelab wrap-up ritual (memory, skills, tooling, git status),
which fires only on an explicit end-of-session signal. Run that ritual **first** when it applies —
the email should describe memory and git state already settled, never promise it. A handoff email
listing work as recorded when it is not yet committed is worse than no email.

Skip only when nothing is outstanding: no unverified claim, no owed work, nothing blocked on Will.
Say so in one line rather than sending an email with five empty sections.

## The five sections, in order

### 1. Flags — claimed but not proven

Anything deployed-but-unverified, verified only on a privileged path, tested at the wrong layer,
or resting on inference rather than observation. For each one, state **the exact check that would
settle it**: a literal command, and what pass and fail each look like.

This section is the reason the email exists. The recurring failure mode is reporting success too
early, and a flag Will can resolve in one command is worth more than a paragraph of hedging.

Include anything deliberately left in an odd state, with the reason. Five threads held open on
purpose read as five stalled threads unless the email says otherwise.

### 2. Gaps — real work that is owed

What remains, including work deliberately not done and why, so a deferred decision does not read
later as an oversight. Name what blocks each item: a decision, a credential, a dependency.

### 3. How to resume each thread

Short trigger phrases Will can send back cold, mapped to what they will pick up. He should not
have to reconstruct context to restart a thread. Add a general fallback — asking what is
outstanding on a topic — for threads gone stale.

### 4. Steps that are his, not mine

Separate explicitly. Anything blocked on a UI action, a credential that must not pass through a
transcript, or a judgment call that is not mine to make. Give exact commands where they exist.

### 5. What shipped and is verified

Brief. Enough that the current state is trustable without re-reading anything.

## Update the console in the same breath (standing rule, 2026-09-06)

Will's instruction, verbatim: *"moving forward, when you wrap up and go to send me an email,
that's a good time to update the console app with the latest."*

**The email and the console are the same act, not two.** The email is the notification; the console
is where the state lives afterwards. An email is read once on a phone and then scrolls away — a
handoff whose open questions exist only there has to be re-derived from a transcript the next time
anyone asks. That is the failure the console hub exists to end.

So before sending, write the handoff's content into `console.jackson2w.dev`:

- **Section 1 and 2 items that need Will's judgement become `decisions` rows** with
  `status: open` and a `decide_by`. Match the house style — the schema carries `context`,
  `why_it_matters`, `recommendation`, `if_otherwise`, `command`, and a `steps` JSON array of
  `{do, why, command, expect}`. A recommendation is not optional; an open decision with no
  recommendation is just a question.
- **Decisions Will made during the session become rows with `status: decided`** and an `outcome`
  recording what was actually done. These are the ones that otherwise vanish — a choice made in
  chat is invisible a week later, and the reasoning behind it is what gets lost first.
- **Multi-step procedures become `runbooks`.**
- Refs are sequential (`D-8`, `RB-2`); read the existing ones first so you do not collide, and
  `INSERT OR REPLACE` on `ref` so a re-run updates rather than duplicates.

**Then say in the email that the console has been updated**, so Will knows the durable copy exists
and the email is a pointer rather than the record.

**Verify it rendered**, do not assume the write landed — `curl` the dashboard and grep for the new
refs. A row in SQLite that the page does not show is not an update.

## Sending it

Use the agent mail path, not a ledger-styled report — this is correspondence, not a status
report:

```bash
scp -q <handoff>.md ansible-ctrl:/tmp/
ssh ansible-ctrl "/root/bin/claude-send-email.sh \
  --to willie@williejackson.com \
  --subject 'Pause handoff YYYY-MM-DD — <topic>' \
  --eyebrow 'Pause handoff' \
  --markdown \
  --body-file /tmp/<handoff>.md; rm -f /tmp/<handoff>.md"
```

**Write one markdown body, not a text body plus a markdown attachment.** `--markdown` renders a
styled HTML part *and* sends the same markdown as the plain-text part, so the laptop-readable
copy the attachment used to provide is now the message itself. An attachment here is now
redundant — attach only something genuinely separate, like a diff or a log.

Use the correspondence dialect so the technical content is set properly. Four inline forms, and
only `$` and `@` need typing — addresses are detected:

| Written | Means | Renders as |
|---|---|---|
| `` `$ systemctl restart foo` `` | a command | filled, hairline border, semibold |
| `` `@ansible-ctrl` `` | a host or device | dotted underline, no fill |
| `` `192.168.50.0/24` `` | a network or address | hairline border, no fill |
| `` `/etc/pve/lxc/100.conf` `` | paths, units, versions, identifiers | filled, no border |

Callouts are `> [!FLAG] text`, with `FLAG` / `BLOCKED` / `OK` / `NOTE` / `NEXT`. **`FLAG` is
section 1's shape** — one per unproven claim, each carrying its check. `NEXT` suits section 3.
Do not decorate every section with a callout; a callout on ordinary prose is noise, and five of
them in a row read as none.

Prose still has to work as plain text, because the plain-text part is this same markdown: keep
lines wrapped, and never rely on the styling to carry meaning.

**Send from `ansible-ctrl`, as `claude@williejackson.com`.** Not from `hermes` or `dfw`: those
send as `chuka@`/`olu@`, which attributes Claude Code's own handoff to an agent, and the `claude`
identity is deliberately unconfigured on both (they consume Telegram and fetched web content, so
a compromise there should not be able to send as Claude Code). Sign the body `-- Claude Code`
anyway — a signature costs nothing and survives being forwarded.

If `ansible-ctrl` is unreachable, say so and put the full handoff in the terminal instead. Never
silently skip it, and do not fall back to an agent host just to get it sent — wrong attribution
on a handoff is worse than a late one.

## Rules that make it worth reading

- **Every flag carries its check.** A flag without a command Will can run is an anxiety, not a
  handoff.
- **State what is unproven as unproven.** Unit tests passing is not the same as a live path
  confirmed; a root-run test is not the same as a confined-agent test. Say which one happened.
- **Deferred decisions are listed, not buried.** If a judgment call was left to Will, it belongs
  in section 4 even if mentioning it feels redundant.
- **Do not pad.** Sections 1 and 4 are the reason he opens it. Section 5 is a paragraph, not a
  changelog.
- **Never include a secret**, and never ask him to paste one back. Credential steps say where the
  value lives and what to write, never the value.

## Related

- Homelab wrap-up ritual and its ordering: `feedback_session_wrapup_protocol` memory.
- Verification standards the flags section depends on:
  `feedback_verify_against_real_execution_path` and `feedback_verify_via_most_authoritative_source`
  memories — a privileged-path or wrong-layer test is exactly what belongs in section 1.
