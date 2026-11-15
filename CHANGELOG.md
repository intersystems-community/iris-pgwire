# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.1.0] - 2026-11-15

PostgreSQL's transaction rules on the DBAPI backend (spec 052). An application written for PostgreSQL gets the same answer from IRIS through PGWire, or a PostgreSQL error naming what IRIS cannot do. In 2.0 it often got a wrong answer and no error: a failed statement left the transaction committable, `FOR UPDATE` locked nothing, an upsert updated nothing and reported success, and a cancel was ignored. Every behaviour below is checked against PostgreSQL 16 by the isolation suite (`make isolation`); what each PostgreSQL feature does through PGWire, and what is refused, is in `docs/POSTGRES_APP_COMPATIBILITY.md`.

The embedded backend is unchanged except for the abort rule and the savepoint stack, which live in the protocol layer and apply to both.

### Behaviour changes

Read these before upgrading. Each one turns a silent wrong answer into PostgreSQL's behaviour or an error. Two settings restore parts of 2.0's behaviour.

- **A failed statement aborts its transaction.** Inside `BEGIN`, an error sets the transaction status to failed (`E` in ReadyForQuery). Every later statement except `COMMIT`, `ROLLBACK` and `ROLLBACK TO SAVEPOINT` gets `25P02`, and `COMMIT` rolls back and replies `ROLLBACK`. In 2.0 the statements around the failure committed. After an error on the extended protocol, messages up to `Sync` are discarded, and a multi-statement `Query` stops at its first error. Both backends.
- **New DBAPI sessions run at READ COMMITTED**, PostgreSQL's default; 2.0 ran them at IRIS's READ UNCOMMITTED, so they read other sessions' uncommitted writes. Reads of a row another transaction is writing now wait for it (IRIS's lock timeout, 10 s by default) and then fail with `40001`. `PGWIRE_DEFAULT_ISOLATION=read uncommitted` restores 2.0's default; any other value stops the server at startup, naming the accepted ones. The pool applies the level to every new connection and to every connection it takes back.
- **What IRIS cannot do exactly is refused with `0A000`**, naming the shape, instead of running something else:
  - `SELECT ... FOR UPDATE` on a join, a subquery or view in `FROM`, with `LIMIT`/`OFFSET`/`TOP`, or on a table with an UPDATE trigger or a `ROWVERSION` or generated column; `FOR SHARE`, `FOR NO KEY UPDATE`, `FOR KEY SHARE` and `SKIP LOCKED`. These were `42601` (IRIS's syntax error) or, for some shapes, ran without a lock.
  - `INSERT ... ON CONFLICT` in any form but the exact one below, `DO NOTHING` included.
  - `PGWIRE_TXN_COMPAT=permissive` runs refused `ON CONFLICT` statements through 2.0's emulation, with its bugs fixed (see Fixed), and logs a warning once per statement shape. Locking clauses are refused in both modes. Any other value stops the server at startup.
- **String columns of tables PGWire creates compare case-sensitively.** IRIS's default collation ignores case, so on a table created through PGWire `c = 'RED'` matched `red` and `Red`, `IN` and `LIKE` ignored case, `min(c)` returned an upper-cased value that wasn't in the table, and a unique key refused `'X'` after `'x'` (`23505`). `CREATE TABLE` and `ALTER TABLE ... ADD COLUMN` now declare every character column `COLLATE %EXACT`, and a PostgreSQL `COLLATE "name"` (DuckDB writes `COLLATE "C"`) is accepted as the same. Strings then sort by code point, as PostgreSQL's `C` collation does, not by a locale. Tables created before 2.1, or outside PGWire, keep their collation: see `KNOWN_LIMITATIONS.md`. Found by irispython-dx's SQLGlot work.
- **New SQLSTATEs**:
  - `55P03` when a lock wait runs out under a `lock_timeout` the client set, and for `FOR UPDATE NOWAIT`. A wait under the server's default timeout is still `40001`.
  - `54000` for the 255th savepoint in one transaction. IRIS keeps 254 alive, released ones included, and the 255th failed with SQLCODE -400 and lost the transaction's work.
  - `57014` for a cancelled statement.
  - `23503` for a foreign-key violation (IRIS SQLCODE -121 to -124), which was `XX000`.
  - `XX000` for the DBAPI driver's `<LIST ERROR>` on every path; the Execute path reported `42P03`.
- **A CancelRequest cancels the statement.** PGWire ends the session's IRIS process (`%SYSTEM.Process.Terminate`, from a connection of its own), so the running statement fails with `57014` within a second and IRIS rolls back its transaction; the session carries on, at its own isolation level, on a fresh connection. In 2.0 the request was acknowledged and ignored, and the cancelled write still ran. PGWire's IRIS user needs permission to end processes; without it the statement runs to completion and is still not committed.
- **Pool connections are out of the DBAPI driver's autocommit mode.** In that mode a write whose client had gone still committed once its lock wait ended (measured with the driver alone; with autocommit off the write was discarded). PGWire commits after each statement of an autocommit session, as before.

### Added

- **Savepoints are tracked by PGWire** (`savepoints.py`). `RELEASE SAVEPOINT`, which IRIS lacks, is answered without sending anything, so psycopg's nested `transaction()` blocks that exit normally no longer raise. A savepoint is re-established after `ROLLBACK TO`, an unknown name is `3B001` and a savepoint outside a transaction `25P01`, as on PostgreSQL.
- **`SELECT ... FOR UPDATE` locks the rows.** IRIS takes no lock for it. Inside a transaction, a single-table `FOR UPDATE` first runs `UPDATE t SET pk = pk WHERE <the same predicate>` and then the `SELECT` without the clause, so a read-then-write counter no longer loses updates. `NOWAIT` runs that update with IRIS's lock timeout at 0.
- **`ON CONFLICT` runs as IRIS's `INSERT OR UPDATE`** when its target is the table's only unique key and `DO UPDATE` sets every inserted column from `EXCLUDED`, with no `WHERE`. Only then do the two statements do the same thing.
- **`SET lock_timeout`** sends IRIS's `SET OPTION LOCK_TIMEOUT`, rounded up to whole seconds (IRIS has no finer unit); `0` and `RESET` restore the server's default wait, and `SHOW` gives PostgreSQL's spelling. Values parse as PostgreSQL 16 parses them, units and `22023` messages included. A session's value is undone when its connection goes back to the pool.
- **SQLAlchemy 2 (`postgresql+psycopg`)** connects, runs Core and ORM CRUD, and nests savepoints with `begin_nested()`. Before, `engine.connect()` failed at `select current_schema()`. Fixed along the way: `current_schema()` and `current_schemas()`, psycopg's `TypeInfo.fetch()` (so pgvector's `register_vector` finds `vector`), `has_table()`, the ORM's multi-row `INSERT ... RETURNING` (now one insert per row, in order), ORM updates (which raised `StaleDataError`), and `SHOW transaction_read_only`.
- **`docs/POSTGRES_APP_COMPATIBILITY.md`**, linked from `KNOWN_LIMITATIONS.md`: each statement about what works or is refused names the isolation-suite check that backs it, and a unit test keeps the two in step.
- **The isolation suite is a release gate** (`docs/RELEASE_CHECKLIST.md` 2a): `make isolation`, `make isolation-permissive` and `make isolation-read-uncommitted`. `make isolation-coverage` and `make coverage-052` fail below 90% coverage of spec 052's modules.

### Fixed

