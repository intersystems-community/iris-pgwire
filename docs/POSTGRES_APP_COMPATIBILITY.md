# PostgreSQL applications on IRIS through PGWire: transactions

What a PostgreSQL application can rely on when it talks to IRIS through PGWire, what PGWire refuses, and what to do
instead. It covers transaction behaviour only; SQL dialect and type differences are in
[`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

Every row below names the check in the isolation suite (`tests/e2e/isolation/`, run by `make isolation`) that measures
it against IRIS through PGWire and against PostgreSQL 16, with PostgreSQL's answer as the expected one. A row with no
check would be a claim nobody measured, so `tests/unit/test_compatibility_doc.py` fails if one appears. Measured on the
DBAPI backend; the embedded backend runs every session in one IRIS process and is documented as single-client.

Status: spec 052 slice 1 (aborted transactions, savepoints). The sections marked "not yet" are spec 052's later slices.

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

## Row locking (`FOR UPDATE`), ON CONFLICT, timeouts, cancel, default isolation

Not yet: spec 052 user stories 3 to 7. Until then, see the "Isolation" and "Related PostgreSQL Statements" sections
of [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

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
