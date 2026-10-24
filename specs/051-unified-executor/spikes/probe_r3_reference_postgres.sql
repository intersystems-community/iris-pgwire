-- Phase 0 probe R3 for feature 051: what does the reference say?
--
-- FR-016 makes real PostgreSQL the reference authority, and Q5 settled that
-- every difference from it is recorded in the divergence ledger as a deliberate
-- pin or a defect to fix. That only works if the reference answers are captured
-- from an actual PostgreSQL rather than from memory of one.
--
-- Run against this repository's own reference container (never another
-- project's database):
--
--   docker run -d --name iris-pgwire-pgref -e POSTGRES_PASSWORD=pgref \
--     -e POSTGRES_DB=pgref -p 55432:5432 postgres:16-alpine
--   docker exec -i iris-pgwire-pgref psql -U postgres -d pgref -f - \
--     < probe_r3_reference_postgres.sql
--
-- Each \echo marks one measurement so the transcript maps onto the probes run
-- against IRIS (probe_r1_host_adapters.py, probe_r2b_embedded_metadata.py).

\pset null '<NULL>'
\set ON_ERROR_STOP off

\echo === R3.1 column types for the three-column corpus statement ===
SELECT 'x' AS s, 42 AS i, CAST(1 AS BIT) AS b \gdesc

\echo === R3.2 can the server describe a statement WITHOUT executing it? ===
-- IRIS answers None for cursor.description before execute; PostgreSQL answers
-- from Parse/Describe. This is the divergence behind the extra connection that
-- handle_describe_message opens.
PREPARE p051 AS SELECT 'x' AS s, 42 AS i, CAST(1 AS BIT) AS b;
SELECT name, statement, parameter_types, result_types FROM pg_prepared_statements WHERE name = 'p051';
DEALLOCATE p051;

\echo === R3.3 empty string versus NULL ===
SELECT '' AS empty, NULL AS nul, ('' IS NULL) AS empty_is_null, length('') AS empty_len;

\echo === R3.4 error wording and SQLSTATE for a missing table ===
SELECT * FROM nosuchtable_051;

\echo === R3.5 command tags: what does each statement kind report? ===
CREATE TABLE probe051 (id int, txt varchar(10));
INSERT INTO probe051 (id, txt) VALUES (1, 'a');
INSERT INTO probe051 (id, txt) VALUES (2, 'b'), (3, 'c');
UPDATE probe051 SET txt = 'z' WHERE id = 1;
DELETE FROM probe051 WHERE id = 3;
SELECT * FROM probe051;

\echo === R3.6 zero-row SELECT still reports column types ===
SELECT id, txt FROM probe051 WHERE 1 = 0 \gdesc

\echo === R3.7 isolation levels the reference accepts AND enforces ===
SHOW default_transaction_isolation;
BEGIN;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
SHOW transaction_isolation;
COMMIT;
BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
SHOW transaction_isolation;
COMMIT;
BEGIN;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SHOW transaction_isolation;
COMMIT;
BEGIN;
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
SHOW transaction_isolation;
COMMIT;

\echo === R3.8 statements the reference CANNOT run, so cannot adjudicate ===
-- Each of these is IRIS dialect. A divergence here is not a defect against
-- PostgreSQL; it has no PostgreSQL answer at all, and the ledger needs a third
-- disposition for it rather than a forced pin-or-fix.
SELECT TOP 1 id FROM probe051;
SELECT %ID FROM probe051;
SELECT id FROM SQLUser.probe051;
SELECT $SYSTEM.SQL.Util.GetOption('IsolationMode');
SELECT CAST('[1,2,3]' AS VECTOR(DOUBLE, 3));
SELECT '[1,2,3]'::vector <=> '[1,2,4]'::vector;

\echo === R3.9 identifier case folding, the DDL normaliser question ===
CREATE TABLE MixedCase051 (ColA int);
SELECT table_name, column_name FROM information_schema.columns WHERE table_name ILIKE 'mixedcase051';
SELECT ColA FROM MixedCase051;
SELECT "ColA" FROM MixedCase051;

DROP TABLE IF EXISTS probe051;
DROP TABLE IF EXISTS MixedCase051;