- **Extended-protocol statements are faster** than in 2.0.1: a SELECT by primary key 1.8 ms instead of 3.2, an UPDATE 0.8 instead of 1.0, a three-statement transaction 3.6 instead of 5.3 (DBAPI backend, Enterprise IRIS 2026.1, median of three alternating runs of `benchmarks/spec052_statement_overhead.py`). Every result over the extended protocol waited 1 ms before going back to read the next message, and every NoData formatted the whole call stack for a log line. Both are removed.
- **`GROUP BY 1` grouped nothing.** IRIS reads `GROUP BY <number>` as a constant, so `SELECT status, count(*) FROM orders GROUP BY 1` returned one row over every order. Each position now becomes the matching select-list expression. Ibis writes this form for every aggregation. An out-of-range position still gives one row where PostgreSQL raises `42P10`.
- **2.0's `ON CONFLICT` emulation** (used under `PGWIRE_TXN_COMPAT=permissive`) decided by error text; it now decides by SQLCODE -119 on the target's own fields. It honours `DO NOTHING`'s target, reports a conflict on another key (`23505`) and a foreign-key violation (`23503`), and reads literal `VALUES` and the table's columns: for those, 2.0 updated nothing and reported success.
- **`PGWIRE_TXN_COMPAT` and `PGWIRE_DEFAULT_ISOLATION` were never read by the server**: `server.py` built its configuration by hand and dropped them.
- **`SET lock_timeout` and `SET statement_timeout` were answered with success** by the protocol layer and never reached IRIS.
- **A transaction-ending `ROLLBACK` uses the driver's rollback.** IRIS's SQL `ROLLBACK` costs about 33 ms per open savepoint (8.7 s with 254); the driver's takes 30 to 55 ms at any depth.
- **Batched statements**: two different statements in one pipeline no longer share the fast-batch path (it ran the first one twice, or failed with `<LIST ERROR>`); `ON CONFLICT`, `UPDATE` and `DELETE` stay off it, so a refusal answers its own Execute and psycopg's rowcount is right.
- **The translator**: the word after `FOR UPDATE` was schema-qualified as a table (`FOR UPDATE SQLUser."NOWAIT"`), and the `GROUP BY` collation rewrite swallowed a following locking clause.

### Not changed

- **`statement_timeout`** is accepted and shown but not enforced; it is logged once per session.
- **An extended-protocol read of a row another transaction holds waits twice** at READ COMMITTED (20 s by default) before `40001`: Describe runs the statement to learn its columns, and Execute runs it again.
- **REPEATABLE READ and SERIALIZABLE are refused** with `0A000`, as in 2.0: IRIS gives neither guarantee. Advisory locks are not provided. `docs/POSTGRES_APP_COMPATIBILITY.md` lists the rest.

## [2.0.1] - 2026-11-15

Transaction fixes for the DBAPI backend, two of them critical, and the ADBC work done since 2.0.0. The first five `Fixed` entries were measured by the track 4 isolation suite (`make isolation`); see `docs/investigations/mvcc-apps-on-iris-pgwire.md` section 5.

### Added

- **The stock ADBC PostgreSQL driver works** (`adbc-driver-postgresql`, used by pandas, Polars, DuckDB and dbt Fusion's Postgres adapter). Before, it could not connect (`Expected 5 or 6 columns from type resolver pg_type query but got 4`), and once it could, every result failed. Verified against 1.12.0 on both backends in both of its fetch modes (binary `COPY`, the only one dbt Fusion uses, and plain binary results). See `docs/ADBC.md` for what works and what does not yet: `adbc_get_objects`, `adbc_get_table_schema` and `adbc_ingest` do not, and `time` and (on the embedded backend) `numeric` columns are declared with the wrong type.
- **`COPY (query) TO STDOUT` in `text`, `csv` and `binary`**, over the simple and the extended protocol, with PostgreSQL's defaults (text, tab-separated, `\N` for NULL). The output matches PostgreSQL 16.15 byte for byte, message boundaries included, which the ADBC driver depends on. The option list no longer needs `WITH` (`COPY (...) TO STDOUT (FORMAT binary)`), and the legacy `BINARY` and `CSV HEADER` keywords are accepted.
- **`pg_type` is a view of rows captured from a real PostgreSQL 16** (`scripts/capture_pg_type.py`): all 32 columns in PostgreSQL's order, including the `typreceive`, `typsend`, `typelem` and `typarray` that clients use to decide how to decode a column, for every type this server can emit and its array type, plus pgvector's. It replaces a handler that matched the shape of a query in Python, answered with four columns of its own choosing and ignored the `WHERE`.
- **Binary encoding of result values is PostgreSQL's** (`value_encoding.py`), checked against bytes captured from a real PostgreSQL 16 for 41 cases: `date`, `time`, `timestamp(tz)`, `numeric` (including NaN and any float or string), `bytea`, `uuid`, `json`, `jsonb`, `vector`, and arrays of those.

### Changed

- **A value that cannot be encoded in the requested binary format is now an error, not text.** The previous encoder sent `str(value)` and logged a warning, so a binary client received text bytes where it expected, say, a 4-byte integer. It also truncated a non-integer sent as an integer (`7.9` became `7`). Both now raise (`22P03`). An OID with no binary format defined still sends its text.
- **`COPY` defaults to PostgreSQL's text format** for `TO STDOUT` when no `FORMAT` is given (it was CSV). `COPY ... FROM STDIN` is unchanged.

### Fixed

- **A disconnected client's open transaction was handed to the next session** (critical, DBAPI backend). When a client disconnected, its IRIS connection went back to the pool with the transaction still open and the isolation level unchanged. The next session given that connection ran inside the abandoned transaction: it read the uncommitted writes, and a bare `COMMIT` from it made them permanent. A session that reported the default level could also run at the previous client's level. On session close PGWire now rolls back, resets the level to the server default, and discards the connection if either step fails. This was the cause of "an accepted `READ COMMITTED` is sometimes not in force"; on a clean connection IRIS honoured it every time.
- **A connection that gave the driver's `<LIST ERROR> Incorrect list format` is no longer reused.** It stays with its session, so a transaction is never moved mid-way, and is discarded when the session ends. The error replaces a unique violation on a connection that had one on the same table before the table was recreated; it comes from below PGWire, and a fresh connection reports `23505`.
- **psycopg's nested `transaction()` blocks committed the inner block's work on rollback** (critical, DBAPI backend). psycopg sends `ROLLBACK TO "_pg3_1"`; the DBAPI backend never added the `SAVEPOINT` keyword IRIS requires, so the statement failed, psycopg ignored the failure, and the inner block's rows were committed. SQLAlchemy's `begin_nested()` was not affected: it spells out `ROLLBACK TO SAVEPOINT`. The rewrite now runs on both backends and matches quoted names, including spaces and doubled quotes. `RELEASE SAVEPOINT` still fails (IRIS has none); psycopg ignores that failure after a rollback, but a nested block that exits normally still raises it.
- **`ROLLBACK TO SAVEPOINT` no longer ends the transaction in PGWire's bookkeeping.** It was taken for a `ROLLBACK`, so the next statement was auto-committed, committing the work before the savepoint with it.
- **Unmapped IRIS errors are `XX000`, not `08000`.** The query, `SET` and `COPY` paths reported any error the classifier did not recognise as `connection_exception`, which tells a client-side pool to discard a healthy connection. `08000` is now kept for a transport failure the error text names. IRIS SQLCODE -375 (unknown savepoint) is `3B001`, as on PostgreSQL.
- **`COPY (query) TO STDOUT` returned the names of the result dictionary's keys** (`success`, `rows`, `columns`, ...) as CSV characters, for every query, because the export iterated the dict the executor returns. It also sent `CopyOutResponse` before running the query, with a column count of 0 and always as text, so a binary client was told the wrong thing before any data existed, and a failing query could only be reported from inside a copy. The query now runs first; a failure is an `ErrorResponse` and no copy. The row count in the command tag is exact (it was counted from newlines).
- **A trailing `;` hid a statement's own column types.** The simple-query path appends `;` before executing, and the type resolver took it as part of the last alias (`AS v;`), so the lookup matched nothing and every statement on that path lost its `CAST(... AS DATE)` and boolean typing. The same query was `varchar` over the simple protocol and `date` over the extended one.
- **`BEGIN TRANSACTION`, `BEGIN WORK`, `COMMIT TRANSACTION`, `END WORK`, `ABORT` and the other PostgreSQL spellings** were sent to IRIS as SQL. The embedded backend happened to accept some and so skipped the server's transaction bookkeeping; the DBAPI backend refused them (`SQL statement expected, BEGIN found`), which made every statement from the ADBC driver, whose spelling is `BEGIN TRANSACTION`, fail.
- **The column names in a `COPY` header** now match `RowDescription`'s (lower case); the shared rule is `wire_column_name`.
- **A bare `pg_type`** (no schema) reaches the view. The schema mapper keeps its own list of view-backed tables, and a test now compares it with the definitions, as a comment there had promised.

## [2.0.0] - 2026-11-13

### BREAKING

- **Clients must now authenticate.** Every earlier version accepted any client and ignored the password: the server answered `AuthenticationOk` before any credential was exchanged, and every session ran as the configured IRIS service account. The server now asks for the client's IRIS password (PostgreSQL's cleartext password exchange) and checks it by logging in to IRIS with it; IRIS remains the only store of users and passwords, and pgwire keeps no verifier. A wrong password, an unknown user and an empty password are refused identically (`28P01`), so the answer does not reveal which accounts exist; an IRIS outage is reported as `57P03`, never as a wrong password.

  The password crosses the wire, so TLS is required. A server started with no TLS and no explicit choice **refuses to start** and says why. The choices:

  - TLS: `PGWIRE_SSL_ENABLED=true` with `PGWIRE_SSL_CERT` and `PGWIRE_SSL_KEY`. When TLS is on, a client that does not negotiate it is refused (`28000`) before any password prompt.
  - `--allow-plaintext-password` (`PGWIRE_ALLOW_PLAINTEXT_PASSWORD=true`): accept passwords over a plain connection, for a trusted network or behind a TLS-terminating proxy.
  - `--trust` (`PGWIRE_AUTH_MODE=trust`): no authentication, the previous behaviour, now an explicit opt-in that logs a warning at startup. For local development.

  To upgrade, give clients real credentials or pass `--trust`. `PGWireServer(...)` now defaults to `auth_mode="password"`, so code that builds one directly must pass `auth_mode="trust"` or an option above. The docker-compose development container sets `PGWIRE_ALLOW_PLAINTEXT_PASSWORD=true`.

  Authentication proves the client knows an IRIS user's password. It does **not** change who a session runs as: statements still execute as the service account, so every user who can log in has that account's privileges. For that reason **only the service account may log in unless you list others**: `PGWIRE_ALLOWED_USERS` (or `--allowed-users`) names the login users, and a list replaces the default rather than extending it. A user who is not listed is refused without any attempt to log in to IRIS, so a stranger cannot spend another user's failed-login attempts, and the refusal reads and times exactly like a wrong password. IRIS's own lockout policy applies to failed logins. See ADR-0003 and ADR-0004. On the embedded backend the check runs in a short-lived child process, because a successful `%SYSTEM.Security.Login` switches the calling process to that user, which in the shared server would change the identity of every concurrent query.

