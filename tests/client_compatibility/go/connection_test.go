package main

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

/**
 * Test basic pgx connection to IRIS PGWire server.
 *
 * Tests P0 Handshake Protocol:
 * - SSL negotiation
 * - StartupMessage processing
 * - Authentication
 * - ReadyForQuery state
 */

func getConnectionConfig() string {
	host := os.Getenv("PGWIRE_HOST")
	if host == "" {
		host = "localhost"
	}

	port := os.Getenv("PGWIRE_PORT")
	if port == "" {
		port = "5432"
	}

	database := os.Getenv("PGWIRE_DATABASE")
	if database == "" {
		database = "USER"
	}

	user := os.Getenv("PGWIRE_USERNAME")
	if user == "" {
		user = "test_user"
	}

	password := os.Getenv("PGWIRE_PASSWORD")
	if password == "" {
		password = "test"
	}

	return fmt.Sprintf("postgres://%s:%s@%s:%s/%s?sslmode=disable",
		user, password, host, port, database)
}

func TestBasicConnection(t *testing.T) {
	// GIVEN: PGWire server is running
	ctx := context.Background()
	connString := getConnectionConfig()

	// WHEN: Attempting to connect
	conn, err := pgx.Connect(ctx, connString)
	require.NoError(t, err, "should establish connection")
	defer conn.Close(ctx)

	// THEN: Connection should be established
	require.NotNil(t, conn)

	// Verify with simple query
	var result int
	err = conn.QueryRow(ctx, "SELECT 1").Scan(&result)
	require.NoError(t, err)
	assert.Equal(t, 1, result)
}

func TestConnectionString(t *testing.T) {
	// GIVEN: Connection string
	ctx := context.Background()
	connString := getConnectionConfig()

	// WHEN: Connecting with connection string
	conn, err := pgx.Connect(ctx, connString)
	require.NoError(t, err, "should connect with connection string")
	defer conn.Close(ctx)

	// THEN: Connection succeeds
	var result int
	err = conn.QueryRow(ctx, "SELECT 1").Scan(&result)
	require.NoError(t, err)
	assert.Equal(t, 1, result)
}

func TestConnectionPooling(t *testing.T) {
	// GIVEN: Connection pool configured
	ctx := context.Background()
	connString := getConnectionConfig()

	config, err := pgxpool.ParseConfig(connString)
	require.NoError(t, err)

	config.MaxConns = 10
	config.MinConns = 1

	pool, err := pgxpool.NewWithConfig(ctx, config)
	require.NoError(t, err, "should create connection pool")
	defer pool.Close()

	// WHEN: Acquiring connections from pool
	conn1, err := pool.Acquire(ctx)
	require.NoError(t, err)
	defer conn1.Release()

	conn2, err := pool.Acquire(ctx)
	require.NoError(t, err)
	defer conn2.Release()

	// THEN: Both connections should work
	var result1, result2 int
	err = conn1.QueryRow(ctx, "SELECT 1").Scan(&result1)
	require.NoError(t, err)
	assert.Equal(t, 1, result1)

	err = conn2.QueryRow(ctx, "SELECT 2").Scan(&result2)
	require.NoError(t, err)
	assert.Equal(t, 2, result2)
}

func TestMultipleSequentialConnections(t *testing.T) {
	// GIVEN: Connection configuration
	ctx := context.Background()
	connString := getConnectionConfig()

	// WHEN: Opening and closing connections sequentially
	for i := 0; i < 3; i++ {
		conn, err := pgx.Connect(ctx, connString)
		require.NoError(t, err, "connection %d should succeed", i)

		// THEN: Each connection should succeed
		var result int
		err = conn.QueryRow(ctx, "SELECT $1::int", i+1).Scan(&result)
		require.NoError(t, err)
		assert.Equal(t, i+1, result)

		conn.Close(ctx)
	}
}

func TestServerInformation(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	connString := getConnectionConfig()

	conn, err := pgx.Connect(ctx, connString)
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Querying server version
	var version string
	err = conn.QueryRow(ctx, "SELECT version()").Scan(&version)
	require.NoError(t, err)

	// THEN: Version should be available
	assert.NotEmpty(t, version)
	t.Logf("Server version: %s", version)
}

func TestConnectionErrorHandling(t *testing.T) {
	// GIVEN: Invalid connection configuration
	ctx := context.Background()
	invalidConnString := "postgres://test_user:test@localhost:9999/USER?sslmode=disable"

	// WHEN: Attempting to connect
	conn, err := pgx.Connect(ctx, invalidConnString)

	// THEN: Should return connection error
	assert.Error(t, err, "should fail to connect to invalid port")
	if conn != nil {
		conn.Close(ctx)
	}
}

func TestConnectionTimeout(t *testing.T) {
	// GIVEN: Connection with timeout
	ctx := context.Background()
	connString := getConnectionConfig()

	config, err := pgxpool.ParseConfig(connString)
	require.NoError(t, err)

	config.MaxConnLifetime = 30 * time.Second
	config.MaxConnIdleTime = 10 * time.Second

	pool, err := pgxpool.NewWithConfig(ctx, config)
	require.NoError(t, err)
	defer pool.Close()

	// WHEN: Using connection with timeout
	conn, err := pool.Acquire(ctx)
	require.NoError(t, err)
	defer conn.Release()

	// THEN: Connection should work with timeout settings
	var result int
	err = conn.QueryRow(ctx, "SELECT 1").Scan(&result)
	require.NoError(t, err)
	assert.Equal(t, 1, result)
}
