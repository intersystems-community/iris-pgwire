# Implementation Plan: surp Lint and ERD Support

**Branch**: `047-surp-lint-support` | **Date**: 2026-08-24 | **Spec**: [spec.md](spec.md)

## Summary

Enable surp's lint and ERD features against IRIS by implementing three PostgreSQL
output-column functions (`format()`, `jsonb_build_object()`, `ARRAY[...]`), adding
`ANY(column)` rewriting for catalog array columns, and adding five new empty or
data-backed catalog views (`pg_depend`, `pg_extension`, `pg_index`, `pg_policy`,
`pg_rewrite`). Together these unblock 5 of 15 lint checks and the FK ERD view without
requiring any client-side workaround.

## Technical Context

**Language/Version**: Python 3.11 (irispython / CPython both supported)
**Primary Dependencies**: existing iris-pgwire stack — `sql_translator/`, `catalog/`,
`catalog/views/definitions.py`, `catalog/functions.py`
**Storage**: IRIS catalog views (SQL DDL installed via `CatalogViewInstaller`); SQL
function bodies via `CatalogFunctionInstaller`
**Testing**: pytest + real IRIS instance (Constitution II); unit tests for pure-Python
rewriting logic (no IRIS needed)
**Target Platform**: IRIS 2024.x+ (embedded Python and DBAPI backends both must pass)
**Performance Goals**: translation-only overhead ≤ 10 ms per query (SC-005; the general
5 ms budget in Constitution V is for simpler queries — the lint SQL is a 15-branch
multi-CTE UNION, so 10 ms is the agreed ceiling for this feature)
**Constraints**: no client-side workarounds; unsupported checks must return zero rows
(not errors); both embedded-Python and DBAPI backends must pass
**Scale/Scope**: catalog-layer change only; no protocol changes, no query result
serialisation changes beyond new function return types

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

Evaluate against `.specify/memory/constitution.md` v1.0.0.