- **SCRAM-SHA-256, OAuth 2.0 and IRIS Wallet credentials are not available, their code is removed, and `PGWIRE_ENABLE_SCRAM` / `enable_scram=True` now stop the server at startup.** They were documented as features and never provided authentication: the SCRAM exchange accepted "any well-formed client-final message", handed the next stage the literal password `"placeholder_password"` and answered with a constant server signature; `PGWIRE_ENABLE_SCRAM` was not read by any code; and a libpq client with the correct password could not log in under SCRAM at all, because the server rejected the empty `n=` username libpq sends. A SCRAM request that was silently ignored left a deployment believing it had authentication. The unreachable code is deleted rather than left as code that fails open: about 1,590 lines in `iris_pgwire.auth` (`scram`, `oauth_bridge`, `wallet_credentials`, `auth_selector`), the 350-line SCRAM handler in `protocol.py`, and the 177 tests that covered only that code. The Kerberos/GSSAPI authenticator, which is also not wired in, stays. The removed code is in git history.

### Fixed

- **The IPM package could not start the server, in any release.** `IrisPGWire.Service.Start()` ran `irispython -m iris_pgwire.server` from the IRIS process's directory, where the package IPM installs (`mgr/python/iris-pgwire/`) is not importable, and it used `%Library.Pipe`, which does not exist in IRIS 2026. It also printed "started successfully" before checking anything. `Start()` now takes the authentication options (`Start(pAllowPlaintextPassword, pTrust, pAllowedUsers, pSSLCert, pSSLKey, pPort, pWaitSeconds)`), launches from the package directory, waits until the server reports that it is listening, and returns the server's own reason when it refuses to start. Values that reach the shell (users list, port, certificate paths) are checked first. `Restart()` keeps the options. See `docs/INSTALLATION.md`.
- **SIGTERM did not stop the server**, so `docker stop` waited out its grace period and `IrisPGWire.Service.Stop()` reported failure, which also failed IPM's Deactivate (uninstall). The server now shuts down on SIGTERM and SIGINT, and `Stop()` falls back to SIGKILL after a grace period.
- **TLS never completed.** `handle_ssl_probe` slept 0.1 s between answering `S` and upgrading the connection, but a client sends its ClientHello the moment it reads `S`, so the plain `StreamReader` consumed those bytes as application data and the handshake hung until it timed out. Reading is now paused before `S` is sent. A client with `sslmode=require` against a TLS-enabled server connected to nothing before this.

- **The embedded backend returned zero rows for any query that selected a `VECTOR` value**, with no error and a normal `CommandComplete`. This covered `SELECT v`, `SELECT *` on a table with a vector column, a computed `TO_VECTOR(...)` in the select list, and `INSERT … RETURNING v`. IRIS cannot hand a logical vector to embedded Python, so the row fetch raised `<OBJECT DISPATCH> *Invalid argument type`, and the executor logged that as a warning and returned an empty result. The DBAPI backend was unaffected. A read-only statement that fails this way is now re-executed in ODBC select mode, where vectors arrive as text, byte-identical to DBAPI's. Every other column keeps exactly the value it had before. A statement that could write is never re-executed, and any other fetch error is now reported to the client instead of becoming an empty result. `tests/e2e/test_vector_projection.py` runs the same assertions against each backend.

- **Transaction isolation was reported, not applied**: `SET TRANSACTION ISOLATION LEVEL …` was swallowed by the generic `SET` shim in `protocol.handle_set_command`, which reads `SET\s+(\w+)`, took the parameter name to be `TRANSACTION`, and answered `CommandComplete("SET")` without sending anything to IRIS. `SHOW TRANSACTION ISOLATION LEVEL` then answered a hardcoded `"read committed"`, and `SHOW transaction_isolation` — the spelling psycopg and SQLAlchemy actually send — missed the lookup table entirely and returned an empty setting. A client asking for READ COMMITTED got success, no effect, and then confirmation of a level it did not have.

  All isolation statements now reach IRIS, and the level is recorded only once IRIS has accepted it, so a level is never reported unless it was applied:

  - `SET TRANSACTION ISOLATION LEVEL`, `SET [SESSION|LOCAL] transaction_isolation = …`, `SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL`, `SET default_transaction_isolation = …`, and the level named on `BEGIN` / `START TRANSACTION`.
  - `transaction_isolation` and `default_transaction_isolation` are kept apart, with the scoping PostgreSQL 16 measurably has: a transaction-scoped level ends with the transaction (COMMIT and ROLLBACK alike), the session default outlives it, and a default set inside a transaction is undone by ROLLBACK. Note that `SET SESSION TRANSACTION ISOLATION LEVEL` is transaction-scoped despite the keyword. IRIS holds one level per session, so IRIS is resynced before the next transaction opens when the effective level changes because a transaction ended rather than because a client asked.
  - A closed session's isolation state is dropped, so a reused session id cannot inherit the previous client's level.

