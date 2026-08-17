# T011a research: making `col = ANY($n)` work through the extended protocol

**Status**: implemented; recommendation revised once (§5), then re-checked against the
built-in alternatives (§6).
**Date**: 2026-08-16, revised 2026-08-17 · **Instance**: IRIS 2026.2 CE in `iris-pgwire-db`, both backends.

## Evidence standard

Every claim below is either (a) a measurement taken on the running instance, with the probe that
produced it named, or (b) a quotation from InterSystems documentation, with its provenance stated.
Nothing here is inferred from how the construct "should" behave.

`docs.intersystems.com` is blocked by this environment's egress proxy — `WebFetch` returns
`EGRESS_BLOCKED`. The documentation quoted below therefore comes from search-result extracts of the
official `%INLIST` and `IN` reference pages, not from the pages themselves. Wherever a documented
claim mattered to the decision it was **re-verified by measurement**, and both are shown. One
documented restriction turned out not to apply to us at all; see "The sargability footnote".

Probes, all under `specs/044-catalog-as-views/spikes/`:

| Probe | Runs where | Answers |
|---|---|---|
| `SpikeT011a.cls` | ObjectScript, `%SQL.Statement` | preparability |
| `probe_inlist_python.py` | embedded **and** DBAPI | can Python bind a `$LIST`? |
| `probe_inlist_semantics.py` | DBAPI | NULL/negation/join semantics, cached-query reuse, encoder parity |

---

## 1. What is actually broken

The task list recorded one defect. There are **two**, independent, and either alone is fatal.

### 1a. The statement cannot be prepared

`protocol.py` answers `Describe(statement)` by running the query with placeholder values
(`_build_metadata_dummy_params`, all `None`) to discover the row description. IRIS never gets as far
as the values:

```
P1  baseline: = ANY(?)
  SQL: SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = ANY(?)
  PREPARE FAILED: ERROR #5540: SQLCODE: -1 Message:  SELECT expected, ? found
                  ^ SELECT nspname FROM pg_catalog . pg_namespace WHERE nspname = ANY ( ?
```

IRIS parses `ANY` only as the quantifier in front of a subquery, so `ANY(?)` is a syntax error
before binding is reached. Substituting values at Execute — which is what
`sql_translator/array_params.py` does today — cannot help, because the failure happens earlier.

### 1b. The array never arrives as an array

`expand_array_params` only fires for a value that `isinstance(..., (list, tuple, set))`. Nothing
ever produces one:

* **text format** (`handle_bind_message`, `protocol.py:2784`) — the parameter is `param_data.decode("utf-8")`,
  tried as `int`, then `float`, then kept as a string. A `text[]` arrives as the literal string
  `{public,pg_catalog}`.
* **binary format** (`_decode_array_binary_parameter`, `protocol.py:3776`) — decodes into a pgvector
  literal string such as `"[1.0,2.0]"`. That routine exists for vectors, and returns `str`.

So even with 1a fixed, the expansion would sit there never matching. This is why the unit tests for
`expand_array_params` pass while `prisma db pull` still fails: the tests hand it a Python list,
which the protocol layer never constructs.

---

## 2. The options

### Option A — inline the values as literals at Execute (what is implemented today)

Rewrite `= ANY($1)` to `IN ('a','b')` using the bound values.

* **Fails on 1a.** Describe still sees `= ANY(?)`, because at Describe there is no array to inline.
  The prepare errors, `send_no_data()` is returned, and the client is told nothing about the result
  shape.
* Also mints a new cached query per distinct element count — measured below.

### Option B — prepare `IN (?)`, re-expand to `IN (?,?,…)` at Execute

Describe would succeed: `IN (?)` prepares (probe P4, `PREPARE OK`).

* The parameter count changes between Describe and Execute. The client was told one parameter and
  binds one; we then execute a statement wanting *n*. The row description happens to stay valid, so
  it can be made to work, but the described statement and the executed statement are different
  statements, and every distinct *n* is a distinct cached query.
* Nothing about it is cheaper than option C.

### Option C — rewrite to `%INLIST ?` and bind the array as an IRIS `$LIST` ✅

`%INLIST` is IRIS's own answer to this exact problem. The official reference says:

> The optional %INLIST SIZE clause provides the integer nn, which specifies an order-of-magnitude
> estimate of the number of list elements in list. […] Because the same cached query is used
> regardless of the number of elements in list, specifying SIZE allows you to create a cached query
> optimized for the anticipated approximate number of elements in list.

> For Dynamic SQL, you can supply the %INLIST predicate values as a single host variable; you must
> supply the IN predicate values as individual host variables. %INLIST allows you to vary the number
> of values to match without creating a separate cached query.

