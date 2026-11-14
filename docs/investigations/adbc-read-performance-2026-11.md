# ADBC read performance through iris-pgwire (2026-11-14)

Reading a result into a DataFrame through iris-pgwire with the stock PostgreSQL ADBC driver
(`adbc-driver-postgresql`) took 52.5 s for 3M rows on the DBAPI backend. The official IRIS driver
took 11.9 s for the same rows. After the changes below it takes 17.9 s: about 1.5 times the
official driver instead of 4.4 times. No client receives a different byte, and nothing is refused
that was not refused before.

The raw results, the benchmark and every probe script are in
`benchmarks/results/adbc-reads-2026-11-14/`. The benchmark itself is
`benchmarks/adbc_native_comparison.py`.

## Setup

- IRIS 2026.2 (container `pgwire-release-lab`, Community licence), table `PGWBench.Bench`: 12
  columns (INT, BIGINT, two NUMERICs, two DOUBLEs, three VARCHARs, TIMESTAMP, DATE), about 20% NULLs,
  the same seeded rows as irispython-dx spec 21 phase 0.
- Four read paths, each into pandas and polars: the official driver (`intersystems-irispython`
  5.4.1, `fetchall` into a DataFrame); the native IRIS ADBC driver (Jim Nelson's, CL 9762165,
  `fetch_arrow_table`); iris-pgwire with `adbc-driver-postgresql` 1.13.0 in its default binary COPY
  mode; and the same with `adbc.postgresql.use_copy=false` (binary result rows).
- Every read checked against the generator's values (`check` mode) before it was timed. Timing:
  2 warm-ups, 5 runs, median.

## Results

| Rows, frame  | Native IRIS ADBC | Official driver | iris-pgwire, DBAPI | iris-pgwire, embedded | iris-pgwire before (DBAPI) |
| ------------ | ---------------- | --------------- | ------------------ | --------------------- | -------------------------- |
| 100k, pandas | 0.13 s           | 0.39 s          | 0.61 s             | 1.07 s                | 1.79 s                     |
| 100k, polars | 0.11 s           | 0.47 s          | 0.61 s             | 1.10 s                | 1.79 s                     |
| 3M, pandas   | 3.09 s           | 11.7 s          | 17.9 s             | not run               | 52.5 s                     |
| 3M, polars   | 2.31 s           | 15.1 s          | 17.5 s             | not run               | 51.4 s                     |

iris-pgwire figures are binary COPY with psycopg installed in the server; without psycopg the DBAPI
100k read is 0.79 s. Binary result rows (`use_copy=false`): 2.27 s before, 0.72 s after (100k,
DBAPI). Embedded at 3M was not run: it holds the whole result in memory.

## What was slow, and what changed

Found by profiling the DBAPI server with py-spy and by timing each stage inside the server
containers (py-spy cannot attach to irispython).

1. **Every value was logged.** `send_data_row` wrote about 17 log lines per row at info level,
   values included, so every value a client read also went into the server log. Removed. It was
   most of a 10 times slowdown in binary result-row mode.
2. **Describe ran the whole query.** A client's Describe needs the columns, but the server ran the
   statement and read every row, then the Execute ran it again. Embedded now stops after one row
   (`row_limit.at_most(1)`, a ContextVar the executors read). The DBAPI backend cannot stop part-way
   (see the driver defect below), so it runs `SELECT TOP 1 * FROM (query) AS pgwire_describe`
   (`dbapi_executor.describe_probe_sql`). IRIS describes the wrapped query exactly as the query
   (checked across 15 query shapes) and refuses the wrapper around an ORDER BY without TOP, a WITH
   and a FOR UPDATE; those, and any query IRIS refuses to wrap, run unwrapped as before. One row,
   not none, because column types are refined from the first row's values.
3. **Binary encoding looked up the type for every value.** `value_encoding.binary_encoder(oid)`
   chooses a column's encoder once, with fast paths for the exact Python types the DBAPI backend
   returns. Everything else goes to `encode_binary`, so the bytes and the refusals are unchanged
   (tested against the 41 PostgreSQL-captured cases, 20,000 random NUMERICs and 20,000 random
   timestamps). Encoding and framing 100k rows: 0.558 s before, 0.346 s after.
4. **One socket write per row.** DataRows and CopyData still go one per row, as PostgreSQL sends
   them, but a batch of them now goes to the socket in one write. The rows before a value that cannot
   be encoded are still sent before the error.
5. **psycopg's C encoder, optional** (`pip install iris-pgwire[fast]`, `row_encoding.py`). It frames
   the same 100k rows in 0.078 s with identical bytes. But it encodes by type OID without checking
   values: it wraps an int4 of 2^31 and an int2 of 2^15, takes the string `'f'` for true, quotes a
   JSON string again, lays out an `int` NUMERIC with different digits, and sends NUMERIC infinity,
   which this server refuses. So it only gets rows whose every value is exactly the expected Python
   type, with int2 and int4 values in range and NUMERICs finite; every other row is encoded by
   iris-pgwire. It uses psycopg's internal `format_row_binary`, so the version is pinned
   (`>=3.2,<3.4`) and the server checks on first use that psycopg encodes a row of every type as
   iris-pgwire does, and logs and stops using it if not. `PGWIRE_ROW_ENCODER=python` turns it off. It
   does not help the embedded backend, whose values (NUMERIC as float, dates as integers) fail the
   type check.

## The official driver loses its place on unread rows

With intersystems-irispython 5.4.1, any cursor left with rows unread breaks its connection: the next
statement fails with "Message out of order" and the connection is lost. That is `fetchmany(1)`
then `close()`, `execute` then `close()` with nothing fetched, and `execute` with no close at all;
only reading to the end works. It shows once a result spans several driver messages (1,000 rows of
these 12 columns is enough). `describe_variants.py` and `repro_fetchmany.py` reproduce it. Recorded
in irispython-dx (`dxlab/results/fetchmany-close-desync-2026-11-14/`), not yet filed with the
driver team.

## What remains

On DBAPI, after these changes, a 100k read is about 0.32 s of the driver's `fetchall`, the probe's
0.03 s, and the rest in encoding, socket writes and the client's decode. The native ADBC driver is
fast because it hands Arrow over directly; every other path builds a Python object for each value,
and nothing in Python closes that gap.

On the embedded backend the floor is `iris.sql.exec`: 0.63 s just to iterate 100k rows.
Embedded types are guessed from values (spec 051 US3): DATE arrives as a Horolog integer, NUMERIC as
float8, and an INT column as int64, or as varchar on a large ORDER BY result. These are pinned as
strict xfails in `tests/e2e/test_adbc.py`.

Text-format results (psql, JDBC, psycopg's default) got the same row encoder: 0.457 s to 0.283 s
per 100k rows, identical bytes. They also send Python's text for some types instead of
PostgreSQL's (track 2 in `docs/plans/2026-11-14-work-tracks.md`).

## Running it again

`run-bench.sh` and `run-e2e-adbc.sh` in the results directory are the wrappers used. They assume
the lab network `pgwire-bench`, irispython-dx's client image `dxlab-adbc-native-client:1`, and the
native driver build under `~/.local/share/irispython-dx/adbc-native/`. Run the embedded and DBAPI
servers one at a time: they share the Community licence's connections.
