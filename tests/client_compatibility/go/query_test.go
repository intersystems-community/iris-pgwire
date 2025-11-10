package pgwirecompat

import (
	"context"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// Test simple query execution via pgx driver.
//
// Tests P1 Simple Query Protocol:
// - Query message handling
// - IRIS SQL execution
// - Row data encoding
// - CommandComplete and ReadyForQuery

func TestSelectConstant(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing SELECT 1
	var result int
	err = conn.QueryRow(ctx, "SELECT 1").Scan(&result)

	// THEN: Should return 1
	assert.NoError(t, err)
	assert.Equal(t, 1, result)
}

func TestSelectMultipleColumns(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing multi-column SELECT
	var num int
	var text string
	var floatVal float64

	err = conn.QueryRow(ctx, "SELECT 1 AS num, 'hello' AS text, 3.14 AS float_val").
		Scan(&num, &text, &floatVal)

	// THEN: Should return all columns correctly
	assert.NoError(t, err)
	assert.Equal(t, 1, num)
	assert.Equal(t, "hello", text)
	assert.InDelta(t, 3.14, floatVal, 0.001)
}

func TestSelectCurrentTimestamp(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing SELECT CURRENT_TIMESTAMP
	var timestamp time.Time
	err = conn.QueryRow(ctx, "SELECT CURRENT_TIMESTAMP").Scan(&timestamp)

	// THEN: Should return a timestamp
	assert.NoError(t, err)
	assert.False(t, timestamp.IsZero(), "Timestamp should not be zero")
	t.Logf("Current Timestamp: %v", timestamp)
}

func TestSelectWithNullValue(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing SELECT with NULL
	var nullCol *int
	var numCol int

	err = conn.QueryRow(ctx, "SELECT NULL AS null_col, 42 AS num_col").
		Scan(&nullCol, &numCol)

	// THEN: NULL should be handled correctly
	assert.NoError(t, err)
	assert.Nil(t, nullCol, "null_col should be nil")
	assert.Equal(t, 42, numCol)
}

func TestMultipleRowsQuery(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
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

	// THEN: Should iterate all rows
	count := 0
	for rows.Next() {
		var id int
		var name string
		err := rows.Scan(&id, &name)
		assert.NoError(t, err)
		count++
		t.Logf("Row %d: id=%d, name=%s", count, id, name)
	}

	assert.NoError(t, rows.Err())
	assert.Equal(t, 3, count, "Should have 3 rows")
}

func TestExecuteNonQuery(t *testing.T) {
	// GIVEN: Active connection with test table
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	_, err = conn.Exec(ctx, "CREATE TABLE IF NOT EXISTS test_exec (id INT)")
	require.NoError(t, err)

	defer func() {
		// Cleanup
		conn.Exec(ctx, "DROP TABLE IF EXISTS test_exec")
	}()

	// WHEN: Executing DELETE
	tag, err := conn.Exec(ctx, "DELETE FROM test_exec")

	// THEN: Should succeed
	assert.NoError(t, err)
	assert.NotNil(t, tag)
	t.Logf("Rows affected: %d", tag.RowsAffected())
}

func TestEmptyResultSet(t *testing.T) {
	// GIVEN: Active connection and empty table
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	_, err = conn.Exec(ctx, "CREATE TABLE IF NOT EXISTS test_empty (id INT)")
	require.NoError(t, err)

	defer func() {
		conn.Exec(ctx, "DROP TABLE IF EXISTS test_empty")
	}()

	// Delete all rows to ensure empty
	_, err = conn.Exec(ctx, "DELETE FROM test_empty")
	require.NoError(t, err)

	// WHEN: Querying empty table
	rows, err := conn.Query(ctx, "SELECT * FROM test_empty")
	require.NoError(t, err)
	defer rows.Close()

	// THEN: Result set should be empty
	assert.False(t, rows.Next(), "Should have no rows")
	assert.NoError(t, rows.Err())
}

func TestPreparedStatement(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Executing prepared statement with parameter
	var result int
	err = conn.QueryRow(ctx, "SELECT $1::int", 42).Scan(&result)

	// THEN: Parameter should be bound correctly
	assert.NoError(t, err)
	assert.Equal(t, 42, result)
}

func TestStringWithSpecialCharacters(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Querying string with special characters
	testString := "O'Reilly's \"Book\""
	var result string
	err = conn.QueryRow(ctx, "SELECT $1::text", testString).Scan(&result)

	// THEN: String should be handled correctly
	assert.NoError(t, err)
	assert.Equal(t, testString, result)
}
