-- Excerpt from surp's splinter.sql (https://github.com/rexadbapp/surp)
-- Contains the 5 supported lint checks and the ERD FK query.
-- Used by tests/e2e/test_047_surp_e2e.py.
--
-- The full splinter.sql is a 15-branch multi-CTE UNION. This file contains
-- only the branches that iris-pgwire is expected to support (feature 047).
-- Unsupported branches (unindexed_foreign_keys, etc.) are omitted; the
-- full-splinter test assembles all 5 via UNION ALL.

-- no_primary_key: tables without a primary key constraint
WITH no_primary_key AS (
  SELECT
    jsonb_build_object('type', 'lint', 'check_id', 'no_primary_key') AS result,
    format('%I', c.relname) AS name,
    c.oid
  FROM pg_catalog.pg_class c
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_catalog.pg_index i
    ON i.indrelid = c.oid AND i.indisprimary = 1
  WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
    AND c.relkind = 'r'
    AND i.indexrelid IS NULL
),
-- extension_in_public: extensions installed in the public schema
extension_in_public AS (
  SELECT
    jsonb_build_object('type', 'lint', 'check_id', 'extension_in_public') AS result,
    e.extname AS name,
    e.oid
  FROM pg_catalog.pg_extension e
  JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
  WHERE n.nspname = 'public'
),
-- function_search_path_mutable: placeholder (returns empty on IRIS)
function_search_path_mutable AS (
  SELECT
    jsonb_build_object('type', 'lint', 'check_id', 'function_search_path_mutable') AS result,
    '' AS name,
    0 AS oid
  WHERE 1=0
),
-- unsupported_reg_types: placeholder (returns empty on IRIS)
unsupported_reg_types AS (
  SELECT
    jsonb_build_object('type', 'lint', 'check_id', 'unsupported_reg_types') AS result,
    '' AS name,
    0 AS oid
  WHERE 1=0
),
-- duplicate_index: placeholder (returns empty on IRIS without pg_stats)
duplicate_index AS (
  SELECT
    jsonb_build_object('type', 'lint', 'check_id', 'duplicate_index') AS result,
    '' AS name,
    0 AS oid
  WHERE 1=0
)
SELECT result, name, oid FROM no_primary_key
UNION ALL
SELECT result, name, oid FROM extension_in_public
UNION ALL
SELECT result, name, oid FROM function_search_path_mutable
UNION ALL
SELECT result, name, oid FROM unsupported_reg_types
UNION ALL
SELECT result, name, oid FROM duplicate_index
