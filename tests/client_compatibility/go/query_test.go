package main

import (
	"context"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

/**
 * Test simple query execution via pgx driver.
 *
 * Tests P1 Simple Query Protocol:
 * - Query message handling
 * - IRIS SQL execution
 * - Row data encoding
 * - CommandComplete and ReadyForQuery
 */

func TestSelectConstant(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing SELECT 1
	var result int
	err = conn.QueryRow(ctx, "SELECT 1").Scan(&result)

	// THEN: Should return 1
	require.NoError(t, err)
	assert.Equal(t, 1, result)
}

func TestMultiColumnSelect(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing multi-column SELECT
	var num int
	var text string
	var floatVal float64

	err = conn.QueryRow(ctx, "SELECT 1 AS num, 'hello' AS text, 3.14 AS float_val").Scan(&num, &text, &floatVal)

	// THEN: Should return all columns correctly
	require.NoError(t, err)
	assert.Equal(t, 1, num)
	assert.Equal(t, "hello", text)
	assert.InDelta(t, 3.14, floatVal, 0.01)
}

func TestNullValues(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing SELECT with NULL
	var nullCol *int
	var numCol int

	err = conn.QueryRow(ctx, "SELECT NULL AS null_col, 42 AS num_col").Scan(&nullCol, &numCol)

	// THEN: NULL should be handled correctly
	require.NoError(t, err)
	assert.Nil(t, nullCol)
	assert.Equal(t, 42, numCol)
}

func TestMultipleQueriesSequentially(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing multiple queries
	var result1 int
	err = conn.QueryRow(ctx, "SELECT 1").Scan(&result1)
	require.NoError(t, err)

	var result2 string
	err = conn.QueryRow(ctx, "SELECT 'second query'").Scan(&result2)
	require.NoError(t, err)

	// THEN: Both queries should succeed
	assert.Equal(t, 1, result1)
	assert.Equal(t, "second query", result2)
}

func TestEmptyResultSet(t *testing.T) {
	// GIVEN: Active connection and empty table
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// Create and empty table
	_, err = conn.Exec(ctx, "CREATE TABLE IF NOT EXISTS test_empty (id INT)")
	require.NoError(t, err)
	_, err = conn.Exec(ctx, "DELETE FROM test_empty")
	require.NoError(t, err)

	// WHEN: Querying empty table
	rows, err := conn.Query(ctx, "SELECT * FROM test_empty")
	require.NoError(t, err)
	defer rows.Close()

	// THEN: Result set should be empty
	assert.False(t, rows.Next(), "should have no rows")

	// Cleanup
	_, _ = conn.Exec(ctx, "DROP TABLE IF EXISTS test_empty")
}

func TestResultMetadata(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing query
	rows, err := conn.Query(ctx, "SELECT 1 AS id, 'test' AS name")
	require.NoError(t, err)
	defer rows.Close()

	// THEN: Metadata should be available
	fieldDescriptions := rows.FieldDescriptions()
	require.Len(t, fieldDescriptions, 2)
	assert.Equal(t, "id", string(fieldDescriptions[0].Name))
	assert.Equal(t, "name", string(fieldDescriptions[1].Name))

	// Verify we have exactly one row
	assert.True(t, rows.Next())
	assert.False(t, rows.Next())
}

func TestStringWithSpecialCharacters(t *testing.T) {
	// GIVEN: Active connection and string with special characters
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	testString := `O'Reilly's "Book"`

	// WHEN: Querying with parameterized query
	var result string
	err = conn.QueryRow(ctx, "SELECT $1::text AS text", testString).Scan(&result)

	// THEN: String should be returned correctly
	require.NoError(t, err)
	assert.Equal(t, testString, result)
}

func TestParameterizedQueries(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing parameterized query
	var num int
	var text string
	err = conn.QueryRow(ctx, "SELECT $1::int AS num, $2::text AS text", 42, "hello").Scan(&num, &text)

	// THEN: Parameters should be bound correctly
	require.NoError(t, err)
	assert.Equal(t, 42, num)
	assert.Equal(t, "hello", text)
}

func TestArrayResult(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing query with multiple rows
	rows, err := conn.Query(ctx, `
		SELECT 1 AS id, 'first' AS name
		UNION ALL
		SELECT 2, 'second'
		UNION ALL
		SELECT 3, 'third'
	`)
	require.NoError(t, err)
	defer rows.Close()

	// THEN: Should return all rows
	var results []struct {
		ID   int
		Name string
	}

	for rows.Next() {
		var id int
		var name string
		err := rows.Scan(&id, &name)
		require.NoError(t, err)
		results = append(results, struct {
			ID   int
			Name string
		}{id, name})
	}

	require.Len(t, results, 3)
	assert.Equal(t, 1, results[0].ID)
	assert.Equal(t, 2, results[1].ID)
	assert.Equal(t, 3, results[2].ID)
}

func TestTransactionCommit(t *testing.T) {
	// GIVEN: Active connection and test table
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	_, err = conn.Exec(ctx, "CREATE TABLE IF NOT EXISTS test_commit (id INT, value VARCHAR(50))")
	require.NoError(t, err)
	defer conn.Exec(ctx, "DROP TABLE IF EXISTS test_commit")

	_, err = conn.Exec(ctx, "DELETE FROM test_commit")
	require.NoError(t, err)

	// WHEN: Transaction with commit
	tx, err := conn.Begin(ctx)
	require.NoError(t, err)

	_, err = tx.Exec(ctx, "INSERT INTO test_commit VALUES (1, 'committed')")
	require.NoError(t, err)

	err = tx.Commit(ctx)
	require.NoError(t, err)

	// THEN: Data should persist
	var count int
	err = conn.QueryRow(ctx, "SELECT COUNT(*) FROM test_commit").Scan(&count)
	require.NoError(t, err)
	assert.Equal(t, 1, count)
}

func TestTransactionRollback(t *testing.T) {
	// GIVEN: Active connection and test table
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	_, err = conn.Exec(ctx, "CREATE TABLE IF NOT EXISTS test_rollback (id INT, value VARCHAR(50))")
	require.NoError(t, err)
	defer conn.Exec(ctx, "DROP TABLE IF EXISTS test_rollback")

	_, err = conn.Exec(ctx, "DELETE FROM test_rollback")
	require.NoError(t, err)

	// WHEN: Transaction with rollback
	tx, err := conn.Begin(ctx)
	require.NoError(t, err)

	_, err = tx.Exec(ctx, "INSERT INTO test_rollback VALUES (1, 'will rollback')")
	require.NoError(t, err)

	err = tx.Rollback(ctx)
	require.NoError(t, err)

	// THEN: Data should NOT persist
	var count int
	err = conn.QueryRow(ctx, "SELECT COUNT(*) FROM test_rollback").Scan(&count)
	require.NoError(t, err)
	assert.Equal(t, 0, count)
}

func TestBatchQueries(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionConfig())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing batch queries
	batch := &pgx.Batch{}
	batch.Queue("SELECT 1")
	batch.Queue("SELECT 2")
	batch.Queue("SELECT 3")

	br := conn.SendBatch(ctx, batch)
	defer br.Close()

	// THEN: All queries should execute
	var result1, result2, result3 int

	err = br.QueryRow().Scan(&result1)
	require.NoError(t, err)
	assert.Equal(t, 1, result1)

	err = br.QueryRow().Scan(&result2)
	require.NoError(t, err)
	assert.Equal(t, 2, result2)

	err = br.QueryRow().Scan(&result3)
	require.NoError(t, err)
	assert.Equal(t, 3, result3)
}
