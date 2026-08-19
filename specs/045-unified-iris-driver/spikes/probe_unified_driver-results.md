# Spike results — `iris-embedded-python-wrapper` as a unified IRIS driver layer

**Date**: 2026-08-17
**Probe**: [`probe_unified_driver.py`](probe_unified_driver.py)
**Package under test**: `iris-embedded-python-wrapper` **0.6.1** (PyPI; MIT; author
`grongier <guillaume.rongier@intersystems.com>`; repo `grongierisc/iris-embedded-python-wrapper`;
classifier `Development Status :: 4 - Beta`; declares `Requires-Dist: intersystems-irispython>=5.0.0`)
**Against**: IRIS `2026.2 (Build 221U)`, container `iris-pgwire-db`, namespace `USER`, reached both
as `localhost:1972` from the host and as an embedded runtime inside the container
**Already installed on the host**: `intersystems-irispython` **5.4.0**, `iris/__init__.py` at
`/usr/local/lib/python3.11/dist-packages/iris/__init__.py`

Nothing below is mocked and nothing below is quoted from the package's description. Where a claim
could not be tested in this environment it is marked **UNTESTABLE**, not guessed.

The package **installed and imported without difficulty** — `pip download` reached PyPI through the
agent proxy, and the wheel is pure Python (69 kB). It was installed with
`pip install --no-deps --target <scratch>/f045libs` and put on `sys.path` by the probe only; nothing
was installed into the system environment or into the container's `site-packages`.

## How each half was run

```bash
# host: native/remote path + coexistence analysis
pip download --no-deps --dest <scratch>/dl iris-embedded-python-wrapper
pip install --no-deps --target <scratch>/f045libs \
    <scratch>/dl/iris_embedded_python_wrapper-0.6.1-py3-none-any.whl
F045_WRAPPER=<scratch>/f045libs python specs/045-unified-iris-driver/spikes/probe_unified_driver.py

# container: embedded path (the host has no IRIS installation)
docker cp <unpacked-wheel>/. iris-pgwire-db:/tmp/f045libs/
docker cp src/iris_pgwire/sql_translator/sqlstate.py iris-pgwire-db:/tmp/sqlstate_045.py
docker cp specs/045-unified-iris-driver/spikes/probe_unified_driver.py iris-pgwire-db:/tmp/probe_045.py
docker exec iris-pgwire-db /usr/irissys/bin/irispython /tmp/probe_045.py --embedded
docker exec iris-pgwire-db /usr/irissys/bin/irispython /tmp/probe_045.py --embedded --read-only
docker exec iris-pgwire-db bash -lc 'LD_LIBRARY_PATH=/usr/irissys/bin python3 /tmp/probe_045.py --embedded'
docker exec iris-pgwire-db bash -lc 'python3 /tmp/probe_045.py --embedded'
```

The running pgwire server on 5432, the proxy on 5433 and the `iris-pgwire-db` container were left
alone throughout; the container work is `docker cp` into `/tmp` plus `docker exec`, with no restart.

---

## 1. Coexistence — it **replaces** the official module, it does not sit beside it

Both distributions claim the *same installed file*. Read from the two `RECORD` files rather than by
installing one over a working environment:

```
wrapper  RECORD: iris/__init__.py,sha256=uRuhcBj46W9S5lg1urXlnYnlerHaX-tJGt9w360pdIg,489
official RECORD: iris/__init__.py,sha256=VeqAIwJ0pzZ6bCdsEX6NjnYGmaXXBsSZx1rE4AOdGbo,360
```

Probe output:

```
-- file paths each distribution claims
   BOTH distributions install: iris/__init__.py
```

**A plain `pip install iris-embedded-python-wrapper` into this environment overwrites
`intersystems_irispython`'s package initialiser, and `pip uninstall` of the wrapper then deletes
it** — leaving the official distribution present but broken. The wrapper's own `iris/__init__.py`
compensates at runtime by appending the official package directory to `__path__`:

```
   import iris -> <scratch>/f045libs/iris/__init__.py
   iris.__path__ = ['<scratch>/f045libs/iris', '/usr/local/lib/python3.11/dist-packages/iris']
```

