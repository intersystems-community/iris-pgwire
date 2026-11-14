# Can MVCC-style PostgreSQL applications run on iris-pgwire?

Status: desk research and code reading, 2026-11-14, then measured the same day by the track 4 spike (section 5). File:line
references are to commit `3938502` on `main` (iris-pgwire 2.0.0 plus unreleased work). Sections 1 to 4 were written before
the spike; where the spike settled a claim, the gotcha table now says **(measured)** and section 5 gives the numbers. Every claim about IRIS or PostgreSQL
behaviour carries a source. Claims marked **(inferred)** were reasoned from the source or the code and have not been
run. Claims marked **(measured, prior)** come from earlier measurements recorded in this repo, chiefly
[`KNOWN_LIMITATIONS.md`](../../KNOWN_LIMITATIONS.md) ("Transaction Isolation: No MVCC, No Snapshots") and
[`specs/051-unified-executor/research.md`](../../specs/051-unified-executor/research.md).

## 1. Short answer

**Only partly, and not without changing the application.** iris-pgwire carries the wire protocol faithfully enough for
the driver and the ORM to connect. It cannot carry the concurrency contract an MVCC-style application was written
against, because IRIS has no snapshots. IRIS runs a lock-based scheme with two usable read levels: READ UNCOMMITTED,
the IRIS default, where readers never wait and see uncommitted data, and READ COMMITTED, where a reader waits on a
writer's row lock and then fails ([SET TRANSACTION][iris-settx]).

Some kinds of application work today:

- **Short OLTP transactions that touch rows by key**, retry on `40001`, and tolerate either dirty reads (at the
  default level) or reads that wait up to 10 s on a contended row (at READ COMMITTED). CRUD services, most REST
  back-ends and ORM-driven admin apps fall here, provided they use the **DBAPI backend** and never request REPEATABLE
  READ or SERIALIZABLE.
- **Single-writer or read-mostly applications**, such as dashboards over data loaded in batches, vector and RAG
  workloads, and analytics on data that is not being written while it is read.

Some kinds do not work without redesign:

- **Anything that depends on a snapshot.** That covers REPEATABLE READ and SERIALIZABLE (refused with `0A000` since
  2.0.0), consistent reports run beside OLTP writes, and SSI with retry as the correctness mechanism.
- **Job queues built on `FOR UPDATE SKIP LOCKED` or `NOWAIT`**, such as Solid Queue, Oban, graphile-worker, pg-boss
  and River. Both clauses fail as `42601` (measured, prior).
- **Anything that coordinates through advisory locks.** That covers Rails and Prisma migrations, Flyway, GoodJob and
  Que.
- **Pessimistic read-modify-write that trusts `SELECT ... FOR UPDATE` to exclude other writers.** IRIS documents
  `FOR UPDATE` on a cursor as performing no operation ([DECLARE][iris-declare]), and E2 measured that it takes no row
  lock: a read-`FOR UPDATE`-then-write counter lost about half its increments (section 5). `KNOWN_LIMITATIONS.md`
  recommends it as a workaround and is wrong.

On the DBAPI backend, a client that disconnects with a transaction open leaves it open on a pooled IRIS connection,
and later sessions run inside it (measured, section 5). Until that is fixed, every client must end its transactions
before disconnecting.

Do not use the embedded backend for concurrent clients at all. All wire sessions share one IRIS process and therefore
one transaction (measured, prior: `KNOWN_LIMITATIONS.md`, "Sessions Share One Transaction").

## 2. Gotchas

Severity: **Critical** means data is wrong with no error. **High** means a common pattern fails or silently loses its
guarantee. **Medium** means it fails loudly, or it costs throughput or latency. **Low** means a cosmetic or rare
difference.

