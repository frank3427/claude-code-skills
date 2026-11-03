---
name: n8n-workflow-api-authoring
description: This skill should be used when authoring an n8n workflow as JSON to import via n8n's REST API (rather than hand-clicking in the editor), when an n8n HTTP Request node's attached credential seems to be silently ignored, when an n8n Code node throws "Module 'X' is disallowed", when a `{{ }}` expression field throws a bare "invalid syntax", when downstream Code node fields go missing/undefined after an HTTP Request node, when importing/updating an n8n workflow via `POST`/`PUT /api/v1/workflows` hits errors like "active is read-only", "PATCH method not allowed", or a referenced error-workflow name not resolving, when a Wait-node-delayed check using `$getWorkflowStaticData` gives a stale/wrong answer, or when decoding n8n's SQLite `execution_data` for debugging without an API key. Trigger phrases include "n8n workflow JSON", "n8n REST API import", "n8n credential not working", "n8n expression invalid syntax", "n8n Module crypto is disallowed", "n8n HTTP Request neverError", "n8n workflow active read-only", "POST /api/v1/workflows", "getWorkflowStaticData stale", "n8n Wait node static data", "n8n execution_data flatted decode".
---

# n8n workflow authoring via REST API

Building an n8n workflow as a JSON file (agent-authored, or scripted) and importing it via
`POST /api/v1/workflows`, instead of hand-clicking every node in the editor. This is a reasonable
middle ground for config-as-code: workflow *logic* (nodes/connections) is versioned and
diffable; *credentials* are still created by hand in the editor so secret values never transit a
file or an agent's context (see the credentials section below). All of the gotchas here were
found the hard way building a real multi-node pipeline (Webhook → external API → GitHub Contents
API with retry logic) and getting it working end-to-end, not from documentation.

## The workflow JSON shape

```json
{
  "name": "my-workflow",
  "nodes": [ {"parameters": {...}, "name": "...", "type": "n8n-nodes-base.X", "typeVersion": N, "position": [x,y], "id": "...", "credentials": {...}} ],
  "connections": { "Node A": { "main": [[ {"node": "Node B", "type": "main", "index": 0} ]] } },
  "settings": { "executionOrder": "v1" }
}
```

Do **not** include `active` or `id` at the top level when creating — see "Import/update API
quirks" below.

## Expression fields (`={{ ... }}`) are not full JavaScript — build complex bodies in a Code node instead

An HTTP Request node's JSON Body (or any `={{ }}` field) looks like it accepts arbitrary JS, but
n8n's expression evaluator does **not** reliably support multi-statement code — an IIFE like:

```
={{ (() => { const x = ...; return JSON.stringify(x); })() }}
```

