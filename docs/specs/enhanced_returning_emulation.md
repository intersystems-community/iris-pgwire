# Enhanced RETURNING Emulation in IRIS PGWire Gateway

## Context

Many PostgreSQL ORMs expect `INSERT`/`UPDATE` statements with `RETURNING` clauses so that code can obtain generated keys or updated rows without issuing a separate query. IRIS does not support `RETURNING` natively in most versions, and the current emulation is limited: it only works for the simplest inserts and cannot handle `ON CONFLICT` or expressions that reference computed columns. This specification defines an enhanced emulation strategy that keeps the emulated result within the same PGWire session and addresses identifier detection, `ON CONFLICT` variants, and multi-row scenarios.

## Goals

1. Always execute the client’s `INSERT`/`UPDATE` in the same transactional session when emulating `RETURNING`.
2. Determine the identifier(s) to return according to a defined priority (identity column, supplied PK value, metadata lookup) so that ORMs receive consistent results.
3. Handle `ON CONFLICT DO NOTHING` and `ON CONFLICT DO UPDATE` semantics when the ORM depends on the returned rows.
4. Describe the feasibility of extending emulation to multi-row inserts.

## Emulation Flow

1. **Parse the incoming statement**. Intercept when the client includes a `RETURNING` clause. Extract the target table, requested columns, and whether an `ON CONFLICT` clause exists.
2. **Begin a PGWire session-local transaction** (if not already in an explicit transaction) so that additional statements run in the same connection context.
3. **Execute the original statement** without modification, but buffering any result set so it can be returned after supplemental statements.
4. **Collect identifiers** based on the hierarchy defined in the next section. This collection may require immediate metadata queries or reuse of values provided in the statement.
5. **If additional rows need to be fetched** (e.g., to produce the requested `RETURNING` projections that IRIS cannot compute directly), issue supplemental `SELECT` statements in the same session, using temporary state (such as a table variable) to reconstruct the desired rows.
6. **Package the emulated returning rows** and send them over the PGWire protocol as the response to the original client command, ensuring that timing reflects that the client still receives the same format as a native `RETURNING` result.

This flow assumes the gateway keeps a mapping between the client statement and the supplemental queries so that errors in emulation can be correlated and surfaced as if they came from the original `INSERT`/`UPDATE`.

## Identifier Retrieval Priority

When the client requests `RETURNING *` or specific columns including the primary key, the gateway must determine which identifier value(s) to send back. Use the following hierarchy:

1. **Identity column**: If the table defines an `IDENTITY` column and the statement does not provide an explicit value, execute `SELECT LAST_IDENTITY()` immediately after the `INSERT`. This ensures generated sequential identifiers are captured reliably.
2. **Client-provided PK**: If the `INSERT`/`UPDATE` statement explicitly assigns a value to the primary key (for example, the ORM supplied `id = 123`), reuse that value directly as the returned identifier without issuing an extra query.
3. **Metadata-driven lookup**: If neither of the previous sources yield a value, query `INFORMATION_SCHEMA.KEY_COLUMN_USAGE` for the table’s primary key columns. Use those column names to `SELECT` the inserted/updated row(s) using a surrogate such as a unique index or a combination of values known from the statement.

If none of the above provides enough information (e.g., a table lacks an identity and the client neither returned the PK nor provided a unique predicate), the gateway should fail gracefully with a clear message that `RETURNING` emulation cannot be completed for the statement.

## Statement Splitting and Session Management

- All emulation steps must execute within the same PGWire session and (logical) transaction that the client used. This means supplemental `SELECT` statements to gather `RETURNING` data cannot be sent to a different connection or executed after the session commits.
- The gateway should reuse the client’s session ID and transaction state; if the client is in autocommit mode, emulation should still run before the commit occurs, so the supplemental selects use the same uncommitted data.
- Temporary state (for example, a temp table used to store generated IDs) must be cleaned up before the session returns control to the client, respecting IRIS’s session lifetime semantics.

## `ON CONFLICT` Support

1. **`ON CONFLICT DO NOTHING`**: If a conflict occurs, the original statement affects zero rows. Emulation should detect this (based on IRIS’s response code) and return an empty `RETURNING` result set to the client, mirroring PostgreSQL’s behavior. No supplemental statements are necessary in this case.
2. **`ON CONFLICT DO UPDATE`**: The gateway should attempt to treat the conflict-handling branch as part of an atomic operation:
   - If the conflict target matches a unique constraint on the table, and the driver can detect the conflict before the insert (for example, by running a `SELECT` first), run either the `INSERT` with `ON CONFLICT DO UPDATE` and, if a conflict is signaled, immediately run the equivalent `UPDATE` statement and capture its affected row(s).
   - If IRIS reports a uniqueness violation, catch the exception, execute a tailored `UPDATE` matching the conflicting row(s), and then perform the `RETURNING` emulation for that update.
   - Always ensure the client sees at most one result row per logical record, and that the result reflects the row that exists after conflict resolution (inserted or updated).

In practice, this may require wrapping the insert/update logic in a try/catch within the gateway so the conflict branch’s resulting rows are returned in the same way as a native `RETURNING` would.

## Multi-row Inserts

- **Feasibility**: Emulating `RETURNING` for multi-row `INSERT` is significantly more complex. IRIS does not expose the batch of inserted addresses directly, and batch `SELECT LAST_IDENTITY()` calls only return the last generated ID.
- **Potential approaches**:
  - Use a **temporary identifier table**: Before `INSERT`, track the values being inserted (especially the ones used for composite keys) into a session-scoped temporary table. After the `INSERT`, `SELECT` from the temporary table joined back to the target table to recover the newly inserted rows’ values.
  - For identity columns, **rate-limit multi-row inserts** to one row per statement when `RETURNING` is requested, to ensure the gateway can call `LAST_IDENTITY()` immediately after each `INSERT`.
  - **Batch ID collection**: If the client inserts many rows but still requires `RETURNING`, the gateway could split the logical insert into single-row inserts under the hood, collecting the generated IDs as it goes. This maintains correctness but may impact performance.
- **Limitations**: Any approach that issues additional statements per inserted row may degrade throughput and might not respect user expectations around atomicity without extra locking/transaction logic. The spec recommends at minimum documenting these trade-offs and, depending on performance impact, limiting multi-row `RETURNING` emulation to small batches or disabling it with a descriptive error when IRIS capabilities are insufficient.

## Summary

This specification outlines a richer emulation strategy for PostgreSQL `RETURNING` results in the IRIS PGWire gateway. By enforcing session-local supplemental queries, defining an identifier retrieval hierarchy, and explicitly handling conflict branches and multi-row cases, the gateway can better support ORMs that assume consistent `RETURNING` behavior. Implementation should focus on maximizing correctness with clear fallbacks and transparent diagnostics for unsupported statements.
