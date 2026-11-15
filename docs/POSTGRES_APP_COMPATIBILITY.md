# PostgreSQL applications on IRIS through PGWire: transactions

What a PostgreSQL application can rely on when it talks to IRIS through PGWire, what PGWire refuses, and what to do
instead. It covers transaction behaviour and string comparison; other SQL dialect and type differences are in
[`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

Every row below names the check in the isolation suite (`tests/e2e/isolation/`, run by `make isolation`) that measures
it against IRIS through PGWire and against PostgreSQL 16, with PostgreSQL's answer as the expected one. A row with no
check would be a claim nobody measured, so `tests/unit/test_compatibility_doc.py` fails if one appears. Measured on the
DBAPI backend; the embedded backend runs every session in one IRIS process and is documented as single-client.

Status: spec 052 complete (aborted transactions, savepoints, row locking, ON CONFLICT, default isolation, lock timeouts, cancel), plus string comparison.

## Aborted transactions

As on PostgreSQL, since 2.1: an error inside a transaction block aborts it.

| Behaviour                                                                                           | Check                                              |
| --------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| After an error, every statement but `ROLLBACK`/`ROLLBACK TO`/`COMMIT` gets `25P02`; status `E`      | `failed_transaction/error_then_commit/simple`      |
| `COMMIT` of an aborted transaction rolls it back and replies `ROLLBACK`                             | `failed_transaction/error_then_commit/extended`    |
| `ROLLBACK` ends the aborted transaction; the session is usable again                                | `failed_transaction/rollback_recovers/simple`      |
| `ROLLBACK TO` a savepoint taken before the error repairs the transaction and keeps the earlier work | `failed_transaction/rollback_to_recovers/extended` |
| With no explicit transaction, an error changes nothing for the next statement                       | `failed_transaction/autocommit_error/simple`       |
| In a pipeline, an error discards the messages up to Sync and aborts the transaction                 | `failed_transaction/pipeline_error`                |
| A pipeline of different statements runs each of them (2.0 ran the first one for all)                | `failed_transaction/pipeline_distinct_statements`  |
| 100 of 100 transactions with a failed statement commit nothing, on both protocols                   | `failed_transaction/never_commits/extended`        |

Before 2.1, the failed statement alone was undone and `COMMIT` committed the work around it.

## Savepoints and nested transactions

PGWire keeps each session's savepoints itself, because IRIS has no `RELEASE`, deletes a savepoint when it is rolled
back to, and allows a limited number per transaction.

| Behaviour                                                                                  | Check                                        |
| ------------------------------------------------------------------------------------------ | -------------------------------------------- |
| psycopg nested `transaction()` blocks, three deep, every mix of normal exit and exception  | `savepoints/psycopg_three_deep/ooo`          |
| Django-style quoted savepoints (`SAVEPOINT "s123_x1"`, `RELEASE SAVEPOINT`, `ROLLBACK TO`) | `savepoints/django_style`                    |
| `ROLLBACK TO` keeps the savepoint, so it can be rolled back to again                       | `savepoints/rollback_to_twice`               |
| `RELEASE SAVEPOINT` succeeds                                                               | `savepoints/release/existing`                |
| Rolling back to an earlier savepoint removes the later ones                                | `savepoints/rollback_to_earlier_drops_later` |
| A duplicate name refers to the most recent savepoint                                       | `savepoints/duplicate_names`                 |
| Unknown name: `3B001`, and the transaction is aborted                                      | `savepoints/rollback_to_unknown`             |
| Unquoted names fold to lower case, quoted ones are exact                                   | `savepoints/identifier_rules`                |
| Outside a transaction block: `25P01`                                                       | `savepoints/outside_a_transaction/savepoint` |

### The one limit: 254 savepoints per transaction

IRIS allows 254 savepoints alive in one transaction, and a released savepoint stays alive until the transaction ends.
Rolling back to a savepoint frees it and everything after it; nothing else does. PostgreSQL has no such limit.

| Behaviour                                                                                                        | Check                        |
| ---------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| The 255th savepoint is refused with `54000` and the transaction aborts (IRIS alone would lose the work silently) | `savepoints/savepoint_limit` |

An application that opens a savepoint per row (an ORM's nested block inside a loop, Django's `atomic()` per save)
inside one long transaction reaches this. Commit in batches of fewer than 254 nested blocks.

## Row locking (`FOR UPDATE`)

IRIS takes no lock for `SELECT ... FOR UPDATE`. Since 2.1 PGWire locks the rows itself, inside a transaction, by
running `UPDATE t SET pk = pk WHERE <the same predicate>` before the SELECT. It does so only where that locks exactly the
rows the SELECT returns, and refuses the other shapes.

| Behaviour                                                                                      | Check                                 |
| ---------------------------------------------------------------------------------------------- | ------------------------------------- |
| A single-table `FOR UPDATE` makes a second locker wait for COMMIT                              | `locking/for_update_vs_for_update`    |
| It makes a writer wait for COMMIT, with bound parameters in the `WHERE`                        | `locking/for_update_params_vs_update` |
| The rows returned are the rows without the clause (`ORDER BY` and `OF <the table>` allowed)    | `locking/rows_as_without_clause`      |
| `NOWAIT` on a row another session holds: `55P03` at once; on a free row it locks               | `locking/nowait_held_row`             |
| Outside a transaction it returns the rows; the lock lasts for the statement only               | `locking/autocommit_for_update`       |
| `GROUP BY`, aggregates and `DISTINCT` with `FOR UPDATE`: `0A000`, as PostgreSQL itself answers | `locking/refused/group_by`            |
| A read-`FOR UPDATE`-then-write counter, 4 workers × 250, both isolation levels: no lost update | `locking/counter_for_update`          |

### Refused in strict mode, `0A000`

PostgreSQL runs these. The message names the shape and what to do instead. `PGWIRE_TXN_COMPAT=permissive` runs them as
2.0 did, **unlocked**, and logs one warning per statement shape (`locking/permissive/join_runs`,
`locking/permissive/warned_once`).

| What                                                                            | Instead                                                       | Check                                               |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------- |
| a join (`JOIN` or a comma in `FROM`)                                            | lock each table's rows with its own single-table `FOR UPDATE` | `locking/refused/join`                              |
| a subquery in `FROM`                                                            | lock the base table's rows first                              | `locking/refused/subquery_in_from`                  |
| `LIMIT`, `OFFSET`, `FETCH`, `TOP` (the lock would cover rows the SELECT skips)  | narrow the `WHERE` to the rows you want                       | `locking/refused/limit`                             |
| a view                                                                          | select from the base table                                    | `locking/refused/view`                              |
| a table with a ROWVERSION or generated column, or an UPDATE trigger             | lock the rows another way                                     | `locking/refused/rowversion`                        |
| `FOR SHARE`, `FOR NO KEY UPDATE`, `FOR KEY SHARE` (IRIS has no shared row lock) | `FOR UPDATE`                                                  | `unsupported_clauses/answer/for_share`              |
| `SKIP LOCKED`                                                                   | `FOR UPDATE NOWAIT`, retrying on `55P03`                      | `unsupported_clauses/answer/for_update_skip_locked` |

A touch of more than 1000 rows counts toward IRIS's lock-escalation threshold and can become a table lock (not
measured: it needs an enterprise-key lab).

## ON CONFLICT

IRIS has no `ON CONFLICT`. Its `INSERT OR UPDATE` matches a row on any unique key and writes every inserted column,
which is PostgreSQL's upsert in one case only. Since 2.1 PGWire sends it for that case and refuses the rest.

| Behaviour                                                                                                                       | Check                                       |
| ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `ON CONFLICT (k) DO UPDATE SET` every inserted column `= EXCLUDED.<column>`, `k` the table's only unique key: PostgreSQL's rows | `on_conflict/strict/pk_only_set_all`        |
| The same on the insert path                                                                                                     | `on_conflict/strict/pk_only_insert_path`    |
| The same with bound parameters and `RETURNING`, both paths                                                                      | `on_conflict/strict/exact_params_returning` |
| The same through executemany                                                                                                    | `on_conflict/executemany_do_update`         |

### Refused in strict mode, `0A000`

PostgreSQL runs these; `INSERT OR UPDATE` would give different rows (measured: `on_conflict/insert_or_update/*`). The
message names the form.

| What                                                           | Instead                                                        | Check                                               |
| -------------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------- |
| `DO UPDATE SET` only some of the inserted columns              | insert only the columns you update, or set all from `EXCLUDED` | `on_conflict/strict/pk_only_set_subset`             |
| a `SET` that reads the existing row (`v = t.v + EXCLUDED.v`)   | compute the value in the client, or `UPDATE` on conflict       | `on_conflict/strict/set_uses_existing_row`          |
| `DO UPDATE ... WHERE`                                          | `UPDATE ... WHERE` yourself on conflict                        | `on_conflict/strict/do_update_where_false`          |
| a table with a second unique key                               | upsert into a table whose only unique key is the target        | `on_conflict/strict/second_unique_key_conflicts`    |
| a target that is not the table's only unique key               | the same                                                       | `on_conflict/strict/target_is_secondary_unique_key` |
| `DO NOTHING` (no atomic insert-or-skip on IRIS)                | check first, or catch `23505`                                  | `on_conflict/do_nothing_fk_violation`               |
| several rows of `VALUES`, `INSERT ... SELECT`, `ON CONSTRAINT` | one row per statement (executemany), target as columns         | `on_conflict/strict/executemany_set_subset`         |

`PGWIRE_TXN_COMPAT=permissive` runs these with PGWire's 2.0 emulation (insert, catch the unique violation, then update
or do nothing), which is **not atomic**: a concurrent writer can slip between the two steps. Since 2.1 it treats only
a unique violation on the conflict target as the conflict, so a foreign-key violation (`23503`) and a conflict on
another key (`23505`) reach the client, and the driver's `<LIST ERROR>` fails the statement with `XX000`
(`on_conflict/permissive/do_nothing_errors`, `on_conflict/permissive/do_update_subset`,
`on_conflict/permissive/list_error`).

What ORMs send, from their documentation and not yet measured here: SQLAlchemy's
`insert().on_conflict_do_update()` with every column in `set_` is the exact form, if the target is the table's only
unique key; `on_conflict_do_nothing()` and Django's `ignore_conflicts=True` are `DO NOTHING`, refused; Django's
`bulk_create(update_conflicts=True)` and Rails's `upsert_all` send several rows of `VALUES`, refused (send one row per
statement).

## Default isolation

New sessions run at READ COMMITTED since 2.1, as on PostgreSQL; before 2.1 they ran at IRIS's default, READ UNCOMMITTED.
`PGWIRE_DEFAULT_ISOLATION=read uncommitted` restores that. IRIS's READ COMMITTED is narrower than PostgreSQL's (see
`KNOWN_LIMITATIONS.md`): a read of a row another transaction holds waits instead of reading the committed version.

| Behaviour                                                                                                                | Check                                                |
| ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| A new session reports `read committed`; its read of a held row waits (IRIS) or reads the committed value                 | `default_isolation/default/read_committed`           |
| With `PGWIRE_DEFAULT_ISOLATION='read uncommitted'` new sessions report and run at it (`make isolation-read-uncommitted`) | `default_isolation/default/read_uncommitted_server`  |
| Any other value of `PGWIRE_DEFAULT_ISOLATION` or `PGWIRE_TXN_COMPAT` stops the server, naming the accepted values        | `default_isolation/startup/pgwire_default_isolation` |

## Lock timeouts

| Behaviour                                                                                                   | Check                                       |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `SET lock_timeout = '2s'` (or `2000`, `'2000ms'`): a write to a held row gives up after 2 s with `55P03`    | `timeouts/lock_timeout/gives_up`            |
| A fraction of a second rounds up to whole seconds (IRIS's unit); `SHOW` reports the value as set (`1500ms`) | `timeouts/lock_timeout/fraction`            |
| `0` and `RESET` restore the default wait (IRIS's 10 s; PostgreSQL's 0 waits forever, IRIS has no such wait) | `timeouts/lock_timeout/zero_and_reset`      |
| A session's `lock_timeout` ends with it; the next session on the pooled connection has the default          | `timeouts/lock_timeout/new_session_default` |
| `statement_timeout` is accepted and reported but **not enforced** (pinned: PostgreSQL cancels with `57014`) | `timeouts/statement_timeout`                |

## Cancel

A CancelRequest (psycopg's `cancel()`, `Ctrl-C` in psql) ends the session's IRIS process, so the running
statement fails at once with `57014` and IRIS rolls its work back. The session carries on with a fresh connection, at
its own isolation level. Before 2.1 the request was acknowledged and ignored, and the cancelled write still happened.
The IRIS user PGWire connects as must be allowed to end processes (`%SYSTEM.Process.Terminate`). If IRIS refuses, the
statement runs until it finishes, is still not committed, and the server logs an error.

| Behaviour                                                                                                   | Check                                 |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| A write waiting on a lock is cancelled with `57014` before the lock is released, and never applied          | `cancel/cancel_lock_wait`             |
| 10 of 10 cancels answered within 1 s, none applied, the session usable afterwards                           | `cancel/cancel/ten_trials`            |
| After a cancel the session keeps its isolation level                                                        | `cancel/cancel/keeps_isolation_level` |
| Inside `BEGIN`, the cancelled statement aborts the transaction (`25P02` until `ROLLBACK`), as on PostgreSQL | `cancel/cancel/inside_transaction`    |
| A cancel with no statement running, or with a wrong secret, changes nothing                                 | `cancel/cancel/no_effect`             |

## String comparison

IRIS's default collation for a string column, `%SQLUPPER`, ignores case. Before 2.1, on a table created through
PGWire, `c = 'RED'` matched `red` and `Red`, `IN` and `LIKE` ignored case, `min(c)` returned an upper-cased value
that wasn't in the table, and a unique key refused `'X'` after `'x'`. Since 2.1, PGWire declares each character
column of a table it creates or alters `COLLATE %EXACT`, so these compare as on PostgreSQL. Tables created in IRIS
by other means keep their own collation and still ignore case.

| Behaviour                                                                                              | Check                           |
| ------------------------------------------------------------------------------------------------------ | ------------------------------- |
| `=`, `<>`, `IN`, `LIKE`, `CASE` and bound parameters are case-sensitive; `ILIKE` and `upper()` are not | `string_collation/comparisons`  |
| A unique key holds `'x'` and `'X'` as two values and refuses a second `'x'`                            | `string_collation/unique_key`   |
| A column added with `ALTER TABLE ... ADD COLUMN` compares the same way                                 | `string_collation/added_column` |
| `COLLATE "C"` (or any PostgreSQL collation name) is accepted, as IRIS's exact collation                | `string_collation/collate_c`    |
| Strings sort by code point, as PostgreSQL's `C` collation, not by a locale (pinned: `en_US` differs)   | `string_collation/ordering`     |

## Drivers and ORMs

| Client                              | What it sends                                                                               | Works                                                                             | Check                                                                              |
| ----------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| psycopg 3                           | `SAVEPOINT "_pg3_n"`, `RELEASE "_pg3_n"`, `ROLLBACK TO "_pg3_n"`                            | nested `transaction()`, pipelines                                                 | `savepoints/psycopg_three_deep/oox`                                                |
| Django                              | quoted `"s<thread>_x<n>"` savepoints                                                        | `atomic()` nesting                                                                | `savepoints/django_style`                                                          |
| SQLAlchemy 2 (`postgresql+psycopg`) | `current_schema()`, psycopg's `to_regtype()` type lookup, `has_table()` through pg_class    | `engine.connect()`, `create_all()`                                                | `sqlalchemy/connect`, `sqlalchemy/core_crud`                                       |
| SQLAlchemy 2 ORM                    | multi-row `INSERT ... SELECT ... FROM (VALUES ...) RETURNING`, `UPDATE`/`DELETE` row counts | add, update, delete, read back                                                    | `sqlalchemy/orm_crud`                                                              |
| SQLAlchemy 2                        | unquoted `SAVEPOINT sa_savepoint_n`, `RELEASE`, `ROLLBACK TO`                               | `begin_nested()` on a Connection and a Session, a duplicate key caught inside one | `savepoints/sqlalchemy_begin_nested`, `savepoints/sqlalchemy_session_begin_nested` |

PGWire answers SQLAlchemy's connect-time questions itself: `current_schema()` is `public`, the name PGWire gives the
IRIS schema in pg_namespace and information_schema. `current_schemas(true)` is `{pg_catalog,public}`. A type lookup
for `hstore` finds nothing, as on a PostgreSQL without that extension. `show transaction isolation level` reports
PGWire's default, `read uncommitted`, where PostgreSQL reports `read committed` (default isolation, above). The ORM's
multi-row INSERT runs as one INSERT per row, in the order SQLAlchemy expects its keys back. Outside an explicit
transaction those rows commit one by one, not as one statement. Prisma, Rails and Hibernate are not measured yet.

## The Hermitage row

Hermitage's anomaly table for IRIS through PGWire is in
[`docs/investigations/mvcc-apps-on-iris-pgwire.md`](investigations/mvcc-apps-on-iris-pgwire.md) section 5, drawn by
`make isolation-table` from the suite's results.