throws a bare `invalid syntax` with no useful line/column detail. The failure is also silent
about *why* — it just refuses to evaluate. This also breaks in a second, sneakier way: nesting a
second `={{ ... }}`-looking string *inside* an outer expression (e.g. building a `messages`
array where one field's value is itself a quoted `"={{ ... }}"` string) gets misparsed, because
the expression scanner isn't brace-depth-aware across nested `}}` occurrences — it can terminate
the outer expression early at the first inner `}}`, silently truncating the rest of the object.

**Fix:** never build a nontrivial JSON body inline in an expression field. Add a **Code** node
immediately before the HTTP Request node that constructs the full body (real JS, `JSON.stringify`
included) and returns it as a single field, e.g. `{ ...previousFields, request_json:
JSON.stringify(body) }`. The HTTP node's Body field then becomes a trivial single-property
reference: `={{ $json.request_json }}` — this form is reliable.

## Attaching a `credentials` block is not enough — `authentication` must also be set

A node can have a valid `credentials` object (matching a real credential ID) and still silently
send an **unauthenticated** request, with no error, no warning in the API response — the target
API just sees a request with no auth header and returns its own 401, which looks like a bad
credential when the real bug is a missing parameter. The `credentials` field only makes a
credential *available* to the node; a separate `parameters.authentication` field decides whether
it's actually *used*:

- **Generic Header Auth credential**: `parameters.authentication = "genericCredentialType"`,
  `parameters.genericAuthType = "httpHeaderAuth"`.
- **A predefined/built-in credential type** (e.g. GitHub, Slack): `parameters.authentication =
  "predefinedCredentialType"`, `parameters.nodeCredentialType = "githubApi"` (or whatever the
  type name is).

Set both the `credentials` object *and* these `parameters` fields on every HTTP Request node that
needs auth — a credential attached without the matching `authentication` parameter is a silent
no-op.

## HTTP Request nodes throw on non-2xx by default, and `continueOnFail` discards the whole item

If a workflow needs to inspect a status code (a 404 meaning "doesn't exist yet" is normal, a 409
meaning "retry with a fresh value" is normal), the naive approach — read `$json.statusCode` in a
downstream node with `continueOnFail: true` on the HTTP node — silently breaks:

1. By default, any non-2xx response makes the HTTP Request node **throw**, not just return a
   status code to inspect.
2. With `continueOnFail: true`, the item that comes out of a thrown failure is a bare `{ error:
   "<message>" }` — it does **not** merge with whatever fields were on the input item. Every
   field the workflow had built up so far (a computed path, a title, a piece of content) is
   gone, and a downstream node referencing `$json.title` gets `undefined` with no obvious link
   back to "the HTTP node ate my data."

**Fix:** set `parameters.options.response.response.neverError = true` and
`parameters.options.response.response.fullResponse = true`. This makes the node return `{
statusCode, headers, body }` for **any** status code without throwing, so status-code branching
becomes ordinary data inspection (`$json.statusCode === 404`) instead of exception handling with
data loss. (Note the doubled `response.response` nesting — that's how this node's parameter
schema is actually structured, not a typo.)

## An HTTP Request node's output *replaces* the item — it does not carry the input forward

Separately from the above: even a **successful** HTTP Request node's output is just its own
response. It does not automatically merge in whatever fields were on the item flowing into it.
A Code node three hops downstream that assumes `$input.first().json.title` still has the value
set five nodes ago (after two HTTP Request hops in between) will get the *last* HTTP response's
fields instead, silently.

**Fix:** don't rely on implicit pass-through across an HTTP node. Reference the node that
actually produced the data you need, explicitly, from any later Code node:
`$('Build Original Data').first().json.title` — this works regardless of how many HTTP hops
happened in between, as long as that named node executed earlier in the same run.

## The Code node sandbox blocks some `require()` calls

`require('crypto')` throws `Module 'crypto' is disallowed` inside a Code node — the sandbox
restricts which built-in modules are reachable, and `crypto` isn't in the default allow-list.
This is easy to miss until a specific code path (e.g. a hashing/dedup step) actually runs. If you
need a hash and don't need cryptographic properties (just determinism), write a small plain-JS
hash function (e.g. a djb2/FNV-style rolling hash over `charCodeAt`) instead of reaching for
`crypto.createHash`. Plain globals like `Buffer` are fine — it's specifically module `require()`
that's restricted, not every Node.js global.

## Claude/Anthropic responses can include a `thinking` block before the `text` block

If an HTTP Request node calls the Anthropic Messages API and a downstream Code node parses the
response, don't assume `response.content[0]` is the text block — extended thinking (even if not
deliberately requested) can put a `{"type": "thinking", ...}` block first, pushing the real
`{"type": "text", "text": "..."}` block to index 1 or later. Find it by type instead of position:

```js
const textBlock = (resp.content || []).find(b => b.type === 'text');
const text = textBlock?.text;
```

## Import/update REST API quirks