| #   | The application relies on (PostgreSQL)                                                                                                                                                           | What IRIS does                                                                                                                                                                                                                                                                                                                                           | What iris-pgwire does today                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Severity                                                                              | Workaround                                                                                                                                                                                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Concurrent sessions are isolated from each other.                                                                                                                                                | An IRIS transaction belongs to the process.                                                                                                                                                                                                                                                                                                              | The embedded backend serves every session from threads of one process, so one client's `COMMIT` commits another client's work (measured, prior). DBAPI gives each session its own connection.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | **Critical** (embedded)                                                               | Use `BACKEND_TYPE=dbapi` for any multi-client deployment.                                                                                                                                                                                                                                           |
| 2   | "Reading never blocks writing and writing never blocks reading" ([PG 13.1][pg-mvcc]). READ COMMITTED reads the last committed version.                                                           | READ UNCOMMITTED returns uncommitted data without waiting. READ COMMITTED waits for the writer, and "if a lock timeout occurs … an SQLCODE -114 error is issued" ([SET TRANSACTION][iris-settx]). The default lock timeout is 10 s ([LockTimeout][iris-locktimeout]). There is no committed version to fall back on.                                     | The default and reported level is `read uncommitted` (`sql_translator/isolation.py:46`, `_isolation.py:99-111`). `-114` and `-110` map to `40001` (`sql_translator/sqlstate.py:103-104`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | **High**                                                                              | Choose a level deliberately. At READ UNCOMMITTED, design for dirty reads. At READ COMMITTED, keep write transactions short, retry `40001`, and budget more than 10 s for any contended read.                                                                                                        |
| 3   | READ COMMITTED applies to every query.                                                                                                                                                           | Documented exceptions: a SELECT with `%NOLOCK`, `DISTINCT` or `GROUP BY`, and any aggregate, "returns the current state of the data, including … changes … that have not been committed". Rows deleted by an in-progress transaction are hidden even though the delete may roll back ([SELECT, "Transaction Processing"][iris-select]; [SUM][iris-sum]). | Passed through untouched (measured, prior: `COUNT`, `SUM`, `GROUP BY` and `DISTINCT` all returned dirty values at READ COMMITTED). **(measured)** in the spike: `GROUP BY`, `SUM` and `COUNT(*)` read dirty at once in 10 of 10 runs; `SELECT DISTINCT n … WHERE id = 1` waited like a plain read, while a full-scan `SELECT DISTINCT n` read dirty at once. Both prior and spike measurements hold: the exception applies to `DISTINCT` over a scan, not over a primary-key lookup.                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | **High**                                                                              | None at the SQL layer. For a report that must be consistent, `LOCK TABLE t IN SHARE MODE` for its duration ([LOCK][iris-lock]); this blocks writers.                                                                                                                                                |
| 4   | A level that the server accepted is in force.                                                                                                                                                    | **(measured)** Reliably, on a clean connection: 50 of 50 plain reads, five spellings, both protocols, each a flat 10.0 s wait then `40001`. The earlier "sometimes returns the uncommitted value immediately" (measured, prior, IRIS 2026.1 CE) is PGWire's doing, not IRIS's: see the next column.                                                      | **(measured)** Returns a disconnected client's IRIS connection to the pool with its transaction still open (`dbapi_executor.py:1458`), and without resetting its isolation level. The next session handed it runs inside the abandoned transaction: an accepted READ COMMITTED reader then reads the uncommitted value at once, and a session that only says `COMMIT` makes it permanent. Other sessions wait on the abandoned locks. Reproduced deterministically.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | **Critical** (DBAPI)                                                                  | End every transaction before disconnecting. The fix belongs in PGWire: ROLLBACK and reset the level when a session closes, or discard the connection. **(measured)** The documented-exceptions candidate is refused for the pinned shape, a plain primary-key read.                                 |
| 5   | REPEATABLE READ and SERIALIZABLE exist; SSI aborts with `40001` and the application retries ([PG 13.2][pg-iso]).                                                                                 | Not available. `REPEATABLE READ` gives SQLCODE -96 and `SERIALIZABLE` -1 (measured, prior). The documented levels are READ UNCOMMITTED, READ COMMITTED and READ VERIFIED ([SET TRANSACTION][iris-settx]).                                                                                                                                                | Refused with `0A000` (`sql_translator/isolation.py:53-60`, `_isolation.py:231-245`). A mid-transaction change is refused with `25001` (`_isolation.py:283-322`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | **High**                                                                              | Configure the client for READ COMMITTED: Rails `transaction(isolation:)`, Django `OPTIONS["isolation_level"]`, SQLAlchemy `isolation_level`, Prisma `isolationLevel`, BenchBase `<isolation>`. Then redesign whatever relied on the stronger level.                                                 |
| 6   | Long reporting transactions see a stable snapshot beside OLTP writes.                                                                                                                            | No snapshot. At READ UNCOMMITTED a report reads partly applied transactions. At READ COMMITTED every row-level read of a locked row waits up to 10 s, and one timeout fails the whole query with `-114`.                                                                                                                                                 | Passed through.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | **High**                                                                              | Run reports where writes are not happening: off-peak, against a copy, or under `LOCK TABLE … IN SHARE MODE`. **(inferred; not measured in the spike)** An IRIS async reporting mirror member would give a separate copy, but this note has not examined it.                                         |
| 7   | Conflicts are rare and cheap. A deadlock is detected after about 1 s and reported as `40P01` ([PG 13.3.4][pg-locks]).                                                                            | Every conflict costs a full lock-timeout wait. IRIS documents deadlock _avoidance_ (lock ordering, timeouts), not detection ([Avoiding Deadlock][iris-deadlock]). **(measured)** A deadlock lasts the full timeout: in Hermitage G1c and OTV, two transactions waiting on each other were released only when one read failed with `40001` after 10.0 s.  | `40001` for both halves; `40P01` is never produced.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | **Medium**                                                                            | Lower the IRIS lock timeout server-side (row 8). Acquire locks in a consistent order. Use retry with jitter.                                                                                                                                                                                        |
| 8   | `SET lock_timeout` and `SET statement_timeout` bound waits.                                                                                                                                      | Per-process lock timeout via `SET OPTION LOCK_TIMEOUT = n`, in whole seconds, 0 allowed ([SET OPTION][iris-setoption]).                                                                                                                                                                                                                                  | Every `SET` other than isolation is answered "success" without reaching IRIS (`protocol.py:1236-1239`, `1862`, `1904-1906`). That includes `SET lock_timeout`, `SET statement_timeout` and even IRIS's own `SET OPTION LOCK_TIMEOUT`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | **Medium**                                                                            | System-wide `[SQL] LockTimeout` in the CPF ([LockTimeout][iris-locktimeout]). A real fix is to map `lock_timeout` to `SET OPTION LOCK_TIMEOUT`, rounded up to whole seconds.                                                                                                                        |
| 9   | `SELECT … FOR UPDATE` takes a row lock that excludes other lockers and writers until commit ([SELECT, locking clause][pg-select]).                                                               | `FOR UPDATE` on a cursor is "optional and perform\[s\] no operation" ([DECLARE][iris-declare]). It is absent from the SELECT synopsis ([SELECT][iris-select]).                                                                                                                                                                                           | Passed through. Measured, prior: it "works", and at READ COMMITTED it contends; at READ UNCOMMITTED it returns the dirty value without waiting. **(measured)** It takes no lock: a second `FOR UPDATE` and a writer go straight through at both levels, and a 4-worker read-`FOR UPDATE`-then-write counter ended at 501 and 508 after 1000 commits. The contention seen before was the ordinary READ COMMITTED read wait on a writer's lock.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | **Critical** (lost updates, no error)                                                 | Do not rely on it. Lock the row with a touch-update first, `UPDATE t SET id = id WHERE id = ?` (**(measured)**: excludes exactly like PostgreSQL's row lock; the same counter ended at 1000 of 1000), or write `UPDATE … SET n = n + 1 WHERE id = ?`, or `LOCK TABLE … IN EXCLUSIVE MODE`.          |
| 10  | `FOR SHARE`, `FOR NO KEY UPDATE`, `FOR KEY SHARE`.                                                                                                                                               | Not in the grammar.                                                                                                                                                                                                                                                                                                                                      | Not translated. **(measured)** They reach IRIS raw and fail as `42601` (SQLCODE -1).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | **Medium**                                                                            | Row 9 measured that `FOR UPDATE` does not lock, so stripping them would overstate their strength. A touch-update would be at least as strong as each of them.                                                                                                                                       |
| 11  | `NOWAIT` and `SKIP LOCKED` job queues.                                                                                                                                                           | No equivalent row-level clauses.                                                                                                                                                                                                                                                                                                                         | `42601` for both (measured, prior). No translator exists. An older integration test expects `NOWAIT` to be stripped (`tests/test_integration_iris_translation.py:112-118`); nothing in `src/` does so.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | **High** for queue apps                                                               | A single consumer per queue, or an IRIS-native queue. **(measured)** `NOWAIT` can map to `LOCK_TIMEOUT 0` around the statement: run directly on IRIS, a contended `UPDATE` under `SET OPTION LOCK_TIMEOUT = 0` failed with `-110` in 0.00 s. `SKIP LOCKED` has no faithful mapping.                 |
| 12  | Advisory locks: `pg_advisory_lock`, `pg_try_advisory_lock`, `pg_advisory_xact_lock` ([PG 13.3.5][pg-locks]). Used by Rails migrations, Prisma Migrate (key `72707369`), Flyway, GoodJob and Que. | No SQL equivalent. ObjectScript `LOCK` on a global name is the native mechanism ([LOCK (ObjectScript)][iris-cos-lock]).                                                                                                                                                                                                                                  | Only `pg_advisory_unlock_all` is intercepted, as a success no-op (`sql_translator/interceptor.py:42`, `202-205`). **(measured)** Every other advisory function reaches IRIS as an unknown function, giving `-359` and then `42883` (`pg_advisory_lock`, `pg_try_advisory_lock`, `pg_advisory_xact_lock`, `pg_advisory_unlock`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | **High** for migration tools                                                          | Rails `advisory_locks: false`, with a single migrator. A real fix **(inferred; a proposal, not measured)**: implement them in PGWire as IRIS `LOCK ^PGWireAdv(key)` with a timeout (0 for `try_`). This works on DBAPI only, because the lock owner is the IRIS process.                            |
| 13  | Optimistic concurrency: `UPDATE … WHERE id = ? AND version = ?`, then branch on the row count. EF Core can also use the `xmin` system column.                                                    | The version predicate matches no row while another transaction holds the new value. Nothing contends, so the row count is 0 even when nothing is ever committed (measured, prior). There is no `xmin`; IRIS offers `ROWVERSION` columns ([RowVersion][iris-rowversion]).                                                                                 | Passed through.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | **High** (false `StaleDataError`)                                                     | Treat a zero row count as inconclusive: re-read the row, then decide. Use a `ROWVERSION` or `BIGINT` version column instead of `xmin`.                                                                                                                                                              |
| 14  | `INSERT … ON CONFLICT` "guarantees an atomic INSERT or UPDATE outcome … even under high concurrency" ([INSERT][pg-insert]).                                                                      | No `ON CONFLICT`. Native `INSERT OR UPDATE` matches on any unique constraint ([INSERT OR UPDATE][iris-insertorupdate]).                                                                                                                                                                                                                                  | Emulated as insert, catch, update. The steps are not atomic. **(measured)** on DBAPI, racing a `DELETE` loop for 1000 upserts never produced 0 rows but failed 0 to 3 times a run with XX000, a DBAPI driver `<LIST ERROR>`. Any error whose text contains "constraint", "unique" or "duplicate" triggers the fallback (`iris_executor.py:2434-2436`, `dbapi_executor.py:741-743`): **(measured)** a foreign-key violation under `DO NOTHING` is swallowed. The conflict target is not checked for `DO NOTHING`: **(measured)** a collision on another unique key is swallowed. Under executemany on the embedded path, `DO UPDATE` is stripped and treated as `DO NOTHING` (`iris_executor.py:1373-1415`, `1590-1597`); **(measured)** on DBAPI executemany `DO UPDATE` is correct. **(inferred; embedded not measured)** The embedded single-statement path strips the clause but does not emulate it (`iris_executor.py:2807-2820`; compare `3417-3437`). | **Critical** (embedded executemany `DO UPDATE`, swallowed errors); **High** otherwise | **(measured)** `INSERT OR UPDATE` is exact only when the conflict target is the table's only unique key and `DO UPDATE` sets every inserted column from `EXCLUDED` with no `WHERE`; with a second unique key it can rewrite the primary key (section 5).                                            |
| 15  | An error aborts the transaction. Later statements get `25P02`, and `COMMIT` becomes `ROLLBACK`.                                                                                                  | Statement-level atomicity: the failed statement is undone and the transaction continues ([INSERT, Transaction Considerations][iris-insert]).                                                                                                                                                                                                             | `STATUS_FAILED_TRANSACTION` is defined (`protocol.py:125`) but never assigned. **(measured)** ReadyForQuery reports `T`, the next statement runs, and `COMMIT` commits the work done before and after the error, on both protocols.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | **High**                                                                              | Always roll back on error, as ORMs do. A fix: track the failed state per session and refuse everything except `ROLLBACK` and `ROLLBACK TO` with `25P02`.                                                                                                                                            |
| 16  | Savepoints: `ROLLBACK TO s` keeps `s`; an unknown savepoint is an error (`3B001`); there is no practical depth limit.                                                                            | `ROLLBACK TO SAVEPOINT` "deletes that savepoint". "If pointname does not exist, or has already been rolled back, this command rolls back the entire transaction." The limit is 255 savepoints ([ROLLBACK][iris-rollback], [SAVEPOINT][iris-savepoint]). `RELEASE SAVEPOINT` does not appear in the IRIS SQL reference.                                   | `ROLLBACK TO x` and `RELEASE x` are rewritten to the `SAVEPOINT` forms (`sql_translator/transaction_translator.py:53-59`, `123-136`). psycopg 3 rolls back a nested block with `ROLLBACK TO "sp"` and then `RELEASE "sp"` (psycopg 3.3.4, `transaction.py:192-202`). On IRIS the second statement names a savepoint the first one deleted. **(measured)** Worse: PGWire's rewrite does not match psycopg's quoted name, so `ROLLBACK TO "_pg3_1"` itself fails (-1), psycopg ignores the failure, and the inner block's work is committed. `RELEASE` fails with -51 (IRIS has none), and -375 and -51 reach the client as `08000`.                                                                                                                                                                                                                                                                                                                           | **Critical** (nested rollback lost)                                                   | Avoid nested transactions in client code. **(measured)** `RELEASE` never rolls anything back on IRIS (it is simply an error), so PGWire must track the savepoint stack itself: re-establish `s` after `ROLLBACK TO s`, answer `RELEASE` without sending it, and return `3B001` for an unknown name. |
| 17  | Row locks never escalate.                                                                                                                                                                        | "The default lock threshold is 1000 locks per table." Beyond it IRIS "escalates the locking level from record locks to a table lock" ([INSERT, Modify Transaction Lock Threshold][iris-insert]). The setting is system-wide ([SET OPTION][iris-setoption]).                                                                                              | Passed through.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | **Medium**                                                                            | Commit batch jobs in chunks below 1000 rows per table. Or raise `LOCK_ESCALATION_THRESHOLD`, which costs lock-table memory for every process.                                                                                                                                                       |
| 18  | Connection count is limited only by `max_connections`.                                                                                                                                           | Licence units. Community Edition refused the 8th DBAPI connection (measured, prior: spec 051 research).                                                                                                                                                                                                                                                  | Pool default is 10 (`server.py:450`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | **Medium**                                                                            | Size the pool to the licence. Run benchmarks on an enterprise key.                                                                                                                                                                                                                                  |
| 19  | A CancelRequest stops the running statement; it fails with `57014` and has no effect.                                                                                                            | No cancel path from outside the process on DBAPI.                                                                                                                                                                                                                                                                                                        | **(measured)** `DBAPIExecutor.cancel_query` returns False. The client's cancel is accepted, the statement keeps waiting, returns no error, and is applied once its lock is free (3.2 s later in the test).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | **High** (a "cancelled" write lands)                                                  | Do not rely on cancel or `statement_timeout`. Bound waits with the IRIS lock timeout instead (row 8).                                                                                                                                                                                               |
| 20  | SQLSTATE classes mean what they say; `08xxx` means the connection is broken.                                                                                                                     | Reports SQLCODEs.                                                                                                                                                                                                                                                                                                                                        | **(measured)** SQLCODEs with no mapping reach the client as `08000`: -14 (`%` untranslated), -51 (`RELEASE`), -375 (unknown savepoint). A duplicate key on a just-created table also arrives as `08000` (section 5). A pool that trusts the class discards a healthy connection.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | **Medium**                                                                            | None client-side. Map -375 to `3B001` and default unknown SQLCODEs to `XX000`.                                                                                                                                                                                                                      |

### What the four ORMs assume

| ORM / framework      | Concurrency features it uses on PostgreSQL                                                                                                                                                                         | Rows hit            |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------- |
| SQLAlchemy           | `isolation_level` engine option; `with_for_update(nowait=, skip_locked=, read=)`; `begin_nested()`, which uses SAVEPOINT, RELEASE and ROLLBACK TO; `version_id_col`; `postgresql.insert().on_conflict_do_update()` | 5, 9-11, 13, 14, 16 |
| Django               | **(inferred from Django's documentation)** READ COMMITTED as the PostgreSQL default; `select_for_update(nowait=, skip_locked=, of=)`; nested `atomic()` savepoints; `bulk_create(update_conflicts=True)`           | 2, 9-11, 14, 16     |
| Rails (ActiveRecord) | `transaction(isolation:)`; `lock_version`; `lock("FOR UPDATE SKIP LOCKED")` in Solid Queue; migrations take `pg_advisory_lock` unless `advisory_locks: false`; `upsert_all` uses `ON CONFLICT`                     | 5, 9, 11-14         |
| Prisma               | `$transaction(…, { isolationLevel })`; Migrate takes `pg_advisory_lock(72707369)`; database-level upserts use `ON CONFLICT`                                                                                        | 5, 12, 14           |

Sources for the ORM column are the vendors' own documentation, listed in section 5. The row mapping is this note's
analysis.

## 3. Benchmarks

Two kinds matter here, and they answer different questions. **Throughput benchmarks** (pgbench, sysbench, HammerDB,
BenchBase) ask how fast a workload runs under contention. On IRIS, the interesting output is the rate of `40001`
retries and the shape of the latency tail, because every conflict costs a lock-timeout wait. **Anomaly suites**
(Hermitage, Elle, PostgreSQL's isolation tester) ask which guarantees hold. For the question this note asks, the
anomaly suites matter more. A fast system that loses updates gives a wrong answer quickly.

| Benchmark                                                                                                          | What it measures                                                                                                                                                                                                                                                                | Would it run through iris-pgwire today?                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | What a result would tell us                                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **pgbench** ([docs][pgbench])                                                                                      | TPS and latency of a "TPC-B (sort of)" script: three `UPDATE`s of a balance, one `SELECT`, one `INSERT` with `CURRENT_TIMESTAMP`, wrapped in `BEGIN` … `END`. Contention is set by the scale factor (one branch row per scale unit). `--max-tries` retries `40001` and `40P01`. | **The run phase: probably. Initialisation: no.** `-i` drops and creates tables with `WITH (fillfactor=…)` (PGWire strips this: `identifier_normalizer.py:221-225`), loads them with `COPY … FROM STDIN WITH (FREEZE ON)` because PGWire reports `server_version` 16 (`protocol.py:835`; pgbench uses FREEZE from version 14 on), then runs `VACUUM ANALYZE` (not handled, reaches IRIS) and `ALTER TABLE … ADD PRIMARY KEY`. `END` is understood as COMMIT (`protocol.py:1207-1209`). The `\set` meta-commands run client-side. **(inferred)** Workable path: create the four tables by hand, load them with `-I g` or a script, and run with `-n` so that pgbench skips VACUUM. | Throughput, plus the retry rate from `--max-tries` and `--failures-detailed`, which on IRIS counts lock timeouts. It also gives a free **correctness check**: afterwards `sum(abalance) = sum(tbalance) = sum(bbalance) = sum(delta)` must hold. That invariant catches lost updates and partial commits (rows 9, 15).                                                 |
| **sysbench oltp\_\*** ([oltp_common.lua][sysbench-lua], [pgsql driver][sysbench-pg])                               | Mixed OLTP: point selects, `BETWEEN` ranges, `SUM`, `ORDER BY`, `DISTINCT`, index and non-index updates, delete followed by insert, in `BEGIN`/`COMMIT`. The prepare phase creates `sbtest` tables with `SERIAL` keys and a secondary index.                                    | **(inferred) Probably, with effort.** It uses server-side prepared statements (`PQprepare` and `PQexecPrepared`) and multi-row `INSERT … VALUES` in prepare (PGWire splits these: `iris_executor.py:1956`). The pgsql driver treats `40001`, `40P01` and `23505` as ignorable and restarts the transaction (`drv_pgsql.c:560-567`), so lock timeouts become restarts rather than errors.                                                                                                                                                                                                                                                                                         | Throughput and latency for a read-heavy or mixed OLTP shape that resembles many web apps, plus the restart rate. **It checks no answers**: the `SUM` and `DISTINCT` queries read dirty data even at READ COMMITTED (row 3), and sysbench would not notice.                                                                                                             |
| **HammerDB TPROC-C** ([pgoltp.tcl][hammerdb])                                                                      | TPC-C-derived OLTP throughput (NOPM/TPM) for New-Order, Payment, Delivery, Order-Status and Stock-Level.                                                                                                                                                                        | **No.** For PostgreSQL the transaction logic lives in server-side PL/pgSQL functions or procedures that HammerDB creates (`CREATE OR REPLACE FUNCTION NEWORD …`, `PROCEDURE NEWORD …`) and then calls. PGWire has no PL/pgSQL. Porting means rewriting the five transactions as IRIS stored procedures, at which point the benchmark is no longer the PostgreSQL one.                                                                                                                                                                                                                                                                                                            | Nothing about PGWire until ported. HammerDB's own native IRIS support, if any, is outside this note.                                                                                                                                                                                                                                                                   |
| **BenchBase** (formerly OLTPBench) ([repo][benchbase])                                                             | A JDBC framework with many workloads: TPC-C, YCSB, SmallBank, TATP, SEATS, Twitter, Epinions and others. Throughput, latency, and abort and retry counts per transaction type.                                                                                                  | **(inferred) Probably, after configuration changes.** It uses the PostgreSQL JDBC driver with client-side SQL. Its sample PostgreSQL TPC-C configuration requests `TRANSACTION_SERIALIZABLE` (`config/postgres/sample_tpcc_config.xml:11`), which PGWire refuses with `0A000`, so set it to `TRANSACTION_READ_COMMITTED`. TPC-C New-Order uses `SELECT … FOR UPDATE` on `district` and `stock` (`NewOrder.java:58-60`, `104-108`), so it exercises row 9 directly. The DDL uses `DROP TABLE IF EXISTS … CASCADE`. The loader uses `reWriteBatchedInserts=true`.                                                                                                                  | TPC-C-shaped throughput with real contention on `district.d_next_o_id`. Paired with the **TPC-C consistency conditions** (W_YTD equals the sum of D_YTD, D_NEXT_O_ID − 1 equals max(O_ID), and so on) run as SQL afterwards, it is a correctness test as well. Duplicate order IDs would prove that `FOR UPDATE` does not exclude.                                     |
| **Hermitage** ([repo][hermitage], [PostgreSQL cases][hermitage-pg])                                                | A catalogue of two-session scripts, one per anomaly: G0, G1a, G1b, G1c, OTV, PMP, P4 (lost update), G-single (read skew), G2-item and G2 (write skew). Each lists what PostgreSQL does at each level.                                                                           | **Yes, almost unchanged.** Plain `create table`, `insert`, `begin`, `set transaction isolation level …`, `select`, `update`, `delete`, `commit`, `abort`. The only obstacle is that the cases are written for manual interleaving in two `psql` terminals, so a small driver must play them (E1). REPEATABLE READ and SERIALIZABLE cases will stop at `0A000`, which is itself the right answer.                                                                                                                                                                                                                                                                                 | A row in Hermitage's own comparison table for "IRIS via PGWire" at READ UNCOMMITTED and READ COMMITTED: which anomalies are prevented, which are allowed, and which are "prevented" by a 10 s timeout. It is the most direct answer to "what can an MVCC developer assume", and it is comparable with the published rows for PostgreSQL, MySQL, Oracle and SQL Server. |
| **Jepsen / Elle** ([Elle][elle], [elle-cli][elle-cli], [Jepsen PostgreSQL 12.3][jepsen-pg])                        | Elle checks a recorded history of transactions (list-append or rw-register) for cycles that prove anomalies (G0 through G2, lost updates, and others), from the outside. Full Jepsen adds fault injection on real clusters.                                                     | **The Elle half: yes.** Elle needs only a history. A psycopg client running list-append transactions (`UPDATE t SET v = v \|\| ',' \|\| ? WHERE k = ?` plus reads) can write the history as JSON for `elle-cli`, which requires Java 21. Full Jepsen (SSH into nodes, partitions) does not fit a single container and is out of scope.                                                                                                                                                                                                                                                                                                                                           | Randomised, high-volume evidence about which anomalies occur under concurrency, rather than the scripted cases Hermitage covers. It would also show whether the flaky READ COMMITTED behaviour (row 4) shows up as G1a or G1b in practice.                                                                                                                             |
| **PostgreSQL isolation tester** (`src/test/isolation`) ([README][pg-isotest], [isolationtester.c][pg-isotester-c]) | Hundreds of `.spec` files, each with setup, sessions, steps and permutations, whose output is diffed against expected files. They cover FK contention, deadlocks, SSI, `FOR UPDATE` variants and more.                                                                          | **No, as written.** The harness detects a blocked session by preparing `SELECT pg_catalog.pg_isolation_test_session_is_blocked($1, '{pids}')` and calls `set_config('application_name', …)` on every connection (`isolationtester.c:193-229`). PGWire has neither. Most specs also use SERIALIZABLE, advisory locks or `FOR KEY SHARE`. **(inferred)** PGWire could implement `pg_isolation_test_session_is_blocked` from its own state (a session with a statement in flight longer than _n_ ms), but expected outputs would need rewriting for IRIS anyway.                                                                                                                    | Little that Hermitage and Elle do not give more cheaply. Its value is as a **spec format**: the `.spec` grammar is a clean way to write E2 to E6 as regression tests.                                                                                                                                                                                                  |

### Which benchmark to run first

**Hermitage, through psycopg, against both iris-pgwire (DBAPI backend) and the reference PostgreSQL 16 on port 55433.** It is the only suite that answers the question directly ("which guarantees can an MVCC developer assume?").
It needs two connections, so it fits inside Community Edition's licence slots once the benchmark lab is free. Each case
has a known answer published by an outside author, so the result is an assertion and not a number. It also finishes in
minutes.

The second run should be **pgbench TPC-B with the balance invariant**. It is the cheapest throughput number that
carries its own correctness check, and its `--max-tries` reporting shows directly what the 10 s lock-timeout model
costs.

## 4. Proposed experiments

E1 to E5 ran in the track 4 spike on 2026-11-14 as `tests/e2e/isolation/` (`make isolation`); section 5 has the
results. E6 and E7 remain, for an enterprise-key lab. The original plan follows. Run them only when `pgwire-release-lab` and
`pgwire-bench-dbapi` are free. Use the DBAPI backend. Run each against iris-pgwire and against the reference PostgreSQL
on port 55433, so that every expected answer comes from PostgreSQL and not from the system under test. Follow the
standing rule from the READ COMMITTED investigation: repeat each shape at least five times and alternate the order
within one script before believing any difference.

### E1. Hermitage through psycopg

1. Write `scripts/hermitage_runner.py`. It opens two psycopg connections (`autocommit=False`) and plays each Hermitage
   case as a list of `(session, sql, expect)` steps. Each step runs in a worker thread with a 15 s deadline, longer
   than the IRIS lock timeout. The runner records one of four outcomes: rows returned, `blocked` (still running after
   1 s; then wait for it), an error SQLSTATE, or the elapsed time.
2. Before every case, run the Hermitage setup: `create table test (id int primary key, value int)` with rows `(1,10)`
   and `(2,20)`. Use two single-row INSERTs if multi-row VALUES gets in the way.
3. Run every case at `read uncommitted` and `read committed`, five times each, in alternating order.
4. Assert against PostgreSQL's recorded outcomes for READ COMMITTED from `postgres.md`, and against PostgreSQL's
   behaviour on port 55433 for READ UNCOMMITTED. PostgreSQL treats that level as READ COMMITTED, so every difference
   becomes a row in the result table.
5. Report a Hermitage-style table with these values: prevented, anomaly, prevented-by-timeout (`40001` after about
   10 s) and flaky (different outcomes across the five runs).

### E2. Does `SELECT … FOR UPDATE` exclude?

1. Seed `create table c (id int primary key, n int)` with the row `(1, 0)`.
2. Session A: `BEGIN; SET TRANSACTION ISOLATION LEVEL READ COMMITTED; SELECT n FROM c WHERE id = 1 FOR UPDATE;` and
   keep the transaction open.
3. Session B, the same statements. Record whether B blocks, for how long, and with which SQLSTATE.
4. Repeat at READ UNCOMMITTED, and with B running `UPDATE c SET n = 5 WHERE id = 1` instead of a SELECT.
5. Lost-update test: 4 workers × 250 iterations of `BEGIN; SELECT n … FOR UPDATE; UPDATE c SET n = <read + 1>;
COMMIT`, retrying on `40001`. **Assert `n = 1000`.** PostgreSQL gives 1000. Any lower value proves that `FOR UPDATE`
   does not exclude, and the workaround in `KNOWN_LIMITATIONS.md` must change.

### E3. ON CONFLICT under the paths PGWire actually takes

1. `create table u (k int primary key, v int)` seeded with `(1, 1)`.
2. Run `INSERT INTO u VALUES (%s, %s) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v` with `cur.executemany` over
   `[(1, 99), (2, 2)]`. **Assert `(1, 99)` and `(2, 2)`.** Reading the code predicts `(1, 1)`.
3. Run the same statement as one `execute`. Then run `DO NOTHING` on the embedded backend in a throwaway lab. **Assert
   no error is raised.**
4. Insert a row that violates a foreign key under `ON CONFLICT DO NOTHING`. **Assert `23503` is raised.** The
   "constraint" match predicts the error is swallowed.
5. Concurrency: worker A loops the upsert on `k = 1` while worker B loops `DELETE FROM u WHERE k = 1`. **Assert every
   upsert reports one row affected.** A report of 0 rows shows the race.

### E4. Savepoint semantics with psycopg's own statements

1. `with conn.transaction(): insert row 1; try: with conn.transaction(): insert row 2; raise Boom; except Boom: pass;
insert row 3`. **Assert rows 1 and 3 are present after commit and row 2 is absent.** This exercises
   `ROLLBACK TO "_pg3_1"` followed by `RELEASE "_pg3_1"`.
2. Raw SQL: `BEGIN; INSERT 1; ROLLBACK TO SAVEPOINT nosuch; COMMIT`. PostgreSQL raises `3B001`, and row 1 is gone
   because the transaction aborted. On IRIS, record whether row 1 survives and whether any error was raised.
3. Record IRIS's response to `RELEASE SAVEPOINT x` for an existing savepoint, for a deleted one and for an unknown one.

### E5. Error inside a transaction, then COMMIT

`BEGIN; INSERT INTO t VALUES (1); INSERT INTO t VALUES (1); COMMIT;` The second INSERT is a duplicate key. **Assert
the table is empty afterwards**, which is PostgreSQL's answer. Reading the code predicts that row 1 is committed. Also
record the ReadyForQuery status byte after the failed INSERT. PostgreSQL sends `E`.

### E6. Lock escalation and lock timeouts

1. Session A: `BEGIN;` then update 1001 distinct rows of table `t` without committing. Session B: update a row that A
   did not touch. Record whether B blocks, and for how long.
2. Repeat with 999 rows. B should not block.
3. `SET lock_timeout = '1s'` in B, then contend on one of A's rows. Record the elapsed time. Reading the code predicts
   about 10 s.

### E7. pgbench with an invariant

1. Create the pgbench tables by hand using IRIS-compatible DDL. Load scale 10 with `pgbench -i -I g` or a loader
   script.
2. `pgbench -n -c 4 -j 2 -T 120 --max-tries=10 --failures-detailed -M prepared` through PGWire. Then run the same
   against port 55433.
3. **Assert** `sum(abalance) = sum(tbalance) = sum(bbalance) = sum(delta)` on both. Report TPS, latency percentiles,
   and retry counts. Run on an enterprise-key container; Community Edition's connection limit would cap `-c`.

## 5. Results (spike, 2026-11-14)

Measured by the isolation suite in [`tests/e2e/isolation/`](../../tests/e2e/isolation/) (`make isolation`), which runs
every case against PGWire and against PostgreSQL 16.15 (`iris-pgwire-pgref`, 127.0.0.1:55433). The PGWire server was
this checkout (`7b6385e` plus the suite) on the DBAPI backend, started with `tests/e2e/_auth_server.py 5442 trust dbapi`
against `pgwire-release-lab` (IRIS 2026.2.0.221.0com, Community Edition, port 2992), the only PGWire server running.
The expected answers come from PostgreSQL: from Hermitage's `postgres.md` and README for E1, and from the PostgreSQL
documentation, checked against the reference server, for the rest. The reference server gave the documented answer in
every check. IRIS's outcomes are pinned in
[`known_differences.py`](../../tests/e2e/isolation/known_differences.py), so a change in any of them fails the suite.
Every Hermitage case and every READ COMMITTED reader ran five times, with the order alternated between runs.

### Headline

1. **Gotcha row 4 is PGWire's bug, not IRIS's.** IRIS honoured READ COMMITTED in every one of 50 plain reads, whatever
   the spelling or protocol. The "accepted but not in force" shape comes from the DBAPI connection pool:
   `DBAPIExecutor.close_session` (`dbapi_executor.py:1458`) returns a disconnected client's IRIS connection to the pool
   with no ROLLBACK. The abandoned transaction stays open with its locks, and the next session handed that connection
   runs inside it. In the reproduction, three READ COMMITTED readers waited 10 s and got `40001`; the fourth, given the
   abandoned connection, read the uncommitted 999 at once. Sessions that only sent `COMMIT` made a disconnected
   client's uncommitted write permanent. Pooled connections also keep the previous session's isolation level: new
   sessions that reported `read uncommitted` waited out the 10 s timeout like READ COMMITTED readers. **Critical**, and
   the first thing spec 052 should fix.
2. **`SELECT ... FOR UPDATE` takes no lock (E2).** A second `FOR UPDATE` and a writer both went straight through, at
   both levels. Four workers doing read-`FOR UPDATE`-then-write ended at 501 and 508 after 1000 commits each run: half
   the increments were lost, with no error. The workaround `KNOWN_LIMITATIONS.md` gives is wrong.
3. **The touch-update excludes.** `UPDATE t SET id = id WHERE ...` (and `SET n = n`) made a second one, and a writer,
   wait for COMMIT exactly as on PostgreSQL. The same counter locked by a touch-update ended at 1000 of 1000 at both
   levels. US4's emulation works on this evidence.
4. **A CancelRequest never reaches IRIS on DBAPI, and the cancelled statement still runs.** The client's cancel was
   accepted, the waiting UPDATE got no error, and it was applied 3.2 s later when the lock holder rolled back.
   PostgreSQL fails it at once with `57014`.
5. **psycopg's nested rollback commits the inner block (E4).** psycopg sends `ROLLBACK TO "_pg3_1"` with a quoted
   name; PGWire's savepoint rewrite does not match it, IRIS rejects it (SQLCODE -1), psycopg logs and ignores the
   error, and the inner block's row is committed. **Critical**: any `with conn.transaction():` nested block, and
   SQLAlchemy's `begin_nested()`, loses its rollback.

### E1, Hermitage

Five runs per cell; no cell varied between runs. Hermitage's `value % 3 = 0` was played as `mod(value, 3) = 0` on both
targets, because PGWire does not translate `%` (see "Other findings").

| Target              | Level            | G0  | G1a | G1b | G1c         | OTV         | PMP | PMP-write | P4  | G-single | G2-item | G2  |
| ------------------- | ---------------- | --- | --- | --- | ----------- | ----------- | --- | --------- | --- | -------- | ------- | --- |
| PostgreSQL 16       | read committed   | ✓   | ✓   | ✓   | ✓           | ✓           | —   | —         | —   | —        | —       | —   |
| PostgreSQL 16       | read uncommitted | ✓   | ✓   | ✓   | ✓           | ✓           | —   | —         | —   | —        | —       | —   |
| IRIS through PGWire | read committed   | ✓   | ✓   | ✓   | ✓ (timeout) | ✓ (timeout) | —   | ✓         | —   | —        | —       | —   |
| IRIS through PGWire | read uncommitted | ✓   | —   | —   | —           | —           | —   | ✓         | —   | —        | —       | —   |

✓ prevented, — anomaly possible, "✓ (timeout)" prevented only because one read failed with `40001` after the 10 s lock
timeout. `scripts/render_hermitage_table.py` draws this table from the suite's results file.

What the table does not show:

- **READ COMMITTED prevents dirty reads by waiting, not by reading the committed version.** In G1a and G1b, T2's read
  blocked until T1 ended; PostgreSQL's did not block at all. G1c and OTV make two transactions wait on each other, and
  IRIS breaks the cycle only when the lock timeout fails one read. The 10 s cost in row 2 of the gotchas, and the
  "deadlock lasts the full timeout" inference in row 7, are both measured here.
- **READ UNCOMMITTED is IRIS's default and PGWire's**, and it matches the MySQL and SQL Server "read uncommitted" rows
  of Hermitage's README: G0 is prevented by write locks and every dirty-read anomaly occurs.
- **PMP-write is stronger than PostgreSQL** at both levels. IRIS's blocked `DELETE ... WHERE value = 20` re-evaluates
  its predicate against the row T1 committed and deletes it, which is the serial order T1 then T2. PostgreSQL deletes
  nothing.
- P4 (lost update), G-single, G2-item and G2 occur, as on PostgreSQL at READ COMMITTED. IRIS has no level that prevents
  them; REPEATABLE READ and SERIALIZABLE stay refused with `0A000`.

### Gotcha row 4: the hypotheses

| Hypothesis                                                                                           | Result                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H1, the track 4 question: the flaky reads used one of IRIS's documented READ COMMITTED exceptions.   | **Refuted for the pinned shape, which was a plain primary-key read.** With a writer holding the row, `SELECT n FROM t WHERE id = 1`, a full scan and a derived table waited 10.0 s and failed with `40001` in 10 of 10 runs each (5 per protocol). `GROUP BY`, `SUM` and `COUNT(*)` read the uncommitted value at once in 10 of 10. `SELECT DISTINCT n ... WHERE id = 1` did not: it waited like a plain read. A full-scan `SELECT DISTINCT n` read dirty at once (single probe), so the exception holds for a scan but not for a primary-key lookup. |
| H2: the outcome depends on how the level is asked for, or on the protocol.                           | **Refuted.** `BEGIN` then `SET TRANSACTION`, `BEGIN ISOLATION LEVEL`, `SET TRANSACTION` with no `BEGIN`, `SET SESSION CHARACTERISTICS` and `SET default_transaction_isolation` then `BEGIN`, on the simple and the extended protocol: 50 of 50 honoured, each a flat 10.0 s wait.                                                                                                                                                                                                                                                                     |
| H3: a pooled IRIS connection carries a disconnected client's open transaction into the next session. | **Confirmed, and it reproduces the pinned disjunction.** See the headline.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

So the memory note "READ COMMITTED is unreliable" is wrong about IRIS: on DBAPI, an accepted READ COMMITTED was in
force every time a clean connection ran it. The earlier probes' trigger was never isolated because it depended on which
pooled connection a session happened to get.

### E2 and the touch-update

| Check                                           | PostgreSQL       | IRIS through PGWire, both levels |
| ----------------------------------------------- | ---------------- | -------------------------------- |
| `FOR UPDATE`, then a second `FOR UPDATE`        | waits for COMMIT | does not wait                    |
| `FOR UPDATE`, then an `UPDATE` of the row       | waits for COMMIT | does not wait                    |
| touch `SET id = id`, then a second touch        | waits for COMMIT | waits for COMMIT                 |
| touch `SET n = n`, then a second touch          | waits for COMMIT | waits for COMMIT                 |
| touch `SET id = id`, then an `UPDATE`           | waits for COMMIT | waits for COMMIT                 |
| Counter, 4 × 250, locked by `FOR UPDATE`        | 1000 of 1000     | 501 and 508 of 1000 commits      |
| Counter, 4 × 250, locked by touch `SET id = id` | 1000 of 1000     | 1000 of 1000                     |

The counter needed no retries on either target. A touch-update of the primary key to itself is accepted by IRIS (the
key is not the IDKEY under the default DDL settings).

Run directly against IRIS on the same lab: with a row held, `SET OPTION LOCK_TIMEOUT = 0` made an `UPDATE` fail with
`-110` in 0.00 s, and `LOCK_TIMEOUT = 2` in 2.00 s, against 10.00 s by default. `NOWAIT` as `LOCK_TIMEOUT 0` (US4) and
`lock_timeout` as `SET OPTION LOCK_TIMEOUT` (US5) both behave as the plan assumes.

### E3, ON CONFLICT

| Check                                                            | PostgreSQL           | IRIS through PGWire                                                     |
| ---------------------------------------------------------------- | -------------------- | ----------------------------------------------------------------------- |
| `executemany` of `DO UPDATE` over `[(1, 99), (2, 2)]`            | `(1, 99)`, `(2, 2)`  | the same (the predicted bug is in the embedded path, not run)           |
| single `DO UPDATE`                                               | `(1, 99)`, 1 row     | the same                                                                |
| `DO NOTHING` with a foreign-key violation                        | `23503`              | no error, nothing inserted                                              |
| `ON CONFLICT (k) DO NOTHING`, row collides on another unique key | `23505`              | no error                                                                |
| 1000 upserts racing a `DELETE` loop                              | 1 row each, no error | never 0 rows; 0 to 3 failures per run with XX000 (DBAPI `<LIST ERROR>`) |
| the same race with native `INSERT OR UPDATE`                     | (ON CONFLICT)        | never 0 rows; 0 or 1 `-110` lock timeout (`40001`) per run              |

Which ON CONFLICT forms IRIS `INSERT OR UPDATE` expresses exactly (PostgreSQL ran the ON CONFLICT form, PGWire the
`INSERT OR UPDATE` a translation would send):

| ON CONFLICT form                                                     | Exact? | IRIS's result when not                                 |
| -------------------------------------------------------------------- | ------ | ------------------------------------------------------ |
| PK the only unique key, `SET` every inserted column `= EXCLUDED.col` | yes    |                                                        |
| the same, insert path (no conflict)                                  | yes    |                                                        |
| `SET` a subset of the inserted columns                               | no     | overwrites the other columns too                       |
| `SET v = t.v + EXCLUDED.v` (reads the existing row)                  | no     | writes the inserted value                              |
| `DO UPDATE ... WHERE` false                                          | no     | updates anyway                                         |
| table has a second unique key, the row collides on it, target `(k)`  | no     | updates the other row and **rewrites its primary key** |
| target is the secondary key, inserted PK differs                     | no     | **rewrites the primary key** to the inserted one       |
| `DO NOTHING`                                                         | no     | (no INSERT OR UPDATE form)                             |

So US3's mapping applies only when the table's one unique constraint is the conflict target and `DO UPDATE` sets every
inserted non-key column from `EXCLUDED`, with no `WHERE`. Everything else needs the emulation or a refusal.

### E4, savepoints

| Script                                        | PostgreSQL                          | IRIS through PGWire                                                        |
| --------------------------------------------- | ----------------------------------- | -------------------------------------------------------------------------- |
| psycopg nested `transaction()` raising inside | rows 1, 3                           | rows **1, 2, 3**: `ROLLBACK TO "_pg3_1"` fails (-1), psycopg ignores it    |
| `ROLLBACK TO SAVEPOINT nosuch`, then COMMIT   | `3B001`, COMMIT is ROLLBACK, empty  | `08000` (-375), whole transaction rolled back, COMMIT succeeds, empty      |
| the same with savepoint `a` established       | `3B001`, empty                      | `08000`, whole transaction rolled back, empty                              |
| `ROLLBACK TO s` twice, with an insert between | both succeed, row 1 only            | second gets `08000` (-375) and rolls back **nothing**: rows 1, 3 committed |
| `RELEASE SAVEPOINT` of an existing savepoint  | succeeds                            | `08000` (-51, IRIS has no RELEASE), nothing rolled back                    |
| `RELEASE` after `ROLLBACK TO`                 | succeeds                            | `08000`                                                                    |
| `RELEASE` of an unknown savepoint             | `3B001`, transaction aborted, empty | `08000`, transaction continues, row 1 committed                            |

IRIS's ROLLBACK reference says a missing or already rolled back savepoint rolls back the entire transaction. Measured,
that holds for a name never created but not for one already rolled back to.

### E5, an error inside a transaction

On both protocols: `BEGIN; INSERT 1; INSERT 1` (a duplicate key); `INSERT 2; COMMIT` committed rows 1 and 2.
PostgreSQL refused `INSERT 2` with `25P02`, turned COMMIT into ROLLBACK and left the table empty. ReadyForQuery stayed
`T` after the error where PostgreSQL sends `E`.

### Other findings

- **A unique violation on a table created moments before arrives as `08000`, not `23505`.** On a table dropped and
  recreated just before, the duplicate-key error reaches the DBAPI driver as `<LIST ERROR> Incorrect list format,
unsupported type for IRISList` instead of SQLCODE -119: 10 of 10 in the suite's check, 57 of 60 by hand, with or
  without a transaction. On a table that has existed a while it is a correct `23505` (175 of 175). It is what the
  ON CONFLICT emulation hit in the upsert-vs-delete race (XX000), because the emulation catches exactly this error.
  Applications that create a table and insert into it at once (tests, migrations, seeders) get the wrong SQLSTATE,
  and an ORM that branches on `23505` misreads it. Not yet narrowed to the driver or IRIS.
- **A connection that hit that error may stay damaged in the pool.** In the suite's whole runs, after the race, later
  unrelated sessions failed with the same `<LIST ERROR>`, and the connection was not marked failed
  (`connection_lost=False`). `make isolation` therefore starts a fresh server, disables pytest-randomly, and runs the
  checks that damage pooled connections (H3, cancel, the race) last. Whether a damaged connection stays damaged was not
  isolated from the new-table trigger above.
- PostgreSQL's `%` operator is not translated (SQLCODE -14).
- IRIS SQLCODEs PGWire does not map reach the client as `08000`, a connection-exception class, which tells a pool to
  discard a healthy connection: -14, -51 and -375 above. `classify_iris_error` should default to `XX000` and map -375
  to `3B001`.
- `INSERT OR UPDATE INTO t` is rewritten to `INSERT OR UPDATE SQLUser."INTO" T` (SQLCODE -30); without `INTO` it works.
- `FOR SHARE`, `FOR NO KEY UPDATE` and `FOR KEY SHARE` fail with `42601` (-1), `NOWAIT` and `SKIP LOCKED` with `42601`
  (-25). `pg_advisory_lock`, `pg_try_advisory_lock`, `pg_advisory_xact_lock` and `pg_advisory_unlock` fail with
  `42883` (-359).
- On the extended protocol a contended READ COMMITTED read waited 10 s, not 20 s, so the Describe probe did not run the
  query a second time for these psycopg executes.

### Not measured

The embedded backend (DBAPI only, by decision), E6 lock escalation and E7 pgbench (both need an enterprise-key lab),
and whether an IRIS async reporting mirror would serve row 6.

## 6. Sources

InterSystems IRIS documentation (records read from the 2026.2 documentation; the links point at the current version):

- [iris-settx]: SET TRANSACTION, including isolation levels, READ COMMITTED waits and `-114`, and READ VERIFIED —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_settransaction>
- START TRANSACTION — <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_starttransaction>
- [iris-select]: SELECT, the synopsis and "More About → Transaction Processing" (READ COMMITTED exceptions for
  `%NOLOCK`, `DISTINCT`, `GROUP BY` and aggregates) —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_select>
- [iris-sum]: SUM, "Changes Made During the Current Transaction" —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_sum>
- [iris-declare]: DECLARE, where `FOR UPDATE` and `FOR READ ONLY` "perform no operation" —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_declare>
- UPDATE, covering `-110` and `%NOLOCK` — <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_update>
- [iris-insert]: INSERT, "Transaction Considerations" and "Modify Transaction Lock Threshold" —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_insert>
- [iris-setoption]: SET OPTION, covering `LOCK_TIMEOUT` and `LOCK_ESCALATION_THRESHOLD` —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_setoption>
- [iris-locktimeout]: CPF `[SQL] LockTimeout`, default 10 —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RACS_LockTimeout>
- [iris-lock]: LOCK TABLE — <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_lock>
- [iris-savepoint]: SAVEPOINT — <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_savepoint>
- [iris-rollback]: ROLLBACK — <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_rollback>
- Transaction Processing (savepoints, non-transactional operations) —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_modify>
- [iris-deadlock]: Avoiding Deadlock — <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GAPPS_lockreq>
- [iris-cos-lock]: LOCK (ObjectScript) — <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RCOS_clock>
- [iris-insertorupdate]: INSERT OR UPDATE —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_insertorupdate>
- [iris-rowversion]: RowVersion, AutoIncrement and Serial Counter Fields —
  <https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_tables>

PostgreSQL documentation (chapter 13 and the SQL reference):

- [pg-mvcc]: 13.1 Introduction — <https://www.postgresql.org/docs/current/mvcc-intro.html>
- [pg-iso]: 13.2 Transaction Isolation — <https://www.postgresql.org/docs/current/transaction-iso.html>
- [pg-locks]: 13.3 Explicit Locking (13.3.4 Deadlocks, 13.3.5 Advisory Locks) —
  <https://www.postgresql.org/docs/current/explicit-locking.html>
- [pg-select]: SELECT, The Locking Clause — <https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE>
- [pg-insert]: INSERT, ON CONFLICT clause — <https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT>
- [pgbench]: pgbench — <https://www.postgresql.org/docs/current/pgbench.html>; source
  <https://github.com/postgres/postgres/blob/master/src/bin/pgbench/pgbench.c> (COPY FREEZE for version 14 and later,
  `vacuum analyze`, retry on `40001` and `40P01`)
- [pg-isotest]: isolation tester README — <https://github.com/postgres/postgres/blob/master/src/test/isolation/README>
- [pg-isotester-c]: isolationtester.c — <https://github.com/postgres/postgres/blob/master/src/test/isolation/isolationtester.c>

Benchmarks and anomaly checkers:

- [sysbench-lua]: https://github.com/akopytov/sysbench/blob/master/src/lua/oltp_common.lua
- [sysbench-pg]: https://github.com/akopytov/sysbench/blob/master/src/drivers/pgsql/drv_pgsql.c
- [hammerdb]: https://github.com/TPC-Council/HammerDB/blob/master/src/postgresql/pgoltp.tcl
- [benchbase]: https://github.com/cmu-db/benchbase "`config/postgres/sample_tpcc_config.xml`,
`src/main/java/com/oltpbenchmark/benchmarks/tpcc/procedures/NewOrder.java`,
`src/main/resources/benchmarks/tpcc/ddl-postgres.sql`"
- TPC-C specification, consistency conditions (clause 3.3.2) — <https://www.tpc.org/tpcc/>
- [hermitage]: <https://github.com/ept/hermitage>; [hermitage-pg]: <https://github.com/ept/hermitage/blob/master/postgres.md>
- [elle]: <https://github.com/jepsen-io/elle>; [elle-cli]: <https://github.com/ligurio/elle-cli>
- [jepsen-pg]: https://jepsen.io/analyses/postgresql-12.3

ORM and tool documentation (for section 2's ORM table):

- SQLAlchemy PostgreSQL dialect (isolation level, `ON CONFLICT`) — <https://docs.sqlalchemy.org/en/20/dialects/postgresql.html>
- SQLAlchemy `with_for_update` — <https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.Select.with_for_update>
- Django databases, PostgreSQL isolation level — <https://docs.djangoproject.com/en/stable/ref/databases/#isolation-level>
- Django `select_for_update` — <https://docs.djangoproject.com/en/stable/ref/models/querysets/#select-for-update>
- Rails configuration, `advisory_locks` — <https://guides.rubyonrails.org/configuring.html>
- Solid Queue (`FOR UPDATE SKIP LOCKED`) — <https://github.com/rails/solid_queue>
- Prisma Migrate advisory locking — <https://www.prisma.io/docs/orm/prisma-migrate/workflows/development-and-production#advisory-locking>
- Prisma transaction isolation level — <https://www.prisma.io/docs/orm/prisma-client/queries/transactions#transaction-isolation-level>
- Npgsql EF Core concurrency tokens (`xmin`) — <https://www.npgsql.org/efcore/modeling/concurrency.html>
- psycopg 3.3.4 `psycopg/transaction.py` (savepoint rollback sends `ROLLBACK TO` then `RELEASE`) —
  <https://github.com/psycopg/psycopg/blob/master/psycopg/psycopg/transaction.py>

In-repo measurements this note builds on:

- [`KNOWN_LIMITATIONS.md`](../../KNOWN_LIMITATIONS.md), section "Transaction Isolation: No MVCC, No Snapshots"
- [`specs/051-unified-executor/research.md`](../../specs/051-unified-executor/research.md), sections "Transaction
  ownership is per-session on DBAPI" and "The licence ceiling is real"
- [`CHANGELOG.md`](../../CHANGELOG.md), section `[2.0.0]`, the isolation changes

[iris-settx]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_settransaction
[iris-select]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_select
[iris-sum]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_sum
[iris-declare]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_declare
[iris-insert]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_insert
[iris-setoption]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_setoption
[iris-locktimeout]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RACS_LockTimeout
[iris-lock]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_lock
[iris-savepoint]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_savepoint
[iris-rollback]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_rollback
[iris-deadlock]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GAPPS_lockreq
[iris-cos-lock]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RCOS_clock
[iris-insertorupdate]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_insertorupdate
[iris-rowversion]: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_tables
[pg-mvcc]: https://www.postgresql.org/docs/current/mvcc-intro.html
[pg-iso]: https://www.postgresql.org/docs/current/transaction-iso.html
[pg-locks]: https://www.postgresql.org/docs/current/explicit-locking.html
[pg-select]: https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE
[pg-insert]: https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT
[pgbench]: https://www.postgresql.org/docs/current/pgbench.html
[pg-isotest]: https://github.com/postgres/postgres/blob/master/src/test/isolation/README
[pg-isotester-c]: https://github.com/postgres/postgres/blob/master/src/test/isolation/isolationtester.c
[hermitage]: https://github.com/ept/hermitage
[hermitage-pg]: https://github.com/ept/hermitage/blob/master/postgres.md
[elle]: https://github.com/jepsen-io/elle
[elle-cli]: https://github.com/ligurio/elle-cli