so `iris.dbapi` still resolves to the official driver's submodule. The mechanism works. It is still
a replacement of a file owned by another distribution, and its correctness depends on
`importlib.metadata` finding `intersystems-irispython` at import time
(`iris_utils/_driver_loader.py::extend_official_driver_path`).

There is a **second name collision, inside IRIS itself**. The wrapper ships a top-level `iris_ep.py`;
InterSystems ships `/usr/irissys/lib/python/iris_ep.py` (header: *"Copyright (c) 2021 by InterSystems
Corporation … Confidential, unpublished property of InterSystems"*), and IRIS's own
`iris/__init__.py` does `from iris_ep import *`. Measured in the container:

```
-- module names the wrapper claims, and what else answers to them
   iris                   wrapper=/tmp/f045libs/iris/__init__.py
                          ALSO   =/usr/irissys/lib/python/iris/__init__.py
   iris_ep                wrapper=/tmp/f045libs/iris_ep.py
                          ALSO   =/usr/irissys/lib/python/iris_ep.py
```

Which one wins is decided by `sys.path`/`sys.modules` order. When IRIS's `iris_ep` was already in
`sys.modules` (because IRIS's `iris` had been imported first), importing the wrapper's `iris`
produced a module that **looks** complete and fails on use — `hasattr(iris, "runtime")` is `True`
because IRIS's `__getattr__` manufactures an ObjectScript package wrapper for any name:

```
   iris.runtime unavailable: Cannot call an iris.package wrapper. If you were trying to call a
   method of an ObjectScript class, check that the name of the wrapper is correct.
   Given name was: runtime.get
   connect failed: NameError: … Given name was: dbapi.connect
```

The probe now purges all six of the wrapper's top-level names from `sys.modules` before importing,
which makes it work reliably. Recording the failure because a deployment cannot purge `sys.modules`
before IRIS starts Python, and the failure signature is a `NameError` about ObjectScript, not
anything that names the real cause.

---

## 2. Does `iris.dbapi` execute SQL against `localhost:1972`? Yes — as a pass-through

```
-- iris.dbapi.connect(mode='native')
   connection class: iris.dbapi.IRISConnection
   SELECT 1 -> ((1,),)
```

`mode="native"` returns **the official driver's own connection object**. The facade is a dispatcher,
not a layer, on this path: the object pgwire's `DBAPIExecutor` would talk to is byte-for-byte the one
it talks to today. Confirmed by running every subsequent measurement twice — once through the facade
and once through `iris.dbapi` directly, with identical results in all cases.

That is why the probe includes an explicit official-driver baseline. Without it, a good facade result
proves nothing about the facade.

---

## 3. The T011h question — the most valuable measurement here

`specs/044-catalog-as-views/tasks.md` T011h records that on the `dbapi` backend the *declared* column
type depended on the row count, because `DBAPIExecutor` refined types from the first row's Python
value and a statement Describe (dummy parameters, zero matches) has no first row.

The probe runs one statement twice — once with a parameter that matches, once with one that matches
nothing — and compares `cursor.description`.

### Native / remote path (official driver, and the facade over it): **stable, and informative**

```
-- T011h — does the declared type depend on the row count? [official driver]
   matching parameter -> 10 row(s)
      table_name                 type_code=12
      namespace                  type_code=12
      is_partition               type_code=-7
      has_row_level_security     type_code=4
      description                type_code=12
      first row: ('customer', 'public', False, 0, None)
      py types : ['str', 'str', 'bool', 'int', 'NoneType']
   non-matching parameter -> 0 row(s)
      table_name                 type_code=12
      namespace                  type_code=12
      is_partition               type_code=-7
      has_row_level_security     type_code=4
      description                type_code=12
   verdict: description is STABLE across {'matching': 10, 'non-matching': 0} rows
```

Identical byte-for-byte across 10 rows and 0 rows, on both the official driver and the facade. The
codes are ODBC types — `12` `SQL_VARCHAR`, `-7` `SQL_BIT`, `4` `SQL_INTEGER` — so the driver
distinguishes a boolean from an integer from a string, **and does so without a row**. It even returns
a Python `bool` for the `CAST(… AS BIT)` column.

### The finding that follows, and it is the important one

T011h's recorded diagnosis says *"IRIS DBAPI reports type_code 4, hence 1043 for everything"*. That is
not what this instance reports. The codes are distinct; pgwire throws them away one function earlier:

```
-- what DBAPIExecutor._map_dbapi_type_to_oid makes of those type codes
   table_name                 type_code=12     -> PostgreSQL OID 1043
   namespace                  type_code=12     -> PostgreSQL OID 1043
   is_partition               type_code=-7     -> PostgreSQL OID 1043
   has_row_level_security     type_code=4      -> PostgreSQL OID 1043
   description                type_code=12     -> PostgreSQL OID 1043
```

`src/iris_pgwire/dbapi_executor.py:1241`:

```python
def _map_dbapi_type_to_oid(self, dbapi_type: Any) -> int:
    """Map DBAPI type to PostgreSQL OID."""
    type_str = str(dbapi_type).upper()
    if "INT" in type_str:
        return 23
    ...
    return 1043
```

The argument is a numeric ODBC code. `str(12).upper()` is `"12"`; it contains none of `INT`, `CHAR`,
`DATE`, `TIME`, so every column falls through to the varchar default. Verified directly, with no
server in the path:

```
12 -> 1043   -7 -> 1043   4 -> 1043   -5 -> 1043   8 -> 1043   93 -> 1043   2 -> 1043   1 -> 1043
```

So the row-count-dependent behaviour T011h fixed was a *second-order* effect: the value-based
refinement existed to repair metadata that the driver had already supplied correctly and this one
function discarded. **This is fixable in-house in one function, with no new dependency.**

### Embedded path (the facade over `%SQL.Statement`): stable, and useless

```
-- T011h — does the declared type depend on the row count? [embedded facade]
   matching parameter -> 10 row(s)
      table_name                 type_code=None
      namespace                  type_code=None
      is_partition               type_code=None
      has_row_level_security     type_code=None
      description                type_code=None
      first row: ('customer', 'public', 0, 0, None)
      py types : ['str', 'str', 'int', 'int', 'NoneType']
   non-matching parameter -> 0 row(s)
      … type_code=None for all five …
   verdict: description is STABLE across {'matching': 10, 'non-matching': 0} rows
```

Stable, but **vacuously**: the facade reports no column type at all on the embedded backend, and no
`bool` for the BIT column either. **The facade cannot be the single place that decides column
metadata**, because on one of its two backends it has no metadata to give. Anything unified on top of
it would still need `sql_translator/column_types.py` for the embedded case — which is the code
044 already wrote.

### A related measurement, about our own embedded path

```
   iris.sql.exec result class: <class 'iris.%SYS.Python.SQLResultSet'>
   has _meta attribute: False (None)
```

`IRISExecutor._materialize_embedded_result` (`iris_executor.py:2366`) starts with
`meta = getattr(result, "_meta", None)` and builds the whole column list from it. On IRIS 2026.2
that attribute does not exist, so the branch is dead and metadata comes from the fallbacks — a
separate discovery query, or the row values. Not verified against other IRIS versions; the attribute
may exist on some, which would explain why the code is written that way.

---

## 4. The T027 question — the wording is **not** normalized

`classify_iris_error` from `src/iris_pgwire/sql_translator/sqlstate.py` was loaded unchanged and run
against each raw message.

### Native / remote (official driver and facade — identical): 3/3, SQLCODE in 3/3

```
   missing table: ProgrammingError
      message : <SQL ERROR>; Details: [SQLCODE: <-30>:<Table or view not found>]\r\n[Location:
                <Prepare>]\r\n[%msg: < Table 'SQLUSER.NO_SUCH_TABLE_F045' not found>]
      classify: 42P01 (undefined_table) — expected 42P01 ok
   missing column: ProgrammingError
      message : <SQL ERROR>; Details: [SQLCODE: <-29>:<Field not found in the applicable tables>]…
      classify: 42703 (undefined_column) — expected 42703 ok
   internal failure: DatabaseError
      message : <SQL ERROR>; Details: [SQLCODE: <-400>:<Fatal error occurred>]\r\n[Location:
                <ServerLoop - Query Open()>]\r\n[%msg: <Unexpected error occurred:  <LIST>…>]
      classify: XX000 (internal_error) — expected XX000 ok
```

### Embedded control, `iris.sql.exec` (no wrapper): 3/3, SQLCODE in 0/3

```
   missing table: SQLError:  Table 'SQLUSER.NO_SUCH_TABLE_F045' not found
      SQLCODE present: False
      classify: 42P01 (undefined_table) — expected 42P01 ok
   missing column: SQLError:  Field 'NO_SUCH_COL_F045' not found in the applicable tables^ SELECT …
      SQLCODE present: False
      classify: 42703 (undefined_column) — expected 42703 ok
   internal failure: SQLError: Unexpected error occurred:  <LIST>%QRS0o+20^%sqlcq.USER.cls267.1
      SQLCODE present: False
      classify: XX000 (internal_error) — expected XX000 ok
```

This reproduces T027 exactly: the two backends word the same three failures completely differently,
and only one carries a SQLCODE.

### Embedded through the facade: **worse, not normalized**

```
   missing table: DatabaseError
      message : 0 ß¤â/ Table 'SQLUSER.NO_SUCH_TABLE_F045' not found¡USER#e^OnAsStatus+1^%Exception.
                SQL.1^1/e^AsStatus+1^%Exception.AbstractException.1^1"e^%Prepare+10^%SQL.Statement…
      SQLCODE present: False; non-printable chars: 28
      classify: 42P01 (undefined_table) — expected 42P01 ok
   missing column: DatabaseError
      message : 0  ¤ã\ Field 'NO_SUCH_COL_F045' not found in the applicable tables^ SELECT …
      SQLCODE present: False; non-printable chars: 30
      classify: 42703 (undefined_column) — expected 42703 ok
   internal failure: DatabaseError
      message : SQLCODE -400: Unexpected error occurred:  <LIST>%QRS0o+20^%sqlcq.USER.cls267.1
      SQLCODE present: True; non-printable chars: 0
      classify: XX000 (internal_error) — expected XX000 ok
```

`_iris_ep/_dbapi_embedded.py:1239` does `raise DatabaseError(str(prepare_status))` — the raw
ObjectScript `%Status` `$LIST`, control bytes included, 28–30 non-printable characters. It has PEP 249
exception *classes* (`ProgrammingError` vs `DatabaseError`), but the message text is the serialised
status, not a normalized string.

`classify_iris_error` still scores **3/3**, because the human-readable fragment survives inside the
blob and the module matches on wording as well as SQLCODE. That is luck, not design, and it is the
one thing here that argues *for* keeping our own classifier whatever driver sits underneath.

**Verdict: error normalization is not delivered.** T027 would still need
`sql_translator/sqlstate.py`, unchanged, on both backends.

---

## 5. The empty-string question — the facade's one clear, verified win

IRIS spells the empty string `$CHAR(0)`; `catalog/functions.py:151` hand-rolls that inside
`PG_ARRAY` (`if value = "" { set value = $char(0) }`).

Four cases were written into three tables — one written by the native driver, one by
`iris.sql.exec`, one by the facade — and each table read back by each of the three readers. SQL's own
verdict was selected alongside the value so there is no ambiguity about what is stored:

```
-- what SQL itself says about the same rows
   SQLUser.f045_null_native:
      id=1 driver_value='\x00' sql_says=NOTNULL len=0     # literal ''
      id=2 driver_value=''     sql_says=ISNULL  len=0     # literal NULL
      id=3 driver_value='\x00' sql_says=NOTNULL len=0     # bound ''
      id=4 driver_value=''     sql_says=ISNULL  len=0     # bound None
```

(That reading is `iris.sql.exec`'s. `sql_says` is IRIS SQL's own `CASE WHEN s IS NULL`.)

Same stored rows, three readers:

| reader | empty string | SQL NULL |
|---|---|---|
| official native driver | `''` | `None` |
| facade, `mode="native"` | `''` | `None` |
| **`iris.sql.exec`** (what `IRISExecutor` uses) | **`'\x00'`** | **`''`** |
| **facade, `mode="embedded"`** | **`''`** | **`None`** |

The embedded API's convention is *inverted relative to Python's*: `''` means SQL NULL, and a real
empty string arrives as a one-byte NUL. `IRISExecutor._normalize_iris_null` (`iris_executor.py:256`)
handles half of that — it maps `""` to `None`, which is right for NULL — and leaves `'\x00'`
untouched. **On the embedded backend a genuine empty string therefore appears to be a one-character
string containing NUL.** Measured at the driver level; **not** verified end-to-end over the wire,
because pgwire's embedded backend only runs inside the container and the running server was not to be
restarted. Stated as a suspicion with evidence, not as a confirmed wire-level defect.

The facade fixes this on the read side for data written either way, and round-trips its own writes
exactly:

```
-- empty string vs NULL, read by embedded facade
   written by native/remote driver (SQLUser.f045_null_native):
      id=1 (literal ''   ) -> ''      id=2 (literal NULL ) -> None
      id=3 (bound ''     ) -> ''      id=4 (bound None   ) -> None
   written by embedded iris.sql.exec (SQLUser.f045_null_embedded):
      id=1 -> ''   id=2 -> None   id=3 -> ''   id=4 -> None
   written by the wrapper's embedded facade (SQLUser.f045_null_facade):
      id=1 -> ''   id=2 -> None   id=3 -> ''   id=4 -> None
```

**The "normalizes SQL NULL and empty strings" claim is verified**, on the embedded path, which is the
only path where it was needed.

### One anomaly, recorded because it is unexplained

Reading the table **in the same process that had just written it** through `iris.sql.exec` gave
different values than reading it from a fresh process:

```
same process as the write:   id=3 (bound '') -> ''    id=4 (bound None) -> '7@%SYS.Python'
fresh process, same rows:    id=3            -> '\x00'  id=4           -> ''
```

`'7@%SYS.Python'` is the marker `_normalize_iris_null`'s docstring already names ("Prepared
statements: Returns '.*@%SYS.Python' for NULL parameters"). IRIS SQL reports both rows as they should
be, so nothing is wrong in the database. **I could not determine the mechanism** and am not calling it
a bug. `--read-only` exists on the probe so the fresh-process reading can be reproduced without a
rewrite in between.

---

## 6. Embedded mode from an ordinary `python3`

### On this host: **UNTESTABLE**, and it would not help

```
   IRISINSTALLDIR = <unset>
   /usr/irissys: absent
   /opt/iris: absent
   /opt/intersystems/iris: absent
   /InterSystems/IRIS: absent
```

There is **no IRIS installation on the host at all** — IRIS runs in the `iris-pgwire-db` container.
`iris.connect(path=…)` needs an install directory with `bin` and `lib/python` on the *same machine*
as the Python process, so the claim cannot be tested from the host, and **it cannot remove the need to
`docker cp` a probe into the container**: the embedded runtime is only reachable where IRIS is
installed, which is inside the container either way. The hoped-for benefit does not exist in this
deployment shape.

### Inside the container: **verified, with a sharp caveat**

Plain `python3` (3.12.3), not `irispython`:

```
   state=embedded-local mode=auto embedded_available=True
   ordinary CPython -> iris.dbapi.connect(path='/usr/irissys')
   connection class: _iris_ep._dbapi_embedded._EmbeddedConnection
   $ZVERSION -> IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.2 (Build 221U) …
```

It works. Also confirmed, from the same run: before the wrapper is on `sys.path`, plain `python3`
reports `[SKIP] embedded control — No module named 'iris'`. The premise — that the embedded module is
not importable from an ordinary `python3` — is real, and the wrapper does solve it.

**The caveat is a partial-functionality failure, not a clean one.** Without `LD_LIBRARY_PATH`
including `/usr/irissys/bin`, the runtime still reports `embedded_available=True`, `connect()` still
succeeds, and `SELECT $ZVERSION` still returns — and then:

```
   missing column: DatabaseError
      message : 0 ¸¤pþ!<UNIMPLEMENTED>ddtab+83^%qaqpsq…
      classify: 42000 (syntax_error_or_access_rule_violation) — expected 42703 MISMATCH
   writing SQLUser.f045_null_facade failed: DatabaseError: <UNIMPLEMENTED>ddtab+83^%qaqpsq
   writing SQLUser.f045_null_embedded failed: SQLCODE -400: ERROR #5002: ObjectScript error:
      <UNIMPLEMENTED>DeCollateCode+3^%ocsCacheSQLFiler
```

DDL and some prepare paths fail with `<UNIMPLEMENTED>` — the symptom the package's own troubleshooting
section names — and, worse, the IRIS error is *replaced* by the loader failure, so
`classify_iris_error` drops to 2/3 through no fault of its own. An environment that is 90% configured
reports itself healthy and then corrupts error reporting on the query path. In a query-path dependency
that is a serious operational risk.

---

## Summary table

| Claim | Verdict | Evidence |
|---|---|---|
| Installs and imports alongside `intersystems-irispython` 5.4.0 | **partly** | imports fine; **both distributions install `iris/__init__.py`**, so a normal install replaces the official file |
| `iris.dbapi` executes SQL over 1972 | **yes** | returns `iris.dbapi.IRISConnection` — the official driver, pass-through |
| `iris.runtime` model (`auto`/`embedded`/`native`) exists | **yes** | `state=unavailable` on the host, `embedded-local` in the container |
| **T011h**: column types independent of row count | **native yes / embedded no** | native `12,-7,4` identical at 10 rows and 0 rows; embedded reports `None` for every column |
| …and is that the facade's contribution? | **no** | identical on the bare official driver; the real defect is `_map_dbapi_type_to_oid` collapsing every ODBC code to 1043 |
| **T027**: error text normalized across backends | **no** | native = official wording with SQLCODE; embedded = raw `%Status` blob, 28–30 control bytes, no SQLCODE |
| `classify_iris_error` still correct as-is | **yes, 3/3 on all three paths** | and 2/3 only when a loader misconfiguration replaces the IRIS error |
| Empty string vs SQL NULL normalized | **yes, on the embedded path** | `''`/`None` versus `iris.sql.exec`'s `'\x00'`/`''`; round-trips its own writes |
| Embedded mode from ordinary `python3` | **untestable on host; verified in container** | no IRIS installation on the host; works in the container, but needs `LD_LIBRARY_PATH` set before Python starts or DDL fails with `<UNIMPLEMENTED>` |
| Removes the need to `docker cp` probes into the container | **no** | the embedded runtime lives where IRIS is installed, which is the container |

## What this means for feature 045

1. **The prize — one place decides column metadata — is not delivered by this package.** On the
   embedded backend it supplies no column types at all, so a unified layer built on it still needs
   `sql_translator/column_types.py`. The T011h property already holds on the native driver, and held
   before the wrapper existed.
2. **Two of the three defects that motivated 045 are ours, not the driver's.**
   `_map_dbapi_type_to_oid` discards correct metadata in five lines; the three materialisers are
   three copies of our own code. Both are fixable behind one internal interface with no new
   dependency.
3. **The one thing the package does better than we do is the embedded NULL/empty-string boundary** —
   verified, and a real fidelity gap on our side. That is a bounded piece of behaviour, and it is
   also implementable in-house now that the exact convention is measured (`'\x00'` = empty string,
   `''` = SQL NULL, on read).
4. **The costs are real and measured**: a file collision with the official distribution, a module-name
   collision with an InterSystems-owned module inside IRIS whose failure signature names neither
   cause, error text made *harder* to classify on the embedded path, and an embedded-local mode that
   reports itself available while DDL fails.

Recommendation and the evidence bar for revisiting it are in [`../spec.md`](../spec.md) §Alternatives.