- **Embedded-Python detection said yes on a host that cannot run embedded Python**: `_detect_iris_environment` asked `hasattr(iris, "sql") and hasattr(iris.sql, "exec")`. Measured on both sides, `hasattr` cannot answer that question — on a host with `iris-embedded-python-wrapper` installed, the `iris` module carries a module-level `__getattr__` that returns a `unittest.mock.MagicMock` for any attribute it does not have, and the embedded module answers any attribute with an `iris.package` placeholder, so both are True in both environments. (The mock is the wrapper's, not the stock driver's: `intersystems-irispython` 5.3.2 and 5.4.0 both raise `AttributeError` for an unknown attribute when the wrapper is absent, and their `iris/__init__.py` imports the wrapper's `__getattr__` only `if os.path.exists(../iris_ep.py)` — while the `iris/__init__.py` on disk here is the wrapper's own, which imports it unconditionally.) On a developer host the executor therefore chose the embedded execution path and called `MagicMock.exec` for every query, which answers with another `MagicMock` rather than raising. Detection is now affirmative: the module must _declare_ `sql` (present in `vars(iris)`, where a name manufactured on demand never lands) and `iris.sql.exec` must not be a test double.

- **The installed `iris-pgwire` command did nothing**: `[project.scripts]` named `iris_pgwire.server:main`, which is `async def`. A console script calls its target and discards the return value, so the command built a coroutine, emitted `RuntimeWarning: coroutine 'main' was never awaited`, and exited 0 without binding a port. Measured against the 1.7.3 wheel in a clean venv, so this is what `pip install iris-pgwire && iris-pgwire` has been doing. `python -m iris_pgwire.server` was unaffected — it goes through the `asyncio.run` under `__main__` — which is how the packaged path stayed broken while every development run worked. The entry point now names a synchronous `cli()` wrapper, and a unit test reads `[project.scripts]` from `pyproject.toml` and rejects a coroutine function as a target, so this fails in a checkout rather than in a release.

- **Command tags carried a row count PostgreSQL sends bare**: `SET`, `SHOW` and the transaction-control verbs are answered with the bare tag, and `BEGIN ISOLATION LEVEL x` is answered `BEGIN` even though the statement sent to IRIS says `START TRANSACTION`.

### Changed

- **BREAKING: `REPEATABLE READ` and `SERIALIZABLE` are refused** with `0A000 feature_not_supported` instead of being accepted and ignored. They are guarantees about what a transaction will not observe, and IRIS has no snapshot mechanism to downgrade them _to_; an error at `SET` is recoverable, a silently violated guarantee is not. This follows the existing rejection of L2 vector distance. A client that previously got a successful `SET SERIALIZABLE` — while running at READ UNCOMMITTED regardless — now gets an error, so releasing this warrants a minor version bump.

- **A mid-transaction level change is refused** with `25001 active_sql_transaction`, as PostgreSQL does, once the open transaction has run a query or entered a savepoint. Re-asserting the level already in force stays accepted, and the session-scoped spellings are always accepted because they describe the next transaction.

- **BREAKING: an unmapped IRIS error is now reported `XX000 internal_error` rather than `42000`.** The old default was defended as the vague answer clients already coped with, which was not accurate: `42000` is class 42, so every code not yet in the SQLCODE table told clients their statement text was at fault and sent them to rewrite SQL that was fine. That is the same defect the `-110` / `-114` mappings fixed — class 42 suppressing a retry — left in place as the default. Class XX is PostgreSQL's own unclassified code and carries no instruction, which is the honest content of an unmeasured error. (ODBC's `HY000` is the equivalent in a DB-API layer, but is absent from PostgreSQL's table and would arrive as an unknown class with no condition name.) Anything matching on `42000` to recognise an IRIS error stops matching; the mapped codes are unaffected, and a call site supplying its own fallback still keeps it.

### Documentation

- KNOWN_LIMITATIONS.md now records what measurement showed rather than what the levels are called: which levels exist, what IRIS's READ COMMITTED does not cover, that an accepted READ COMMITTED is not a guarantee (either a flat 10s lock timeout or an immediate dirty read, trigger not isolated), that lock conflicts arrive as retryable `40001`, that optimistic locking reports false conflicts, and that sessions share one transaction in the in-IRIS deployment. Those divergences are pinned by tests — `pytest -m pinned_limitation tests/protocol tests/integration` — so a change in one cannot leave the document quietly wrong.

## [1.7.3] - 2026-08-26

Backfilled: this version shipped without a changelog entry.

### Fixed

- **`CREATE INDEX IF NOT EXISTS … USING hnsw` not idempotent on a second run**: three interlocking causes. The `CREATE_INDEX_IF_NOT_EXISTS` construct strips `IF NOT EXISTS` and leaves a `/* IF_NOT_EXISTS */` marker before HNSW translation runs, and the HNSW patterns in `constructs.py` and `vector_syntax.py` did not match the marker, so the translated IRIS SQL dropped `IF NOT EXISTS` altogether; the simple-query path did not pass `original_sql`, so `DdlErrorHandler` only ever saw the translated DDL; and `VectorQueryOptimizer.is_duplicate_object_error` matched SQLCODEs only, while IRIS emits `Class '…' already has index named '…'.` as plain text with no SQLCODE. `original_sql` is now threaded through `_safe_execute` and `_execute_embedded_statement_sequence` as well.

- **Duplicate-index detection missed a SQLCODE that never reached the message**: `DdlErrorHandler` now checks `e.sqlcode == -324` directly as well as matching the text. `iris.sql.exec` can raise a `SQLError` whose `.sqlcode` is `-324` while `str(e)` omits it (confirmed on IRIS 2026.2), which defeated text-only matching for both HNSW and plain `CREATE INDEX IF NOT EXISTS`.

## [1.7.2] - 2026-08-26

### Fixed

- **`JSONB_CONTAINS` stored procedure always returning 1**: IRIS SQL DDL compiled the function body with uppercase parameter names (`LEFTJSON`, `RIGHTJSON`) but the function signature used camelCase (`leftJson`, `rightJson`). Since ObjectScript variable names are case-sensitive, the body variables were always undefined at runtime; IRIS treated the `<UNDEFINED>` error in the early-exit check as truthy, short-circuiting to `QUIT 1`. Fixed by aligning the signature to uppercase (`LEFTJSON VARCHAR(65535), RIGHTJSON VARCHAR(65535)`). Also hardened the `"null"` left-operand guard against IRIS string-literal uppercasing by using `$ZCVT(LEFTJSON,"L") = "null"` instead of a bare literal comparison.

- **`CREATE INDEX IF NOT EXISTS` not idempotent**: IRIS raises `"Class 'Schema.Table' already has index named 'IdxName'."` when a duplicate index is created, but `DdlErrorHandler._is_duplicate_error()` did not match this message. Added `r"already\s+has\s+index\s+named"` to the duplicate-error patterns so `IF NOT EXISTS` is honoured correctly.

## [1.7.1] - 2026-08-26

### Fixed

- **IRIS irispython compatibility**: Capped `pydantic<2.12` and added `typing_extensions>=4.12.2,<5` to prevent `pydantic>=2.12` pulling in `typing_extensions>=4.14.1`, which is newer than the `4.12.2` bundled with IRIS irispython (affects IRIS 2024.x and 2025.x). Packages running iris-pgwire inside an IRIS embedded Python environment no longer get a `DistributionNotFound` / version conflict on install.

## [1.7.0] - 2026-08-25

### Added

