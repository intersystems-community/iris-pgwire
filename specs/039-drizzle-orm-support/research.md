# Research: Drizzle ORM DDL Translation Support

This document captures the functional and technical context gathered while planning the Drizzle ORM DDL translation work described in `specs/039-drizzle-orm-support/spec.md`.

## 1. IRIS DDL Capabilities & Limitations

### Decision
- Target the existing IRIS DDL surface (`CREATE/ALTER/DROP TABLE`, `CREATE/DROP INDEX`, etc.) as defined in the InterSystems SQL command catalog and rely on the SQLTranslator pipeline to normalize incoming PostgreSQL syntax into those supported statements.
- Respect persistent-class protections by honoring the `DdlAllowed` flag before emitting destructive DDL.
- Treat quoted (delimited) identifiers as the way to bypass IRIS’s broader reserved-word set while unquoted names continue to be uppercased.
- Execute migration batches inside explicit transactions (`START TRANSACTION` + `COMMIT/ROLLBACK`) and, when required, coordinate concurrent migration runners through `LOCK TABLE ... IN EXCLUSIVE MODE` or manual ObjectScript locks instead of PostgreSQL-style advisory locks.

### Rationale
- The [InterSystems SQL Commands reference](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_COMMANDS) lists all the DDL operations that the engine actually executes, so we can safely mirror Drizzle’s DDL by translating into that subset. Complementing this, the TSQL view of DDL makes it clear that ALTER/CREATE/DROP and index management are centrally supported.
- `DdlAllowed` (persistent-class keyword) is the gatekeeper for SQL DDL mutations and will throw SQLCODE -300 if a table is protected, so our translator must detect when a table/class is not DDL-modifiable instead of blindly issuing DROP/ALTER statements.
- The [Identifiers guide](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_identifiers) explains that unquoted identifiers are case-insensitive (and uppercased) while delimited identifiers preserve casing. Combined with the [Reserved words list](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_reservedwords), this means we can automatically quote any identifier that matches IRIS-reserved tokens without requiring schema changes in Drizzle.
- InterSystems supports explicit transactions via `START TRANSACTION`/`COMMIT`/`ROLLBACK` (see [START TRANSACTION](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_starttransaction) and [ROLLBACK](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_rollback)), so full migration files can be wrapped in a single transaction for all-or-nothing semantics.
- There is no built-in PostgreSQL-style `pg_advisory_lock`; instead we can use the [LOCK TABLE](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_lock) command or the generic lock table utilities ([Locks (Tools/APIs)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=ITECHREF_lock)) to coordinate a single migrating process.

### Alternatives Considered
- Delegate quoting/reserved-word handling to the Drizzle schema by forcing developers to wrap IRIS-reserved names in quotes; rejected because it defeats the promise of zero-touch migrations.
- Build a separate dialect layer that only allows a narrow subset of DDL; rejected because current and future Drizzle migrations rely on the broader set captured by IRIS’s SQL commands.
- Rely on PostgreSQL-style advisory locks by simulating them in ObjectScript globals; instead the translator should use the documented `LOCK TABLE` behavior since it directly exposes the locking semantics we need.

### References
- InterSystems SQL command catalog (list of supported DDL statements). [KEY=RSQL_COMMANDS](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_COMMANDS)
- `DdlAllowed` class keyword that gates schema mutation. [KEY=ROBJ_class_ddlallowed](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=ROBJ_class_ddlallowed)
- Identifier rules and quoting semantics. [KEY=GSQL_identifiers](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_identifiers)
- Reserved words list that expands beyond PostgreSQL. [KEY=RSQL_reservedwords](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_reservedwords)
- Transaction control statements (`START TRANSACTION`, `ROLLBACK`). [KEY=RSQL_starttransaction](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_starttransaction), [KEY=RSQL_rollback](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_rollback)
- Explicit locking commands for coordinating migrations. [KEY=RSQL_lock](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_lock), [KEY=ITECHREF_lock](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=ITECHREF_lock)

