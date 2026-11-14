# Work tracks after the ADBC read-performance work (2026-11-14)

On 2026-11-14 Thomas Dyar and an agent session sorted the open iris-pgwire work, and the
ideas around it, into seven tracks. Each track is a different kind of work, so each goes through a
different route. This file is so that plan outlives the session. Update it as tracks finish; don't
start a parallel plan.

Decided so far: track 1 first (done in that session), then **track 4** as the next big track.
Track 5 is second.

## The tracks

| #   | Track                                             | What is in it                                                                                                                                                                                                                           | Route                                                                                                                     | Where                                     |
| --- | ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| 1   | Finish the read-performance work                  | The Describe row cap, the row encoder, the optional psycopg accelerator, the benchmark. See `docs/investigations/adbc-read-performance-2026-11.md`                                                                                      | `/code-review` against `main`, then fix, then commit. **Done 2026-11-14**                                                 | iris-pgwire                               |
| 2   | Text-format values are Python's, not PostgreSQL's | Text DataRows send `str(value)`: `bytea` as `b'\xde\xad'`, JSON as `{'a': 1}`, arrays as `[1, 2, 3]`, NUMERIC as `1E+14`, `inf`/`nan`, `+00:00` offsets. `value_encoding.encode_text` already gives PostgreSQL's text                   | `/tdd`: one slice. Changes what text clients receive, so it is its own change. **Done 2026-11-14** (`5a9bafc`, `7b6385e`) | iris-pgwire                               |
| 3   | Embedded backend typing and memory                | Types guessed from values (DATE as a Horolog integer, NUMERIC as float8, INT as int64 or varchar on large results), the whole result held in memory (6.4 GB at 3M rows), `iris.sql.exec` read speed                                     | Already specified: spec 051 US3 (T034–T038) and T087. `/implement` the existing tasks                                     | iris-pgwire                               |
| 4   | **Transactions for PostgreSQL-style apps**        | COMMIT after an error commits earlier work (STATUS_FAILED_TRANSACTION never set), FOR UPDATE may not lock, ON CONFLICT is not atomic, savepoint differences, aggregates reading uncommitted rows. Hermitage and pgbench as the measures | `/grilling` on `docs/investigations/mvcc-apps-on-iris-pgwire.md`, then a spec, then tickets. Several sessions             | iris-pgwire                               |
| 5   | IRIS for the Python data world                    | Lazy server-side dataframes (an Ibis IRIS backend, "dbplyr for IRIS"), DuckDB `ATTACH` through iris-pgwire, dbplyr through RPostgres, Flight SQL, dbt Python models, the release of the native IRIS ADBC driver                         | `/wayfinder`: decisions before code. See below                                                                            | Probably irispython-dx (Thomas to decide) |
| 6   | Answers that sit with other people                | Releasing the native IRIS ADBC driver (irispython-dx spec 21, Q13, with Jim Nelson); the intersystems-irispython unread-rows desync (recorded in irispython-dx `dxlab/results/fetchmany-close-desync-2026-11-14/`)                      | `/to-questionnaire` for Jim if the agent-bus thread does not settle it                                                    | Outside these repos                       |
| 7   | Not engineering                                   | Where the 1.x security note goes (unpublished, awaiting Thomas), PyPI token rotation, expired IRIS key copies in `~/ws/iris-fhirsqlbuilder-dbt-integratedml`, release-branch cleanup                                                    | Thomas's To Do list                                                                                                       | —                                         |

## Order

1. Track 1. Done.
2. Track 2. Done 2026-11-14 (`5a9bafc`, `7b6385e`), with the DISTINCT ticket as its own slice.
   - Text DataRows now use `value_encoding.encode_text`. A timestamp's fraction drops its trailing
     zeros (`.5`), as PostgreSQL's does, in COPY text too. On embedded, NUMERIC and DATE still go out
     wrong because the _OID_ is guessed (track 3); `tests/e2e/test_text_format_values.py` holds
     that as a strict xfail.
   - The ticket was narrower than written: plain `SELECT DISTINCT` was already `%EXACT`. Broken
     were `GROUP BY` (uppercased, and merged `alpha` with `Alpha`), `COUNT(DISTINCT x)` (counted
     them once) and `SELECT DISTINCT x ... ORDER BY x` (SQLCODE -12: the refiner, run again at
     Describe and Execute, expanded the alias to `DISTINCT %EXACT x`). Fixed in
     `sql_translator/refiner.py`; `tests/e2e/test_exact_collation.py` compares with PostgreSQL on
     both backends.
   - Seen on the way, not fixed: `BYTEA` and `TIMESTAMPTZ` in `CREATE TABLE` are not translated
     (IRIS error 5373); a `TIME` insert on embedded fails validation; `ORDER BY` on strings sorts
     by IRIS's collation, not PostgreSQL's.