One placeholder in the source, one placeholder in the target. The parameter count the client is told
at Describe is the count it binds at Bind — option B's hazard disappears rather than being managed.

---

## 3. Measurements

### Preparability (`SpikeT011a.cls`)

| Shape | Prepare | `parameterCount` |
|---|---|---|
| `= ANY(?)` | ❌ SQLCODE -1, "SELECT expected, ? found" | — |
| `%INLIST ?` | ✅ | 1 |
| `%INLIST ? SIZE ((10))` | ✅ | 1 |
| `IN (?)` | ✅ | 1 |
| `= ?` | ✅ | 1 |

Executed with bound `$LIST`s: one value → 1 row, two values → 2 rows, no-match → 0 rows, empty list
→ 0 rows. A plain (non-`$LIST`) string → SQLCODE -400, matching the documented requirement that
"if the match expression is not in %List format, %INLIST generates an SQLCODE -400 error".

### Binding a `$LIST` from Python (`probe_inlist_python.py`)

Neither Python path can hand IRIS a list object:

| Value | Embedded (`iris.sql`) | DBAPI (`iris.dbapi`) |
|---|---|---|
| `["public","pg_catalog"]` | **0 rows, no error** | `ProgrammingError: Unsupported argument type` |
| `("public","pg_catalog")` | **0 rows, no error** | `ProgrammingError: Unsupported argument type` |
| `iris.IRISList` instance | unavailable — resolves to an ObjectScript package wrapper and raises | `ProgrammingError: Unsupported argument type` |
| raw `$LIST` **bytes** | ✅ correct rows | ✅ correct rows |
| `$LISTFROMSTRING(?, ',')` | ✅ correct rows | ✅ correct rows |

Two things follow. First, raw bytes are the only value both backends accept, so pgwire has to encode
the `$LIST` itself — hence `sql_translator/iris_list.py`. Second, note the embedded row: passing a
Python list returns **zero rows and no error**. That is the silent-empty failure mode this whole
feature exists to remove, so the encoder must never be bypassed.

`$LISTFROMSTRING` works but is rejected: it splits on a delimiter, and catalog values are arbitrary
strings that may contain any delimiter chosen.

### Encoder parity

`encode_iris_list` is checked byte-for-byte against the driver's own `IRISList.getBuffer()` — the
authoritative encoder, from the package pgwire already depends on. **349 cases, 0 mismatches**:
every header-width boundary (253/254/255/65534/65535/70000-byte elements), both integer signs at
every width boundary, `2**63` (where the driver switches to decimal text), floats, `None`, booleans,
latin-1 vs UTF-16 strings, and 230 random cases.

Four encoding rules were found by reading the driver's output, not by guessing, and each had already
produced a wrong answer before it was found:

1. a one-byte length header counts itself; the 2- and 4-byte forms do not;
2. positive integers use minimal **signed** bytes, so 128 is `\x80\x00`, not `\x80`;
3. negative integers drop sign-extension bytes — -256 is `\x00`, -1 is empty;
4. beyond signed 64-bit the driver stores decimal text.

### Semantics against `= ANY` (`probe_inlist_semantics.py`, and a table carrying a NULL row)

| PostgreSQL | IRIS | Rows returned | Agrees |
|---|---|---|---|
| `k = ANY('{a}')` | `k %INLIST $LB("a")` | `a` (NULL row excluded) | ✅ |
| `k = ANY('{}')` | `k %INLIST NULL` | none | ✅ |
| `k = ANY('{NULL}')` | `k %INLIST $LB(NULL)` | none | ✅ |
| `k = ANY('{a,NULL}')` | `k %INLIST $LB("a",NULL)` | `a` only | ✅ |
| `NOT (k = ANY('{a}'))` | `NOT (k %INLIST $LB("a"))` | `b` only, NULL row excluded | ✅ |
| `oid = ANY('{2200}')` | `oid %INLIST $LB(2200)` | the matching row | ✅ |

The documented restriction — "Neither %INLIST nor NOT %INLIST can be used to return NULL fields" — is
visible in rows 1 and 5 and is *the same answer PostgreSQL gives*, because `NULL = anything` is
unknown there too. It is a match, not a divergence.

The empty array needs care. An empty `$LIST` is zero bytes, and binding `b""` over the DBAPI fails:

```
SQLCODE -400 … <LIST>first+4^%sqlcq.USER.cls99.1
```

Binding `None` instead returns zero rows cleanly on both backends, which is the right answer for
`= ANY('{}')`, and is the same value Describe already passes for its dummy parameter — so it is one
behaviour, not two.

