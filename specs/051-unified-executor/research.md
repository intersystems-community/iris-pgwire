# Phase 0 Research: Unified Executor

**Feature**: `051-unified-executor`
**Date**: 2026-09-20
**Status**: Complete — R1–R5 answered by measurement, R6 answered negatively with a named blocker

Every number below was measured on this machine on 2026-09-20 against this
repository's own containers: `iris-pgwire-db` (IRIS 2026.1 CE, host port 2972)
and `iris-pgwire-pgref` (PostgreSQL 16.14, host port 55432). Probe scripts live
in `spikes/` and print one `KEY: value` line per measurement so a claim can be
re-derived rather than believed.

Two findings reverse things this feature previously recorded as settled. Both
are called out as **Correction** and both change the design.

---

## R1. How many adapters are there — two or three?

**Decision: two.** `IRISExecutor._execute_external_async` and `DBAPIExecutor`
drive the _same_ adapter under two names. The `Capabilities` type needs two
columns, not three, and the external path is deleted in US6 rather than ported.

### Method and result

`iris_executor.py:3640` calls `iris.connect(hostname=, port=, namespace=,
username=, password=)`; `dbapi_connection_pool.py:313` calls
`iris.dbapi.connect(...)` with the identical keyword arguments. Feature 045
asked whether these are one thing or two and never checked.

`spikes/probe_r1_host_adapters.py` compares them across 29 measurements:
connection type and MRO, public attribute sets, cursor type, rows, row type,
`description` with rows / with zero rows / before execute, rowcount for SELECT
and INSERT and DDL, empty-vs-NULL, qmark parameters, error type and MRO and text
and args, and the transaction surface.

**29 identical, 0 differing, 0 one-sided.** They are distinct function objects
(`iris.connect` is `iris._elsdk_.connect`, `iris.dbapi.connect` is
`iris.dbapi.connect`) that both return `iris._elsdk_.IRISConnection`, whose
`.cursor()` is `iris.dbapi.Cursor` in both cases.

### The result survives a contaminated environment

The probe was run twice, and the verdict is the same both times:

| Environment                                  | `iris.connect` resolves to                | Verdict         |
| -------------------------------------------- | ----------------------------------------- | --------------- |
| Clean venv, `intersystems-irispython==5.3.2` | `iris._elsdk_.connect`                    | 29/29 identical |
| Repository `.venv` (wrapper installed)       | `_iris_ep._runtime_facade.public_connect` | 29/29 identical |

This matters because the repository's own `.venv` has
`iris-embedded-python-wrapper 0.5.21` installed alongside _two_ overlapping
`intersystems_irispython` dist-infos (5.2.1 and 5.3.2), and SDK 5.3.2's
`iris/__init__.py` deliberately hands the module over when the wrapper is
present:

```python
file_name_ep = os.path.join(os.path.dirname(current_dir), "iris_ep.py")
if os.path.exists(file_name_ep):
    from iris_ep import *
    from iris_ep import __getattr__
```

That is not accidental shadowing — it is an SDK-sanctioned handoff, including
the attribute-manufacturing `__getattr__` that ADR-0002 warns about. It
**strengthens** ADR-0002 rather than contradicting it. The measured consequence
is narrow: the wrapper replaces `iris.connect` only, leaves `iris.dbapi`
untouched, and does not change any of the 29 observable behaviours.

### Why R1 could not be answered inside the container

The first attempt ran the probe under `/usr/irissys/bin/irispython`, where
`iris.__file__` is `/usr/irissys/lib/python/iris/__init__.py` — IRIS's own
embedded wrapper package, not the pip SDK. There, `iris.connect` and
`iris.dbapi.connect` are both uncallable `iris.package` objects:

```text
NameError: Cannot call an iris.package wrapper. ... Given name was: connect
NameError: Cannot call an iris.package wrapper. ... Given name was: dbapi.connect
```

**This is a capability fact, not just a probe failure: the DBAPI adapter is
unreachable from inside an `irispython` process.** The two adapters are not
merely different code paths, they are available in disjoint environments. FR-012
(refuse impossible configurations loudly at startup) must therefore treat
"DBAPI requested while running under `irispython`" as one of the configurations
it refuses.

### Consequence for the design

`_execute_external_async` (`iris_executor.py:3278+`) is not a third adapter
needing a third capability column. It is a second implementation of the DBAPI
adapter living inside the embedded executor's file, and it already calls
`_prepare_sql`, so it inherits the 8-step preparation that `DBAPIExecutor` does
not get. US6 deletes it; nothing is lifted out of it first.

---

## R2. Can the embedded backend report per-column types by any route?

