# Bug Report: iris-agentic-dev — three defects and a distribution question

**Status**: 🔎 OPEN — not yet raised upstream
**Upstream**: [intersystems-community/iris-agentic-dev](https://github.com/intersystems-community/iris-agentic-dev)
**Reporter**: Thomas Dyar
**Date**: 2026-08-16

> **Scope**: defects in **iris-agentic-dev** only, so this can be filed upstream as-is.
> Issues in iris-pgwire's own configuration and docs that surfaced during the same session are
> tracked separately in [iris-pgwire-iad-setup-issues.md](iris-pgwire-iad-setup-issues.md).

## Environment

- **iris-agentic-dev**: 1.0.0, built from source at `master` @ `c5be2b7` (2026-08-07)
- **IRIS**: `intersystems/iris-community:latest-cd` — IRIS for UNIX (Ubuntu Server LTS for
  x86-64 Containers) 2026.2 (Build 221U)
- **Container**: `iris-pgwire-db`, ports `1972:1972` and `52773:52773`
- **Platform**: Linux x86-64 (containerised CI-like sandbox), root
- **Rust**: cargo 1.94.1 (29ea6fb6a 2026-03-24)

## Summary

Used iris-agentic-dev to corroborate findings from the `043-local-first-sync` Phase 0 spikes. It
did that job well — `iris_table_info` and `resolve_storage` independently reproduced the spike's
storage result. Getting to that point took longer than it should have, and using it surfaced three
defects plus one packaging question.

All three defects are in iris-agentic-dev itself. Ordered by impact:

| # | Issue | Severity | Confidence |
|---|-------|----------|-----------|
| 1 | HTTP 401 surfaces as `error decoding response body` | **High** — misdiagnoses every auth failure | High, reproduced |
| 2 | `journal_search` returns empty `global`, appears to ignore `global_pattern` | **High** — tool returns wrong results silently | High, scoped below |
| 3 | `tool` subcommand advertises tools it cannot dispatch | Medium — discoverability | High, reproduced |
| — | Not distributed on PyPI (question, not a defect) | Low — see below | High, reproduced |

---

## How setup actually went

Recorded because most of the friction was avoidable, and one part of it was my own error.

### 1. Not distributed on PyPI — intentional?

`pip install iris-agentic-dev` finds nothing, while sibling projects in the same org resolve:

| Package | PyPI |
|---|---|
| `iris-agentic-dev` | 404 |
| `iris_agentic_dev` | 404 |
| `iris-devtester` | 200 |
| `iris-vector-graph` | 200 |

The project is Rust, so this may be deliberate — a Python package would only ever be a shim around
a binary. **Raising it as a question, not a defect**: is a PyPI presence intended? Downstream
projects have written `pip install`-based instructions on the assumption that one exists, which is
what prompted the question.

### 2. I built from source unnecessarily — my mistake, with a contributing factor

I queried the GitHub releases API to find a Linux binary:

```console
$ curl -sS https://api.github.com/repos/intersystems-community/iris-agentic-dev/releases/latest
# → tag_name: None
```

I read that as "no releases published" and built from source instead
(`cargo build --release --bin iris-agentic-dev`, 3m23s, clean, no warnings of note).

**That inference was wrong.** The documented download URLs work:

| Asset | Result |
|---|---|
| `iris-agentic-dev-macos-arm64` | **200** |
| `iris-agentic-dev-linux-x86_64` | **200** |
| `iris-agentic-dev-linux-x64` | 404 |
| `iris-agentic-dev-macos-x64` | 404 |
| `iris-agentic-dev-windows-x64.exe` | 404 |

Both README-documented assets exist. I had guessed at asset names rather than reading the README's
own URLs, and the API returning nothing useful (likely unauthenticated rate-limiting in this
sandbox) reinforced the wrong conclusion.

**No action needed from the project** beyond possibly publishing macOS x64 and Windows builds, if
those platforms are in scope. Recorded so the next person does not repeat it.

### 3. The connection is over the web port

The CLI connects via the **Atelier REST API on the web port (52773)**, not the SQL port. Every
connection flag is web-oriented: `--host`, `--web-port`, `--web-prefix`, `--scheme`. This is
correct and consistent behaviour — noted only because `port` is accepted as a serde alias for
`web_port` (`workspace_config.rs:15`), so a config naming the *SQL* port parses cleanly and
silently misconfigures the client. A validation warning when the configured port looks like a
superserver port (1972/51773/…) would turn a confusing connection error into an obvious one.

*(A downstream config doing exactly that is tracked in iris-pgwire's own issue log, not here.)*

### 4. Community-image credentials

`intersystems/iris-community:latest-cd` started without `ISC_DEFAULT_PASSWORD`, leaving `_SYSTEM`
in a state where `/api/atelier/` returns 401. Resolved with:

```objectscript
set props("Password") = "SYS"
set sc  = ##class(Security.Users).Modify("_SYSTEM", .props)
set sc2 = ##class(Security.Users).UnExpireUserPasswords("*")
```

Ordinary container setup — but the way the tool reported it is defect 1 below.

---

## Defect 1 — HTTP 401 surfaces as `error decoding response body`

**Severity: High.** Every authentication failure is reported as a parsing problem, pointing the
user at the wrong subsystem.

### Reproduction

With `_SYSTEM`'s password set to something other than the one supplied:

```console
$ IRIS_HOST=localhost IRIS_WEB_PORT=52773 IRIS_USERNAME=_SYSTEM IRIS_PASSWORD=SYS \
  iris-agentic-dev query "SELECT 1"
error: error decoding response body
```

`curl` against the same endpoint at the same moment:

```console
$ curl -sS -o /dev/null -w "%{http_code}\n" -u _SYSTEM:SYS http://localhost:52773/api/atelier/
401
```

### Expected

Something naming the actual condition, e.g.:

```
error: authentication failed (HTTP 401) for user '_SYSTEM' at http://localhost:52773/api/atelier/
hint: check credentials, or whether the account requires a password change
```

### Suspected cause

The HTTP response body is deserialized without first checking the status code, so a non-JSON error
page fails to parse and the parse error is what propagates. Checking status before decoding — and
special-casing 401/403 — would fix the whole class.

**Worth noting**: 401-on-first-use is the *default* state of a freshly started community container,
so this is likely the first error many new users encounter.

---

## Defect 2 — `journal_search` returns an empty global and appears to ignore `global_pattern`

**Severity: High.** The tool returns results that look valid and are not filtered as requested.

### Reproduction

```console
$ python3 mcpcall.py journal_search '{"global_pattern":"IadCheck","max_entries":5}'
{"entries":[
  {"global":"","job_id":502,"timestamp":"2026-08-16 18:59:18","type":"SET"},
  {"global":"","job_id":504,"timestamp":"2026-08-16 18:59:18","type":"SET"},
  {"global":"","job_id":504,"timestamp":"2026-08-16 18:59:18","type":"SET"},
  {"global":"","job_id":504,"timestamp":"2026-08-16 18:59:18","type":"ZKILL"},
  {"global":"","job_id":481,"timestamp":"2026-08-16 18:59:18","type":"SET"}
],"returned":5,"success":true}
```

Every `global` is empty, and the five records returned have nothing to do with `IadCheck`.

### Cause

`journal_search_impl` (`crates/iris-agentic-dev-core/src/tools/admin_tools.rs`) gates both the
`GlobalReference` read and the `global_pattern` filter on:

```objectscript
If rec.TypeName="SetKillRecord" { ... }
```

`TypeName` does not take that value. `SetKillRecord` is the **class** name. Measured across 4,000
records in the current journal file on 2026.2:

```
distinct TypeName values seen: SET; ZKILL; BeginTrans; CommitTrans; KILL
matches for TypeName="SetKillRecord": 0 (out of 4000)
```

while `$classname(rec)` for those same records is `%SYS.Journal.SetKillRecord`:

```
TypeName='SET'    class=%SYS.Journal.SetKillRecord  gref=^["^^/usr/irissys/mgr/"]SYS("LastLicenseKey")
TypeName='ZKILL'  class=%SYS.Journal.SetKillRecord  gref=^["^^/usr/irissys/mgr/"]SYS("JRNZIP","pid")
```

So the guard never fires: `gref` is never populated, and because the filter lives behind the same
guard, `global_pattern` never excludes anything.

### Suggested fix

Discriminate on the class rather than the type name:

```objectscript
If $classname(rec)["SetKillRecord" { Set gref = rec.GlobalReference }
```

or test the type against the real domain (`"SET"`, `"KILL"`, `"ZKILL"`).

### Scope of this evidence

One journal file, one IRIS version (2026.2), non-mirrored, no ECP. The conclusion follows
necessarily *if* the observed `TypeName` domain is complete; I did not verify that across versions
or against mirrored/ECP journals. Please confirm the comparison was not intended to match something
else before treating this as settled.

**Note**: this same mistake reached our own spike code, written after reading this implementation.
It is an easy one to make — `TypeName` reads like it should hold the class name.

---

## Defect 3 — `tool` subcommand advertises tools it cannot dispatch

**Severity: Medium** (discoverability, not correctness).

### Reproduction

```console
$ iris-agentic-dev tool resolve_storage -a '{"class":"User.IadCheck"}'
error: unknown tool: resolve_storage

$ iris-agentic-dev tool __nope__
error: unknown tool '__nope__'
available tools:
  ...
  resolve_storage        ← listed here
  ...
```

Four tools are listed but unreachable from the CLI:

| Tool | `tool` CLI | MCP stdio |
|---|---|---|
| `iris_doc_search` | `unknown tool` | works |
| `journal_search` | `unknown tool` | works |
| `resolve_storage` | `unknown tool` | works |
| `my_access` | `unknown tool` | works |

Spot-checked as dispatching normally: `iris_info`, `iris_query`, `iris_execute`, `iris_global`,
`iris_table_info`, `docs_introspect`, `kb`.

### Cause

`ToolCommand::run` validates the name against `TOOL_NAMES` (the full Merged toolset), then
dispatches through `tools.call_for_test(&name, ...)`, whose coverage is narrower. The two error
messages differ — the first from the CLI's own validation, the second from core — which is how the
gap is visible.

### Suggested fix

Either route the CLI through the same registry the MCP server uses, or filter the advertised list
to what `call_for_test` actually handles. The second is a one-liner and removes the surprise.

### A retraction

An earlier draft of this report claimed the gap contradicted a comment asserting a test enforces
parity. **That was a misreading.** The comment on `TOOL_NAMES` says it tracks
`IrisTools::registered_tool_names(Toolset::Merged)` — a different relation that says nothing about
dispatch coverage — and `call_for_test` is named like a deliberately narrow test entry point. This
may well be intended behaviour, in which case only the advertised list needs adjusting.

---

## What worked well

Worth recording alongside the defects:

- **Build from source was clean** — `cargo build --release`, 3m23s, no intervention.
- **`iris_table_info` handled a DDL-created table correctly**, returning the hashed global
  `^poCN.DvER.1` via the class projection rather than falling back to name inference.
- **`resolve_storage` agreed** — `^poCN.DvER.1` / `^poCN.DvER.I`, storage type
  `%Storage.Persistent`.
- **The MCP stdio transport worked first try** against a hand-rolled JSON-RPC client (`initialize`
  → `notifications/initialized` → `tools/call`), which is what made defects 2 and 3 separable.

Both storage results independently corroborated the `043-local-first-sync` Q2 spike, which is what
the tool was brought in to do.

### A note on `sql_table_inspect`'s inference fallback — *not* filed as a defect

`table_info_impl` falls back to inferring `^Schema.TableD` when the class-projection lookup finds
no row. On 2026.2 that convention holds for class-defined tables (`Spike.Legacy` →
`^Spike.LegacyD`, verified present) and does **not** hold for DDL-created ones (`SQLUser.SpikeQ2` →
`^poCN.DyVu.1`, with `^SQLUser.SpikeQ2D` absent).

An earlier draft called this a proven bug. **Retracted.** Both behaviours are documented IRIS
storage design; the fallback is a reasonable heuristic for the case it targets; and it is not
reached for DDL tables anyway, because the class projection resolves first. Flagging it only as a
latent edge case worth a comment in the code, at most.

---

## Reproduction environment

The container and binary used here are ephemeral. To reproduce:

```bash
docker run -d --name iris-pgwire-db -p 1972:1972 -p 52773:52773 \
  intersystems/iris-community:latest-cd --check-caps false

# Community image: clear the initial password state before connecting
cat > /tmp/pw.txt <<'EOF'
 set props("Password")="SYS" do ##class(Security.Users).Modify("_SYSTEM",.props)
 do ##class(Security.Users).UnExpireUserPasswords("*")
 HALT
EOF
docker exec -i iris-pgwire-db iris session IRIS -U %SYS < /tmp/pw.txt

curl -fsSL https://github.com/intersystems-community/iris-agentic-dev/releases/latest/download/iris-agentic-dev-linux-x86_64 \
  -o /usr/local/bin/iris-agentic-dev && chmod +x /usr/local/bin/iris-agentic-dev

export IRIS_HOST=localhost IRIS_WEB_PORT=52773 IRIS_USERNAME=_SYSTEM IRIS_PASSWORD=SYS
iris-agentic-dev query "SELECT \$ZV"
```

## Related

- [iris-pgwire-iad-setup-issues.md](iris-pgwire-iad-setup-issues.md) — the iris-pgwire-side issues
  from the same session, kept separate so this report can be filed upstream unedited
- `specs/043-local-first-sync/research.md` §7 — the spike results this tool corroborated
- `specs/043-local-first-sync/spikes/` — the probe harness, including the `TypeName` fix