### Cached-query reuse — the documented advantage, measured

Four executions each with 1, 2, 3 and 4 values, counting rows in
`INFORMATION_SCHEMA.STATEMENTS` for statements touching `pg_namespace`:

| Approach | Cached queries added |
|---|---|
| `%INLIST ?` with a bound `$LIST` | **0** |
| inlined `IN ('a','b',…)` (option A) | **4** |

An ORM introspecting *n* tables issues these with many different list lengths. Option A turns each
length into a distinct cached query; `%INLIST` reuses one.

### The sargability footnote

The reference page warns:

> A WHERE clause with the format `WHERE ? %INLIST ListOfString`, where `?` is a literal value and
> `ListOfString` is the name of a column in the table that stores a %List of strings, is not
> sargable.

That is the **reverse orientation** — literal on the left, list-valued *column* on the right. What we
emit is `column %INLIST ?`, the other way round. Measured on a 5 000-row table with an index on `k`:

```
col %INLIST ?              Read index map SQLUser.SargProbe.SargProbeK, looping on %SQLUPPER(k)
                           (with a given set of values) and ID.
col IN ('k1','k2')         Read index map SQLUser.SargProbe.SargProbeK, looping on %SQLUPPER(k)
                           (with a given set of values) and ID.
```

Identical plans. The warning does not apply to our orientation.

Cost, same table, as `SIZE` varies:

| Shape | Cost | Access |
|---|---|---|
| `= ?` | 83 800 | index |
| `%INLIST ? SIZE ((1))` | 83 800 | index |
| `%INLIST ? SIZE ((2))` | 167 400 | index |
| `IN ('k1','k2')` | 167 400 | index |
| `%INLIST ?` (no SIZE) | 418 200 | index |
| `%INLIST ? SIZE ((10))` | 649 600 | index |
| `%INLIST ? SIZE ((1000))` | 1 013 600 | full scan |

`SIZE ((2))` costs exactly what `IN` with two literals costs, so the planner treats them the same
once it knows the count. Without `SIZE` the planner assumes about five elements. That is the right
default for us and **`SIZE` is deliberately not emitted**: it is part of the statement text, so
varying it per call would recreate precisely the cached-query multiplicity the construct exists to
avoid. Bucketing by order of magnitude is available later if a workload needs it.

---

## 4. Recommendation

**Adopt option C.** Concretely:

1. **Translate**, uniformly and before preparation, `expr = ANY($n)` → `expr %INLIST ?`, and
   `expr <> ALL($n)` / `NOT (expr = ANY($n))` → `NOT (expr %INLIST ?)`. Because it happens at
   translation time, Describe and Execute see the same statement and the parameter count is
   preserved — the ParameterDescription sent to the client stays true.
2. **Decode** PostgreSQL array parameters at Bind into Python lists — text `{a,b}` with its quoting
   and escaping rules, and the binary array format for element types other than the vector case that
   already has an owner.
3. **Encode** the bound list as `$LIST` bytes with `encode_iris_list`; bind `None` for an empty
   array.
4. **Keep** the literal-inlining path for the simple-query protocol, where the array arrives already
   written into the SQL text and there is no parameter to bind.

Why not the alternatives, in one line each: option A cannot survive Describe, and option B can only
be made to work by telling the client about a statement other than the one that runs.

### Residual risks

* **Only the `= ANY` / `<> ALL` spellings are handled.** `ANY(SELECT …)` is a different construct and
  must be left alone — the rewrite has to require a parameter or an array literal inside the
  parentheses.
* **Array element typing.** A `$LIST` element encoded as a string compares equal to a numeric column
  in IRIS (measured: `oid %INLIST $LB('2200')` matched `oid = 2200`), so a mistyped element degrades
  quietly rather than erroring. Decode text arrays to the element type implied by the parameter OID
  where one was given.
* **Nested and multidimensional arrays** have no `%INLIST` equivalent. They should error rather than
  flatten.


---

## 5. Revision, 2026-08-17: the `$LIST` encoder is gone

The first implementation of option C encoded the `$LIST` byte format in Python
(`sql_translator/iris_list.py`). That format is undocumented. It was derived by
calling `IRISList.getBuffer()` — a public method on a package pgwire already
depends on — and reading the bytes it returned for around thirty inputs. No
decompilation, but the distinction does not matter much: it is a private layout
inferred from samples, and four of its rules only surfaced because a sample
disagreed with a guess.

Two facts settled it:

* **The safety net was not running.** The parity tests were written to compare
  against `IRISList.getBuffer()` on every run. In the unit suite all 48 of them
  **skipped** — `iris.IRISList unavailable` — so the guarantee held only in the
  ad-hoc script that first produced it.
* **There is a supported route, and it is cheap.** `CREATE FUNCTION …
  LANGUAGE OBJECTSCRIPT` is ordinary SQL DDL. A function that takes the
  elements as one plain string and assembles the list with `$LISTBUILD` costs
  **4.6 µs per query** (measured, 1000 executions each, against a budget of
  5 ms) and uses nothing undocumented.

So the shape is now:

    col = ANY($1)   ->   col %INLIST PGWire.PG_ARRAY($1)

with the parameter carrying `2|6:public10:pg_catalog` — a count, then each
element length-prefixed. Length-prefixed rather than delimited so no value needs
escaping and none can be misread, which is what rules out `$LISTFROMSTRING`. The
count lets `PG_ARRAY` reject a desynchronised parse instead of returning
plausible wrong rows.

`sql_translator/iris_list.py` and its tests are deleted. Nothing in pgwire
reproduces an IRIS-internal format any more.

### What this uncovered

**The functions were never installed by anything.** `PGWire.Catalog.cls` had to
be loaded by hand with `$SYSTEM.OBJ.Load`, and no code did it. Feature 044
shipped with every catalog view depending on `PGWire.PG_OID` — so it worked on
this instance, where the class had been loaded manually during development, and
would have failed at startup on any fresh one. Installing the functions over SQL
removes the manual step and works on both backends, where loading a class file
needs the source on the *server's* filesystem.

**Translating our own DDL corrupted it.** Two rules for writing ObjectScript
inside SQL DDL, each of which cost a debugging round:

| | Symptom |
|---|---|
| `for i = 1:1:4` | The SQL parser reads `:1` as a host variable — "Parameter Name error, First value cannot be a digit". Use `while`. |
| `RETURNS %Library.List` | Uppercased in transit to `%LIBRARY.LIST`; class names are case-sensitive. Use a SQL type name. |

And the pipeline uppercased the function *bodies* too, turning
`$SYSTEM.Encryption` into `%SYSTEM.ENCRYPTION` and casing a declared parameter
differently from its uses. Both installed cleanly and failed on every call.
Fixed with a verbatim-SQL guard (`sql_translator/verbatim.py`): SQL pgwire wrote
itself is not client SQL and must not be translated.

**ContextVars do not cross `run_in_executor`.** The first attempt at that guard
did nothing, because the embedded backend hands `_sync_execute` to
`loop.run_in_executor`, which — unlike `asyncio.to_thread` — does not carry the
context into the worker thread, and `_prepare_sql` reads the guard in there. It
now runs through an explicit `contextvars.copy_context()`. Worth knowing for any
future ContextVar on that path.

### Verified

From a namespace with the functions dropped, the views dropped and the
ObjectScript class deleted, the server installs its own catalog at startup and
answers **8/8** end-to-end cases on **both** backends. `PGWire.PG_OID` returns
3909377549 and 1128014727, matching Python's `OIDGenerator` exactly.


---

## 6. The built-in list constructs, measured

Prompted by a search of `community.intersystems.com`. That host is egress-blocked here as well, so
again the prose comes from search extracts; every behavioural claim below was then measured on the
instance (`spikes/probe_list_constructs.py`).

The community's own idiom for this problem is the one we implement:

> `%INLIST` takes a single `$LISTBUILD()` as parameter with a variable number of values that you pass
> at runtime by only 1 "?" placeholder, while `IN (p1,p2,p3,p4)` or `IN (?,?,?,?)` requires a fixed
> static number of parameters during execution.

Four constructs exist for getting that list, and all four work. What separates them:

| Construct | Installed code | ms/query | Verdict |
|---|---|---|---|
| `%INLIST PGWire.PG_ARRAY(?)` | one SQL function | **0.202** | shipped |
| `= ANY (SELECT v FROM JSON_TABLE(?, …))` | none | 0.992 | viable; see below |
| `%INLIST (SELECT %DLIST(v) FROM JSON_TABLE(?, …))` | none | — | works, but `= ANY` with extra steps |
| `%INLIST $LISTFROMSTRING(?, ',')` | none | — | **unsafe** |

300 executions each, one element, against `plain IN ('public')` at 0.342 ms for scale.

### `$LISTFROMSTRING` is the trap

It is the obvious shortcut and it fails silently:

```
two clean values                    -> ['pg_catalog', 'public']
a value containing the delimiter    -> []
```