3. Track 4, the next big track (Thomas, 2026-11-14). Decisions below. The 2.0.1 hotfix is done; spec 052 is next.
4. Track 5 after it.
5. Track 3 whenever spec 051 is next.

## Track 4 starting point

`docs/investigations/mvcc-apps-on-iris-pgwire.md` lists the gotchas and recommends Hermitage
first, then pgbench TPC-B. The memory note "READ COMMITTED is unreliable" (accepted is not the
same as in force) applies.

## Track 4 decisions (grilling with Thomas, 2026-11-14)

**Goal.** Measure, then fix what the wire layer can fix faithfully, and document the rest.
Emulating advisory locks (for Rails and Prisma migrations, Flyway) could be a later spec. `SKIP
LOCKED` has no faithful mapping and stays refused.

**The rule.** For each gotcha: emulate in PGWire when the emulation is exact; otherwise refuse
loudly with a PostgreSQL SQLSTATE; never pass a Critical or High gotcha through silently. The one
forced exception is dirty aggregates, `DISTINCT` and `GROUP BY` at READ COMMITTED (gotcha row 3),
which cannot be detected cheaply and stay documented.

**Strict by default.** A server-wide `PGWIRE_TXN_COMPAT=permissive` restores the old behaviour for
the _refusals only_ (locking clauses, ON CONFLICT forms with no atomic mapping), with a warning
logged once per statement shape. The exact emulations (25P02, the savepoint stack, `3B001`) are
always on: permissive mode never brings back commit-after-error.

**Backends.** DBAPI only. The embedded backend stays single-client in the docs; its guard against
concurrent transactions is spec 051 task T088.

**Order.**

1. Done 2026-11-14: hedged the `SELECT ... FOR UPDATE` workaround in `KNOWN_LIMITATIONS.md`;
   added T088 to spec 051.
2. **Spike session**, before any spec (done 2026-11-14; see the next section):
   - Build the isolation suite as pytest (`tests/e2e/isolation/`, marker `-m isolation`, a
     `make isolation` target, run in its own pytest process). Every case runs against PGWire and
     against `iris-pgwire-pgref` (PostgreSQL 16, port 55433). Expected answers come from
     PostgreSQL or from Hermitage's published `postgres.md`, never from IRIS. IRIS's outcomes are
     pinned as known differences. A thin script renders the Hermitage-style table from the suite.
   - Run it on `pgwire-release-lab` (port 2992) with this checkout's DBAPI server.
   - Cover E1 to E5, plus three added checks: whether a touch-update's lock
     (`UPDATE t SET pk = pk WHERE ...`) excludes a second one; which `ON CONFLICT` forms IRIS
     `INSERT OR UPDATE` can express exactly; and whether a CancelRequest reaches IRIS on DBAPI.
   - Test the hypothesis that the flaky READ COMMITTED sequences (gotcha row 4) used one of
     IRIS's documented exceptions.
   - Write the results into the investigation doc: a "Results" section, each "(inferred)" in the
     gotcha table updated to "(measured)", the Hermitage table. Then a short grilling round for any
     result that contradicts an assumption below.