## 2. IRIS Type System Mapping

### Decision
- Reuse the existing `iris_pgwire.type_mapping` registry to map PostgreSQL-friendly types (`text`, `boolean`, `uuid`, `jsonb`, `serial`/`bigserial`, etc.) to IRIS equivalents, letting the registry drive both translator output and client metadata functions.
- Enforce known IRIS limits (e.g., NUMERIC precision capped at 38 digits, timestamp precision bounded by the `TimePrecision` setting) when Drizzle migrations specify larger precision scales.
- Treat JSON/array-style payloads as IRIS dynamic entities (`%Library.DynamicObject`/`%Library.DynamicArray`) and map them to PostgreSQL `json`/`jsonb` so that Drizzle’s `jsonb` columns still behave like structured payloads.

### Rationale
- `type_mapping.py` already declares that IRIS `VARCHAR`/`TEXT`/`BIT`/`UUID` map to PostgreSQL `character varying`/`text`/`boolean`/`uuid`, while `JSON`/`JSONB` map to the PostgreSQL JSON types that Drizzle emits. Reusing that registry allows translator formatting to stay in sync with the rest of the system and exposes simple configuration hooks if we need to adjust behavior per deployment.
- IRIS decimals (and `%Decimal` conversions) only accept precision up to **38 digits** ([`$DECIMAL`](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RCOS_fdecimal)), so we should detect incoming `NUMERIC(p,s)` definitions beyond that limit, raise a clear error, and suggest the supported precision range instead of silently truncating.
- Timestamp/time precision is capped by the configurable `[SQL] TimePrecision` (0‑9 fractional digits, default 0) and timezone-aware functions respect the host timezone ([`TimePrecision`](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RACS_TimePrecision), [`CURRENT_TIMESTAMP`](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_currenttimestamp)). This lets us translate `timestamp with time zone` columns by targeting the IRIS `TIMESTAMP` types and adjusting fractional digits according to the session’s `TimePrecision`.
- JSON support in IRIS is provided by `%Library.DynamicObject`/`%Library.DynamicArray`, which are designed to interoperate with JSON literal constructors ([`Working with Datatypes`](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GJSON_datatypes)). The translator can therefore treat Drizzle’s `jsonb` columns as `%DynamicObject` storage under the hood while keeping `jsonb` as the exposed PostgreSQL type.

### Alternatives Considered
- Introduce custom IRIS-only data types for every PostgreSQL type; rejected because it would diverge from ORMs’ expectations and multiple code paths already rely on the existing registry.
- Allow oversized `NUMERIC` precision by silently truncating; rejected because it would misreport data precision to Drizzle/ORMs.
- Pretend JSON columns are just text; rejected to avoid losing structured querying semantics and to keep JSON functions mapping consistent with existing translator behavior.

### References
- Type mapping registry that ties IRIS names to PostgreSQL `text`, `boolean`, `uuid`, `jsonb`, etc. (`type_mapping.py` in the codebase). [/src/iris_pgwire/type_mapping.py](src/iris_pgwire/type_mapping.py)
- NUMERIC precision caps through `$DECIMAL`. [KEY=RCOS_fdecimal](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RCOS_fdecimal)
- Timestamp precision/timezone handling via `TimePrecision` and `CURRENT_TIMESTAMP`. [KEY=RACS_TimePrecision](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RACS_TimePrecision), [KEY=RSQL_currenttimestamp](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_currenttimestamp)
- JSON/dynamic entity support documents. [KEY=GJSON_datatypes](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GJSON_datatypes)

## 3. Existing iris-pgwire Architecture

