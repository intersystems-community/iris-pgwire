"""Phase 0 probe R2 (follow-up) for feature 051.

The first pass showed ``iris.%SYS.Python.SQLResultSet`` exposes no metadata
accessor at all, and a ``%SQL.Statement`` attempt using ``prepare`` / ``%Metadata``
/ ``_GetColumnName`` returned None or raised. Those may have been the wrong API
names rather than a real absence, and R2 is load-bearing — it decides whether
FR-009 ("where the driver reports a usable type, use it") can ever apply to the
embedded adapter, or whether FR-010's fallback is the common case there.

This pass uses the ObjectScript names as the Python wrapper exposes them
(``_Prepare``, ``%Metadata`` via ``_Get``/attribute, ``%GetMetadata``) and reports
each attempt separately so a failure names which call failed.

    docker cp probe_r2b_embedded_metadata.py iris-pgwire-db:/tmp/
    docker exec iris-pgwire-db /usr/irissys/bin/irispython /tmp/probe_r2b_embedded_metadata.py
"""

import traceback

STMT = "SELECT 'x' AS s, 42 AS i, CAST(1 AS BIT) AS b"


def out(key, value):
    print(f"{key}: {value}")


def attempt(key, fn):
    try:
        out(key, repr(fn()))
        return True
    except Exception as e:  # noqa: BLE001 - the failure IS the measurement
        out(f"{key}_FAILED", repr(str(e)))
        return False


def main():
    import iris

    print("=== %SQL.Statement, ObjectScript names ===")
    stmt = iris.cls("%SQL.Statement")._New()
    out("stmt_type", type(stmt).__module__ + "." + type(stmt).__name__)
    # NOTE: dir() on an iris.%SQL.Statement proxy ABORTS the embedded Python
    # process — exit 1, no exception, no traceback, uncatchable. Measured on
    # IRIS 2026.1 CE. dir() on iris.%SYS.Python.SQLResultSet is fine, so the
    # abort is class-specific. Probe named attributes only, never dir().

    attempt("_Prepare", lambda: stmt._Prepare(STMT))

    # %SQL.StatementMetadata, if the prepare populated it.
    for name in ("_Metadata", "Metadata", "_GetMetadata", "GetMetadata"):
        attempt(f"stmt.{name}", lambda n=name: getattr(stmt, n))

    md = None
    for name in ("_Metadata", "Metadata"):
        try:
            candidate = getattr(stmt, name)
            if candidate is not None:
                md = candidate
                out("metadata_from", name)
                break
        except Exception:  # noqa: BLE001, S112
            continue

    if md is not None:
        out("md_type", type(md).__module__ + "." + type(md).__name__)
        for name in ("columnCount", "_columnCount", "columns", "_columns"):
            attempt(f"md.{name}", lambda n=name: getattr(md, n))
        # Per-column type, if columns is a collection.
        try:
            cols = md.columns
            for idx in (1, 2, 3):
                col = cols._GetAt(idx)
                out(
                    f"md.col{idx}",
                    repr(
                        (
                            getattr(col, "colName", None),
                            getattr(col, "ODBCType", None),
                            getattr(col, "clientType", None),
                            getattr(col, "typeClass", None),
                        )
                    ),
                )
        except Exception as e:  # noqa: BLE001
            out("md.columns_walk_FAILED", repr(str(e)))
            out("md.columns_walk_traceback", traceback.format_exc().replace("\n", " | "))

    print("=== %SQL.Statement execute, then the result set's own metadata ===")
    try:
        rs = stmt._Execute()
        out("rs_type", type(rs).__module__ + "." + type(rs).__name__)
        for name in ("_GetColumnCount", "GetColumnCount", "_GetColumnName", "_GetMetadata"):
            attempt(f"rs.{name}_exists", lambda n=name: hasattr(rs, n))
        attempt("rs._GetColumnCount()", lambda: rs._GetColumnCount())
        for idx in (1, 2, 3):
            attempt(f"rs._GetColumnName({idx})", lambda i=idx: rs._GetColumnName(i))
            attempt(f"rs._GetColumnType({idx})", lambda i=idx: rs._GetColumnType(i))
    except Exception as e:  # noqa: BLE001
        out("stmt_execute_FAILED", repr(str(e)))
        out("stmt_execute_traceback", traceback.format_exc().replace("\n", " | "))

    print("=== iris.sql.exec result: anything type-shaped at all? ===")
    rs2 = iris.sql.exec(STMT)
    out("rs2_type", type(rs2).__module__ + "." + type(rs2).__name__)
    attempt("rs2.ResultSet", lambda: rs2.ResultSet)
    try:
        inner = rs2.ResultSet
        if inner is not None:
            out("inner_type", type(inner).__module__ + "." + type(inner).__name__)
            for name in ("_GetColumnCount", "_GetColumnName", "_GetColumnType", "_GetMetadata"):
                attempt(f"inner.{name}_exists", lambda n=name: hasattr(inner, n))
            attempt("inner._GetColumnCount()", lambda: inner._GetColumnCount())
            for idx in (1, 2, 3):
                attempt(f"inner._GetColumnName({idx})", lambda i=idx: inner._GetColumnName(i))
                attempt(f"inner._GetColumnType({idx})", lambda i=idx: inner._GetColumnType(i))
    except Exception as e:  # noqa: BLE001
        out("inner_FAILED", repr(str(e)))

    # The dataframe route: pandas dtypes are a type report of a sort. Whether it
    # is usable for FR-009 is a separate question; whether it exists is not.
    attempt("rs2.dataframe_exists", lambda: hasattr(rs2, "dataframe"))
    try:
        df = rs2.dataframe()
        out("dataframe_dtypes", repr(dict(df.dtypes.astype(str))))
    except Exception as e:  # noqa: BLE001
        out("dataframe_FAILED", repr(str(e)))


if __name__ == "__main__":
    main()