3. **Spec 052, "PostgreSQL transaction semantics on IRIS"**, written from the results, one spec:
   - US1: a failed statement aborts the transaction. Later statements get `25P02`, and `COMMIT`
     becomes `ROLLBACK`.
   - US2: savepoints follow PostgreSQL. PGWire tracks the savepoint stack, returns `3B001` for an
     unknown name, and handles psycopg's `ROLLBACK TO` followed by `RELEASE`.
   - US3: ON CONFLICT. Map to `INSERT OR UPDATE` what it expresses exactly; refuse the rest with
     `0A000` in strict mode. Permissive keeps insert-catch-update, with its bugs fixed (executemany
     dropping `DO UPDATE`, swallowing any error whose text says "constraint", `DO NOTHING`
     ignoring its target, the embedded path not emulating). Amends spec 049 FR-002.
   - US4: locking clauses. If E2 shows `FOR UPDATE` does not lock, emulate it with a touch-update
     where the shape allows (single-table FROM, a predicate PGWire can lift), and refuse other
     shapes. Its known gaps: it fires UPDATE triggers, bumps `ROWVERSION`, and counts toward the
     1000-lock escalation. `NOWAIT` becomes `LOCK_TIMEOUT 0` around the statement and fails with
     `55P03`. `SKIP LOCKED` becomes a clean `0A000` (today `42601`).
   - US5: `lock_timeout` maps to `SET OPTION LOCK_TIMEOUT`, rounded up to whole seconds; `0`
     restores the server default. `statement_timeout` stays an accepted no-op, logged and
     documented.
   - US6: the isolation suite (Hermitage, E2 to E6, the pgbench invariant) is the phase gate and a
     release-checklist item. Plus a user-facing `docs/POSTGRES_APP_COMPATIBILITY.md` (what works,
     what needs redesign, the ORM table, permissive mode, the Hermitage row), linked from
     `KNOWN_LIMITATIONS.md`.
   - A server setting `PGWIRE_DEFAULT_ISOLATION`, with READ UNCOMMITTED as the default in 2.1.
     Revisit the default from E1's results before 052's plan is frozen.
   - Tickets are `specs/052-.../tasks.md` through `/speckit.tasks`, tests first. No GitHub issues
     unless Thomas says to file them.
4. **Later:** E6 and E7 (lock escalation, pgbench) on an enterprise-key lab; running the suite in
   CI; `statement_timeout` as a real `57014` once the cancel path is known; maybe advisory locks.
5. **Ships as 2.1.0**, strict by default, with a "behaviour changes" section in the changelog.

## Track 4 spike results and decisions (grilling with Thomas, 2026-11-14)

Done: the spike ran (Order step 2). The suite is `tests/e2e/isolation/`, run by `make isolation`: 108 checks, green,
with IRIS's outcomes pinned. The results, the Hermitage table and the updated gotcha table are in
`docs/investigations/mvcc-apps-on-iris-pgwire.md` section 5. These results contradicted the plan above, and were
settled as follows:

1. **Gotcha row 4 is a PGWire bug, so it ships as a 2.0.1 hotfix before spec 052.** Done 2026-11-14 on branch
   `hotfix/2.0.1` (`3424acb`), not yet released. `DBAPIExecutor.close_session`
   returns a disconnected client's IRIS connection to the pool with its transaction open and its isolation level
   unchanged; the next session runs inside it, and a bare `COMMIT` makes another client's uncommitted write permanent.
   IRIS itself honoured READ COMMITTED in 50 of 50 clean reads. The fix: on session close, ROLLBACK, reset the level,
   and discard a connection whose driver is out of step. The suite's `h3/*` checks are its regression tests. Spec 052
   references it.