### Decision
- Build on the current `SQLTranslator` pipeline (`sql_translator/translator.py`) to extend parsing + mapping logic so that DDL statements from Drizzle travel through the same cache/parser/validator workflow as DML.
- Introduce DDL-specific mappings and validators inside the existing construct registries (`sql_translator/mappings`) so that DDL constructs are recognized, normalized, and either rewritten or skipped based on rules already exercised by the test suite.
- Leverage the translation API documentation to expose the translator as both an internal component and a standalone service for experimentation (e.g., `docs/architecture/TRANSLATION_API.md`), then evolve the pipeline gradually.

### Rationale
- `SQLTranslator` orchestrates parsing (via `parser.py`), caching, mapping, validation, and final cleanup while recording diagnostic metrics and warnings. Adding DDL handling here keeps the stack consistent and lets existing instrumentation (SLA checks, error handling) surface migration problems.
- The translation registries (`mappings/{datatypes,constructs,document_filters}.py`) already model IRIS features with `ConstructType`/`ConstructMapping`, so introducing new DDL-specific construct types or mapping rules simply follows the pattern used for document filters and boolean translation.
- The translation API doc (`docs/architecture/TRANSLATION_API.md`) outlines how the translator already supports extra endpoints (cache stats, validation levels) and shows that the pipeline is production-quality and easily callable from tests.
- Integration tests such as `tests/integration/test_drizzle_migration.py` already validate Drizzle-style DDL patterns (enums, boolean defaults, RLS statements), proving that the test infrastructure supports regression coverage for translation work.

### Alternatives Considered
- Fork the translator into a separate DDL-only pipeline; rejected because it would duplicate caching/validation logic and split instrumentation.
- Try to translate DDL purely by regex rewrites before parsing; rejected because existing translator already depends on AST-aware parsing for accuracy and for reusing mapping metadata across queries.

### References
- Service-level documentation for the translator pipeline and API surface. [`docs/architecture/TRANSLATION_API.md`](docs/architecture/TRANSLATION_API.md)
- The translator orchestrator currently implemented in `sql_translator/translator.py`. [/src/iris_pgwire/sql_translator/translator.py](src/iris_pgwire/sql_translator/translator.py)
- Integration test suite already exercising Drizzle-like DDL patterns. [`tests/integration/test_drizzle_migration.py`](tests/integration/test_drizzle_migration.py)

## 4. Drizzle ORM Migration Patterns

### Decision
- Treat Drizzle migrations as ordered SQL files in a `drizzle/` folder that contain standard PostgreSQL DDL (`CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX`, etc.) plus occasional enums and row-level security statements; the translator should rewrite or skip the PostgreSQL-specific constructs before passing IRIS-compatible SQL down the wire.
- Preserve `__drizzle_migrations` logging semantics by keeping a compatible journal table and, when possible, respect the ordering that `drizzle-kit migrate` uses (read migrations, query the journal, apply unapplied scripts). Customize the table/schema per Drizzle config if needed.
- Because Drizzle currently does not obtain an exclusive lock on the migration journal (see community discussion), iris-pgwire must enforce its own lock/coordination when running migrations through pgwire to avoid concurrent writers.