- **JSONB containment operator `@>` / `<@`** (feature 050): SQL normalizer now rewrites `col::jsonb @> val` to `PGWire.JSONB_CONTAINS(col, val) = 1` and `<@` with swapped arguments. `::jsonb` casts on parameter placeholders are stripped (IRIS stores JSON as VARCHAR). New `JSONB_CONTAINS` ObjectScript stored procedure installed at startup via `catalog/functions.py`; implements recursive object, array, and scalar containment semantics. Verified against [SimpleMem](https://github.com/koaning/simplemem) fork. 22 unit tests + 5 integration tests.

### Fixed

- **`execute_many()` ON CONFLICT duplicate suppression** (feature 049): When `ON CONFLICT DO NOTHING` is stripped before batch execution, per-row IRIS duplicate key errors (5804) are now suppressed and counted as skipped rather than crashing the entire batch. psycopg3 pipeline-mode Sync/Flush already handled correctly (confirmed by source audit). 17 unit tests + 3 integration tests.

- **SimpleMem client compatibility** (feature 048): Five wire-protocol / SQL translation gaps that prevented [SimpleMem](https://github.com/koaning/simplemem) from running against iris-pgwire:
  - `LIMIT ?` / `OFFSET ?` parameterized clauses are now inlined as integer literals before execution (IRIS rejects `LIMIT ?`)
  - `CREATE EXTENSION IF NOT EXISTS <name>` is silently accepted (was: syntax error)
  - `ILIKE` / `NOT ILIKE` rewritten to `LOWER(col) [NOT] LIKE LOWER(val)`
  - IRIS LONGVARCHAR / CLOB stream objects unwrapped to plain strings in result rows
  - `ON CONFLICT DO NOTHING` stripped in the `execute_many()` code path (was only stripped in the single-row path)
  - 27 regression unit tests covering all five cases.

## [1.6.0] - 2026-08-24

### Added

- **surp / Neovim Supabase TUI compatibility** (`sql_translator/`): iris-pgwire now runs [surp](https://github.com/kcmyang/surp) — a Neovim TUI for Supabase-compatible databases — against IRIS without patching the client.

  - **`ARRAY[...]` constructor rewrite** (`array_literal.py`): PostgreSQL `ARRAY['a','b']` syntax is rewritten to `'{a,b}'` string literals that IRIS accepts.
  - **`ANY(col)` column membership rewrite** (`array_params.py`): `col = ANY(column_ref)` patterns are translated to `INSTR`-based substring lookup, enabling surp's `no_primary_key` lint CTE.
  - **Variadic function dispatch** (`pg_functions.py`): `format()` and `jsonb_build_object()` calls with 2 or 3 arguments are dispatched to new fixed-arity `PGWire.FORMAT2`, `PGWire.FORMAT3`, and `PGWire.JSONB_BUILD_OBJECT4/6` SQL functions, since IRIS does not support variadic SQL functions.

- **Four new ObjectScript SQL functions** (`catalog/functions.py`): `FORMAT2`, `FORMAT3`, `JSONB_BUILD_OBJECT4`, and `JSONB_BUILD_OBJECT6`, installed at startup via `CREATE OR REPLACE FUNCTION … LANGUAGE OBJECTSCRIPT`. Implements PostgreSQL `%I` (quoted identifier) and `%L` (quoted literal) format specifiers for `FORMAT2`/`FORMAT3`.

- **Five new catalog views** (`catalog/views/definitions.py`): `pg_depend`, `pg_extension`, `pg_index`, `pg_policy`, and `pg_rewrite`. These are required by surp's ERD and lint queries (`splinter.sql`). All five use the `CatalogViewInstaller` DDL path and are added to `VIEW_BACKED_TABLES` in `schema_mapper.py`.

- **Local-first sync research** (`docs/sync/`): Evaluation of PGlite, Electric's HTTP shape protocol, Replicache push semantics, and IRIS change-feed substrates (trigger outbox, journal CDC, version-column polling, Interoperability/Kafka). Includes verified IRIS journal CDC patterns and a phased implementation plan.

### Fixed

- **CTE alias qualified as user table** (`schema_mapper.py`): The bare-table schema mapper now extracts CTE names from `WITH … AS (…)` clauses and skips qualifying them. Previously, `FROM no_primary_key` in a multi-CTE lint query was rewritten to `FROM SQLUser."NO_PRIMARY_KEY"`, causing IRIS table-not-found errors.

- **`pg_class` interceptor fired on multi-CTE queries** (`catalog/catalog_router.py`): The `is_simple_pg_class` guard now excludes queries whose text begins with `WITH`, preventing surp's 5-branch `splinter.sql` CTE from being intercepted by the Python-side handler rather than executed against the view.

- **`pg_index` and `pg_extension` handler-backed intercept removed**: Both tables are now view-backed; unit tests updated to assert `result is None` (declined by router) rather than a Python-emulated result.

- **`LIST(col, sep)` separator argument** (`catalog/views/definitions.py`): IRIS `LIST()` aggregate does not accept a separator argument. Changed `LIST(col.ORDINAL_POSITION, ' ')` to `LIST(col.ORDINAL_POSITION)` in the `pg_index` view body.

- **Prisma 6 → 7 upgrade** (`examples/prisma-iris-demo`): Prisma 7.9.1 removes the indirect `deepmerge-ts/<8.0.0` risk surface introduced in 6.13+. Chevrotain pinned to `^10.5.0`.

### Changed

- **Test coverage**: 90% line coverage (16,273/18,082 lines). 232 new unit tests covering surp SQL translation, new catalog functions, new views, router routing, and module-level edge cases.
- **SQLSTATE classification** (`v1.5.x` carry-forward): DBAPI type fixes and SQLSTATE error code classification landed in the `feat(catalog+sync)` commit included in this release.

## [1.5.9] - 2026-07-19

### Fixed

- **`integratedml.py` `%ModelExists` check never matched** (`integratedml.py`): `handle_system_function_query` compared the literal `"%SYSTEM.ML.%ModelExists"` against `sql.upper()`, so it never matched because the literal itself was mixed-case. Fixed by uppercasing the literal to `"%SYSTEM.ML.%MODELEXISTS"`.
- **`VectorQueryRequest` field validation silently skipped dimension check** (`models/vector_query_request.py`): `query_vector` was declared before `vector_dimensions` in the Pydantic v2 model; `info.data` at validator time therefore never contained `vector_dimensions`, so the dimension mismatch check was always skipped. Fixed by swapping field declaration order so `vector_dimensions` is visible in `info.data` when `query_vector` is validated.
- **`IdentifierNormalizer` CREATE TABLE regex consumed closing parenthesis** (`sql_translator/identifier_normalizer.py`): The `create_table_pattern` regex included a trailing `(\))` capture group that absorbed the closing paren before the manual paren-depth scanner could find it, causing `normalize_create_table` to silently return the original SQL unchanged for any CREATE TABLE with nested parens. Removed the trailing group; the paren scanner now handles termination correctly.

### Added

- **`AGENTS.md` agent-oriented rewrite**: Replaced Codex boilerplate with actionable AI agent guidance — when to use iris-pgwire, where to look, AI agent workflows (SQL translation verify via `iris_query`, wire protocol debug, integration test run patterns), IRIS DBAPI reference, iad ecosystem integration with `.iris-agentic-dev.toml` config, and agent skill pointers.
- **`skills/iris-pgwire/SKILL.md`**: New agent skill file covering psycopg3/asyncpg/SQLAlchemy connection strings, parameter style (`$N` wire → `?` IRIS), PostgreSQL→IRIS type mapping, full SQL translation differences, integration test patterns (container attach, skip fixtures, pure translation tests), transaction semantics, environment variables, and gotchas.
- **`pip install iris-pgwire[ai]`** (`pyproject.toml`): Added `ai` optional dependency group (`iris-agentic-dev>=1.0`) for iad-powered IRIS introspection during development.

### Changed

- **Test coverage**: 47% → 92% (5,349 tests across unit, contract, integration, and e2e suites).
- **README**: Rewritten for accuracy — removed fabricated "171/171 tests" stat, dead ZPM class reference, and wrong version. Reflects actual 92% coverage, v1.5.9, correct Quick Start.
- **Root cleanup**: Removed 12 debug/scratch scripts and 3 AI-tooling files from git tracking; added to `.gitignore`.
- **JS dependencies**: Resolved 41 Dependabot CVEs in `examples/prisma-iris-demo` (hono, defu, effect, lodash) and `tests/client_compatibility/nodejs` (js-yaml, picomatch) via package bumps and `overrides`.

## [1.5.8] - 2026-06-08

### Added

- **HNSW DDL translation** (`vector_optimizer.py`): pgvector-style `CREATE INDEX USING hnsw` DDL is now translated to IRIS HNSW syntax with `Distance=` parameter mapping (`vector_cosine_ops` → `Cosine`, `vector_ip_ops` → `DotProduct`). L2 (`vector_l2_ops`) raises `NotImplementedError` as IRIS does not support L2 HNSW indexes.
- **JSON operator translation** (`vector_optimizer.py`): PostgreSQL `->` / `->>` JSON operators are now translated to IRIS `JSON_QUERY` / `JSON_VALUE` equivalents, enabling ORMs and clients that use JSON column access patterns to work transparently.
- **`IF NOT EXISTS` duplicate-error suppression** (`vector_optimizer.py`, `protocol.py`): `CREATE TABLE IF NOT EXISTS` and similar DDL statements that trigger IRIS duplicate-object errors (SQLCODE -5016, -5019, -5002) are now silently suppressed with a synthetic success response, matching PostgreSQL `IF NOT EXISTS` semantics.

## [1.5.7] - 2026-03-09

### Fixed

- **`_prepare_sql` overwrote translated SQL with untranslated original after RETURNING strip**: After the 1.5.6 fix, `_prepare_sql` correctly used `original_sql` for `ReturningPlan.from_sql` RETURNING detection. However, line 699 then unconditionally did `optimized_sql = plan.stripped_sql`. Since `plan` was built from `original_sql`, `plan.stripped_sql` was the _original_ (untranslated) SQL with just `RETURNING` removed — still containing `DEFAULT`, `$1`-style params, unquoted schema names, etc. This overwrote the correctly-translated `optimized_sql` from the normalization pipeline, causing IRIS to receive e.g. `INSERT INTO "SESSION" (...) VALUES (..., DEFAULT)` → `SQLCODE -12`. Fixed by applying `ReturningPlan._strip_clauses()` directly to `optimized_sql` when `original_sql` was provided, rather than using `plan.stripped_sql`. The `else` branch (no `original_sql`) continues to use `plan.stripped_sql` as before.

## [1.5.6] - 2026-03-09

### Fixed

- **`INSERT ... RETURNING` returns empty array with Extended Query Protocol (Drizzle / Better Auth) — complete fix**: v1.5.5 fixed the Describe phase (NoData → RowDescription), but the Execute phase still returned zero rows. Two additional root causes:

  1. **Fast-batch bypass used translated SQL for `has_returning` check** (`protocol.py` Execute handler): The batch fast-path (`is_dml and not has_returning`) inspected `translated_query` (RETURNING stripped) instead of `original_query`. This caused `has_returning=False`, so INSERT...RETURNING was incorrectly fast-batched — the INSERT executed and sent a synthetic `CommandComplete` immediately, but `_emulate_returning` was never reached and zero DataRows were returned.

  2. **`_prepare_sql` used translated SQL for `ReturningPlan`** (`iris_executor.py`): Even when the fast-batch was bypassed, `_prepare_sql` built `ReturningPlan` from `optimized_sql` (which has RETURNING stripped by the normalization pipeline). `plan.has_returning` was therefore always `False`, so the RETURNING emulation block was never entered. Fixed by adding an `original_sql` parameter to `_prepare_sql`, `_execute_external_async`, `_execute_embedded_async`, and `execute_query`, threading the pre-translation SQL all the way through so `ReturningPlan` can detect RETURNING correctly.

- **Impact**: Affects both embedded and external IRIS connection modes. Better Auth "Failed to create session", Drizzle `.returning()` always `[]`, SQLAlchemy `.returning()` with psycopg3.

## [1.5.5] - 2026-03-09

### Fixed

- **`INSERT ... RETURNING` always empty with Extended Query Protocol (Drizzle / postgres.js / Better Auth)**: When a client uses the Extended Query Protocol (Parse → Describe → Bind → Execute), the Describe phase was incorrectly sending `NoData` instead of `RowDescription` for `INSERT ... RETURNING` statements. Root cause: `handle_describe_message` built the `ReturningPlan` from `translated_query`, which has the `RETURNING` clause stripped (because IRIS doesn't support it natively). `has_returning` was therefore always `False` at Describe time, causing `send_no_data()`. Clients like postgres.js and Drizzle ORM rely on the Describe response to decide whether to read rows at Execute time — receiving `NoData` caused them to discard all returned rows silently. Fixed by using `original_query` (the pre-translation SQL, which still contains `RETURNING`) for `ReturningPlan` detection in both the "Describe Statement" (`describe_type == "S"`) and "Describe Portal" (`describe_type == "P"`) branches of `handle_describe_message`.
- **Impact**: Drizzle ORM `.returning()` returned `[]`. Better Auth failed at sign-in ("Failed to create session") because session creation uses `.returning()`. Any ORM or client using Extended Query Protocol with `RETURNING` (SQLAlchemy `returning()` with psycopg3, etc.) was affected.

### Added

- **E2E regression tests for RETURNING via Extended Query Protocol** (`tests/e2e/test_returning_extended_protocol.py`): 4 passing tests covering `INSERT ... RETURNING *`, specific columns, multiple rows, and RowDescription presence verification via `prepare=True` (forces Extended Query Protocol). 1 xfail for `UPDATE ... RETURNING` (separate pre-existing limitation).

## [1.5.4] - 2026-03-06

### Fixed

- **`CREATE INDEX USING HNSW WITH (...)` translation**: pgvector-style HNSW index DDL is now correctly translated to IRIS syntax. Both pgvector forms are handled:
  - `CREATE INDEX name ON table USING hnsw (col vector_cosine_ops)` — operator class maps to `Distance='Cosine'`
  - `CREATE INDEX name ON table (col) USING HNSW WITH (M=16, ef_construction=64)` — column-first form with explicit parameters
  - All three distance metrics: `vector_cosine_ops` → `'Cosine'`, `vector_ip_ops` → `'DotProduct'`, `vector_l2_ops` raises `NotImplementedError` (L2 distance not supported in IRIS HNSW)
  - Parameters `M` and `ef_construction`/`efConstruction` pass through correctly
  - Schema-qualified table names (e.g. `SQLUser.mytable`) supported
  - `IF NOT EXISTS` clause stripped (not supported by IRIS)
  - Native IRIS `AS HNSW(...)` syntax passes through untouched

### Added

- **E2E tests for HNSW index creation** (`tests/e2e/test_hnsw_index.py`): 12 tests covering pgvector syntax translation, live index creation/verification against IRIS, parameter passthrough, and native syntax passthrough.

## [1.5.3] - 2026-03-06

### Fixed

- **`<=>` cosine distance semantics**: `ORDER BY embedding <=> query ASC` now correctly returns the most-similar rows first. pgvector `<=>` is cosine _distance_ (0.0 = identical), but IRIS `VECTOR_COSINE()` is cosine _similarity_ (1.0 = identical). The translator was emitting bare `VECTOR_COSINE(...)`, which caused `ORDER BY ASC` to return the _least_-similar row first. Fixed by wrapping as `(1 - VECTOR_COSINE(...))` to convert similarity → distance. Affects both `<=>` operator rewrites in `vector_optimizer.py` (already fixed in v1.5.2) and explicit `cosine_distance()`/`vector_cosine_distance()` function calls in `sql_translator/normalizer.py` (fixed now).

### Added

- **E2E regression test for cosine ordering** (`tests/e2e/test_vector_cosine_ordering.py`): inserts three vectors with known relative similarities, queries with `<=>`, and asserts the most-similar row is returned first — the test that would have caught this bug before it shipped.

## [1.5.2] - 2026-03-05

### Fixed

- **RETURNING emulation silent failure (Extended Query Protocol)**: `INSERT ... RETURNING` returned no rows when using postgres.js, Drizzle ORM, or any client that uses the Extended Query Protocol. Root cause: column names extracted from the INSERT were kept lowercase (e.g. `"id"`), but IRIS stores unquoted column names in uppercase (`ID`). The quoted `WHERE "id" = ?` clause matched nothing. Fixed by uppercasing the extracted column name in both `iris_executor.py` and `dbapi_executor.py`.

## [1.5.1] - 2026-03-05

### Added

- **`PGWIRE_QUERY_TIMEOUT` env var**: Per-query execution timeout (default 30s) that cancels a stalled IRIS query and returns an error to the client immediately, rather than holding the pool slot for the full `PGWIRE_POOL_TIMEOUT`. On timeout the offending connection is evicted (closed) rather than recycled, preventing lock-held connections from polluting the pool. Fixes the concurrent write load pool exhaustion bug where IRIS row locks on `DELETE + INSERT + UPDATE` sequences blocked subsequent `SELECT` queries until the pool fully saturated.

### Fixed

- **COPY FROM STDIN without header**: Rows were silently dropped because the bulk executor used placeholder column names (`column_0`, `column_1`, …) that don't exist in IRIS. Now fetches real column names from `INFORMATION_SCHEMA.COLUMNS` via a direct DBAPI call that bypasses the pg_catalog emulation layer.
- **COPY FROM STDIN column list**: Same root cause — explicit column list COPY now correctly maps CSV values to the specified columns.

## [1.5.0] - 2026-02-28

### Added

- **Drizzle ORM Migration Support**: Complete compatibility with Drizzle-style migrations including UUID/JSON handling, boolean defaults, and enum type mappings.
- **Transaction Rollback Support**: Migrations now use explicit `START TRANSACTION` for proper rollback capability in IRIS.
- **Enhanced DDL Translation**:
  - UUID columns automatically use `%Library.UniqueIdentifier` native type
  - JSON/JSONB columns automatically use `%Library.DynamicObject` native type
  - `DEFAULT gen_random_uuid()` automatically skipped (IRIS limitation)
  - `DEFAULT NOW()` automatically converted to `CURRENT_TIMESTAMP`
  - `ALTER TABLE RENAME COLUMN` marked as unsupported

### Changed

- **Comprehensive Code Simplification**: Major readability and maintainability improvements across all source files — `protocol.py`, `iris_executor.py`, `dbapi_executor.py`, `sql_translator/`, `auth/`, and `catalog/`. Functions shortened, duplication eliminated, and nesting reduced. No behaviour changes.

### Fixed

- **DDL Parser Comment Handling**: `CREATE TABLE` statements prefixed with `--` SQL comments (as emitted by Drizzle CLI) are now correctly parsed.
- **Migration Failure Detection**: Invalid SQL statements (e.g. `CREATE TAABLE`) that the DDL parser cannot recognise are now executed raw against IRIS so the database rejects them and the migration fails as expected.
- **UUID/JSON DDL Handling**: Both CREATE TABLE and ALTER TABLE now correctly use IRIS native types for UUID and JSON columns.
- **Transaction Management**: Migration executor now disables auto-commit and uses explicit transaction control for reliable rollback.
- **Test Infrastructure**: All e2e tests pass; pool size increased to 20 to prevent exhaustion across sequential test classes.

## [1.3.0] - 2025-02-06

### Added

- **IRIS 2024.2+ compatibility**: Automatic `%EXACT` wrapping for `SELECT DISTINCT` and `UNION` preserves PostgreSQL set semantics on IRIS 2024.2+.
- **Enhanced RETURNING emulation**: Multi-column and `RETURNING *` workflows now return metadata-rich results without forcing separate queries.
- **ON CONFLICT support**: `DO NOTHING` and `DO UPDATE` branches replay IRIS-safe logic while keeping the client-facing `RETURNING` output consistent.
- **Metadata-driven DEFAULTs**: Translators consult IRIS metadata to expand `DEFAULT` references in INSERT/UPDATE statements.
- **Global boolean literals**: PostgreSQL `true`/`false` constants are translated into IRIS equivalents everywhere in the pipeline.
- **DBAPI session pinning**: Connections remain tied to their originating session so identity lookups (`LAST_IDENTITY()`/`%EXACT` selects) stay accurate.

### Fixed

- **TypeError in DBAPIConnection**: Connection age calculations no longer raise `TypeError` when the pool is drained.
- **IntegratedML decorators**: Signature mismatches in `IntegratedML` wrappers were corrected so they proxy arguments without losing positional context.

## [1.2.23] - 2026-01-25

### Fixed

- **Namespace Stabilization**: Added a `%SYS` reset and retry logic to `SetNamespace` in embedded mode. This prevents `<NAMESPACE>` errors when switching context immediately after a database restore or creation.
- **Improved Reliability**: Mitigated race conditions and stale configuration cache issues in `irispython` environments.

## [1.2.22] - 2026-01-25

## [1.2.21] - 2026-01-18

### Fixed

- **Vector Cast Support**: Added explicit translation for `CAST(expr AS vector)` and `expr::vector` into IRIS-native `TO_VECTOR(expr, DOUBLE)`, resolving the "'VECTOR' is not a supported CAST target" error.
- **Function Mapping**: Integrated pgvector function name mapping (e.g., `vector_cosine_distance` → `VECTOR_COSINE`) into the unified translation pipeline.
- **Robust Placeholder Handling**: Updated translator to convert `%s` placeholders to `?` early, preventing incorrect normalization to `%S`.

## [1.2.1] - 2026-01-17

### Fixed

- **Definitive Model Stabilization**: Bumping version to ensure all TDD-verified model fixes are included in the published package. Resolves `KeyError: 'cache_hit'` by ensuring consistent `PerformanceStats` object propagation.

## [1.2.0] - 2026-01-17

### Added

- **Quality Assurance Suite**: Introduced `test_sql_translation_pipeline_quality.py` to ensure model consistency and protocol stability across releases.

### Fixed

- **Major Model Stabilization**: Unified `TranslationResult` and `PerformanceStats` across the entire pipeline.
- **Protocol Reliability**: Fixed `AttributeError` and `KeyError` in `protocol.py` by standardizing on validated dataclass objects instead of raw dictionaries.
- **Consistent Schema Naming**: Ensured `translated_sql` is used consistently across all integration tests and the core pipeline.

## [1.1.9] - 2026-01-17

## [1.1.8] - 2026-01-17

### Fixed

- **Protocol Data Model Alignment**: Switched from object attribute to dictionary access for `performance_stats` in `protocol.py`. This fixes the `AttributeError` when processing queries.
- **Cache Hit Metric**: Ensured `cache_hit` is always present in the performance dictionary returned by the SQL pipeline, resolving `KeyError` crashes.
- **Authorship & License**: Updated LICENSE and documentation to correctly reflect Thomas Dyar as the author and owner.

## [1.1.7] - 2026-01-17

### Fixed

- **AttributeError in Protocol**: Fixed `PGWireProtocol` to use dictionary access instead of dot notation for `performance_stats` returned by the new `SQLPipeline`.
- **KeyError in Protocol**: Added missing `cache_hit` key to the `performance_stats` dictionary in `SQLTranslator` to prevent crashes during statement parsing.
- **Embedded Namespace Context**: Strengthened the `SetNamespace` logic in background execution threads to ensure consistent IRIS namespace context and prevent intermittent "Class not found" errors.
- **Redundant SQL Mapping**: Removed legacy schema translation code in `iris_executor.py` that was conflicting with the centralized `SQLPipeline`.

## [1.1.6] - 2026-01-17

### Changed

- **Structural Simplification**: Decoupled 350+ lines of query interception logic from `IRISExecutor` into a dedicated `SQLInterceptor` registry.
- **Centralized SQL Pipeline**: Implemented `SQLPipeline` to orchestrate all SQL transformations (filtering, normalization, refinement, optimization) in a single pass, ensuring consistency and preventing redundant processing.
- **Unified SQL Refinement**: Created `SQLRefiner` to host ad-hoc IRIS-specific fixes (like the `ORDER BY` alias fix), removing redundant and inconsistent regex logic from `protocol.py` and `vector_optimizer.py`.

## [1.1.5] - 2026-01-17

### Fixed

- **Robust Identifier Normalization**: Removed word boundaries from the `IdentifierNormalizer` regex to ensure qualified names (e.g., `SQLUser."WORKFLOW"`) are always matched as a single unit, even with complex quoting or whitespace around dots.
- **Idempotent Bare Table Mapping**: Added a look-back check in `schema_mapper.py` to prevent double-prefixing of tables (e.g., `SQLUser.SQLUser."TABLE"`) when the schema is already present but separated by whitespace.
- **Improved SAVEPOINT Handling**: Ensured savepoint identifiers are matched correctly within the new unified identifier pattern.

## [1.1.4] - 2026-01-17

### Changed

- **Author Update**: Formally updated `__author__` to Thomas Dyar.
- **Status Update**: Promoted package to "Stable/Production" status.

## [1.1.3] - 2026-01-17

### Fixed

- **Redundant SQL Transformation**: Removed a redundant call to `translate_input_schema` in `IRISExecutor`. This prevented "double patching" where identifiers could be incorrectly nested (e.g., `SQLUser."SQLUser."TABLE""`).
- **Namespace Context in Embedded Python**: Added explicit `SetNamespace` calls in the background threads used by `iris.sql.exec`. This ensures reliable class resolution and prevents "Class not found" errors in embedded mode.
- **Qualified Identifier Normalization**: Updated the identifier normalizer regex and replacement logic to handle dots properly. Schema-qualified names (like `SQLUser."USER"`) are now handled as single units, ensuring consistent casing and quoting across the entire identifier.
- **Improved CREATE TABLE Parsing**: Fixed a bug where qualified table names in `CREATE TABLE` statements (e.g., `SQLUser."workflow"`) were being incorrectly uppercased to `SQLUSER`.

## [1.1.2] - 2026-01-17

### Fixed

- **Dynamic Schema Mapping**: Fixed hardcoded "public" schema references in `translate_input_schema`. Now builds regex dynamically from `SCHEMA_MAP` keys (e.g., handles `drizzle`, `public`, etc.).
- **Bare Table Mapping**: Implemented automatic schema prefixing for bare table names (e.g., `FROM "workflow"` -> `FROM SQLUser."WORKFLOW"`). This ensures IRIS can resolve classes when ORMs omit the schema.
- **Robust Table Normalization**: Ensured all mapped table names are consistently uppercased and double-quoted to prevent conflicts with IRIS reserved words (like `USER`) and satisfy case-sensitive identifier requirements.
- **Reliable Schema Regex**: Refined regex patterns to correctly handle all combinations of quoted and unquoted schemas and table names, resolving "dangling quote" errors.

## [1.1.1] - 2026-01-17

## [1.1.0] - 2026-01-17

### Added

- **IRIS Technical Reference**: Added definitive guide to `AGENTS.md` covering DBAPI connection patterns, embedded SQL parameter passing, and case-sensitivity rules.

### Fixed

- **Robust Schema Mapping**: Rewrote `translate_input_schema` to correctly preserve table name quoting and casing (e.g., `public."workflow"` -> `SQLUser."workflow"`). This resolves "Class not found" errors in IRIS when ORMs use quoted identifiers.
- **Embedded Parameter Passing**: Ensured `iris.sql.exec` receives parameters as positional arguments using the splat operator (`*params`) in all execution paths.
- **Redundant Translation Cleanup**: Removed conflicting schema translation regexes in `iris_executor.py` that were previously stripping quotes from identifiers.

## [1.0.9] - 2026-01-17

### Fixed

- **Parameter Passing Bug**: Fixed `iris_executor.py` to correctly pass parameters to `iris.sql.exec(*params)`, enabling parameterized queries in embedded mode.
- **Schema Case Sensitivity**: Fixed normalizer to preserve `SQLUser` casing (instead of `SQLUSER`), satisfying case-sensitive package requirements in IRIS.
- **DDL Case Sensitivity**: Fixed `IdentifierNormalizer` to respect quoted identifier casing in `CREATE TABLE` statements, preventing "Class not found" errors during subsequent queries.

## [1.0.8] - 2026-01-17

### Added

- **Final DDL Compatibility Polish**: Refined regex patterns for `USING btree` and PostgreSQL cast stripping to handle broader syntax variations.
- **Enhanced Integration Testing**: Added comprehensive end-to-end migration test covering all Feature 036 constructs.

## [1.0.7] - 2026-01-17

### Added

- **PostgreSQL DDL Compatibility Enhancement**: Implemented automatic interception and transformation of PostgreSQL-specific DDL constructs to enable seamless migrations.
- **Generated Column Stripping**: Added support for automatically removing `GENERATED ALWAYS AS ... STORED` column definitions from `CREATE TABLE` statements.
- **Enum Type Registration**: Added logic to skip `CREATE TYPE ... AS ENUM`, register the type name, and automatically map subsequent columns using that type to `VARCHAR(64)`.
- **Index Dependency Tracking**: Implemented `SkippedTableSet` to track tables whose creation was skipped, ensuring dependent `CREATE INDEX` statements are also skipped.
- **Strict DDL Mode**: Added a configurable `strict_ddl` flag (default `false`) to control whether unsupported constructs should be skipped with a warning or raise an error.
- **Construct Stripping**: Added automatic stripping of `USING btree`, PostgreSQL type casts (`::type`), and `WITH (fillfactor)` from DDL statements.

## [1.0.6] - 2026-01-16

### Added

- **Multi-statement DDL with comments**: Updated `DdlSplitter` to be fully comment-aware and strip comments before execution to prevent IRIS parsing errors.
- **Prepared statement translation ($n → ?)**: Consolidated parameter translation logic into `SQLTranslator` for consistency across all query paths.
- **Default keyword in VALUES clause**: Implemented `DefaultValuesTranslator` to rewrite `INSERT` statements using `DEFAULT` within `VALUES` lists.
- **Timestamp binding normalization**: Updated `DATETranslator` and `IRISExecutor` to normalize ISO 8601 timestamps (stripping `T`, `Z`, and offsets) into IRIS-accepted ODBC formats.
- **ALTER TABLE translation**: Updated `DdlSplitter` to translate PostgreSQL `SET DATA TYPE` and `DROP NOT NULL` syntax to IRIS-compatible `ALTER COLUMN` commands.

### Fixed

- Fixed IRIS execution error "Input encountered after end of query" by improving semicolon and comment handling in the DDL splitter.
- Resolved "LITERAL (1) found" errors during migrations by avoiding no-op SELECT injections for skipped DDL.
- Enhanced IRIS data type mapping to better handle PostgreSQL OIDs (e.g., `BIGINT`, `TINYINT`).

## [1.0.5] - 2026-01-15

## [0.1.0] - 2025-01-05

### Added

- PostgreSQL wire protocol server for InterSystems IRIS
- Dual backend execution paths (DBAPI and Embedded Python)
- Support for vectors up to 188,962 dimensions (1.44 MB)
- pgvector compatibility layer with operator translation
- Async SQLAlchemy support (86% complete, production-ready)
- FastAPI integration with async database sessions
- Zero-configuration BI tools integration (Apache Superset, Metabase, Grafana)
- SQL Translation REST API with <5ms SLA
- Connection pooling with 50+20 async connections
- HNSW vector index support (5× speedup at 100K+ scale)
- Binary parameter encoding for large vectors (40% more compact)
- Constitutional compliance framework with 5ms SLA tracking
- Comprehensive documentation and examples

### Performance

- ~4ms protocol translation overhead (preserves IRIS native performance)
- Simple query latency: 3.99ms avg, 4.29ms P95
- Vector similarity (1024D): 6.94ms avg, 8.05ms P95
- 100% success rate across all dimensions and execution paths

### Documentation

- Complete BI tools setup guide
- Async SQLAlchemy quick reference
- Vector parameter binding documentation
- Dual-path architecture guide
- HNSW performance investigation findings
- Translation API reference

[Unreleased]: https://github.com/intersystems-community/iris-pgwire/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/intersystems-community/iris-pgwire/releases/tag/v0.1.0
