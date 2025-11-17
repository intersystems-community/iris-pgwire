import pg from 'pg';
const { Client, Pool } = pg;

/**
 * Test basic node-postgres connection to IRIS PGWire server.
 *
 * Tests P0 Handshake Protocol:
 * - SSL negotiation
 * - StartupMessage processing
 * - Authentication
 * - ReadyForQuery state
 */

const getConnectionConfig = () => ({
  host: process.env.PGWIRE_HOST || 'localhost',
  port: parseInt(process.env.PGWIRE_PORT || '5432'),
  database: process.env.PGWIRE_DATABASE || 'USER',
  user: process.env.PGWIRE_USERNAME || 'test_user',
  password: process.env.PGWIRE_PASSWORD || 'test',
  ssl: false, // Plain text for testing
});

describe('Basic Connection Tests', () => {
  test('should establish basic connection', async () => {
    // GIVEN: PGWire server is running
    const client = new Client(getConnectionConfig());

    // WHEN: Attempting to connect
    await client.connect();

    try {
      // THEN: Connection should be established
      expect(client).toBeDefined();

      // Verify with simple query
      const result = await client.query('SELECT 1');
      expect(result.rows).toHaveLength(1);
      expect(result.rows[0]['?column?']).toBe(1);
    } finally {
      await client.end();
    }
  });

  test('should connect with connection string', async () => {
    // GIVEN: Connection string
    const config = getConnectionConfig();
    const connectionString = `postgres://${config.user}:${config.password}@${config.host}:${config.port}/${config.database}`;

    const client = new Client({ connectionString, ssl: false });

    // WHEN: Connecting with connection string
    await client.connect();

    try {
      // THEN: Connection succeeds
      const result = await client.query('SELECT 1');
      expect(result.rows).toHaveLength(1);
    } finally {
      await client.end();
    }
  });

  test('should support connection pooling', async () => {
    // GIVEN: Connection pool configured
    const pool = new Pool({
      ...getConnectionConfig(),
      max: 10,
      min: 1,
    });

    try {
      // WHEN: Acquiring connections from pool
      const client1 = await pool.connect();
      const client2 = await pool.connect();

      // THEN: Both connections should work
      const result1 = await client1.query('SELECT 1');
      const result2 = await client2.query('SELECT 2');

      expect(result1.rows[0]['?column?']).toBe(1);
      expect(result2.rows[0]['?column?']).toBe(2);

      client1.release();
      client2.release();
    } finally {
      await pool.end();
    }
  });

  test('should handle multiple sequential connections', async () => {
    // GIVEN: Connection configuration
    const config = getConnectionConfig();

    // WHEN: Opening and closing connections sequentially
    for (let i = 0; i < 3; i++) {
      const client = new Client(config);
      await client.connect();

      // THEN: Each connection should succeed
      const result = await client.query('SELECT $1::int', [i + 1]);
      console.log(`Connection ${i} columns:`, result.fields.map(f => f.name));
      console.log(`Connection ${i} row:`, JSON.stringify(result.rows[0], null, 2));
      expect(result.rows[0].int4).toBe(i + 1);

      await client.end();
    }
  });

  test('should expose server information', async () => {
    // GIVEN: Active connection
    const client = new Client(getConnectionConfig());
    await client.connect();

    try {
      // WHEN: Querying server version
      const result = await client.query('SELECT version()');

      // THEN: Version should be available
      expect(result.rows).toHaveLength(1);
      const version = result.rows[0].version;
      expect(version).toBeDefined();
      console.log('Server version:', version);
    } finally {
      await client.end();
    }
  });

  test('should handle connection errors gracefully', async () => {
    // GIVEN: Invalid connection configuration
    const client = new Client({
      ...getConnectionConfig(),
      port: 9999, // Invalid port
    });

    // WHEN: Attempting to connect
    // THEN: Should throw connection error
    await expect(client.connect()).rejects.toThrow();
  });
});