**Correction. Decision: yes — and the type codes are identical to the DBAPI
adapter's.** An earlier pass in this feature recorded "no metadata by any route
tried". That conclusion was wrong: it used the wrong API names. The corrected
result changes the US3 design.

### Method and result

`%SQL.Statement` is reachable and populated, using ObjectScript names as the
Python wrapper exposes them (`_Prepare`, `_Metadata`, and `GetAt` — _not_
`prepare`, `getvalue("%Metadata")`, `_GetAt`):

```text
_Prepare("SELECT 'x' AS s, 42 AS i, CAST(1 AS BIT) AS b")  ->  1
stmt._Metadata      ->  iris.%SQL.StatementMetadata
md.columnCount      ->  3
md.columns          ->  iris.%Collection.ListOfObj
md.columns.GetAt(i) ->  iris.%SQL.StatementColumn
```

Per column, every field the wire needs is present:

| Column | `colName` | `ODBCType` | `clientType` | `precision` | `scale` | `isNullable` |
| ------ | --------- | ---------- | ------------ | ----------- | ------- | ------------ |
| 1      | `s`       | 12         | 10           | 32          | `'0'`   | 2            |
| 2      | `i`       | 4          | 5            | 10          | `'0'`   | 2            |
| 3      | `b`       | -7         | 16           | 1           | `'0'`   | 2            |

The DBAPI adapter's `cursor.description` for the same statement reports
`[('s', 12), ('i', 4), ('b', -7)]`. **The ODBC type codes agree exactly.**

What remains true from the earlier pass is narrower than what was recorded: the
`iris.sql.exec` result object (`iris.%SYS.Python.SQLResultSet`) has no metadata
member — its `dir()` is `['IterationStarted', 'ResultSet', ... 'dataframe',
'oref']` plus `%`-methods, with no `_meta` and no `description`. The mistake was
generalising from that one route to "no route".

### Consequence for the design

