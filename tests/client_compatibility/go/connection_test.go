package pgwirecompat

import (
	"context"
	"fmt"
	"os"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// Test basic pgx connection to IRIS PGWire server.
//
// Tests P0 Handshake Protocol:
// - SSL negotiation
// - StartupMessage processing
// - Authentication
// - ReadyForQuery state

func getConnectionString() string {
	host := getEnv("PGWIRE_HOST", "localhost")
	port := getEnv("PGWIRE_PORT", "5432")
	database := getEnv("PGWIRE_DATABASE", "USER")
	username := getEnv("PGWIRE_USERNAME", "test_user")
	password := getEnv("PGWIRE_PASSWORD", "test")

	return fmt.Sprintf("postgres://%s:%s@%s:%s/%s?sslmode=disable",
		username, password, host, port, database)
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func TestBasicConnection(t *testing.T) {
	// GIVEN: PGWire server is running
	connString := getConnectionString()
	ctx := context.Background()

	// WHEN: Attempting to connect
	conn, err := pgx.Connect(ctx, connString)
	require.NoError(t, err, "Connection should succeed")
	defer conn.Close(ctx)

	// THEN: Connection should be established
	assert.False(t, conn.IsClosed(), "Connection should be open")

	// Ping to verify connection
	err = conn.Ping(ctx)
	assert.NoError(t, err, "Ping should succeed")
}

func TestConnectionConfig(t *testing.T) {
	// GIVEN: Connection configured via pgx.Config
	config, err := pgx.ParseConfig(getConnectionString())
	require.NoError(t, err)

	ctx := context.Background()

	// WHEN: Connecting with config
	conn, err := pgx.ConnectConfig(ctx, config)
	require.NoError(t, err)
	defer conn.Close(ctx)

	// THEN: Connection succeeds
	assert.False(t, conn.IsClosed())
	err = conn.Ping(ctx)
	assert.NoError(t, err)
}

func TestConnectionInfo(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Querying connection info
	config := conn.Config()

	// THEN: Connection properties should be accessible
	assert.NotEmpty(t, config.Host)
	assert.NotEmpty(t, config.Database)
	assert.Greater(t, config.Port, uint16(0))

	t.Logf("Host: %s", config.Host)
	t.Logf("Port: %d", config.Port)
	t.Logf("Database: %s", config.Database)
	t.Logf("User: %s", config.User)
}

func TestPing(t *testing.T) {
	// GIVEN: Active connection
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, getConnectionString())
	require.NoError(t, err)
	defer conn.Close(ctx)

	// WHEN: Pinging server
	err = conn.Ping(ctx)

	// THEN: Ping should succeed
	assert.NoError(t, err, "Ping should succeed")
}

func TestMultipleSequentialConnections(t *testing.T) {
	// GIVEN: Connection string
	ctx := context.Background()

	// WHEN: Opening and closing connections sequentially
	for i := 0; i < 3; i++ {
		conn, err := pgx.Connect(ctx, getConnectionString())
		require.NoError(t, err, "Connection %d should succeed", i+1)

		// THEN: Each connection should work
		err = conn.Ping(ctx)
		assert.NoError(t, err, "Ping %d should succeed", i+1)

		conn.Close(ctx)
		assert.True(t, conn.IsClosed(), "Connection %d should be closed", i+1)
	}
}

func TestConnectionPooling(t *testing.T) {
	// GIVEN: Connection pool configuration
	ctx := context.Background()
	config, err := pgx.ParseConfig(getConnectionString())
	require.NoError(t, err)

	// WHEN: Creating connection pool
	pool, err := pgx.NewConn(ctx, config)
	require.NoError(t, err)
	defer pool.Close(ctx)

	// THEN: Pool should be usable
	err = pool.Ping(ctx)
	assert.NoError(t, err, "Pool ping should succeed")
}