2. **The 2.0.1 hotfix also carries three small fixes.** Done in `3424acb`. The re-measurement (investigation doc,
   section 5, "2.0.1 re-measurement") changed three things for spec 052: the second `ROLLBACK TO` does roll back the
   whole transaction (the spike's "rolls back nothing" was PGWire auto-committing); a psycopg nested block that exits
   normally raises on `RELEASE` and loses the outer transaction, which raises US2's priority; and the `<LIST ERROR>`
   comes from below PGWire, per connection, after a table is recreated.
   - IRIS SQLCODEs with no mapping default to `XX000`, not `08000`.
   - -375 maps to `3B001`.
   - The savepoint rewrite matches a quoted name, which fixes psycopg's `ROLLBACK TO "_pg3_1"`. Today that statement
     fails and psycopg ignores the failure, so a nested `transaction()` block commits its inner work.
3. **US3 stays as planned, with two amendments.** Map to `INSERT OR UPDATE` only the one shape it expresses exactly:
   the conflict target is the table's only unique key, and `DO UPDATE` sets every inserted column from `EXCLUDED`,
   with no `WHERE`. With a second unique key, `INSERT OR UPDATE` rewrites the primary key. Refuse the rest in strict
   mode.
   - Drop "executemany dropping `DO UPDATE`" from US3's bug list: it is embedded-only, so it moves to spec 051.
   - Add "the emulation classifies by SQLCODE -119, not by error text". On a just-created table the unique violation
     arrives as the driver's `<LIST ERROR>` instead.
4. **CancelRequest becomes loud in spec 052.** PGWire answers it by closing the session's IRIS connection, so the
   statement fails and its transaction rolls back. Today the cancel is acknowledged, never reaches IRIS, and the
   cancelled write lands. A true cancel through IRIS's own API joins the "later" list.
5. **The 2.1 default isolation is READ COMMITTED**, with `PGWIRE_DEFAULT_ISOLATION=read uncommitted` as the escape
   hatch, listed under "behaviour changes". READ UNCOMMITTED reads dirty data silently; READ COMMITTED fails loudly
   (a 40001 after the lock timeout), and US5's `lock_timeout` mapping bounds the wait. GROUP BY, aggregates and
   full-scan DISTINCT still read dirty at READ COMMITTED (gotcha row 3), which stays documented.
6. **US4 is confirmed.** `FOR UPDATE` takes no lock (a counter lost half its updates), and the touch-update excludes
   exactly (1000 of 1000). Run directly on IRIS, `SET OPTION LOCK_TIMEOUT = 0` failed a contended write in 0.00 s, so
   `NOWAIT` and `lock_timeout` map as planned.
7. **US2 grows.** IRIS has no `RELEASE` (-51), and a second `ROLLBACK TO` the same savepoint rolls back nothing. PGWire
   therefore tracks the stack itself: it re-establishes a savepoint after `ROLLBACK TO`, answers `RELEASE` without
   sending it, and returns `3B001` for an unknown name.
8. `KNOWN_LIMITATIONS.md` now says `FOR UPDATE` takes no lock and recommends the touch-update instead. It also gives
   the pool as the cause of the "accepted READ COMMITTED not in force" shape.

## Track 5 decision map

The decisions, in the order they depend on each other:

1. **How results reach Python:** iris-pgwire with `adbc-driver-postgresql`, the native IRIS ADBC
   driver, or a Flight SQL server beside IRIS. Measured 2026-11-14 on 100k and 3M rows: the native
   driver is 3 to 7 times faster than the official driver; iris-pgwire is now 1.2 to 1.5 times
   slower than the official driver on DBAPI.
2. **Whether an Ibis IRIS backend is "dbplyr for IRIS",** and what that means for dbt Python
   models, which on other warehouses run as Snowpark or PySpark dataframes inside the database.
3. **Whether dbt Fusion is the second user that justifies releasing the native driver.** Thomas's
   experimental IRIS adapter in `~/ws/dbt-fusion` (commits `8c818de`, `4c52471`) already runs on
   it: seeds through its bulk ingest, the relation cache through `GetObjects`, and the commit
   message records 74 passing tests on 2026.2.
4. **Which repo owns the work.**

Two prototypes, about an hour each, answer decision 1 with evidence rather than opinion:

- Ibis's PostgreSQL backend pointed at iris-pgwire (no new code; finds where iris-pgwire's
  PostgreSQL compatibility falls short).
- DuckDB `ATTACH ... (TYPE postgres)` pointed at iris-pgwire (filters and column selection run in
  IRIS, joins in DuckDB, reads over the binary COPY path made faster on 2026-11-14).

Landscape notes, 2026-11: Ibis compiles through SQLGlot to about 20 backends, not IRIS; Narwhals
can run lazily on Ibis, DuckDB or SQLFrame; Polars' LazyFrame optimises in-process only; ADBC is the
usual Arrow-native client API, with Columnar's `dbc` installing drivers, the Flight SQL one
included.

## Follow-ups from the 2026-11-14 code review

- `send_data_row`, `_serialize_column_value`, `_encode_binary_column_value` and
  `_get_data_row_format_code` in `protocol.py` have no production caller left; delete them and
  point their tests at `row_encoding.data_row_encoder`.
- The external embedded path (`_execute_external_async`) does not cap rows at Describe.
- On the DBAPI backend the Describe probe's first row is not always the query's first row (seen with
  `DISTINCT`). Types refined from that row could then differ between Describe and Execute, but only
  for a column IRIS does not type, where one first row is NULL. That class of mismatch already existed
  for a statement Describe, whose dummy parameters match no rows.
