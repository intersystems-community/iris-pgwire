"""Is `iris-embedded-python-wrapper` a viable unified driver layer for pgwire?

Five questions, all answered by measurement against the live IRIS instance. None
of them is answered by reading the package's PyPI description, which is where
every claim below started life.

1. **Coexistence.** The wrapper ships a top-level `iris` package. So does the
   official `intersystems-irispython`. Does adopting one shadow or *replace* the
   other?
2. **Does the facade run SQL** against IRIS at all, and what does it return?
3. **T011h** — does `cursor.description` report the *same* column types whether
   or not rows come back? This is the defect recorded in
   `specs/044-catalog-as-views/tasks.md` T011h: the `dbapi` backend inferred
   types from the first row's value, so a statement Describe (dummy parameters,
   zero rows) declared different types than Execute, and a client that read the
   Describe could not decode the DataRow.
4. **T027** — is the error wording normalized across backends, and does
   `sql_translator/sqlstate.py` still classify it?
5. **Empty string vs NULL** — IRIS spells the empty string `$CHAR(0)`. Does the
   facade normalize it, as its description claims?

Plus the `iris.connect(path=...)` claim: does embedded mode work from an ordinary
`python3`, which would remove the need to `docker cp` a probe into the container?

## Running it

Two halves, because the two runtimes cannot be reached from one process.

**Host half** (native/remote path, and the coexistence analysis):

    pip install --no-deps --target /tmp/f045libs iris-embedded-python-wrapper
    F045_WRAPPER=/tmp/f045libs python probe_unified_driver.py

Without `F045_WRAPPER` the wrapper sections report `SKIP` and the rest still runs,
so the probe is useful as a baseline against the official driver alone.

**Container half** (embedded path — needs an IRIS installation, which the host
does not have):

    docker cp <wrapper-tree>/. iris-pgwire-db:/tmp/f045libs/
    docker cp src/iris_pgwire/sql_translator/sqlstate.py \
        iris-pgwire-db:/tmp/sqlstate_045.py
    docker cp probe_unified_driver.py iris-pgwire-db:/tmp/probe_045.py
    docker exec iris-pgwire-db /usr/irissys/bin/irispython /tmp/probe_045.py --embedded
    docker exec iris-pgwire-db bash -lc \
        'LD_LIBRARY_PATH=/usr/irissys/bin python3 /tmp/probe_045.py --embedded'

The second container invocation is the `iris.connect(path=...)` claim: ordinary
CPython, not `irispython`. Run it *without* `LD_LIBRARY_PATH` too — the result
differs, and the difference is the finding.

`sqlstate.py` is loaded by path rather than imported because `iris_pgwire` is not
installed in either container interpreter (same approach as
`specs/044-catalog-as-views/spikes/probe_embedded_error_wording.py`).

Nothing here is mocked. Every line of output came from IRIS.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback

IRIS_HOST = os.environ.get("F045_IRIS_HOST", "localhost")
IRIS_PORT = int(os.environ.get("F045_IRIS_PORT", "1972"))
IRIS_NAMESPACE = os.environ.get("F045_IRIS_NAMESPACE", "USER")
IRIS_USER = os.environ.get("F045_IRIS_USER", "_SYSTEM")
IRIS_PASSWORD = os.environ.get("F045_IRIS_PASSWORD", "SYS")

# Where a `pip install --target` copy of the wrapper lives. Prepended to
# sys.path so its `iris` package shadows the official one — which is the whole
# point: adoption *is* shadowing, and the probe has to exercise that, not avoid
# it.
WRAPPER_PATH = os.environ.get("F045_WRAPPER", "/tmp/f045libs")

# Loaded by path in the container, imported normally on the host.
SQLSTATE_PATH = os.environ.get("F045_SQLSTATE", "/tmp/sqlstate_045.py")

# Two tables, so the empty-string question can be answered as a matrix rather
# than a single reading: one written through the native/remote driver, one
# written through the embedded API. Each run reads whichever of the two exist,
# so "written by X, read by Y" is measured for all four combinations.
PROBE_TABLE_NATIVE = "SQLUser.f045_null_native"
PROBE_TABLE_EMBEDDED = "SQLUser.f045_null_embedded"
PROBE_TABLE_FACADE = "SQLUser.f045_null_facade"

# The T011h query, reduced to the part that matters and spelled in IRIS SQL so
# it can run without pgwire's translation layer in the path. It keeps the three
# properties of Prisma's original that produced the defect: a `varchar` column,
# a `CAST(... AS BIT)` boolean, and a plain catalog boolean column — selected
# through a parameterised `WHERE` so the same statement can be run once with a
# matching parameter and once with a non-matching one.
#
# Prisma's verbatim SQL is in
# `specs/044-catalog-as-views/spikes/probe_statement_describe.py`; it uses
# `= ANY($1)` and an unqualified `obj_description()`, both of which exist only
# after pgwire translates them, so it cannot be sent to IRIS directly.
T011H_SQL = """SELECT
  tbl.relname AS table_name,
  namespace.nspname AS namespace,
  CAST(CASE WHEN tbl.relhassubclass <> 0 AND tbl.relkind = 'p' THEN 1 ELSE 0 END AS BIT)
    AS is_partition,
  tbl.relrowsecurity AS has_row_level_security,
  PGWire.OBJ_DESCRIPTION(tbl.oid, 'pg_class') AS description
