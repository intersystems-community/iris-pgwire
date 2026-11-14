# Work tracks after the ADBC read-performance work (2026-11-14)

On 2026-11-14 Thomas Dyar and an agent session sorted the open iris-pgwire work, and the
ideas around it, into seven tracks. Each track is a different kind of work, so each goes through a
different route. This file is so that plan outlives the session. Update it as tracks finish; don't
start a parallel plan.

Decided so far: track 1 first (done in that session), then **track 4** as the next big track.
Track 5 is second.

## The tracks

| #   | Track                                             | What is in it                                                                                                                                                                                                                           | Route                                                                                                         | Where                                     |
| --- | ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| 1   | Finish the read-performance work                  | The Describe row cap, the row encoder, the optional psycopg accelerator, the benchmark. See `docs/investigations/adbc-read-performance-2026-11.md`                                                                                      | `/code-review` against `main`, then fix, then commit. **Done 2026-11-14**                                     | iris-pgwire                               |
| 2   | Text-format values are Python's, not PostgreSQL's | Text DataRows send `str(value)`: `bytea` as `b'\xde\xad'`, JSON as `{'a': 1}`, arrays as `[1, 2, 3]`, NUMERIC as `1E+14`, `inf`/`nan`, `+00:00` offsets. `value_encoding.encode_text` already gives PostgreSQL's text                   | `/tdd`: one slice. Changes what text clients receive, so it is its own change                                 | iris-pgwire                               |
| 3   | Embedded backend typing and memory                | Types guessed from values (DATE as a Horolog integer, NUMERIC as float8, INT as int64 or varchar on large results), the whole result held in memory (6.4 GB at 3M rows), `iris.sql.exec` read speed                                     | Already specified: spec 051 US3 (T034–T038) and T087. `/implement` the existing tasks                         | iris-pgwire                               |
| 4   | **Transactions for PostgreSQL-style apps**        | COMMIT after an error commits earlier work (STATUS_FAILED_TRANSACTION never set), FOR UPDATE may not lock, ON CONFLICT is not atomic, savepoint differences, aggregates reading uncommitted rows. Hermitage and pgbench as the measures | `/grilling` on `docs/investigations/mvcc-apps-on-iris-pgwire.md`, then a spec, then tickets. Several sessions | iris-pgwire                               |
| 5   | IRIS for the Python data world                    | Lazy server-side dataframes (an Ibis IRIS backend, "dbplyr for IRIS"), DuckDB `ATTACH` through iris-pgwire, dbplyr through RPostgres, Flight SQL, dbt Python models, the release of the native IRIS ADBC driver                         | `/wayfinder`: decisions before code. See below                                                                | Probably irispython-dx (Thomas to decide) |
| 6   | Answers that sit with other people                | Releasing the native IRIS ADBC driver (irispython-dx spec 21, Q13, with Jim Nelson); the intersystems-irispython unread-rows desync (recorded in irispython-dx `dxlab/results/fetchmany-close-desync-2026-11-14/`)                      | `/to-questionnaire` for Jim if the agent-bus thread does not settle it                                        | Outside these repos                       |
| 7   | Not engineering                                   | Where the 1.x security note goes (unpublished, awaiting Thomas), PyPI token rotation, expired IRIS key copies in `~/ws/iris-fhirsqlbuilder-dbt-integratedml`, release-branch cleanup                                                    | Thomas's To Do list                                                                                           | —                                         |

## Order

1. Track 1. Done.
2. Track 2, in a fresh session: small and self-contained.
3. Track 4, the next big track (Thomas, 2026-11-14).
4. Track 5 after it.
5. Track 3 whenever spec 051 is next.

## Track 4 starting point

`docs/investigations/mvcc-apps-on-iris-pgwire.md` lists the gotchas and recommends Hermitage
first, then pgbench TPC-B. Two related findings from 2026-11-14:

- IRIS `SELECT DISTINCT` returned an uppercased value (`'ALPHA'` for a stored `alpha`) under its
  default collation. A PostgreSQL application would not expect that.
- The memory note "READ COMMITTED is unreliable" (accepted is not the same as in force) applies.

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
