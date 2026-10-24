# ADR-0002: `iris-embedded-python-wrapper` is not adopted as the driver layer

- **Status**: Accepted
- **Date**: 2026-09-20
- **Deciders**: Thomas Dyar
- **Relates to**: `specs/045-unified-iris-driver/spec.md` §Alternatives B,
  `specs/045-unified-iris-driver/spikes/probe_unified_driver-results.md`,
  `specs/051-unified-executor/`

## Context

`iris-embedded-python-wrapper` (PyPI, MIT, single maintainer) offers a DB-API facade over both the
embedded and native IRIS backends plus normalisation of empty-string and NULL handling. On its face
it is a candidate for exactly the job feature 051 is doing: one driver surface, two runtimes.

It was measured twice — once in the feature 045 spike, once again on 2026-09-20 in the
`iris-pgwire-db` container — because the diagnosis it would serve has come up repeatedly.

## Decision

Not adopted. The driver layer stays on `intersystems-irispython` alone, and the unification in
feature 051 is written in-house.

## Rationale, measured

1. **The novel capability is already in the official SDK.** Stock `intersystems-irispython` 5.4.0
   ships `iris.dbapi`: `hasattr(iris, 'dbapi')` is False, but `from iris import dbapi` works and
   `connect()` returns `iris.dbapi.IRISConnection`. The wrapper's native arm is a pass-through to
   this. The only arm that is not a pass-through is the embedded one, which this project already
   implements directly.
2. **It cannot be the single source of column metadata.** Measured: every `cursor.description` type
   code on its embedded path is `None`. A unified metadata decision on top of it still needs
   `sql_translator/column_types.py`, so it does not satisfy what would be the point of adopting it.
   051's R2 sharpens this: IRIS itself **does** report per-column ODBC types on the embedded side, via
   `%SQL.Statement._Prepare` → `._Metadata` → `.columns.GetAt(i).ODBCType`, matching the DBAPI
   adapter's codes exactly. So the `None`s are the wrapper's choice of route, not an IRIS limitation —
   adopting it would mean inheriting a gap that the platform does not have.
3. **Its embedded errors are harder to classify, not easier.** It raises the raw ObjectScript
   `%Status` `$LIST` with 28-30 non-printable bytes and no SQLCODE. Today's `iris.sql.exec` gives
   plain text. Classification survived the spike at 3/3 by wording match — luck, not contract.
4. **It collides with files the official SDK owns — with the SDK's cooperation, which makes it
   worse, not better.** Measured: version 0.6.1 and
   `intersystems-irispython` 5.4.0 both install `iris/__init__.py`, so installing it replaces the
   SDK's package initialiser and uninstalling it deletes the file. It also claims the top-level name
   `iris_ep`, which InterSystems itself ships at `/usr/irissys/lib/python/iris_ep.py`; when IRIS's
   copy wins, `iris.runtime` exists to `hasattr` and then raises
   `Cannot call an iris.package wrapper ... Given name was: runtime.get`.

   Re-measured on 2026-09-20 during 051's R1 probe, in this project's own `.venv`: SDK 5.3.2's
   `iris/__init__.py` **deliberately hands the module over** when the wrapper is present —

   ```python
   file_name_ep = os.path.join(os.path.dirname(current_dir), "iris_ep.py")
   if os.path.exists(file_name_ep):
       from iris_ep import *
       from iris_ep import __getattr__
   ```

   — so `iris.connect` resolves to `_iris_ep._runtime_facade...public_connect`, and the
   attribute-manufacturing `__getattr__` this ADR objects to is imported by the SDK itself rather than
   shadowing it. Two overlapping `intersystems_irispython` dist-infos (5.2.1 and 5.3.2) are installed
   alongside it. What the wrapper does **not** do, measured: it leaves `iris.dbapi` untouched and
   changes none of 29 observable behaviours. The collision is real; the behavioural risk is confined to
   the one name it replaces. That narrows the hazard without changing the decision — an SDK-sanctioned
   handoff is harder to reason about than a plain collision, not easier.

5. **Its embedded-local mode fails late rather than at configuration time.** Measured: it reports
   `embedded_available=True` and answers `SELECT $ZVERSION`, then fails DDL with
   `<UNIMPLEMENTED>ddtab+83^%qaqpsq` when `LD_LIBRARY_PATH` is not set before Python starts. This
   also dropped SQLSTATE classification to 2/3 by substituting the loader error for the IRIS error.
6. **The benefit that motivated looking at it does not exist here.** Embedded-local mode needs an
   IRIS installation on the host; measured, there is none, so it is unreachable from where pgwire
   runs and the `docker cp` workflow it would have removed stays either way.
7. **It would put a Development-Status-4-Beta, single-maintainer package on the critical path of
   every query**, and it invalidates feature 044's verification — every `pg_catalog` view,
   `PG_ARRAY`, boolean handling, binary array parameter and SQLSTATE probe was measured through the
   current driver.

## Consequences

Feature 051 is entirely in-house work with no upstream help, and the empty-string normalisation the
wrapper does well has to be written here (it is a requirement of 051, carried from 045 FR-010).

Do **not** install this package into `iris-pgwire-db` to try it. Its `iris` module manufactures
attributes for unknown names, which contaminates every subsequent measurement taken in that
container.

## When to reopen

All five of these must become true, each measured. This list is carried verbatim in intent from
`specs/045-unified-iris-driver/spec.md`:

1. Its embedded DB-API reports usable per-column type metadata, at minimum distinguishing boolean,
   integer and string with **zero rows** present.
2. Its embedded error surface carries a SQLCODE or a stable documented wording.
3. It stops claiming `iris/__init__.py` and `iris_ep`, or the project accepts a documented pinned
   install layout in which neither collision can occur.
4. Embedded-local mode fails loudly at configuration time when the loader path is wrong.
5. Feature 051 is complete first, so that adoption is measured as replacing a known-good layer with
   the differential corpus as the oracle.

Point 5 is not negotiable regardless of 1-4: a driver swap and a consolidation performed together
have no bisectable failure.