| #   | Principle              | Gate                                                                                                                                                                | Status                                    |
| --- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| I   | Protocol Fidelity      | No client-side workaround — unsupported checks return zero rows, not errors; `format()`/`jsonb_build_object()`/`ARRAY[]` return values compliant with PG wire types | PASS                                      |
| II  | Test-First Development | E2E tests against real IRIS (surp's lint SQL executed verbatim); unit tests for format/jsonb/ARRAY rewriting logic; no mocks                                        | PASS — tests written first per task order |
| III | Phased Implementation  | P0: research on `ANY(col)` INSTR rewrite pattern and existing `conkey` storage format. P1: design and contracts. P2: tasks. All phases have exit criteria below     | PASS                                      |
| IV  | IRIS Integration       | Catalog view DDL and SQL function DDL work on both embedded and DBAPI paths (same installer used by feature 044)                                                    | PASS                                      |
| V   | Production Readiness   | Translation overhead measured for the full lint SQL; `ARRAY[...]` rewrite and `ANY(col)` rewrite are O(n) regex passes with no new async paths                      | PASS — budget stated as ≤10 ms            |
| VI  | Vector Performance     | No vector operations involved                                                                                                                                       | N/A                                       |

**Technical Constraints**:

- `import iris` (not `intersystems_irispython`) — not affected by this change
- Container restart required after installing new catalog views — captured in tasks
- `public` → IRIS schema mapping — unaffected; new views follow the same `IRIS_SCHEMA`
  pattern as existing ones

## Project Structure

### Documentation (this feature)

```text
specs/047-surp-lint-support/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── quickstart.md        ← Phase 1 output
└── tasks.md             ← Phase 2 output (/speckit.tasks)
```

### Source Code (existing layout, changes in-place)

```text
src/iris_pgwire/
├── catalog/
│   ├── functions.py              ← ADD: FORMAT, JSONB_BUILD_OBJECT SQL functions
│   └── views/
│       └── definitions.py        ← ADD: PG_DEPEND, PG_EXTENSION, PG_INDEX,
│                                          PG_POLICY, PG_REWRITE views;
│                                          register in CATALOG_VIEWS tuple
├── sql_translator/
│   ├── array_params.py           ← ADD: rewrite_any_col_to_instr() for ANY(col)
│   ├── pg_functions.py           ← ADD: 'format' and 'jsonb_build_object'
│   │                                     to PG_FUNCTION_MAP (redirect to PGWire.*)
│   └── pipeline.py               ← VERIFY: array_params rewrites are in the pipeline
│                                   ADD: ARRAY[...] SELECT-column rewriter pass

tests/
├── unit/
│   └── test_047_surp_lint.py     ← unit tests (format, jsonb, ARRAY[], ANY(col))
└── e2e/
    └── test_047_surp_e2e.py      ← E2E: full lint SQL + ERD query against real IRIS
```

## Phase 0: Research

All research items have been resolved by reading the existing codebase — no external
spike required because the constraints are already encoded in comments:

### R1 — `ANY(col)` rewrite pattern (conkey/indkey)

**Decision**: Regex rewrite `expr = ANY(col)` → `INSTR(',' || col || ',', ',' || CAST(expr AS VARCHAR) || ',') > 0`

**Rationale**: `conkey` is already stored as `{1,2,...}` PostgreSQL int2[] text format
(brace-comma-separated). The rewrite must handle this format. `INSTR(',' || col || ',')`
requires stripping the outer braces first — the rewrite becomes:
`INSTR(',' || REPLACE(REPLACE(col, '{', ''), '}', '') || ',', ',' || CAST(expr AS VARCHAR) || ',') > 0`

**Scope**: only `= ANY(col)` where the operand is a bare column reference (not a `$n`
parameter — that case is already handled by `rewrite_any_to_inlist()`). Applied by
`array_params.py` after the existing parameter-based rewrite.

**Alternatives considered**: expand FK rows in the catalog view (one row per conkey
element) — rejected because it would multiply result set size and break aggregate queries
like `COUNT(DISTINCT conname)`. JSON_CONTAINS — rejected because IRIS SQL has no
JSON_CONTAINS function.

---

### R2 — `format()` implementation approach

**Decision**: Install as a PGWire SQL function (`PGWire.FORMAT`) in `catalog/functions.py`,
redirect unqualified `format(` calls via `pg_functions.py` PG_FUNCTION_MAP.

**Rationale**: Same pattern already used for `format_type`, `obj_description`,
`pg_get_expr`, `col_description`. The ObjectScript body implements `%s`, `%I`, `%L`
substitution with a `while` loop (no colons in loop syntax per existing codebase note).

**`%I` quoting**: wrap value in double-quotes, escape internal double-quotes by doubling.
**`%L` quoting**: wrap value in single-quotes, escape internal single-quotes by doubling.
**NULL handling**: PostgreSQL `format()` with a NULL argument returns NULL — implemented
as an early `if arg = "" { quit "" }` guard per IRIS convention.

---

### R3 — `jsonb_build_object()` implementation approach

**Decision**: Install as `PGWire.JSONB_BUILD_OBJECT` SQL function; redirect via
`pg_functions.py`. Returns a `VARCHAR` containing a JSON object string (not a JSONB
binary — IRIS has no JSONB type; wire protocol sends it as text OID 114 / json, which
surp accepts identically).

**Implementation**: ObjectScript reads paired arguments from a delimited string
(same encoding as PG_ARRAY uses), builds `{"k":"v",...}`. Odd argument count →
raise SQLCODE -400 with message matching PostgreSQL's error text.

**Alternative**: A pure-SQL implementation with repeated `|| '"' || key || '":"' || val`
concatenation would require knowing the argument count at compile time — impossible for
variadic. ObjectScript body is required.

---

### R4 — `ARRAY[...]` SELECT-column rewriting

**Decision**: Regex pre-pass in `pipeline.py` (or a new `array_literal.py` module)
rewrites `ARRAY['a', 'b', ...]` in SELECT output columns to `'{a,b,...}'` (a plain
string literal in PostgreSQL int2[] text format).

**Scope guard**: only match `ARRAY[` in the SELECT list, not inside WHERE/JOIN. A
conservative approach: apply the rewrite to the full SQL text but only match
`ARRAY[` that is not preceded by an operator or comparison token. Given that surp's
uses of `ARRAY[...]` are always in a `ARRAY['PERFORMANCE']` SELECT expression, a
simple `ARRAY\[` → brace-string conversion is safe.

**Alternatives considered**: AST-based rewriting — overkill; the current translator
uses regex throughout and this pattern is simple.

---

### R5 — New catalog views: pg_depend, pg_extension, pg_index, pg_policy, pg_rewrite

**pg_depend** — always empty. Schema (PostgreSQL 15 measured):
`(classid oid, objid oid, objsubid int4, refclassid oid, refobjid oid, refobjsubid int4, deptype "char")`

**pg_extension** — always empty. Schema:
`(oid oid, extname name, extowner oid, extnamespace oid, extrelocatable bool, extversion text)`

**pg_index** — data-backed. Query from `INFORMATION_SCHEMA.TABLE_CONSTRAINTS` for PK/UNIQUE
constraints (same source as `pg_constraint`). `indkey` stored as space-separated text
(e.g., `"1 2"`) per clarification Q5 (mirrors PG `int2vector` serialisation).
Schema subset required by surp: `(indexrelid, indrelid, indnatts, indnkeyatts,
indisunique, indisprimary, indisvalid, indkey, indisready, indislive)`.

**pg_policy** — always empty. Schema:
`(oid oid, polname name, polrelid oid, polcmd "char", polpermissive bool, polroles oid[], polqual text, polwithcheck text)`

**pg_rewrite** — always empty. Schema:
`(oid oid, rulename name, ev_class oid, ev_type "char", ev_enabled "char", is_instead bool, ev_qual text, ev_action text)`

**Decision**: `pg_index` as a live view (data-backed) because `pg_stat_user_indexes`
lint check checks `not in (select indexrelid from pg_index)` — an empty pg_index would
cause false positives. `pg_depend`, `pg_extension`, `pg_policy`, `pg_rewrite` are
always empty because IRIS has no equivalent objects.

---

## Phase 1: Design & Contracts

### Data Model

See `data-model.md` (generated below).

### Contracts

This feature has no HTTP/RPC API surface. The "contract" is the SQL function signatures
and catalog view schemas — documented in `contracts/` below.

### Component Design

#### 1. `catalog/functions.py` — new SQL functions

```text
PGWire.FORMAT(pattern VARCHAR, args VARCHAR) RETURNS VARCHAR
  - args is a PG_ARRAY-encoded variadic argument list (same encoding as PG_ARRAY uses)
  - Caller passes args via a helper rewrite or as a single encoded string
```

**PROBLEM**: SQL functions in IRIS do not support variadic arguments. PostgreSQL's
`format(pattern, a, b, c, ...)` has a variable number of arguments. The PG_FUNCTION_MAP
redirect must collect all arguments into a single encoded string before passing to
`PGWire.FORMAT`.

**Solution**: Add a new rewrite pass in `pg_functions.py` specifically for `format(`:
capture the full argument list text, URL/delimiter-encode it as `PGWire.FORMAT(pattern,
PGWire.PG_ARRAY_PACK(arg1, arg2, ...))`, where `PGWire.PG_ARRAY_PACK` is a new
variadic-ish aggregate. **Simpler alternative**: since surp's `format()` calls always
have exactly 2 arguments (the `format('%I', table_name)` pattern), implement
`PGWire.FORMAT(pattern VARCHAR, arg1 VARCHAR)` for the 2-arg case and
`PGWire.FORMAT3(pattern VARCHAR, arg1 VARCHAR, arg2 VARCHAR)` for 3-arg. The
`pg_functions.py` rewrite determines the argument count and routes accordingly.

**Decision**: 2-arg and 3-arg fixed-arity functions (`PGWire.FORMAT2`,
`PGWire.FORMAT3`). The rewrite in `pg_functions.py` counts arguments and calls the
right variant. This avoids variadic encoding complexity entirely.

```text
PGWire.FORMAT2(pattern VARCHAR, arg1 VARCHAR) RETURNS VARCHAR
PGWire.FORMAT3(pattern VARCHAR, arg1 VARCHAR, arg2 VARCHAR) RETURNS VARCHAR

PGWire.JSONB_BUILD_OBJECT(args VARCHAR) RETURNS VARCHAR
  - args is a PG_ARRAY-encoded key/value list
  - pg_functions.py packs all arguments: jsonb_build_object(k1,v1,k2,v2)
    → PGWire.JSONB_BUILD_OBJECT(PGWire.PG_PACK(k1, v1, k2, v2))
```

**PROBLEM**: `PGWire.JSONB_BUILD_OBJECT` has the same variadic problem.
**Solution**: Same fixed-arity approach — inspect argument count in the rewrite and
call `PGWire.JSONB_BUILD_OBJECT2(k1, v1)`, `PGWire.JSONB_BUILD_OBJECT4(k1,v1,k2,v2)`,
etc. surp uses `jsonb_build_object('type','lint','check_id',...)` — exactly 4 arguments
in the lint SQL. Implement 2-key (4-arg) and 3-key (6-arg) variants; add more as needed.

#### 2. `sql_translator/pg_functions.py` — function rewriting

Add rewriting logic (not just a name map) for `format` and `jsonb_build_object`:

- Count arguments by parsing the argument list text
- Route to the appropriate fixed-arity `PGWire.*` function
- Leave qualified calls (`pg_catalog.format(...)`) untouched

#### 3. `sql_translator/array_params.py` — `ANY(col)` column rewrite

New function `rewrite_any_col_to_instr(sql)`:

```text
Pattern: (\w+(?:\.\w+)?)\s*=\s*ANY\s*\(\s*([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)?)\s*\)
         where the ANY operand is NOT a $n/$? placeholder (already handled)
         and NOT a quoted string literal (already handled by expand_array_literals)

Rewrite:
  attnum = ANY(con.conkey)
  → INSTR(',' || REPLACE(REPLACE(con.conkey, '{', ''), '}', '') || ',',
           ',' || CAST(attnum AS VARCHAR) || ',') > 0
```

Applied after `rewrite_any_to_inlist()` (which handles `$n`) and
`expand_array_literals()` (which handles string literals).

#### 4. `sql_translator/pipeline.py` — `ARRAY[...]` rewrite

New function `rewrite_array_literals(sql)` in a new `array_literal.py` module:

```text
Pattern: ARRAY\s*\[\s*((?:'[^']*'(?:\s*,\s*'[^']*')*)?)\s*\]
         matched case-insensitively

Rewrite: ARRAY['PERFORMANCE', 'SCHEMA'] → '{PERFORMANCE,SCHEMA}'
         (a plain string literal in PostgreSQL array text format)
```

Injected early in the pipeline, before the main translator, since IRIS cannot parse
`ARRAY[...]` syntax at all.

#### 5. `catalog/views/definitions.py` — new views

Five new `CatalogView` objects added and registered in `CATALOG_VIEWS` tuple.

### Constitution Check (post-design)

Re-evaluated after Phase 1 design:

| #   | Principle            | Status                                                                                                                                                                 |
| --- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| I   | Protocol Fidelity    | PASS — `format()` and `jsonb_build_object()` return correct PG wire types; empty views return valid empty result sets; `ARRAY[]` rewrite produces PG array text format |
| II  | Test-First           | PASS — unit tests precede implementation tasks in task order                                                                                                           |
| III | Phased               | PASS — research done, design complete, tasks next                                                                                                                      |
| IV  | IRIS Integration     | PASS — fixed-arity ObjectScript functions avoid variadic encoding; both backends use same installer                                                                    |
| V   | Production Readiness | PASS — rewrite passes are regex O(n); budget is 10 ms for this query shape                                                                                             |
| VI  | Vector Performance   | N/A                                                                                                                                                                    |

One complexity item to track:

| Complexity                                                                                          | Why Needed                                           | Simpler Alternative Rejected                                                                                                                                                                               |
| --------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fixed-arity `FORMAT2`/`FORMAT3` and `JSONB_BUILD_OBJECT4`/`JSONB_BUILD_OBJECT6` instead of variadic | IRIS SQL functions do not support variadic arguments | True variadic would require PG_ARRAY encoding + packing on the rewrite side, adding a new encoded wire format and a new function; fixed-arity is simpler and matches actual usage patterns in splinter.sql |

## Complexity Tracking

| Violation                                      | Why Needed                                | Simpler Alternative Rejected Because                                                          |
| ---------------------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------------------------- |
| Fixed-arity FORMAT/JSONB_BUILD_OBJECT variants | IRIS SQL has no variadic function support | True variadic needs a new encoding wire format; fixed-arity covers all actual surp call sites |
