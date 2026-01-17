# Quickstart: IRIS pgwire compatibility fixes

## Prerequisites
- IRIS container running with pgwire service enabled.
- Python 3.11 environment with test dependencies installed.

## Validation Steps

### 1) Multi-statement DDL with comments
Run a DDL script containing leading comments and multiple statements. Confirm statements execute in order and no SELECT/no-op appears in IRIS logs.

### 2) Prepared statement parameter translation
Execute a prepared statement with `$n` placeholders through a PostgreSQL client and verify successful execution without `$n` reaching IRIS.

### 3) DEFAULT in VALUES
Run an INSERT with per-column DEFAULT values and verify defaults are applied (not NULL) when defined.

### 4) Timestamp normalization
Insert ISO 8601 timestamps with `T` and `Z` suffixes and verify IRIS accepts them without errors; confirm stored format matches IRIS-accepted timestamp strings.

### 5) ALTER TABLE SET DATA TYPE / DROP NOT NULL
Run ALTER TABLE statements that change type or drop NOT NULL and verify:
- Supported changes execute successfully.
- Unsupported changes return clear, actionable errors.

## Tests
- Run `pytest` with iris-devtester-backed integration tests for each issue category.