1. **One ODBC-type table serves both adapters.** FR-009 ("where the driver
   reports a usable type, use it") is achievable on embedded, not just DBAPI.
2. **FR-010's declared-absence fallback is not the embedded common case.** It
   narrows to the `iris.sql.exec` route specifically. US3 should prepare via
   `%SQL.Statement` precisely so that metadata is available.
3. **Embedded can describe without executing; DBAPI cannot.** `_Prepare`
   populates `_Metadata` before any execution, whereas the DBAPI adapter's
   `description` is `None` until `execute()` runs (measured, both environments).
   This is a genuine asymmetry and belongs in `Capabilities` as
   `describe_without_execute`. It is also the lever for the extra connection
   `handle_describe_message` opens under CE's licence ceiling.
4. **045's `_map_dbapi_type_to_oid` defect is confirmed on live data.** It
   collapses 12, -7 and 4 to OID 1043, so INTEGER and BIT are both reported to
   the client as varchar, on both adapters.

### A hazard worth recording

`dir()` on an `iris.%SQL.Statement` proxy **aborts the embedded Python process**
— exit 1, no exception, no traceback, uncatchable. `dir()` on
`iris.%SYS.Python.SQLResultSet` is fine, so the abort is class-specific. Any
introspection helper in the unified executor must probe named attributes rather
than enumerate them. Measured on IRIS 2026.1 CE.

---

## R3. What does the reference actually say?

**Decision: PostgreSQL 16.14 in this repository's own container is the
reference, and the divergence ledger needs a third disposition.** Q5 settled
that every difference is recorded as a deliberate _pin_ or a defect to _fix_,
with nothing unclassified. Measurement shows a third class exists that is
neither.

### The container

`docker-compose.yml` has no reference PostgreSQL _server_. Its two
`postgres:15-alpine` services are a psql client (`pgclient`, `command: sleep
infinity`, `PGHOST=iris`) and Metabase's own backing store. T002 therefore adds
a service rather than pointing at an existing one. `dxlab-postgres` belongs to
another project and was not used.

Reference captured from `iris-pgwire-pgref`, PostgreSQL 16.14, via
`spikes/probe_r3_reference_postgres.sql`.

### Reference answers, against the two adapters

| Question                           | PostgreSQL 16.14               | DBAPI adapter                               | Embedded adapter       | Disposition                |
| ---------------------------------- | ------------------------------ | ------------------------------------------- | ---------------------- | -------------------------- |
| Types of `'x'`, `42`, `BIT`        | `text`, `integer`, `bit`       | 12, 4, -7                                   | 12, 4, -7              | pin (IRIS has no `text`)   |
| Describe without executing         | yes, `{text,integer,bit}`      | no (`None`)                                 | yes (`%SQL.Statement`) | fix on DBAPI               |
| `''` vs `NULL`                     | `''`, `NULL`, not null         | `('', None)`                                | `('\x00', '')`         | fix on embedded            |
| Zero-row SELECT reports types      | yes                            | yes                                         | yes (`_Prepare`)       | agrees                     |
| Missing table                      | `42P01` relation ... not exist | SQLCODE -30 in text, no `sqlcode` attribute | bare text, no code     | fix both (map to SQLSTATE) |
| `INSERT` one row / multi-row       | `INSERT 0 1` / `INSERT 0 2`    | rowcount 1                                  | —                      | agrees                     |
| `UPDATE` / `DELETE`                | `UPDATE 1` / `DELETE 1`        | rowcount 1                                  | —                      | agrees                     |
| DDL                                | `CREATE TABLE`                 | rowcount 0                                  | —                      | agrees                     |
| SELECT rowcount                    | n/a (row count in tag)         | **-1**                                      | —                      | pin, must not reach a tag  |
| Unquoted identifier                | folds to lower (`cola`)        | —                                           | —                      | see note                   |
| `"ColA"` quoted after unquoted DDL | errors, hints `cola`           | —                                           | —                      | see note                   |

Identifier folding is the reference behaviour behind commit 43e3cde
("stop asserting a case convention the normalizer abandoned"). PostgreSQL folds
unquoted identifiers to lower case and then _rejects_ `"ColA"`; IRIS does not.
Any case assertion in the ledger has to name which of the two it is asserting.

### The third disposition

Six probe statements have **no PostgreSQL answer at all**, so they cannot be
classified as pin or fix:

| Statement                                 | PostgreSQL 16.14                    |
| ----------------------------------------- | ----------------------------------- |
| `SELECT TOP 1 id FROM t`                  | syntax error at or near `1`         |
| `SELECT %ID FROM t`                       | syntax error at or near `%`         |
| `SELECT id FROM SQLUser.t`                | relation `sqluser.t` does not exist |
| `SELECT $SYSTEM.SQL.Util.GetOption(...)`  | syntax error at or near `$`         |
| `CAST('[1,2,3]' AS VECTOR(DOUBLE, 3))`    | type `vector` does not exist        |
| `'[1,2,3]'::vector <=> '[1,2,4]'::vector` | type `vector` does not exist        |

**Two decisions follow.** First, FR-014/FR-015 gain a third disposition —
_no reference answer_ — with the same requirement that nothing sits
unclassified; a divergence in IRIS-only dialect is adjudicated against the
project's own documented intent, not against PostgreSQL. Second, the last two
rows are avoidable: T002 should use a **pgvector-enabled image**
(`pgvector/pgvector:pg16`) so that `<=>` and `<#>` — the operators this
feature's headline defect concerns — become adjudicable against a real
reference instead of falling into the unadjudicable bucket. `<->` stays
unadjudicable by choice, since the constitution requires rejecting it.

---

## R4. What does preparation cost, and is unification affordable?

**Decision: unification is essentially free — 1.1% of the budget at worst. There
is no performance argument for the fork.**

### The three implementations are not nested, they are disjoint

The call sites settle what each path runs:

| Step                                  | embedded inline `:1206-1270` | `_prepare_sql` `:848-948`                 | DBAPI inline `:242-281` |
| ------------------------------------- | ---------------------------- | ----------------------------------------- | ----------------------- |
| `translate_transaction_command`       | yes                          | yes                                       | **no**                  |
| normalization (`_get_normalized_sql`) | no                           | yes                                       | **no**                  |
| the six rewrites                      | yes                          | no                                        | yes (**verbatim copy**) |
| `optimize_vector_query`               | no                           | yes                                       | **no**                  |
| `ReturningPlan.from_sql`              | no                           | yes, with `metadata_cache` and `executor` | yes, with **neither**   |
| `_translate_placeholders`             | no                           | no                                        | yes                     |

The six rewrites (`rewrite_array_literals`, `rewrite_any_to_inlist` +
`expand_array_literals` + `encode_inlist_params`, `rewrite_any_col_to_instr`,
`rewrite_boolean_projections`, `rewrite_pg_function_calls`,
`rewrite_boolean_literal_comparisons`) appear **twice in src**, line for line,
at `iris_executor.py:1230-1266` and `dbapi_executor.py:242-278`. This is the
FR-001 case stated with line numbers, and it is the mechanism that produced the
vector defect: a step added to one copy is simply absent from the other.

### Measured cost

`spikes/probe_r4_preparation_cost.py`, median of 200 runs per statement, against
the 5 ms budget:

| Statement               | six rewrites | `optimize_vector_query` | unified (both) | % of budget |
| ----------------------- | ------------ | ----------------------- | -------------- | ----------- |
| `plain_select`          | 0.0098 ms    | 0.0013 ms               | 0.0110 ms      | 0.2%        |
| `wide_select` (30 cols) | 0.0550 ms    | 0.0043 ms               | 0.0550 ms      | **1.1%**    |
| `vector_order_by`       | 0.0147 ms    | 0.0152 ms               | 0.0271 ms      | 0.5%        |
| `boolean_projection`    | 0.0389 ms    | 0.0011 ms               | 0.0416 ms      | 0.8%        |
| `pg_function`           | 0.0238 ms    | 0.0014 ms               | 0.0251 ms      | 0.5%        |

**The step DBAPI omits costs 0.0152 ms on the statement it exists for.** The
fork buys nothing measurable; it only loses correctness.

### The double refine is measurable, and it dominates

`SQLRefiner.refine` runs twice per statement (`normalizer.py:258` and
`pipeline.py:61`):

| Statement            | once      | twice     | % of budget wasted |
| -------------------- | --------- | --------- | ------------------ |
| `wide_select`        | 0.3047 ms | 0.6095 ms | **12.2%**          |
| `boolean_projection` | 0.0022 ms | 0.0043 ms | 0.1%               |

One redundant `refine` on a 30-column statement costs **5.5× the entire
six-rewrite block**. The answer to "is the double refine measurable or merely
untidy" is: measurable, and the single largest item in preparation. Collapsing
it to one call is worth a task in its own right.

### T028 reproduced, with a sharper trigger than recorded

The parameter-renumbering defect fires when the vector parameter is a **string**
— which is what a pgvector client sends over the wire — because
`optimize_vector_query` then inlines it as a literal and drops it from the
parameter list without renumbering what follows:

```text
in   SELECT id FROM docs ORDER BY embedding <=> $1 LIMIT $2   params=['[0.1,0.2]', 5]
out  SELECT id FROM docs ORDER BY (1 - VECTOR_COSINE(embedding,
     TO_VECTOR('[0.1,0.2]', DOUBLE))) LIMIT $2                params=[5]
                                              ^^ $2 with one parameter left
```

Two of five shapes hit it (`ORDER BY` with a trailing `LIMIT $n`, and a
projected distance with `LIMIT $n`). A `list` parameter escapes it only because
conversion _fails_ first (`Could not convert vector parameter: param_type=int`)
and the placeholder is left alone — so the bug fires precisely when the
conversion succeeds. The two-operator shape preserves `$1`/`$2` correctly,
making the behaviour inconsistent between one-operator and two-operator
statements. `<->` correctly raises `NotImplementedError`, as the constitution
requires.

These four rows are the first entries in the differential corpus, per the Q9
condition on the 1.8.0 fix.

### Incidental findings

- `optimize_vector_query` logs **two INFO records and a per-call metrics dict on
  every invocation**, including statements it does not modify. On the hot path
  this is noise that swamped the first measurement run.
- `_prepare_sql` step 7 re-runs `_get_normalized_sql(sql, ...)` on the
  **original** `sql` when `'"public"'` appears, discarding steps 1–6. Not timed
  here; flagged as a correctness question for US2.
- The normalizer class is `SQLTranslator`, not `SQLNormalizer`; the probe's
  normalizer benchmark did not run for that reason and the normalizer's own cost
  is still unmeasured. It is the one preparation step without a number.

---

## R5. What do the capabilities actually evaluate to?

**Decision: the values below, measured, not asserted.**

`KNOWN_LIMITATIONS.md:366-391` measures the embedded backend and states that
DBAPI is different because each session holds its own connection, but never
records the counter-measurement. `spikes/probe_r5_dbapi_sessions.py` supplies
it, and the result is more nuanced than the claim.

### Transaction ownership is per-session on DBAPI; isolation is not

Two DBAPI connections, A with `autocommit = False`:

```text
A: INSERT (id 1), uncommitted
B: SELECT COUNT(*)            ->  1     B sees A's uncommitted row
B: COMMIT                     ->  count still 1
A: ROLLBACK                   ->  count 0
fresh connection: COUNT(*)    ->  0     PostgreSQL would say 0
```

Compare embedded, where the final count is **1**: B's `COMMIT` commits A's work
and A's `ROLLBACK` has nothing to undo.

So the difference is real but it is about **ownership**, not isolation. On DBAPI
each session owns its transaction — `ROLLBACK` undoes its own work and one
client's `COMMIT` does not commit another's. On _both_ adapters a session sees
another's uncommitted rows. Recording "DBAPI has transaction isolation" would
overstate it and seed exactly the kind of unmeasured capability FR-011 exists to
prevent.

### Isolation levels: accepted versus in force

| Level              | PostgreSQL 16.14            | IRIS via DBAPI        |
| ------------------ | --------------------------- | --------------------- |
| `READ UNCOMMITTED` | accepted, reported in force | accepted              |
| `READ COMMITTED`   | accepted, reported in force | accepted              |
| `REPEATABLE READ`  | accepted, reported in force | rejected, SQLCODE -96 |
| `SERIALIZABLE`     | accepted, reported in force | rejected, SQLCODE -1  |

The `SERIALIZABLE` rejection is worth a ledger line of its own: the error
message _lists_ `SERIALIZABLE` among the expected tokens and then fails to parse
it.

Acceptance is not enforcement. The dirty read above was observed at the default
level, and the existing note that `READ COMMITTED` is accepted without being in
force stands. `isolation_levels_in_force` is therefore **empty on both
adapters**, while `isolation_levels_accepted` differs.

### The licence ceiling is real and the default exceeds it

Opening DBAPI connections one at a time until failure:

```text
opened 1 .. 7
8th:  iris.dbapi.OperationalError: <COMMUNICATION LINK ERROR> Failed to connect
      to server; Details: ... Unable to allocate a license
```

**7 concurrent connections**, against `server.py:76 connection_pool_size: int =
10` and `server.py:349 PGWIRE_POOL_SIZE` default 10. FR-013 (pool ≤ licence
units) is confirmed as a live defect, not a theoretical one, and the failure
mode is an `OperationalError` at connect time — which is what a pool that
retries turns into the apparent hang in
`tests/contract/test_dbapi_executor_contract.py`.

### Declared values

| Capability                   | embedded                    | dbapi                                       |
| ---------------------------- | --------------------------- | ------------------------------------------- |
| `per_session_transactions`   | `False`                     | `True`                                      |
| `cross_session_dirty_reads`  | `True`                      | `True`                                      |
| `max_concurrent_sessions`    | `1`                         | `min(pool_size, licence_units)`, 7 measured |
| `isolation_levels_accepted`  | (unmeasured, see below)     | `{READ UNCOMMITTED, READ COMMITTED}`        |
| `isolation_levels_in_force`  | `frozenset()`               | `frozenset()`                               |
| `reports_column_types`       | `True` via `%SQL.Statement` | `True` via `description`                    |
| `describe_without_execute`   | `True`                      | `False`                                     |
| `available_under_irispython` | `True`                      | `False` (R1)                                |

`cross_session_dirty_reads` and `describe_without_execute` are new columns that
came out of measurement; neither was in the plan's Phase 1 sketch.
`isolation_levels_accepted` on embedded is the one cell still unmeasured — it
needs the same `SET TRANSACTION ISOLATION LEVEL` sweep run in-container, and it
is not blocking, because `in_force` is empty either way.

---

## R6. Which wire tests are adapter-sensitive?

**Decision: cannot be answered today. The per-adapter wire diff is specified as
a container-side job, and the marker set is seeded from static analysis and the
corpus rather than from a diff. This confirms rather than changes the Q7/Q10
design.**

### What was attempted

The intended method was to run the wire suites once per adapter and diff. The
two adapters live in disjoint environments (R1), so this is two runs: DBAPI on
the host, embedded in-container under `irispython`. The host half was attempted
first, against `tests/e2e` and `tests/protocol` (151 tests).

Getting to a runnable state required installing test dependencies absent from
the project venv (`pytest`, `pytest-asyncio`, `pytest-timeout`, `psycopg`,
`sqlalchemy`, `docker`, `sqlparse`, `testcontainers`, `testcontainers-iris`);
`uv run pytest` fails at resolution, and `.venv` ships no `pip`.

### The blocker

With dependencies in place, **106 of 151 tests error in session setup**, before
any adapter behaviour is exercised:

```text
tests/conftest.py:547 load_base_fixture
src/iris_pgwire/testing/base_fixture_builder.py:67 restore_fixture
/Users/tdyar/ws/iris-devtester/iris_devtester/fixtures/loader.py:260 load_fixture
/Users/tdyar/ws/iris-devtester/iris_devtester/fixtures/loader.py:312 _verify_load
FixtureLoadError: Table verification failed: expected string or bytes-like
object, got 'NoneType'
```

The tables compile (`Compiling table SQLUser.Patients`, `SQLUser.LabResults`,
`SQLUser.benchmark_vectors`) and then verification feeds `None` to a regex.
`loader.py:311-312` catches every exception and re-raises it as the string
"Table verification failed", so a `TypeError` in the dependency is reported as a
data problem in this repository.

The same root cause appears in the DBAPI pre-flight check, where it is reported
as an authentication problem — `DBAPI verification failed after password
remediation`, three attempts, each `error="expected string or bytes-like
object, got 'NoneType'"`. Working past that one with the supported
`IRIS_SKIP_DBAPI_VERIFY=1` escape simply surfaced the fixture-loader instance
behind it.

**This is a defect in `iris-devtester`, a different repository.** Per the
cross-repo rule it was diagnosed read-only and not modified. It is not an
adapter difference and it is not caused by the wrapper — R1's probe runs
identically with and without the wrapper installed, so the `NoneType` is
upstream of that.

Host run for the record, with the caveat that it measures the blocker and not
the adapters: 34 passed, 10 failed, 106 errors, 7 skipped, 4 of the errors being
`Timeout (>120s)`. Five skips report `Container 'iris-pgwire-test' not found` —
a container name no compose file defines, which is a second, independent
environment assumption worth a task.

### What follows for the design

1. **The corpus belongs below the wire, as Q7 and Q10 chose.** Every probe in
   this document ran to completion against the real container with no fixture
   machinery at all, while the wire suite could not reach its first assertion.
   An oracle that depends on the fragile layer cannot certify the layer beneath
   it. This is now an argued position rather than a preference.
2. **The per-adapter full-suite comparison is container-only.** The embedded
   half cannot run on the host at all (R1), and the host half is blocked by a
   dependency defect. The nightly per-adapter job is the only place this
   comparison can live.
3. **The `backend_sensitive` marker set is seeded from static analysis**, not
   from a diff: the call-site table in R4 names the steps one path runs and the
   other does not, which identifies the sensitive surface directly — vector
   operators, transaction commands, normalization-dependent SQL, and
   `RETURNING` (where DBAPI constructs `ReturningPlan` without `metadata_cache`
   or `executor`).
4. **Three new tasks**, none of which existed in `tasks.md`: pin the test
   dependency set so the suite is runnable from a clean checkout; report the
   `iris-devtester` `_verify_load` defect upstream (drafted only — filing needs
   explicit approval); and remove or define the `iris-pgwire-test` container
   assumption.

A known blind spot stands unchanged: files that pass on both adapters for
different reasons will not show up in any diff, and no method here detects them.

---

## R7. Does `TO_VECTOR(?)` bind through pgwire? _(added 2026-10-17, not a Phase 0 question)_

Asked from the irispython-dx project, which measured DB-API binding directly and found two of this
repo's documents contradicting each other. Measured on **IRIS 2026.2.0.221.0com**. The container
has been rebuilt since R1-R6, which ran on 2026.1. The client was psycopg 3.3.6, and the DBAPI
backend used `intersystems_irispython` 5.3.2. Both backends were tested. Embedded is the container's
own server, which runs `src` from the `iris-pgwire-gh` checkout; that checkout differs from this one
in 7 files, none on the vector or parameter path. DBAPI ran from this checkout's `src` on the host.
Probes: `spikes/probe_to_vector_binding.py` and `spikes/probe_to_vector_max_dims.py`.

| Measurement                                                                 | embedded                    | DBAPI                       |
| --------------------------------------------------------------------------- | --------------------------- | --------------------------- |
| INSERT via `TO_VECTOR(%s, DOUBLE, n)`, n = 1,024 (21.6 KB), 4,096 (87.7 KB) | OK                          | OK                          |
| Rank via `ORDER BY VECTOR_COSINE(v, TO_VECTOR(%s, DOUBLE, n))`              | matches local order         | matches local order         |
| Same, 2-arg `TO_VECTOR(%s, DOUBLE)`                                         | matches                     | matches                     |
| Same, untyped `TO_VECTOR(%s)`, DOUBLE column                                | `-259`                      | `-259`                      |
| `ORDER BY v <=> %s LIMIT %s`                                                | matches                     | `-25` (not translated)      |
| `SELECT v` / `SELECT id, v`, any vector projection                          | **0 rows, no error**        | exact values                |
| Largest dimension through `TO_VECTOR`, checked by value                     | **65,536**; 65,537 → `-263` | **65,536**; 65,537 → `-263` |

Findings that bear on this feature:

1. **Embedded drops every row that projects a `VECTOR` column.** IRIS raises
   `<OBJECT DISPATCH>next+9^%SYS.Python.SQLResultSet.1 *Invalid argument type` while fetching, and
   `iris_executor.py:2644-2649` catches it, logs a warning, and returns an empty result with a normal
   `CommandComplete`. The type OID of every column in that projection also degrades to `1043`. This
   is a Principle I violation, silent degradation, and the clearest one-sided defect found so far. The
   differential corpus would catch it on its first vector row. Seeded into T012 as a **fix**.

   **Fixed the same day, in the working tree** (`src/iris_pgwire/embedded_vector_fetch.py`). A
   read-only statement whose fetch fails this way is re-executed through `%SQL.Statement` in ODBC
   select mode. There a vector arrives as text, byte-identical to what DBAPI sends. The only other
   types whose form differs between the modes, `%Library.Date`, `%Library.Time` and
   `%Library.PosixTime`, are converted back to logical. Measured: those three conversions reproduce the
   logical values exactly, and every other common type reads identically in both modes. So
   non-vector columns are unchanged, including their existing defects. A statement that could write
   is never re-executed. Every other fetch error now raises instead of returning zero rows. The same
   re-fetch covers the `RETURNING` emulation's re-select, which was a second silent-empty path.
   `tests/e2e/test_vector_projection.py` fails 5 of 5 against the unfixed server and passes 5 of 5
   on both backends with the fix. `tests/unit/test_embedded_vector_fetch.py` adds 37 unit tests.

   Why nothing caught it: twelve test files create `VECTOR` columns and none reads one back. The
   `pgwire_server` fixture (`tests/conftest.py:692`) starts an in-process server on the host, where
   only DBAPI can run, so the e2e suite has never exercised embedded at all, whatever
   `PGWIRE_BACKEND_TYPE` says. And `tests/unit/test_iris_executor_unit.py` asserted the swallow:
   `test_fetch_error_handled_gracefully` checked that a fetch error became `rows == []`. That test is
   now inverted.

2. **The optimizer never consults the column's element type.** It substitutes `FLOAT` for untyped
   `TO_VECTOR` (`vector_optimizer.py:302`) and hard-codes `DOUBLE` for pgvector operators and
   INSERT literals (`:433`, `:436`, `:571`). Measured on embedded: `<=>` fails against a `FLOAT`
   column and works against `DOUBLE`; untyped fails against `DOUBLE` and works against `FLOAT`. Each
   path assumes one column type. Preparation needs the column's declared type to choose correctly,
   which is a catalog lookup and an argument for preparation having metadata access (FR-010).
3. **The 3-arg form `TO_VECTOR(?, DOUBLE, n)` bypasses the optimizer entirely.** The `ORDER BY`
   pattern (`vector_optimizer.py:239`) admits at most one type argument, so the statement reaches
   IRIS with its marker intact. That is why it works. It also means the most explicit form is the one
   preparation never sees.
4. **`_MAX_TO_VECTOR_LITERAL_BYTES = 3000` (`vector_optimizer.py:23`) is dead.** It is defined and
   never read. The live `ORDER BY` threshold is 1 MB (`:21`). The 2025 "3 KB limit" in
   `specs/013-vector-query-optimizer/E2E_FINDINGS.md` was this inlining threshold, not a binding
   limit.
5. **The error class differs by adapter for the same SQLCODE.** `-259` surfaces as
   `SyntaxErrorOrAccessRuleViolation` (42000) on embedded and as `DuplicateCursor` (42P03) on DBAPI.
   42P03 is wrong for this error. That is a `sqlstate.py` mapping divergence for the ledger (FR-018).

Found while fixing finding 1. All are pre-existing, none is fixed here, and all belong in the
ledger:

- **R2 correction.** Embedded statement metadata reports DATE as ODBC code `9` and TIMESTAMP as `11`,
  where DBAPI's `description` reports `1091` and `1093`. R2's "codes agree exactly" holds for the three
  types it measured (varchar, integer, bit), not in general, so one shared ODBC table is not yet
  justified for date and time. A vector column reports `12`, the same as VARCHAR. Only
  `typeClass = %Library.Vector` distinguishes it, and a computed `TO_VECTOR(...)` reports
  `%Library.String`.
- **Embedded non-vector materialisation is wrong on its own.**
  - A DATE comes back as `int4 67860`, the raw logical day count.
  - A TIME comes back as raw seconds (`45296`).
  - A `LONGVARCHAR` comes back as the stream's internal `$LIST` handle (`%Stream.GlobalCharacter`),
    not its text.
  - An integer `id` alongside them degrades to varchar.
  - In text format, a query over DATE/BIT/TIMESTAMP columns fails client-side with
    `invalid literal for int() with base 10: ''`.
- **DBAPI binary format fails on a DATE column** with `int() argument must be ... not
'datetime.date'`, and the next text-format query on that connection then fails too.
- **The embedded backend rejects an ISO TIME literal on INSERT** (`'12:34:56'` fails validation).
  `CAST('12:34:56' AS TIME)` works.
- **A failure in `RETURNING` emulation is still logged and dropped** (`iris_executor.py`,
  `_emulate_returning`'s outer handler). Raising there would tell a client that a committed INSERT
  failed, so this needs a decision, not a one-line change.
- **The server ignores SIGTERM.** `main()` handles only `KeyboardInterrupt`, so stopping it took
  SIGKILL.

Corrected as a result: `docs/VECTOR_PARAMETER_BINDING.md`, whose 188,962-dim figure came from
`SELECT 1 WHERE %s IS NOT NULL` with a Python list and therefore measured `float8[]` array transport,
not a vector bind; its verification command now goes through `TO_VECTOR`. And
`specs/013-vector-query-optimizer/E2E_FINDINGS.md`, whose "cannot bind" conclusion does not
reproduce. Both carry a dated note naming the build.

---

## R8. What the ADBC driver exposed _(added 2026-10-24, not a Phase 0 question)_

Measured by driving `adbc-driver-postgresql` 1.12.0 against both backends (IRIS 2026.2.0.221.0com,
`intersystems_irispython` 5.3.2 for DBAPI). The driver is a good probe because it is strict: it
decodes binary by the OIDs it was told, in two ways (binary `COPY` and binary result format), and
resolves types from `pg_type` by name. Findings that bear on this feature, none fixed here unless
stated:

1. **The same statement declared different types depending on the path (fixed).** On DBAPI,
   `SELECT CAST('2026-10-24' AS DATE)` was `varchar` over the simple protocol and `date` over the
   extended one. Cause: the simple path appends `;`, and `resolve_column_type_oids` took the
   semicolon as part of the last alias, so the lookup by name matched nothing and the statement's own
   evidence about its types was silently lost on that path. This is the T011h defect (a type decided
   in more than one place) in its most ordinary form, and it is what US3 exists to remove. The fix
   strips a trailing terminator in the resolver; the structural problem (preparation differs by
   path) remains.
2. **Error reporting differs by executor.** The embedded executor returns `{"success": False}`; the
   DBAPI executor re-raises. Anything that calls `execute_query` outside the two existing call sites
   has to handle both, and COPY now does.
3. **DBAPI type codes depend on the expression.** For `CAST(... AS DATE|TIME|TIMESTAMP)` this driver
   reports `9`, `10` and `11`; the executor's table (built from table columns) expects `1091`,
   `1092` and `1093`. `9` and `10` are not mapped, so a bare date or time falls to `varchar` unless
   the statement text says otherwise.
4. **Declared types still wrong, pinned as strict xfails in `tests/e2e/test_adbc.py`:** `TIME` is
   `varchar` on both backends (and on embedded its value is raw seconds, `'45296'`); `NUMERIC` is
   `float8` on embedded and correctly `numeric` on DBAPI.
5. **`COPY` defaults differ in direction.** `TO STDOUT` now defaults to PostgreSQL's text format;
   `FROM STDIN` still defaults to CSV with a comma. A psycopg `copy.write_row` sends text and would
   be mis-parsed. Item 6 of the ADBC request (bulk ingest) is where this gets settled.
6. **Unsupported, and needed by the driver beyond queries:** `pg_database`, `pg_table_is_visible`,
   `unnest(conkey)`, the `!~` operator, the `regclass` cast, and `CURRENT_SCHEMA()`. `adbc_ingest`
   fails first at `CURRENT_SCHEMA()` on both backends. `adbc_get_objects` returns an empty result
   and `adbc_get_table_schema` fails on `regclass`.
7. **A guard that was promised and did not exist.** `schema_mapper.VIEW_BACKED_TABLES` is a second
   copy of the definitions' list, with a comment saying a test keeps them in agreement. There was
   only a per-view assertion, so a view added without one (`pg_type`) was unreachable by its bare
   name. `test_pg_type_view.py` now compares the lists directly.

Seed into T012 as divergences: items 1 (fix, done), 3, 4 and 5.

---

## Summary of changes to the feature's own artifacts

| Artifact   | Change required                                                                                                                                               |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `spec.md`  | FR-014/FR-015 gain a third disposition, _no reference answer_. FR-009/FR-010 corrected: embedded reports types.                                               |
| `spec.md`  | FR-012 must refuse "DBAPI requested under `irispython`". FR-011 gains `cross_session_dirty_reads`, `describe_without_execute`, `available_under_irispython`.  |
| `plan.md`  | `Capabilities` has two adapters, not a possible three. Phase 0 closed.                                                                                        |
| `tasks.md` | T002 uses a pgvector image. New tasks: collapse the double `SQLRefiner.refine`; pin test dependencies; upstream defect report; `iris-pgwire-test` assumption. |
