---
name: agent-command-approval-gate
description: This skill should be used when building or reviewing an approval gate that decides whether a self-hosted agent's shell command needs human approval — OpenClaw/Olu, Hermes/Chuka, or any agent whose exec tool needs a human in the loop for privileged or outbound actions. Covers the three command-matching designs and why only one is safe (substring over-gates, anchored regex under-gates, command-position tokenizer is correct by construction), the full wrapper-bypass catalogue, the heredoc/backtick false positive the tokenizer introduces and its provable fix, block-vs-gate as originating-vs-continuing, the refactor regression a unit harness structurally cannot catch, OpenClaw's 512-char approval cap, the three-case live-fire protocol, and drift detection for a gate living where no playbook deploys it. Built across `dfw` (OpenClaw `admin-changes-gate`) and `hermes` (Hermes `outbound-email-approval`) 2026-09-01 to 2026-09-05. Trigger phrases include "approval gate", "pre_tool_call hook", "before_tool_call", "gate agent commands", "requireApproval", "which commands need approval", "agent sent email without asking", "gate regex bypass", "sudo bypasses the gate", "command position matching", "tokenize shell command", "gate prompts on read-only commands", "false positive approval prompt", "hey compose blocked", "agent-send-email.sh gated", "approval description too large", "live-fire gate test", "gate manifest drift", "DANGEROUS_PATTERNS", "tools.exec.security full".
---

# Agent command approval gates

How to decide that a command an agent is about to run needs a human. Built and re-built across two
hosts over five days; every failure mode below is one that actually shipped.

The config-and-hook side of gating lives in `openclaw-deployment` (Gotcha 2, `tools.exec.security`
vs `ask`) and `hermes-agent-deployment` (`DANGEROUS_PATTERNS`, `approvals.mode`). **This skill is
about the part those don't cover: matching.** Getting the hook to fire is easy. Deciding *which*
commands it fires on is where every real bug was.

## Why matching is the hard part

An approval gate has exactly two ways to fail:

- **Under-gate** — a privileged command runs with no prompt. Silent. Presents as "no prompt fired",
  indistinguishable from the gate not being installed. This is the failure that matters.
- **Over-gate** — a harmless command prompts. Noisy, fail-safe, and *not* free: an approval the
  human clicks through without reading is worth less than no approval at all. Both implementations
  here carry that reasoning in their own headers.

So the target is not "match aggressively." It is **match exactly the invocations, and nothing that
merely mentions them.** That turns out to be a parsing problem, not a pattern problem.

## The three designs, in the order they get invented

Every implementation walks this path. Skip to design 3.

### 1. Substring — over-gates

```ts
re: /\bhey\s+compose\b/
```

`grep hey compose`, `cat` of a script containing the string, `ls -l /path/to/agent-send-email.sh`
— all prompt. Chuka found this first on hermes: a read-only inspection of the sender's own path
tripped a prompt. Safe, but it trains reflexive approval.

### 2. Anchored regex — UNDER-gates, do not ship this

The natural fix is to anchor to "start of a command":

```ts
re: /(?:^|[;&|]\s*|(?:^|\s)[A-Z_][A-Z0-9_]*=\S*\s+)hey\s+compose\b/
```

This looks right and is materially worse than what it replaced, because it moves the failure from
over-gating to under-gating. Verified bypasses against exactly this pattern:

| Shape | Why it slips |
|---|---|
| `sudo hey compose …` | `sudo` is not start-of-string, a separator, or an env assignment |
| `env` / `nohup` / `time` / `doas` / `command` / `exec` prefix | same |
| `$(hey compose …)` | `$(` is not in the separator class |
| `` `hey compose …` `` | backtick is not either |
| `( hey compose … )` | subshell open is not either |
| any invocation on line 2+ of a multi-line command | `^` without the `m` flag is start-of-*string* |

Each is patchable by adding an alternation. That is the tell that the design is wrong: **the next
wrapper someone invents is a new hole.** A regex cannot see command position because command
position is a property of shell grammar, not of text.

### 3. Command-position tokenizer — correct by construction

Split into segments at every point a new command can begin, strip the things that wrap a command
without changing which command it is, then match on `argv[0]`/`argv[1]`.

Reference implementation (hermes, Python — `outbound-email-approval/__init__.py`):