- **`POST /api/v1/workflows` rejects `active` in the body**: `request/body/active is read-only`.
  Strip `active` (and `id`, if present from a prior export) before posting. Activate separately
  via `POST /api/v1/workflows/{id}/activate` (there's also a `/deactivate`) after import.
- **Updating an existing workflow is `PUT`, not `PATCH`**: `PATCH /api/v1/workflows/{id}` returns
  `PATCH method not allowed`. Use `PUT /api/v1/workflows/{id}` with the full `{name, nodes,
  connections, settings}` body — partial updates aren't supported, so `GET` the current
  definition first, mutate what you need in memory, and `PUT` the whole thing back.
- **An error-workflow reference needs the real numeric/string ID, not a name.** If workflow A's
  `settings.errorWorkflow` should point at workflow B, import B first, capture its returned `id`
  from the creation response, and set A's `settings.errorWorkflow` to that ID before importing A.
  A workflow name string in that field does not resolve.
- **`GET /api/v1/credentials` returns id/name/type/sharing metadata only — never secret values.**
  This is safe to call and inspect freely; use it to map credential names to their real
  instance-specific IDs so imported workflow JSON (which can only meaningfully carry a `name` for
  portability) gets wired to working credentials rather than needing manual reselection in the
  editor after every import.
- Credentials **can** be created via `POST /api/v1/credentials` with `{name, type, data: {...}}`
  where the shape of `data` matches the credential type's fields (e.g. Header Auth wants `{name,
  value}`; GitHub API wants `{server, user, accessToken}`). This is fine for credentials that
  aren't themselves a sensitive third-party secret being freshly typed by a human (e.g. an
  n8n-internal API key used only for that instance's own execution lookups) — see the security
  note below for where to draw the line.

## No usable API key? Update via the `n8n` CLI instead of the REST API

If no REST API key value was ever persisted (n8n never returns a key's raw value after creation)
and minting a fresh one means a human clicking through the editor UI, the `n8n` CLI is a
legitimate DB-backed alternative, run over SSH on the host with `N8N_USER_FOLDER` set to the
service's data dir:

```
n8n export:workflow --id=<id> --pretty --output=file.json   # rollback point
# ...edit file.json's nodes/connections, keep "id" and "active"...
n8n import:workflow --input=file.json                       # updates in place by matching "id"
```

Two gotchas:

- **`import:workflow` always deactivates the workflow**, regardless of the JSON's `"active"`
  field. `--activeState=fromJson` would preserve it but only works in queue/multi-main mode — on
  a single-instance deployment it errors outright. Reactivate instead with the deprecated but
  functional `update:workflow --id=<id> --active=true`.
- **Neither CLI command notifies the already-running server process** — both write straight to
  the DB, but a webhook's active registration lives in the running process's memory (set at
  startup). The CLI says as much (`Note: Changes will not take effect if n8n is running...`).
  `systemctl restart n8n` (or equivalent) is required afterward for the new node graph to
  actually take effect; verify via the startup log's `Activated workflow "<name>"` line.

## Where secrets should and shouldn't flow

Workflow JSON only ever *references* a credential by id/name — it never embeds a secret value.
Keep it that way deliberately: create any credential holding a genuine third-party secret
(an API key for an external service, a webhook shared secret, a bot token) **by hand in the n8n
editor UI**, not via a script that has the raw value passed through it, so the secret's only
resting place is n8n's own encrypted credential store. Reserve `POST /api/v1/credentials`
scripting for credentials that are themselves low-sensitivity/internal (e.g. an n8n API key
whose only purpose is calling that same n8n instance's own REST API).

When a secret genuinely does need to move between two hosts to get into place (e.g. reading an
existing token from one host's env file to configure something on another), never print it to
a terminal/tool-output transcript and never write it to a file at rest as an intermediate step —
pipe it directly host-to-host (`ssh A "read-the-value" | ssh B "consume-it"`), and have the
consuming side `read` it from stdin into a shell variable used immediately, not from a
positional argument or a file. This keeps the value out of both the visible output and any
on-disk trace, and out of shell history/process-argument visibility on either host.

**Rotating an *existing* credential's value is a different case from creating a new one, and API
scripting is fine here even for a genuine third-party secret** — the "create by hand in the
editor" guidance above is about not having a *brand-new* secret value pass through a script; once
a credential already exists, `PATCH /api/v1/credentials/{id}` updates it in place (confirmed
working 2026-07-19, `credentialSchema`-shaped `data` object, e.g.
`{"name": "...", "type": "telegramApi", "data": {"accessToken": "...", "baseUrl": "..."}}` for a
Telegram credential — the GET response never echoes `data` back, consistent with n8n's
write-only-secrets design). Since the destination here is an HTTPS API rather than another
SSH-reachable host, the host-to-host pipe pattern above doesn't directly apply — instead, build
the request body **server-side, on the same host that already holds the source value** (e.g. a
small Python script using `urllib`/`requests`, run over SSH on that host), so the raw value only
ever exists in that host's process memory long enough to make the API call, and never appears in
any command's arguments, any intermediate file, or anything that flows back to the calling
session. See the `credential-rotation-protocol` skill for the general version of this pattern.

## Debugging a failed execution via the API

`GET /api/v1/executions/{id}?includeData=true` returns the full run, including
`data.resultData.error` (message/description of what failed and `lastNodeExecuted`) and
`data.resultData.runData` (a per-node log of what each node actually received/returned — the
fastest way to see exactly which field was `undefined` or which status code came back, rather
than guessing from the workflow JSON alone).

## `$getWorkflowStaticData` is unsafe as a signal between separate webhook executions when a Wait node is involved

`$getWorkflowStaticData('global')` looks like a simple shared mutable object any node in the
workflow can read/write, and it does persist to the `workflow_entity.staticData` column across
runs. But **a paused Wait-node execution resumes from a snapshot of static data taken when it
started/was queued, not a live re-read of the current DB row.** If workflow logic looks like
"execution A writes a completion flag, execution B (paused in a Wait node since before A started)
reads that flag after waking up," B will not see A's write even though A's write landed in the DB
well before B resumed — B is working from stale state captured at its own start time. This is
easy to hit with a "did event Y happen before this timeout" pattern across two different webhook
event types hitting the same workflow. Confirmed by inspecting real execution data (see below):
both executions agreed on the same business key (a meeting ID in this case), ruling out a
data-shape mismatch — the write was simply invisible to the already-paused reader.

**Fix:** don't use static data as a cross-execution signal when a Wait node separates the writer
and reader in time. Make the post-wait check authoritative against real external state instead —
e.g., query the actual system of record (a GitHub file's existence, a database row, an API) for
whatever the "did it happen" question really depends on. Regular node-to-node references
(`$json`, `$('Node Name')`) are NOT affected by this — they're part of the execution's own
persisted run data and survive a Wait-node pause/resume correctly; it's specifically the
*workflow-global* static data object that's snapshotted.

## Decoding execution data straight from n8n's SQLite DB (no API key needed)

When there's no REST API key and you need to inspect real historical execution payloads/outputs
(e.g. to diagnose the static-data issue above), n8n's `execution_data.data` column is
`flatted`-encoded (a deduplicating JSON serialization, not plain JSON) — `JSON.parse` on it
fails or produces garbage. Decode with the `flatted` package n8n already ships:

```js
const { parse } = require('/usr/lib/node_modules/n8n/node_modules/flatted/cjs/index.js');
// row.data is the raw column value (read via sqlite3's stdlib module and written to a file —
// avoid piping through multiple nested SSH hops with inline shell quoting, it mangles the string)
const data = parse(fs.readFileSync('/tmp/exec_row.json', 'utf8'));
const run = data.resultData.runData;   // keyed by node name, each an array of run attempts
console.log(run['Some Node'][0].data.main[0][0].json);
```

Get the raw row with a small Python script (stdlib `sqlite3`, no CLI tool needed) writing straight
to a file — safer than threading the value through shell command substitution across an SSH hop.
`execution_entity` (id, workflowId, status, startedAt, stoppedAt) is plain columns and queryable
directly; only `execution_data.data` needs the `flatted` decode.

## Retiring an unused credential on SQLite with no API key (2026-09-12, n8n 2.37)

The CLI can't delete credentials. The public API needs a user API key, and creating one just to delete
something is a new credential path. Using the UI is fine if a human is present. Otherwise:

1. **Prove it's unused, by id AND by name**, read-only via Python's stdlib `sqlite3` with
   `file:…?mode=ro`, since the `sqlite3` CLI is often not installed. Check `workflow_entity.nodes`,
   `workflow_history.nodes`, and **every** table with a credential column.
2. **Map the foreign keys first**, because 2.x grew many tables: `pragma foreign_key_list(<t>)` for
   each table referencing `credentials_entity`. On 2.37:
   - `shared_credentials`, `credential_dependency`, `agent_credential_dependency` and
     `dynamic_credential_*`: CASCADE
   - `chat_hub_*`: SET NULL
   - `instance_credential_assignment`: **RESTRICT**, so it must have no row for the target
3. **Take an encrypted backup**, loading the env from its file inside a root shell so the encryption
   key never goes on a command line:
   `bash -c 'set -a; . /root/.config/n8n.env; set +a; exec runuser -u n8n -m -- n8n export:credentials --id=<id> --output=<dir>/cred.json'`.
   Confirm its `data` is still an encrypted string.
4. **Stop n8n**, copy `database.sqlite`, `-shm` and `-wal` together, then delete in one transaction with
   `pragma foreign_keys=ON` (SQLite's default is **off**, so cascades wouldn't run). Assert that exactly
   1 row was deleted and the dependent rows went to 0, otherwise roll back.
5. **Start n8n** and poll `/healthz` for 200 (about 5 s downtime), then confirm the other credentials and
   active workflows are intact.

`Failed to start Python task runner in internal mode … virtual environment is missing` at startup is a
long-standing, benign message on npm installs without the Python runner. Check whether it predates a
change before attributing it to one.
