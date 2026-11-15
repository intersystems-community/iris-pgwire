# PostgreSQL applications on IRIS through PGWire: transactions

What a PostgreSQL application can rely on when it talks to IRIS through PGWire, what PGWire refuses, and what to do
instead. It covers transaction behaviour only; SQL dialect and type differences are in
[`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

Every row below names the check in the isolation suite (`tests/e2e/isolation/`, run by `make isolation`) that measures
it against IRIS through PGWire and against PostgreSQL 16, with PostgreSQL's answer as the expected one. A row with no
check would be a claim nobody measured, so `tests/unit/test_compatibility_doc.py` fails if one appears. Measured on the
DBAPI backend; the embedded backend runs every session in one IRIS process and is documented as single-client.

Status: spec 052 slices 1 and 2 (aborted transactions, savepoints, row locking, ON CONFLICT). The sections marked "not yet" are spec 052's later slices.

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

## Timeouts, cancel, default isolation

Not yet: spec 052 user stories 5 to 7. Until then, see the "Isolation" section of
[`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

## Drivers and ORMs

| Client    | What it sends                                                    | Works                             | Check                               |
| --------- | ---------------------------------------------------------------- | --------------------------------- | ----------------------------------- |
| psycopg 3 | `SAVEPOINT "_pg3_n"`, `RELEASE "_pg3_n"`, `ROLLBACK TO "_pg3_n"` | nested `transaction()`, pipelines | `savepoints/psycopg_three_deep/oox` |
| Django    | quoted `"s<thread>_x<n>"` savepoints                             | `atomic()` nesting                | `savepoints/django_style`           |

SQLAlchemy 2 with the psycopg dialect does not connect yet: it asks `select current_schema()` while connecting,
and PGWire does not translate `current_schema()` (`42883`). Its `begin_nested()` sends the same three statements as
the rows above. Prisma, Rails and Hibernate use them too; none is measured yet.

## The Hermitage row

Hermitage's anomaly table for IRIS through PGWire is in
[`docs/investigations/mvcc-apps-on-iris-pgwire.md`](investigations/mvcc-apps-on-iris-pgwire.md) section 5, drawn by
`make isolation-table` from the suite's results.
