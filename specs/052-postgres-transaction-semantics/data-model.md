# Data Model: PostgreSQL Transaction Semantics on IRIS (spec 052)

No persistent data. All state is per wire session, in memory, and is discarded when the session ends or its IRIS
connection is replaced (2.0.1's reset on close, a cancel).

## Transaction status (protocol layer)

Field `PGWireProtocol.transaction_status`, the byte ReadyForQuery sends. Owned by `protocol.py`.

| State  | Byte | Meaning                                   |
| ------ | ---- | ----------------------------------------- |
| Idle   | `I`  | no explicit transaction                   |
| Open   | `T`  | explicit transaction, usable              |
| Failed | `E`  | explicit transaction, aborted by an error |

Transitions:

| From    | Event                                                | To  | Reply                                       |
| ------- | ---------------------------------------------------- | --- | ------------------------------------------- |
| `I`     | `BEGIN` / `START TRANSACTION` (any spelling)         | `T` | `BEGIN`                                     |
| `I`     | a statement fails                                    | `I` | the error                                   |
| `T`     | a statement fails (any `ERROR` sent)                 | `E` | the error                                   |
| `T`     | `COMMIT`                                             | `I` | `COMMIT`                                    |
| `T`/`E` | `ROLLBACK`                                           | `I` | `ROLLBACK`                                  |
| `E`     | `COMMIT` (any spelling)                              | `I` | `ROLLBACK` (the transaction is rolled back) |
| `E`     | `ROLLBACK TO` an established savepoint               | `T` | `ROLLBACK`                                  |
| `E`     | `ROLLBACK TO` an unknown name                        | `E` | `3B001`                                     |
| `E`     | any other statement                                  | `E` | `25P02`, not sent to IRIS                   |
| any     | session ends, or a cancel closes its IRIS connection | —   | state discarded; IRIS rolls back            |

Validation: the status changes only through these transitions. A `FATAL` error ends the session instead.

## Extended-protocol discard flag (protocol layer)

`PGWireProtocol._discard_until_sync: bool`. Set when an error is sent while handling Parse, Bind, Describe, Execute or
Close; while set, every message but Sync is dropped; Sync clears it and sends ReadyForQuery with the current status.

## Savepoint stack (executor layer, shared by both backends)

Per session, cleared at every transaction end.

| Field         | Type                             | Meaning                                                                 |
| ------------- | -------------------------------- | ----------------------------------------------------------------------- |
| `entries`     | list of (client name, IRIS name) | established savepoints, oldest first                                    |
| `next_id`     | int                              | suffix for the next IRIS name (`pgw_sp_<n>`), unique in the transaction |
| `iris_levels` | int                              | IRIS savepoints issued in this transaction, released ones included      |

Client names are compared by PostgreSQL's identifier rules: an unquoted name folds to lower case, a quoted one is exact.

Operations and their IRIS statements:

| Operation       | Effect on `entries`                               | Sent to IRIS                                                    | Errors                                   |
| --------------- | ------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------- |
| `SAVEPOINT x`   | push (x, `pgw_sp_<next_id>`)                      | `SAVEPOINT pgw_sp_<n>`                                          | `54000` at the limit                     |
| `ROLLBACK TO x` | drop every entry above the most recent `x`        | `ROLLBACK TO SAVEPOINT <x's name>`, then `SAVEPOINT <x's name>` | `3B001` if unknown; `54000` at the limit |
| `RELEASE x`     | drop the most recent `x` and every entry above it | nothing                                                         | `3B001` if unknown                       |
| transaction end | clear; `iris_levels = 0`                          | (the `COMMIT` or `ROLLBACK` itself)                             |                                          |

Invariant: `iris_levels <= 254` (IRIS's limit; measured, research R4). Every error above aborts the transaction.

The isolation mixin's `savepoint_depth` (`_isolation.py`) is replaced by `len(entries)`.

## Session settings (executor layer)

| Setting             | Source                                                  | Reset on close (2.0.1 reset)         |
| ------------------- | ------------------------------------------------------- | ------------------------------------ |
| isolation level     | `SET ...`, `BEGIN ISOLATION LEVEL`, default from config | to `PGWIRE_DEFAULT_ISOLATION`        |
| `lock_timeout`      | `SET lock_timeout`; the client's value kept for `SHOW`  | to the server's default lock timeout |
| `statement_timeout` | `SET statement_timeout`; recorded only                  | nothing to reset in IRIS             |

## Server settings (`BackendConfig`)

| Field               | Env var                    | Values                               | Default          |
| ------------------- | -------------------------- | ------------------------------------ | ---------------- |
| `default_isolation` | `PGWIRE_DEFAULT_ISOLATION` | `read committed`, `read uncommitted` | `read committed` |
| `txn_compat`        | `PGWIRE_TXN_COMPAT`        | `strict`, `permissive`               | `strict`         |

Any other value stops the server at startup with a message listing the accepted values.

## Statement shape (permissive-mode warnings)

The statement text with literals and parameter markers replaced, whitespace collapsed. A set of shapes already warned
about, per server process, bounded (oldest dropped past 1000) so it cannot grow without limit.