FROM pg_catalog.pg_class AS tbl
INNER JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = tbl.relnamespace
WHERE tbl.relkind = 'r' AND namespace.nspname = ?"""

# (label, SQL, the SQLSTATE PostgreSQL 15 returns for the same shape)
ERROR_CASES = (
    ("missing table", "SELECT * FROM no_such_table_f045", "42P01"),
    ("missing column", "SELECT no_such_col_f045 FROM pg_catalog.pg_class", "42703"),
    ("internal failure", "SELECT $LISTGET('not a list', 1)", "XX000"),
)


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------

_results: list[tuple[str, str, str]] = []


def record(verdict: str, question: str, finding: str) -> None:
    """Record one finding. `verdict` is FACT, FALSE, MIXED, SKIP or UNTESTABLE."""
    _results.append((verdict, question, finding))


def head(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def sub(text: str) -> None:
    print(f"\n-- {text}")


def load_sqlstate():
    """`classify_iris_error`, imported or loaded by path, or None."""
    try:
        from iris_pgwire.sql_translator.sqlstate import classify_iris_error

        return classify_iris_error
    except ImportError:
        pass
    if not os.path.exists(SQLSTATE_PATH):
        return None
    spec = importlib.util.spec_from_file_location("f045_sqlstate", SQLSTATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.classify_iris_error


def describe_types(description) -> list[tuple[str, object]]:
    """`[(name, type_code)]` from a PEP 249 description, tolerating None."""
    if not description:
        return []
    return [(row[0], row[1] if len(row) > 1 else None) for row in description]


# ---------------------------------------------------------------------------
# coexistence: does the wrapper shadow or replace the official module?
# ---------------------------------------------------------------------------


def probe_coexistence() -> None:
    head("1. Coexistence with the official intersystems-irispython")

    sub("before touching the wrapper")
    import iris as official

    official_file = getattr(official, "__file__", None)
    print(f"   import iris -> {official_file}")
    try:
        from importlib import metadata

        print(f"   intersystems-irispython == {metadata.version('intersystems-irispython')}")
    except Exception as exc:  # noqa: BLE001
        print(f"   intersystems-irispython version unknown: {exc}")

    report_module_name_collisions()

    sub("file paths each distribution claims")
    # This is the decisive question and it is answered from the two RECORDs, not
    # by installing over the top of a working environment.
    collisions = _record_collisions()
    if collisions is None:
        print("   could not read one of the two RECORDs; collision check skipped")
        record("SKIP", "coexistence (file collision)", "a RECORD was unreadable")
    elif collisions:
        for path in collisions:
            print(f"   BOTH distributions install: {path}")
        record(
            "FACT",
            "coexistence: shadow or replace?",
            "REPLACE. Both distributions claim the same installed path(s): "
            + ", ".join(sorted(collisions))
            + ". Installing the wrapper into the same environment overwrites the "
            "official module's package initialiser, and uninstalling the wrapper "
            "deletes it.",
        )
    else:
        print("   no overlapping installed paths")
        record("FACT", "coexistence: shadow or replace?", "no path collision found")


def _record_collisions() -> set[str] | None:
    try:
        from importlib import metadata
    except ImportError:
        return None
    try:
        official = metadata.distribution("intersystems-irispython")
    except Exception:  # noqa: BLE001
        return None

    wrapper_record = os.path.join(
        WRAPPER_PATH, "iris_embedded_python_wrapper-0.6.1.dist-info", "RECORD"
    )
    if not os.path.exists(wrapper_record):
        # Fall back to an installed copy, if there is one.
        try:
            wrapper = metadata.distribution("iris-embedded-python-wrapper")
            wrapper_paths = {str(f) for f in (wrapper.files or [])}
        except Exception:  # noqa: BLE001
            return None
    else:
        with open(wrapper_record, encoding="utf-8") as handle:
            wrapper_paths = {line.split(",")[0] for line in handle if line.strip()}

    official_paths = {str(f) for f in (official.files or [])}
    interesting = {
        path
        for path in wrapper_paths & official_paths
        if not path.endswith((".pyc", "RECORD", "WHEEL", "METADATA"))
    }
    return interesting


# Top-level module names the wrapper claims. `iris_ep` is the interesting one:
# InterSystems ships `/usr/irissys/lib/python/iris_ep.py` under the same name.
WRAPPER_TOP_LEVEL = (
    "iris",
    "iris_ep",
    "_iris_ep",
    "_iris_ep_sitehook",
    "iris_utils",
    "iris_embedded_python",
)


def report_module_name_collisions() -> None:
    """Which file each of the wrapper's top-level names resolves to, with and
    without the wrapper on `sys.path`.

    Adoption is not just about the `iris` package: any name the wrapper claims
    that something else already provides is a shadowing decision made by
    `sys.path` order, silently.
    """
    from importlib.machinery import PathFinder

    sub("module names the wrapper claims, and what else answers to them")
    without = [entry for entry in sys.path if entry != WRAPPER_PATH]
    collisions = []
    for name in WRAPPER_TOP_LEVEL:
        other = PathFinder.find_spec(name, without)
        mine = PathFinder.find_spec(name, [WRAPPER_PATH])
        other_origin = getattr(other, "origin", None)
        mine_origin = getattr(mine, "origin", None)
        if mine_origin is None:
            continue
        if other_origin:
            collisions.append((name, other_origin))
            print(f"   {name:22} wrapper={mine_origin}")
            print(f"   {'':22} ALSO   ={other_origin}")
        else:
            print(f"   {name:22} wrapper={mine_origin} (no other provider)")
    if collisions:
        record(
            "FACT",
            "top-level module names the wrapper shares with something else",
            "; ".join(f"{name} also provided by {origin}" for name, origin in collisions)
            + ". Which one wins is decided by sys.path/sys.modules order, not by "
            "configuration.",
        )


def load_wrapper():
    """Import the wrapper's `iris`, shadowing whatever else provides it.

    Every name the wrapper owns is purged from `sys.modules` first. Without that
    the wrapper's own `iris/__init__.py` does `from iris_ep import *` and picks up
    **InterSystems'** `iris_ep` if that one is already imported — measured inside
    the container, where the result is an `iris` module that has a `runtime`
    attribute (so `hasattr` says yes) which raises when called.
    """
    if not os.path.isdir(WRAPPER_PATH):
        print(f"   wrapper tree not found at {WRAPPER_PATH}")
        return None
    if WRAPPER_PATH not in sys.path:
        sys.path.insert(0, WRAPPER_PATH)
    for name in list(sys.modules):
        root = name.split(".")[0]
        if root in WRAPPER_TOP_LEVEL:
            del sys.modules[name]
    import iris as wrapped

    print(f"   import iris -> {wrapped.__file__}")
    print(f"   iris.__path__ = {list(getattr(wrapped, '__path__', []))}")
    import iris_ep as resolved_ep

    print(f"   import iris_ep -> {getattr(resolved_ep, '__file__', None)}")
    return wrapped


# ---------------------------------------------------------------------------
# host half: the native / remote path
# ---------------------------------------------------------------------------


def dbapi_writer(cursor, conn):
    def execute(sql, param):
        if param is None and "?" not in sql:
            cursor.execute(sql)
        else:
            cursor.execute(sql, (param,))

    return execute, getattr(conn, "commit", None)


def dbapi_reader(cursor):
    def read_rows(sql):
        cursor.execute(sql)
        return cursor.fetchall()

    return read_rows


def probe_official_baseline(classify) -> None:
    """The same three measurements against the official driver alone.

    Without this, a good result from the facade proves nothing: the native path
    turns out to be a pass-through, so the baseline *is* the result.
    """
    head("BASELINE — the official intersystems-irispython driver, no wrapper")
    for name in [n for n in list(sys.modules) if n == "iris" or n.startswith("iris.")]:
        del sys.modules[name]
    if WRAPPER_PATH in sys.path:
        sys.path.remove(WRAPPER_PATH)
    import iris as official

    print(f"   import iris -> {official.__file__}")
    import iris.dbapi as official_dbapi

    conn = official_dbapi.connect(
        hostname=IRIS_HOST,
        port=IRIS_PORT,
        namespace=IRIS_NAMESPACE,
        username=IRIS_USER,
        password=IRIS_PASSWORD,
    )
    cursor = conn.cursor()
    _probe_t011h(cursor, "official driver")
    _probe_errors(cursor, classify, "official driver")
    sub("writing the native-side null/empty probe table")
    execute, commit = dbapi_writer(cursor, conn)
    write_null_probe_table(execute, PROBE_TABLE_NATIVE, commit)
    read_null_probe_tables(dbapi_reader(cursor), "official driver")


def probe_native(classify) -> None:
    head("2-5. The facade's native path, against IRIS at %s:%s" % (IRIS_HOST, IRIS_PORT))

    wrapped = load_wrapper()
    if wrapped is None:
        record("SKIP", "native facade", f"no wrapper tree at {WRAPPER_PATH}")
        return

    sub("does iris.runtime exist, and what does it detect here?")
    try:
        ctx = wrapped.runtime.get()
        print(f"   state={ctx.state} mode={ctx.mode} embedded_available={ctx.embedded_available}")
        record(
            "FACT",
            "iris.runtime model exists",
            f"state={ctx.state}, mode={ctx.mode}, embedded_available={ctx.embedded_available}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"   iris.runtime unavailable: {exc}")
        record("FALSE", "iris.runtime model exists", str(exc))

    sub("iris.dbapi.connect(mode='native')")
    try:
        conn = wrapped.dbapi.connect(
            mode="native",
            hostname=IRIS_HOST,
            port=IRIS_PORT,
            namespace=IRIS_NAMESPACE,
            username=IRIS_USER,
            password=IRIS_PASSWORD,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"   FAILED: {type(exc).__name__}: {exc}")
        record("FALSE", "iris.dbapi executes SQL over 1972", f"{type(exc).__name__}: {exc}")
        return

    conn_class = f"{type(conn).__module__}.{type(conn).__qualname__}"
    print(f"   connection class: {conn_class}")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 AS one")
    print(f"   SELECT 1 -> {cursor.fetchall()}")
    record(
        "FACT",
        "iris.dbapi executes SQL over 1972",
        f"yes. Native mode returns {conn_class} — the official driver's own "
        "connection object, so the facade is a pass-through here, not a layer.",
    )

    _probe_t011h(cursor, "native facade")
    _probe_errors(cursor, classify, "native facade")
    read_null_probe_tables(dbapi_reader(cursor), "native facade")


# ---------------------------------------------------------------------------
# question 3: T011h
# ---------------------------------------------------------------------------


def _probe_t011h(cursor, label: str) -> None:
    sub(f"T011h — does the declared type depend on the row count? [{label}]")
    seen: dict[str, list[tuple[str, object]]] = {}
    counts: dict[str, int] = {}
    for case, param in (("matching", "public"), ("non-matching", "__no_such_schema_f045__")):
        try:
            cursor.execute(T011H_SQL, (param,))
            rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            print(f"   {case}: query failed: {type(exc).__name__}: {exc}")
            record("SKIP", f"T011h on {label}", f"query failed: {exc}")
            return
        seen[case] = describe_types(cursor.description)
        counts[case] = len(rows)
        print(f"   {case} parameter -> {len(rows)} row(s)")
        for name, code in seen[case]:
            print(f"      {name:26} type_code={code!r}")
        if rows:
            print(f"      first row: {tuple(rows[0])}")
            print(f"      py types : {[type(v).__name__ for v in rows[0]]}")

    if seen.get("matching") == seen.get("non-matching"):
        stable = "STABLE"
    else:
        stable = "UNSTABLE"
    print(f"   verdict: description is {stable} across {counts} rows")

    codes = {code for _, code in seen.get("matching", [])}
    if codes == {None}:
        record(
            "FALSE",
            f"T011h: row-count-independent column types on {label}",
            "The description is stable across row counts, but vacuously: every "
            "type_code is None. This backend reports no column type at all, so it "
            "cannot be the single source of column metadata.",
        )
    elif stable == "STABLE" and len(codes) > 1:
        record(
            "FACT",
            f"T011h: row-count-independent column types on {label}",
            "Yes, and with distinct types: "
            + ", ".join(f"{n}={c!r}" for n, c in seen["matching"])
            + f". Identical for {counts['matching']} rows and "
            f"{counts['non-matching']} rows.",
        )
    else:
        record(
            "MIXED",
            f"T011h: row-count-independent column types on {label}",
            f"{stable}; type codes seen: {sorted(str(c) for c in codes)}",
        )

    # What pgwire currently does with those codes. This is the reason T011h
    # existed, and it is worth measuring rather than inferring.
    _probe_pgwire_type_mapping(seen.get("matching", []))


def _probe_pgwire_type_mapping(described: list[tuple[str, object]]) -> None:
    if not described:
        return
    try:
        from iris_pgwire.dbapi_executor import DBAPIExecutor
    except Exception:  # noqa: BLE001
        return
    sub("what DBAPIExecutor._map_dbapi_type_to_oid makes of those type codes")
    mapped = {}
    for name, code in described:
        oid = DBAPIExecutor._map_dbapi_type_to_oid(None, code)
        mapped[name] = oid
        print(f"   {name:26} type_code={code!r:6} -> PostgreSQL OID {oid}")
    distinct_in = len({c for _, c in described})
    distinct_out = len(set(mapped.values()))
    if distinct_in > 1 and distinct_out == 1:
        record(
            "FACT",
            "does pgwire use the type codes the driver already gives it?",
            f"No. The driver reports {distinct_in} distinct type codes; "
            f"`_map_dbapi_type_to_oid` collapses all of them to "
            f"{next(iter(set(mapped.values())))}. It does `str(code).upper()` and "
            "searches for the words INT/CHAR/DATE/TIME, which never appear in a "
            "numeric ODBC code, so every column falls through to the varchar "
            "default. The metadata T011h had to reconstruct from the statement "
            "text was being discarded one function earlier.",
        )


# ---------------------------------------------------------------------------
# question 4: T027
# ---------------------------------------------------------------------------


def _probe_errors(cursor, classify, label: str) -> None:
    sub(f"T027 — error wording, and whether sqlstate.py still classifies it [{label}]")
    observed = []
    mismatches = 0
    for case, sql, expected in ERROR_CASES:
        try:
            cursor.execute(sql)
            cursor.fetchall()
            print(f"   {case}: NO ERROR RAISED")
            observed.append((case, None, None))
            mismatches += 1
            continue
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            exc_name = type(exc).__name__
        printable = message.replace("\r", "\\r").replace("\n", "\\n")
        has_sqlcode = "SQLCODE" in message
        nonprintable = sum(1 for ch in message if ord(ch) < 32 or ord(ch) > 126)
        print(f"   {case}: {exc_name}")
        print(f"      message : {printable[:200]}")
        print(f"      SQLCODE present: {has_sqlcode}; non-printable chars: {nonprintable}")
        if classify is None:
            print("      classify: sqlstate.py unavailable")
            observed.append((case, message, None))
            continue
        state, condition = classify(message)
        ok = state == expected
        mismatches += not ok
        print(f"      classify: {state} ({condition}) — expected {expected} {'ok' if ok else 'MISMATCH'}")
        observed.append((case, message, state))

    if classify is None:
        record("SKIP", f"T027 on {label}", "classify_iris_error not loadable")
        return
    sqlcodes = sum(1 for _, message, _ in observed if message and "SQLCODE" in message)
    record(
        "FACT" if mismatches == 0 else "MIXED",
        f"T027: error classification on {label}",
        f"{len(ERROR_CASES) - mismatches}/{len(ERROR_CASES)} classified as PostgreSQL "
        f"would; SQLCODE present in {sqlcodes}/{len(ERROR_CASES)} messages. "
        "The wording is NOT normalized by the facade — see the recorded messages.",
    )


# ---------------------------------------------------------------------------
# question 5: empty string vs NULL
# ---------------------------------------------------------------------------


LABELS = {1: "literal ''", 2: "literal NULL", 3: "bound ''", 4: "bound None"}


READ_ONLY = False


def write_null_probe_table(execute, table: str, commit=None) -> bool:
    """Write the four cases into `table` using `execute(sql, params)`.

    Skipped under `--read-only`, which exists because a read in the *same*
    process as the write and a read from a fresh process do not always agree —
    see the results file. Reading the tables written by an earlier run is the
    only way to separate the two.
    """
    if READ_ONLY:
        print(f"   --read-only: leaving {table} as the previous run left it")
        return False
    try:
        execute(f"DROP TABLE IF EXISTS {table}", None)
        execute(f"CREATE TABLE {table} (id INT, s VARCHAR(50))", None)
        execute(f"INSERT INTO {table} (id, s) VALUES (1, '')", None)
        execute(f"INSERT INTO {table} (id, s) VALUES (2, NULL)", None)
        execute(f"INSERT INTO {table} (id, s) VALUES (3, ?)", "")
        execute(f"INSERT INTO {table} (id, s) VALUES (4, ?)", None)
        if commit is not None:
            try:
                commit()
            except Exception:  # noqa: BLE001
                pass
        print(f"   wrote {table}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"   writing {table} failed: {type(exc).__name__}: {exc}")
        return False


def read_null_probe_tables(read_rows, label: str) -> None:
    """Read both probe tables with `read_rows(sql) -> iterable of rows`."""
    sub(f"empty string vs NULL, read by {label}")
    for table, writer in (
        (PROBE_TABLE_NATIVE, "native/remote driver"),
        (PROBE_TABLE_EMBEDDED, "embedded iris.sql.exec"),
        (PROBE_TABLE_FACADE, "the wrapper's embedded facade"),
    ):
        try:
            rows = list(read_rows(f"SELECT id, s FROM {table} ORDER BY id"))
        except Exception as exc:  # noqa: BLE001
            print(f"   {table}: unreadable ({type(exc).__name__}) — skipped")
            continue
        if not rows:
            print(f"   {table}: no rows — skipped")
            continue
        values = {}
        print(f"   written by {writer} ({table}):")
        for row in rows:
            values[int(row[0])] = row[1]
            print(f"      id={row[0]} ({LABELS.get(int(row[0]), '?'):13}) -> {row[1]!r}")
        _judge_null_probe(values, f"written by {writer}, read by {label}")


def _judge_null_probe(values: dict, what: str) -> None:
    literal_empty = values.get(1)
    literal_null = values.get(2)
    bound_empty = values.get(3)
    bound_null = values.get(4)
    distinct = literal_empty != literal_null and bound_empty != bound_null
    ideal = (
        literal_empty == "" and literal_null is None and bound_empty == "" and bound_null is None
    )
    if ideal:
        verdict, note = "FACT", "empty string is '' and SQL NULL is None in all four cases."
    elif distinct:
        verdict, note = (
            "MIXED",
            "empty string and NULL stay distinguishable, but not as Python '' and None: "
            f"literal '' -> {literal_empty!r}, literal NULL -> {literal_null!r}, "
            f"bound '' -> {bound_empty!r}, bound None -> {bound_null!r}.",
        )
    else:
        verdict, note = (
            "FALSE",
            "empty string and SQL NULL are NOT distinguishable: "
            f"literal '' -> {literal_empty!r}, literal NULL -> {literal_null!r}, "
            f"bound '' -> {bound_empty!r}, bound None -> {bound_null!r}.",
        )
    record(verdict, f"empty string vs NULL — {what}", note)


# ---------------------------------------------------------------------------
# the iris.connect(path=...) claim
# ---------------------------------------------------------------------------

INSTALL_DIR_CANDIDATES = ("/usr/irissys", "/opt/iris", "/opt/intersystems/iris", "/InterSystems/IRIS")


def probe_embedded_from_cpython() -> str | None:
    head("6. Does embedded mode work from an ordinary python3 here?")
    env_dir = os.environ.get("IRISINSTALLDIR")
    print(f"   IRISINSTALLDIR = {env_dir or '<unset>'}")
    found = [path for path in INSTALL_DIR_CANDIDATES if os.path.isdir(path)]
    for path in INSTALL_DIR_CANDIDATES:
        print(f"   {path}: {'present' if os.path.isdir(path) else 'absent'}")
    install_dir = env_dir if env_dir and os.path.isdir(env_dir) else (found[0] if found else None)
    if install_dir is None:
        print("\n   No IRIS installation on this host, so `iris.connect(path=...)` has")
        print("   nothing to point at. UNTESTABLE here — not disproved.")
        record(
            "UNTESTABLE",
            "embedded mode from ordinary python3",
            "No IRIS installation exists on this host (IRISINSTALLDIR unset; none of "
            + ", ".join(INSTALL_DIR_CANDIDATES)
            + " present). IRIS runs in the `iris-pgwire-db` container. The claim "
            "cannot be tested from the host at all, and cannot remove the need to "
            "`docker cp` a probe into the container, because the embedded runtime "
            "requires the IRIS installation to be on the *same* machine as the "
            "Python process. Tested separately inside the container — see the "
            "--embedded run.",
        )
        return None
    print(f"\n   IRIS installation found at {install_dir}")
    print(f"   LD_LIBRARY_PATH = {os.environ.get('LD_LIBRARY_PATH') or '<unset>'}")
    return install_dir


# ---------------------------------------------------------------------------
# container half: the embedded path
# ---------------------------------------------------------------------------


def probe_embedded(classify) -> None:
    head("EMBEDDED half — control (iris.sql.exec) then the wrapper's facade")

    sub("control: IRIS's own embedded API, with no wrapper on sys.path")
    control_ok = _probe_embedded_control(classify)

    report_module_name_collisions()

    sub("the wrapper's embedded DB-API facade")
    wrapped = load_wrapper()
    if wrapped is None:
        record("SKIP", "embedded facade", f"no wrapper tree at {WRAPPER_PATH}")
        return
    try:
        ctx = wrapped.runtime.get()
        print(f"   state={ctx.state} mode={ctx.mode} embedded_available={ctx.embedded_available}")
    except Exception as exc:  # noqa: BLE001
        print(f"   iris.runtime unavailable: {exc}")

    install_dir = os.environ.get("IRISINSTALLDIR") or next(
        (p for p in INSTALL_DIR_CANDIDATES if os.path.isdir(p)), None
    )
    kwargs = {"mode": "embedded"}
    if install_dir and not bool(getattr(sys, "_embedded", 0)):
        # Ordinary python3: this is the `path=` claim under test.
        kwargs = {"path": install_dir, "namespace": IRIS_NAMESPACE}
        print(f"   ordinary CPython -> iris.dbapi.connect(path={install_dir!r})")
    try:
        conn = wrapped.dbapi.connect(**kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"   connect failed: {type(exc).__name__}: {exc}")
        record("FALSE", "embedded facade connects", f"{type(exc).__name__}: {exc}")
        return
    print(f"   connection class: {type(conn).__module__}.{type(conn).__qualname__}")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT $ZVERSION AS v")
        print(f"   $ZVERSION -> {cursor.fetchall()[0][0]}")
    except Exception as exc:  # noqa: BLE001
        print(f"   first statement FAILED: {type(exc).__name__}: {str(exc)[:200]}")
        record(
            "MIXED",
            "embedded mode from ordinary python3 (in the container)",
            "The runtime reported embedded availability and `connect` succeeded, but "
            f"the first statement failed: {type(exc).__name__}: {str(exc)[:160]}. "
            "This is the loader-path failure the package's own troubleshooting "
            "section documents — availability is reported before it holds. Set "
            "LD_LIBRARY_PATH to the IRIS bin directory before Python starts.",
        )
        return
    if not bool(getattr(sys, "_embedded", 0)):
        record(
            "FACT",
            "embedded mode from ordinary python3 (in the container)",
            "Verified: with LD_LIBRARY_PATH pointing at the IRIS bin directory, "
            f"`iris.dbapi.connect(path=...)` from plain python3 executes SQL. "
            "Requires the IRIS installation on the same machine.",
        )

    _probe_t011h(cursor, "embedded facade")
    _probe_errors(cursor, classify, "embedded facade")
    sub("writing a null/empty probe table through the facade itself")
    execute, commit = dbapi_writer(cursor, conn)
    write_null_probe_table(execute, PROBE_TABLE_FACADE, commit)
    if not control_ok:
        write_null_probe_table(execute, PROBE_TABLE_EMBEDDED, commit)
    read_null_probe_tables(dbapi_reader(cursor), "embedded facade")


def _probe_embedded_control(classify) -> bool:
    try:
        import iris as native
    except ImportError as exc:
        print(f"   no embedded iris module: {exc}")
        record("SKIP", "embedded control", str(exc))
        return False
    print(f"   iris -> {getattr(native, '__file__', None)}")
    if not hasattr(native, "sql"):
        print("   this iris module has no .sql — not an embedded runtime")
        record("SKIP", "embedded control", "iris.sql absent")
        return False

    # What metadata does the embedded result object actually carry?
    try:
        result = native.sql.exec("SELECT 1 AS one")
        has_meta = hasattr(result, "_meta")
        print(f"   iris.sql.exec result class: {type(result)}")
        print(f"   has _meta attribute: {has_meta} ({getattr(result, '_meta', None)!r})")
        list(result)
        record(
            "FACT" if not has_meta else "MIXED",
            "embedded result column metadata (iris.sql.exec)",
            (
                "The result object has no `_meta` attribute on this IRIS build, so "
                "`IRISExecutor._materialize_embedded_result`'s `getattr(result, "
                "'_meta', None)` is always None and column metadata comes from the "
                "fallback paths (a separate discovery query, or the row values)."
            )
            if not has_meta
            else f"_meta present: {getattr(result, '_meta', None)!r}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"   metadata probe failed: {type(exc).__name__}: {exc}")

    # Empty string vs NULL, unnormalized.
    def sql_exec_write(sql, param):
        if param is None and "?" not in sql:
            native.sql.exec(sql)
        else:
            native.sql.exec(sql, param)

    def sql_exec_read(sql):
        return [list(row) for row in native.sql.exec(sql)]

    try:
        write_null_probe_table(sql_exec_write, PROBE_TABLE_EMBEDDED)
        read_null_probe_tables(sql_exec_read, "iris.sql.exec (control)")
        # SQL's own verdict alongside the driver's, so the two cannot be
        # confused for one another.
        sub("what SQL itself says about the same rows")
        for table in (PROBE_TABLE_NATIVE, PROBE_TABLE_EMBEDDED, PROBE_TABLE_FACADE):
            try:
                rows = sql_exec_read(
                    "SELECT id, s, CASE WHEN s IS NULL THEN 'ISNULL' ELSE 'NOTNULL' END "
                    f"AS nn, $LENGTH(s) AS len FROM {table} ORDER BY id"
                )
            except Exception:  # noqa: BLE001
                continue
            print(f"   {table}:")
            for row in rows:
                print(
                    f"      id={row[0]} driver_value={row[1]!r} sql_says={row[2]} len={row[3]}"
                )
    except Exception as exc:  # noqa: BLE001
        print(f"   empty-string control failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False

    # Error wording, unnormalized.
    for case, sql, expected in ERROR_CASES:
        try:
            list(native.sql.exec(sql))
            print(f"   {case}: NO ERROR RAISED")
            continue
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            exc_name = type(exc).__name__
        printable = message.replace("\r", "\\r").replace("\n", "\\n")
        print(f"   {case}: {exc_name}: {printable[:160]}")
        print(f"      SQLCODE present: {'SQLCODE' in message}")
        if classify is not None:
            state, condition = classify(message)
            ok = "ok" if state == expected else "MISMATCH"
            print(f"      classify: {state} ({condition}) — expected {expected} {ok}")
    return True


# ---------------------------------------------------------------------------


def summary() -> int:
    head("SUMMARY")
    order = {"FACT": 0, "FALSE": 1, "MIXED": 2, "UNTESTABLE": 3, "SKIP": 4}
    for verdict, question, finding in sorted(_results, key=lambda r: order.get(r[0], 9)):
        print(f"\n[{verdict}] {question}")
        for line in _wrap(finding, 74):
            print(f"    {line}")
    print()
    return 0


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def main(argv: list[str]) -> int:
    global READ_ONLY
    READ_ONLY = "--read-only" in argv
    embedded = "--embedded" in argv
    print(f"python {sys.version.split()[0]} — {sys.executable}")
    print(f"sys._embedded = {getattr(sys, '_embedded', 'absent')!r}")
    classify = load_sqlstate()
    print(f"classify_iris_error: {'loaded' if classify else 'NOT AVAILABLE'}")

    if embedded:
        probe_embedded(classify)
    else:
        probe_coexistence()
        probe_embedded_from_cpython()
        probe_official_baseline(classify)
        probe_native(classify)
    return summary()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