No error — the row simply does not come back. Any delimiter can occur in a catalog value, so there
is no safe choice of one. This is exactly the silent-empty class of failure feature 044 exists to
remove, so it is rejected outright rather than treated as a fallback.

### `JSON_TABLE` is a genuine zero-install alternative

`= ANY (subquery)` is standard SQL that IRIS parses natively — confirmed, which also retires an
assumption the rewrite's guard was resting on untested. Combined with `JSON_TABLE` it needs **no
installed function at all**, and JSON escaping is a solved problem, so there is no format of ours to
get wrong. It handled everything: one value, several, the empty array, negation, the `IN` form, a
numeric column against string elements, a NULL parameter (what Describe binds), commas, embedded
quotes, `café`, an astral character, elements of 10 000 characters with no truncation, and 5 000
elements. Cached-query count: 0 added across four different list lengths, same as PG_ARRAY.

It is not chosen, for two reasons and one non-reason:

* **5× the cost** — 0.992 ms against 0.202 ms. Database-side execution, so it does not touch the
  constitutional 5 ms *translation* budget, but ORM introspection issues these constantly.
* **The installer is not avoidable.** `PG_OID` and `PG_PUBLIC_SCHEMA` have to be installed for any
  view to compile, so "zero install" saves one function in a mechanism that must exist regardless.
  This is what makes the argument for JSON_TABLE much weaker than it first appears.
* **Not** the IRIS version floor. `JSON_TABLE` arrived in 2024.1 and this project already targets
  2024.2+, so that objection does not hold — worth stating because it was the first thing assumed.

One hazard if it is ever adopted: a nested array silently produces garbage rather than an error
(`[["a","b"]]` returned two rows of `1`). `parse_pg_array_literal` already declines nested arrays
before they reach IRIS, and that guard would have to stay.

### `%DLIST` — noted for later

`%DLIST(expr)` is an aggregate that builds a real `$LIST` from query results, verified here
(`$LISTLENGTH(%DLIST(nspname))` = 3). Not useful for this problem — `= ANY (subquery)` does the same
job more directly — but it is the right tool for **T015–T018**, where `pg_index` and `pg_constraint`
need a column list aggregated server-side.

### Conclusion

Keep `PG_ARRAY`. It is the cheapest option, it uses only documented API, and it rides an installer
the feature needs anyway. `JSON_TABLE` is recorded as a tested fallback rather than a discarded
idea; the honest summary is that the two are close and the deciding factor is that the installer
exists either way.


---

## 7. What the drift test found

`PG_ARRAY` replaced a Python encoder for someone else's private format with a Python encoder for our
own. That is a real improvement — correctness now rests only on `$LISTBUILD`, which is documented —
but it does not remove the need to check the two halves agree. The unit tests compare
`encode_pg_array` against `decode_pg_array`, a **Python mirror** of the ObjectScript. A mirror is not
the thing: if the two drift, every unit test still passes.

That is precisely what made the old `$LIST` parity tests worthless, so
`tests/integration/test_pg_array_against_iris.py` drives the function **actually installed in IRIS**,
and treats a missing function as a failure rather than a skip.

It found two defects on its first run, both in the empty-string case, and both silent:

**IRIS SQL spells the empty string as `$CHAR(0)`.** Measured by inspecting the bytes a function
actually receives:

| bound value | what the function sees |
|---|---|
| `''` | one byte, `$CHAR(0)` |
| `NULL` | genuinely empty, length 0 |
| `'x'` | one byte, `x` |

An empty column value is stored the same way. Two consequences:

1. **`PG_ARRAY('')` raised "missing element count".** The guard tested `encoded = ""`, which is false
   for a bound empty string, so it fell through to the parser. Now `(encoded = "") || (encoded =
   $char(0))`.
2. **A zero-length element could never match.** `$LISTBUILD($EXTRACT(…))` for a zero-length element
   builds a true ObjectScript `""`, which is a different value from the `$CHAR(0)` an empty column
   holds — so `x = ANY('{""}')` returned nothing, with no error. Now built as `$char(0)`.

Neither was reachable from Python: `decode_pg_array` agreed with the encoder perfectly, because both
were reasoning about logical values while IRIS was storing a different byte.

A third, smaller finding: `$LIST` throws `<NULL VALUE>` on a null element, so the test itself has to
use `$LISTGET` — otherwise a NULL in the array reads as a decoder failure.

### Standing gap

`decode_pg_array` remains a mirror and can still drift from the ObjectScript. It is only used by
tests, and the integration suite above is what actually pins the contract. Anyone changing the
ObjectScript body must run that suite; the unit tests alone will not catch it.
