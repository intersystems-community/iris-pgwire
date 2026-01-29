# iris-pgwire-gh Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-17

## Active Technologies
- Python 3.11 + python>=3.11, psycopg[binary], iris-devtester, intersystems-irispython (026-address-gaps-in)
- PostgreSQL (via InterSystems IRIS) (026-address-gaps-in)
- Python 3.11 + intersystems-irispython, psycopg[binary], iris-devtester (034-issues-that-likely)
- InterSystems IRIS (via PostgreSQL wire protocol) (034-issues-that-likely)
- Python 3.11 + intersystems-irispython, psycopg[binary], iris-devtester (035-number-1-short)
- Python 3.11 + psycopg[binary], intersystems-irispython, iris-devtester (036-address-all-6)
- InterSystems IRIS (via pgwire) (036-address-all-6)
- Python 3.11 + psycopg[binary], intersystems-irispython, iris-devtester (036-address-all-6)
- Python 3.11+ + `intersystems-irispython`, `psycopg[binary]`, `pydantic`, `structlog` (037-pg-type-catalog)

- Python 3.11+ + `iris-devtester`, `intersystems-irispython`, `psycopg[binary]` (033-devtester-skills)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes
- 037-pg-type-catalog: Added Python 3.11+ + `intersystems-irispython`, `psycopg[binary]`, `pydantic`, `structlog`
- 036-address-all-6: Added Python 3.11 + psycopg[binary], intersystems-irispython, iris-devtester
- 036-address-all-6: Added Python 3.11 + psycopg[binary], intersystems-irispython, iris-devtester


<!-- MANUAL ADDITIONS START -->

## IRIS Technical Reference (Critical for DBAPI & Embedded)

### 1. DBAPI Connection Pattern (intersystems-irispython)
Always use this robust import pattern to obtain the DBAPI module. This handles different package versions and environment quirks.
```python
try:
    import iris.dbapi as iris_dbapi # Modern/Standard
except ImportError:
    try:
        import intersystems_iris.dbapi._DBAPI as iris_dbapi # Deep Fallback
    except ImportError:
        # Last resort: check if iris module itself has connect (older versions)
        import iris as iris_dbapi
```

### 2. Embedded SQL Execution (iris.sql.exec)
When running code inside IRIS (Embedded Python), parameters **MUST** be passed using the splat operator `*params` to be treated as positional arguments.
```python
# CORRECT
iris.sql.exec(sql, *params)

# INCORRECT (passes list as a single argument)
iris.sql.exec(sql, params) 
```

### 3. Case Sensitivity & Identifiers
- **Schema Name**: Always use `SQLUser` (exact casing). IRIS package/schema names are case-sensitive.
- **Quoted Identifiers**: Identifiers in double quotes (e.g., `"workflow"`) are case-sensitive in IRIS.
- **Unquoted Identifiers**: Automatically mapped to UPPERCASE by IRIS.
- **Normalization**: To ensure consistency, the normalizer should preserve the casing of quoted identifiers and map unquoted ones to uppercase, but it **MUST NOT** change the case of the `SQLUser` schema prefix.

<!-- MANUAL ADDITIONS END -->