### Rationale
- The Drizzle migration fundamentals page clearly shows that migrations are generated SQL files (`migration.sql` inside `drizzle/yyyy...` folders) containing `CREATE TABLE` statements with columns like `uuid`, `text`, `boolean`, `DEFAULT gen_random_uuid()` and `CREATE INDEX` statements – exactly the constructs we wish to support ([Drizzle migrations fundamentals](https://orm.drizzle.team/docs/migrations)).
- `drizzle-kit migrate` (https://orm.drizzle.team/docs/drizzle-kit-migrate) enumerates the runtime workflow: it reads the migration folder, queries `__drizzle_migrations`, applies unapplied SQL, and logs successful runs. That gives us an explicit point to integrate translation (wrap each file in a transaction and skip/translate unsupported statements).
- The `drizzle-kit` docs also state that the journal table and schema can be customized, so our translation layer should permit the same, ensuring Drizzle still sees the journal it expects.
- Community discussion on migration safety ([Migration production safety questions](https://www.answeroverflow.com/m/1300037379272212531)) highlights that concurrent migration runs can execute twice because Drizzle does not acquire an exclusive lock on the journal. This reinforces the need for iris-pgwire to acquire a table-level lock or other coordination before applying migrations.

### Alternatives Considered
- Requiring Drizzle to maintain its own migration runner outside of pgwire and only calling it from inside IRIS; rejected because it would break the goal of running `drizzle-kit migrate` over pgwire.
- Creating a custom Drizzle dialect (rewriting TypeScript schema to IRIS SQL); ruled out by scope.

### References
- Drizzle migration fundamentals and example SQL file structure. [Drizzle migrations fundamentals](https://orm.drizzle.team/docs/migrations)
- `drizzle-kit migrate` command behavior and journal table customization. [Drizzle Kit migrate](https://orm.drizzle.team/docs/drizzle-kit-migrate)
- Community discussion noting the lack of exclusive locking around `__drizzle_migrations`. [Migration production safety questions](https://www.answeroverflow.com/m/1300037379272212531)

## 5. Best Practices for SQL Translation

### Decision
- Use an AST-based translation pipeline rather than regex/search-and-replace so each DDL construct can be understood in context before being rewritten or skipped.
- Apply dialect-specific placeholders/macros (a la Flyway) when the same SQL script must run across IRIS and PostgreSQL, letting the translator substitute IRIS-friendly syntax at runtime rather than requiring separate migration files.
- Surface clear, actionable error messages for unsupported DDL constructs by piggybacking on Flyway-style error logging/overrides.

### Rationale
- The SQLGlot write-up describes why AST-based parsing/transpilation is the only robust approach when multiple dialects (and their quirks) need to be supported simultaneously, which matches the translator architecture we already have ([SQLGlot article](https://medium.com/towards-data-engineering/sqlglot-the-sql-parser-transpiler-and-optimizer-powering-modern-data-engineering-b735fd3d79b1)).
- The Flyway article “One Flyway Migration Script for Diverse Database Systems” demonstrates that placeholders/macros allow a single SQL script to support multiple dialects; we should take the same approach by parameterizing the constructs that differ between PostgreSQL and IRIS (e.g., index modifiers, `USING btree`, generated columns) rather than duplicating migration files ([Flyway placeholders article](https://www.red-gate.com/hub/product-learning/flyway/one-flyway-migration-script-for-diverse-database-systems)).
- Flyway’s migration error handling guide explains that migrations should capture and expose all database warnings/errors, let operators tweak behavior via configuration, and keep the migration history table in sync with success/failure ([Flyway migration error handling](https://documentation.red-gate.com/fd/migration-error-and-logging-handling-275218520.html)). Borrowing this mindset means our translator should emit structured warnings (e.g., `[DDL-SKIP] GENERATED column ignored`) and highlight unsupported DDL constructs with a clear message before failing the migration file.

### Alternatives Considered
- Continue using ad-hoc regex/templated rewrites; rejected because it would be fragile for complex DDL (and existing translator already is AST-driven).
- Provide only high-level warnings without mapping to specific constructs; rejected because operators rely on precise error messaging to fix schema definitions.

### References
- AST-based translation is necessary for multi-dialect SQL. [SQLGlot article](https://medium.com/towards-data-engineering/sqlglot-the-sql-parser-transpiler-and-optimizer-powering-modern-data-engineering-b735fd3d79b1)
- Placeholder/macros approach for supporting multiple dialects using the same migration script. [Flyway article](https://www.red-gate.com/hub/product-learning/flyway/one-flyway-migration-script-for-diverse-database-systems)
- Flyway’s documented error logging/override patterns. [Flyway migration error handling](https://documentation.red-gate.com/fd/migration-error-and-logging-handling-275218520.html)
