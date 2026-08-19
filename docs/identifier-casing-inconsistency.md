# DDL column-name casing is inconsistent

**Found**: 2026-08-17, while clearing the Constitution Principle II gate for feature 044.
**Status**: open, diagnosed, deliberately not fixed inside 044 — see below.
**Symptom**: two failing tests, `tests/unit/test_generated_columns.py::test_generated_column_skip`
and `::test_generated_column_multiple_skip`.

## What happens

`IdentifierNormalizer.normalize` uppercases column names in `CREATE TABLE` **only when the statement
contains a string literal**:

```
CREATE TABLE t1 (col1 text)                 ->  CREATE TABLE T1 (col1 TEXT)     -- preserved
CREATE TABLE t1 (col1 text DEFAULT 'val')   ->  CREATE TABLE T1 (COL1 TEXT ...) -- uppercased
```

Both go through `normalize`. The difference is `_split_on_string_literals`: a statement with a
literal is split into chunks, and the chunk carrying the column definitions no longer matches the
`CREATE TABLE` pattern that exists specifically to preserve column case, so it falls through to the
generic identifier path, which uppercases everything.

## Which behaviour is intended

Preserving lowercase is intended. The code says so, in `identifier_normalizer.py`:

```python
# CRITICAL FIX: Detect CREATE TABLE context to preserve lowercase column names
# PostgreSQL clients expect lowercase column names, but IRIS needs uppercase table names
```

So:

* the two failing tests assert the **pre-fix** behaviour (`ID INT`) and are stale;
* `tests/unit/test_cast_removal.py` asserts `COL1 TEXT` and **passes** — but only because its
  fixture contains `DEFAULT 'val'`, i.e. it passes *because of this bug*. Fixing the bug will fail
  that test.

That is the whole reason this is not a two-line change: the three tests disagree, and one of them is
green for the wrong reason.

## Why feature 044 did not fix it

Column-name casing in DDL is what every client sees for every `CREATE TABLE`, not a catalog concern.
Changing it from inside a catalog feature would be a wide-blast-radius change smuggled in under an
unrelated scope. It is recorded as Complexity Tracking C-1 in
`specs/044-catalog-as-views/plan.md` instead, with the constraint that 044 must neither make these
tests worse nor "fix" them by altering DDL casing.

## What a fix needs

1. Decide the rule and write it down: unquoted column names in `CREATE TABLE` are preserved as
   given (matching the existing comment's intent), or uppercased uniformly.
2. Make `_split_on_string_literals` not lose the `CREATE TABLE` context — most likely by detecting
   the statement kind before splitting rather than per chunk.
3. Update all three tests together, `test_cast_removal.py` included, and say in the commit that it
   was passing for the wrong reason.
4. Check the round trip a client actually sees: create a table through pgwire, then introspect it,
   and confirm the column names come back as the client wrote them.
