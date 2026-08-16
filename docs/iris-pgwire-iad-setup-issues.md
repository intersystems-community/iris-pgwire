# [RESOLVED] iris-pgwire issues found while setting up iris-agentic-dev

**Status**: ✅ RESOLVED — both fixed in the same commit that filed this
**Scope**: defects in **iris-pgwire's own** packaging and documentation
**Date**: 2026-08-16

> Defects in the iris-agentic-dev tool itself are tracked separately in
> [iris-agentic-dev-bug-report.md](iris-agentic-dev-bug-report.md), so that report can be filed
> upstream without carrying our issues into someone else's tracker.

## Summary

Setting up iris-agentic-dev against a live IRIS 2026.2 container surfaced two problems that belong
to this repository, not to the tool. Both were in instructions a new contributor would follow
literally, and both fail in ways that point away from the real cause.

| # | Issue | Impact | Status |
|---|-------|--------|--------|
| 1 | `AGENTS.md` configures the SQL port where the web port is required | Silent misconfiguration → confusing connection error | ✅ Fixed |
| 2 | `pyproject.toml` `[ai]` extra declares a package that is not installable | `pip install iris-pgwire[ai]` fails outright | ✅ Fixed in docs; `pyproject.toml` decision outstanding |

---

## Issue 1 — `AGENTS.md` documented the SQL port

**Severity**: Medium. Fails at connection time with an error that does not mention configuration.

`AGENTS.md` documented the iris-agentic-dev connection block as:

```toml
[connections.iris-pgwire-db]
host = "localhost"
port = 2972          # ← the IRIS superserver (SQL) port
```

iris-agentic-dev connects over the **Atelier REST API on the web port**, not the SQL port. Its
flags are all web-oriented (`--host`, `--web-port`, `--web-prefix`, `--scheme`), and the default is
`52773`.

### Why this fails quietly

`port` is a **serde alias for `web_port`** in the tool's config schema
(`crates/iris-agentic-dev-core/src/iris/workspace_config.rs:15`). So the line does not error as an
unknown key — it parses successfully and sets the *web* port to `2972`. The tool then makes HTTP
requests against the superserver port, and the resulting failure looks like a network or auth
problem rather than a config mistake.

Contributing factor: the surrounding prose in `AGENTS.md` lists the container's ports as
`2972 (IRIS DBAPI)` and `52776 (web portal)`, so `2972` looks like the obvious choice unless you
already know the tool speaks HTTP.

### Fix

`AGENTS.md` now uses `web_port` explicitly, points at the mapped web port, and carries a warning
against the alias:

```toml
[connections.iris-pgwire-db]
host = "localhost"
web_port = 52776   # iad connects over the Atelier REST API on the WEB port,
                   # not the SQL port. Use the host port mapped to IRIS 52773.
```

> **Do not put the SQL port here.** `port` is accepted as an alias for `web_port`, so `port = 2972`
> parses cleanly and silently points iad at the SQL port.

**Also raised upstream** as a suggestion, not a defect: the tool could warn when a configured port
looks like a superserver port (1972 / 51773 / 2972).

---

## Issue 2 — the `[ai]` extra promises an install that cannot succeed

**Severity**: Medium. The documented install path fails on a clean machine.

`pyproject.toml` declares:

```toml
ai = [
    "iris-agentic-dev>=1.0",
]
```

and `AGENTS.md` instructed `pip install iris-pgwire[ai]`. That package is not on PyPI:

```console
$ pip install iris-agentic-dev
ERROR: Could not find a version that satisfies the requirement iris-agentic-dev
       (from versions: none)
ERROR: No matching distribution found for iris-agentic-dev
```

Sibling projects in the same org do resolve (`iris-devtester`, `iris-vector-graph` → 200), so this
is specific to iris-agentic-dev — which is a **Rust binary**, and may never have been intended to
ship as a Python package.

### Fix

`AGENTS.md` no longer promises a pip install. It documents the real distribution channels:

```bash
# Linux x86-64
curl -fsSL https://github.com/intersystems-community/iris-agentic-dev/releases/latest/download/iris-agentic-dev-linux-x86_64 \
  -o /usr/local/bin/iris-agentic-dev && chmod +x /usr/local/bin/iris-agentic-dev

# macOS (Apple Silicon)
brew install https://raw.githubusercontent.com/intersystems-community/iris-agentic-dev/master/Formula/iris-agentic-dev.rb
```

### Outstanding decision

**The `[ai]` extra in `pyproject.toml` is still declared and still unsatisfiable.** The docs no
longer point at it, so nobody is led into the failure, but `pip install iris-pgwire[ai]` remains
broken for anyone who finds the extra by other means. Three options:

1. **Remove the extra.** Cleanest, if nothing else will ever go in it.
2. **Keep it and empty it**, with a comment pointing at the binary install.
3. **Leave it**, on the expectation that iris-agentic-dev publishes a PyPI shim.

Deferred pending the upstream answer to the distribution question in the
[iris-agentic-dev report](iris-agentic-dev-bug-report.md#1-not-distributed-on-pypi--intentional).
Option 2 is the recommendation if that answer is "no PyPI planned".

---

## Verification

After both fixes, following `AGENTS.md` from scratch against a fresh container reaches a working
connection:

```console
$ iris-agentic-dev query "SELECT 1 AS ok, \$ZV AS version"
ok      version
1       IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.2 (Build 221U) ...
```

One step remains manual and is not an iris-pgwire bug: a freshly started
`intersystems/iris-community` container leaves `_SYSTEM` in a state where the Atelier API returns
401 until the password is set and un-expired. That is documented in the reproduction section of the
upstream report.

## Related

- [iris-agentic-dev-bug-report.md](iris-agentic-dev-bug-report.md) — the three upstream defects
- `AGENTS.md` — the corrected setup instructions
- `specs/043-local-first-sync/spikes/iris-agentic-dev.toml.example` — working config template
