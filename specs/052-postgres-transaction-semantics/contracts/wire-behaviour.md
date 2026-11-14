# Wire Contract: what a client sees (spec 052)

This server's contract is the PostgreSQL protocol, so the contract is written as the messages a client receives.
Every row is a check in `tests/e2e/isolation/`, run against PGWire and against PostgreSQL 16 with PostgreSQL's answer
expected. "Strict" is the default; "permissive" is `PGWIRE_TXN_COMPAT=permissive`.

## Aborted transactions (US1)

| Client sends, in an explicit transaction             | ErrorResponse / CommandComplete | ReadyForQuery |
| ---------------------------------------------------- | ------------------------------- | ------------- |
| a statement that fails                               | the statement's SQLSTATE        | `E`           |
| then any statement but ROLLBACK, ROLLBACK TO, COMMIT | `25P02`                         | `E`           |
| then `COMMIT` (or `END`, `COMMIT WORK`, ...)         | `CommandComplete` `ROLLBACK`    | `I`           |
| then `ROLLBACK`                                      | `CommandComplete` `ROLLBACK`    | `I`           |
| then `ROLLBACK TO s` (established before the error)  | `CommandComplete` `ROLLBACK`    | `T`           |

Extended protocol: after an ErrorResponse, messages up to Sync produce no output; Sync produces ReadyForQuery.

## Savepoints (US2)

| Client sends                              | Result                                               |
| ----------------------------------------- | ---------------------------------------------------- |
| `SAVEPOINT s`                             | `CommandComplete` `SAVEPOINT`                        |
| `ROLLBACK TO [SAVEPOINT] s`               | `CommandComplete` `ROLLBACK`; `s` still established  |
| `RELEASE [SAVEPOINT] s`                   | `CommandComplete` `RELEASE`                          |
| `ROLLBACK TO` / `RELEASE` an unknown name | `3B001`; ReadyForQuery `E`                           |
| the 255th savepoint in one transaction    | `54000`; ReadyForQuery `E`                           |
| any of these outside a transaction        | `25P01` (`no_active_sql_transaction`), as PostgreSQL |

## Row locking clauses (US3)

| Statement, in an explicit transaction                               | Strict                                  | Permissive             |
| ------------------------------------------------------------------- | --------------------------------------- | ---------------------- |
| `SELECT ... FROM t WHERE p FOR UPDATE`                              | rows locked, rows as without the clause | same                   |
| the same with `NOWAIT`, a row locked elsewhere                      | `55P03` at once                         | same                   |
| `FOR UPDATE` on a join, subquery, view, aggregate, `LIMIT`          | `0A000`                                 | runs unlocked, warning |
| `FOR SHARE` / `FOR NO KEY UPDATE` / `FOR KEY SHARE` / `SKIP LOCKED` | `0A000`                                 | as 2.0, warning        |

## ON CONFLICT (US4)

| Statement                                                                  | Strict            | Permissive                                                         |
| -------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------ |
| target is the only unique key, `DO UPDATE SET` every column `= EXCLUDED.c` | PostgreSQL's rows | same                                                               |
| any other form, `DO NOTHING` included                                      | `0A000`           | emulated; a non-target error reaches the client (`23503`, `23505`) |
| the driver reports `<LIST ERROR>` for the conflict                         | (refused before)  | `XX000`                                                            |

## Timeouts (US5)

| Client sends                                  | Then, on a locked row                                      |
| --------------------------------------------- | ---------------------------------------------------------- |
| nothing                                       | `40001` after the server's default (10 s on the lab)       |
| `SET lock_timeout = '2s'`                     | `55P03` after about 2 s                                    |
| `SET lock_timeout = '1500ms'`                 | `55P03` after about 2 s (rounded up); `SHOW` says `1500ms` |
| `SET lock_timeout = 0` / `RESET lock_timeout` | as "nothing"                                               |
| `SET statement_timeout = ...`                 | accepted, not enforced, logged once                        |

## Cancel (US6)

| Situation                                | Cancelled session sees                                 |
| ---------------------------------------- | ------------------------------------------------------ |
| a statement running or waiting on a lock | `57014`; transaction rolled back; ReadyForQuery `I`    |
| next statement                           | runs on a fresh IRIS connection at the session's level |
| no statement running                     | nothing                                                |
| wrong secret                             | nothing                                                |

## Default isolation (US7)

| Server setting                              | `SHOW transaction_isolation` in a new session |
| ------------------------------------------- | --------------------------------------------- |
| none                                        | `read committed`                              |
| `PGWIRE_DEFAULT_ISOLATION=read uncommitted` | `read uncommitted`                            |
| anything else                               | server refuses to start                       |