```python
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|&\n]|\$\(|`|\(")
_TRANSPARENT_PREFIXES = frozenset(
    {"sudo", "env", "command", "exec", "nohup", "time", "builtin", "doas"}
)
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

def _command_positions(command: str):
    """Yield the argv of each command position in a shell string."""
    for segment in _SEGMENT_SPLIT.split(command):
        tokens = segment.strip().split()
        index = 0
        while index < len(tokens) and (
            _ENV_ASSIGNMENT.match(tokens[index])
            or tokens[index] in _TRANSPARENT_PREFIXES
        ):
            index += 1
        if index < len(tokens):
            yield tokens[index:]
```

The TypeScript port (dfw) adds one thing worth copying — **basename comparison with a trailing-paren
strip**, because the splitter leaves `$(hey compose …)`'s closing paren attached to the last token:

```ts
function cmdWord(token: string | undefined): string {
  if (!token) return "";
  return (token.split("/").pop() ?? token).replace(/\)+$/, "");
}
```

`FOO=1 sudo /usr/local/bin/hey compose …` now presents as `["hey", "compose"]`; `grep hey compose`
presents as `["grep", …]`. Every bypass in the table above is covered without enumerating any of
them.

**Keep substring matching for shapes where the string appearing anywhere means the mutation is in
play** — an admin-server endpoint like `127.0.0.1:8790/changes`, for instance. Those never
false-positive on reads, so the tokenizer buys nothing. Mixed matching is correct here, not lazy.

## The tokenizer's own false positive — know it before you ship

`SEGMENT_SPLIT` contains `\n` and a backtick. Both are correct for shell. Both mean **heredoc
bodies and markdown inline code spans get parsed as command positions.** Observed live on dfw
2026-09-05 when the agent wrote its own test results into a memory file:

```
GATED    cat >> notes.md <<'EOF' … prose containing `agent-send-email.sh --help` … EOF
GATED    echo `agent-send-email.sh --help`
BLOCKED  echo `hey compose --to a@b`
GATED    heredoc with agent-send-email.sh at the start of a line
silent   echo 'agent-send-email.sh --help is the command'    (no backtick)
silent   echo the script agent-send-email.sh exists           (mid-sentence)
```

The third line is the sharp end: **an agent cannot document its own gate**, because prose
mentioning the blocked command inside backticks is itself blocked. Agents write markdown
constantly — memory files, notes, handoff entries — so this fires in normal operation, not in
contrived cases.

**The fix that is provable rather than heuristic: strip single-quoted heredoc bodies before
tokenizing.** `<<'EOF'` is literal by definition — no expansion of `$( )`, backticks, or variables
— so its body can never execute anything, and removing it from consideration cannot create a
bypass. Unquoted `<<EOF` *does* expand and must stay tokenized.

Bare backticks outside a heredoc are the unfixable half: distinguishing markdown from command
substitution needs quoting state that a split-based tokenizer does not have. **Accept the
over-gating.** Removing backtick from the separator class to quiet it re-opens a genuine bypass,
and that trade is backwards.

## Block vs gate: originating vs continuing

Not a risk ranking. The line that held up in practice:

- **Block** the shape that is wrong no matter who approves it. On both hosts, `hey compose` sends
  as the human's own identity, so a prompt asks him to bless a message already addressed wrongly —
  and when it is the message he asked for, approving is the natural reflex. Blocking with a
  `blockReason` naming the correct path is better: the agent self-corrects in the same turn.
- **Gate** anything that continues an existing thread or sends as the agent's own identity.
- **Leave open** reads, search, triage, calendar, contacts, and drafts. `--draft` is the review
  lane — an unsent draft never leaves the account — so it stays open even for an otherwise blocked
  verb.
- Carve-outs need checking against the CLI's real help output, not assumption. `compose --thread-id`
  is semantically a reply, so it is *gated*, not blocked.

## The regression a unit harness structurally cannot catch

The first tokenizer port changed `classify()` from returning a string to returning an object, and
left one interpolation behind:

```ts
const verdict = classify(command);          // now an object
…
description: `Gated: ${gatedLabel}\n` +     // the old string variable — undefined
```

Result: **every gated path threw `ReferenceError`** while the blocked and pass-through paths
worked normally. A 42-case harness reported all green, because it tested `classify()` — and the
defect was in the caller consuming its return value.

**A unit test over an extracted pure function cannot see a defect in its caller.** Test through the
real entry point: import the plugin, stub only the SDK module to capture the registered handler,
and fire synthetic events at it.

```js
const r = await handler({ toolName: "exec", toolKind: "shell", params: { command } });
const outcome = r?.block ? "blocked" : r?.requireApproval ? "gated" : "pass";
```

Note also that `node --experimental-strip-types --check` validates **syntax only** and passes an
undefined identifier cleanly. `tsc --noEmit` names it immediately. A green `--check` is not a green
build.

## OpenClaw's 512-char approval cap

OpenClaw **rejects an approval request whose `description` exceeds 512 characters**, and approval
failures are fail-closed — so an over-long description *blocks a legitimate action* and presents as
"the gate is broken," not "the message was too long." Slice the embedded command:

```ts
description: `Gated: ${verdict.label}\nCommand: ${command.slice(0, 240)}\nApprove to run once, or deny.`
```

Hermes has no known equivalent cap; apply the bound anyway. Also set `timeoutBehavior: "deny"` with
a few-minute `timeoutMs`, so an unnoticed prompt fails closed instead of executing hours later.

## Live-fire protocol — three cases, and the third is not optional

A gate verified only by harnesses is a gate that has never been observed. Harnesses cannot
distinguish a loaded gate from an unloaded one; on dfw a test was once reported as "gate verified"
when no prompt had ever fired. After any restart that loads new gate code, run exactly this, one
command at a time, with the human watching:

1. **Positive baseline** — a gated command in its plainest form. Expect a prompt.
2. **Positive via wrapper** — the same command behind `env` or `sudo`. Expect a prompt. *This is
   the case that distinguishes the tokenizer from the regex it replaced.*
3. **Negative** — a read-only command that merely mentions the gated one, e.g.
   `grep -c compose /usr/local/bin/agent-send-email.sh`. Expect **no prompt**. A prompt here means
   the old code is still loaded.

Choose commands inert even if approved by mistake (`--help` works well). Stop immediately if 1 or 2
produce no prompt: that is a fail-open gate, which is worse than any bug you were testing for.

**Read the prompts, not the journal, to attribute results.** The gateway journal logs
`plugin.approval.waitDecision` with a duration and an id and **no command text**, so it cannot say
which command any decision belongs to. The Telegram approval messages carry the full command. Two
hours were lost inferring attribution from surrounding log lines and getting it wrong.

## Drift detection when the gate lives where nothing deploys it

An agent-owned plugin under the agent's home is invisible to Ansible and to Claude Code, so a
rebuild drops the only enforcement gate silently. The arrangement that works:

- The **agent** publishes sha256 of its live plugin files hourly to a path on the shared exchange
  channel (a script-payload cron job — no model calls).
- A **root health publisher** compares those hashes against a copy vendored into the host's Ansible
  repo, emitting `gate_manifest_missing`, `gate_manifest_age_min`, and `gate_files_mismatched`.
- The **peer host** alerts on all three, so a dead agent cannot hide its own drift.

**Honest limit, and state it in the code:** this asks the subject to self-report, so it detects
*accident* — a rebuild, an unrecorded edit, a stopped job — and not an agent publishing a
stale-but-matching manifest. Root could hash the plugin directly and close that; on this fleet it
is deliberately not done, because the agent's home is a boundary the human set.

Expect the first firing to catch **you**, not the agent: vendoring is manual, so the human-side copy
goes stale the moment the agent patches and publishes. That is the check working.

### Give the check a consumer, or it trains its reader to ignore it

Detection without a scheduled response is not monitoring. On 2026-09-05 this exact alert fired every
~15 minutes for **ten hours — 39 consecutive failures** — because re-vendoring was a manual step
nobody was scheduled to do. The agent had improved its own gate twice and published both times; the
human-side copy simply stood still. Nothing was broken and nothing was learned until someone asked.

Automate the toil, not the judgement:

- An hourly job on the host, offset ~10 minutes **after** the agent's manifest tick so it reads a
  settled hash rather than racing it.
- It **stages**, it does not accept. Auto-accepting makes the drift check self-silencing — any live
  change instantly becomes the recorded one, and "vendored" stops meaning *a version someone looked
  at* and starts meaning *whatever the agent last had*. Accident is precisely what a
  converge-on-anything loop erases, and accident is all this check was ever able to catch.
- Only stage an export whose **content hashes to the manifest**. If no such export exists, the live
  gate moved and was never published — a different situation that must stay noisy.
- **One notification per distinct drift**, fingerprinted on the manifest. Replacing a repeated alert
  nobody acts on with a differently-shaped repeated alert fixes nothing.
- Accepting is one command, which **re-verifies against the manifest at accept time too** — the gate
  may have moved again since staging, and recording a version that was never running is worse than
  the drift it closes.
- Offer auto-accept as a documented flag, defaulted off. That is the owner's call, not the
  implementer's.

**A script that commits on someone's behalf must stage only what it touched.** The accept step's
`git add -A` swept three unrelated uncommitted files into a commit titled *"Re-vendor
admin-changes-gate: index.ts"* — accurate in content, wrong in name. Scope the add to the vendored
directory and exit cleanly when it has nothing to commit. This only surfaced because the path
happened to run against a dirty repo; a clean-repo test passes and says nothing.

And give it a way to be tested that does not page anyone (`..._NOTIFY=false`). Exercising the clean
path proves nothing about the branch that matters.

### Vendored-vs-disk is not disk-vs-loaded

The manifest hashes what is **on disk**. It says nothing about what the running process has loaded,
and plugins load at process start. Both agents on this fleet reported their own loaded state
incorrectly within the same day, in opposite directions: one said its fix was pending when a restart
had already made it live, the other said pending and was right. **Neither agent can observe its own
loaded build**, and nothing here checks that third gap. Settle it from outside with the unit's
`ActiveEnterTimestamp` against the plugin's mtime — one command, and it beats any agent's account of
itself.

## Hermes: what an "always" press actually covers (checked 2026-11-02)

Plugin approvals don't share a key with the built-in patterns. `tools/approval.py` keys a plugin
`{"action": "approve"}` as `plugin_rule:<rule_key>` when the hook gives one, and otherwise as
`plugin_rule:<tool>:<sha256(message)[:12]>`. **Put the command text in the message and don't
set a rule_key.** Then a "session" or "always" press covers only that exact call, never the
whole class. A stable message, or a rule_key, turns one careless "always" into a permanent hole.

The built-in `execute_code` guard is different: it uses the fixed key `execute_code`, so one
"always" press allowlists every script forever (`command_allowlist: [execute_code]` in
config.yaml). Plugin hooks still fire on execute_code, so a gate built as a plugin survives that
press, while a gate that relies on the built-in prompt does not. **Before trusting any Hermes
gate, read `command_allowlist` in config.yaml.**

### A gate for an API-backed skill: cover every route, not just the CLI

On the Google gate (hermes `google-actions-approval`), the skill's CLI was only one of four
routes. The agent had already used raw `googleapiclient` code: it listed calendars, which the
CLI can't do. The routes are:

- the CLI, by command position;
- the wrapped binary (`gws`);
- raw client calls (`events().delete(`) in execute_code, heredocs, `python -c`, and **.py files
  the terminal runs**, which the hook reads at call time;
- raw HTTP with a mutating method.

Two traps:

- Match `.events().update(`, not a bare `.update(`, or every Python `dict.update` prompts.
- The shell variable the skill documents (`$GAPI calendar delete`) sits in argv[0]
  unexpanded, so a token that is a bare `$VAR` has to count as the CLI.

## Review checklist

- [ ] Matching is command-position, not substring, for anything that appears in ordinary prose
- [ ] Every wrapper in `_TRANSPARENT_PREFIXES` is covered — verify with a real test, not by reading
- [ ] Single-quoted heredoc bodies stripped before tokenizing
- [ ] Tests fire the **handler**, not the classifier
- [ ] Both directions covered: gated shapes prompt, read-only mentions stay silent
- [ ] Approval description bounded (≤512 for OpenClaw), no `undefined` interpolation
- [ ] `timeoutBehavior: "deny"`
- [ ] Every send/mutation route is gated — a new route added later silently defeats the gate (for API skills: CLI, wrapped binary, raw client code incl. script files, raw HTTP)
- [ ] Hermes: approval message embeds the command, no rule_key; `command_allowlist` read
- [ ] Live-fire run after the restart that loads it, all three cases
- [ ] A vendored copy plus drift detection exists if the plugin lives outside IaC
- [ ] The drift check has a scheduled consumer, not just an alert
- [ ] `ActiveEnterTimestamp` vs plugin mtime checked before believing any claim about what is loaded
