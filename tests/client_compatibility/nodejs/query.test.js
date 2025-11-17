import pg from 'pg';
const { Client } = pg;

/**
 * Test simple query execution via node-postgres driver.
 *
 * Tests P1 Simple Query Protocol:
 * - Query message handling
 * - IRIS SQL execution
 * - Row data encoding
 * - CommandComplete and ReadyForQuery
 */

const getConnectionConfig = () => ({
  host: process.env.PGWIRE_HOST || 'localhost',
  port: parseInt(process.env.PGWIRE_PORT || '5432'),
  database: process.env.PGWIRE_DATABASE || 'USER',
  user: process.env.PGWIRE_USERNAME || 'test_user',
  password: process.env.PGWIRE_PASSWORD || 'test',
  ssl: false,
});

describe('Simple Query Tests', () => {
  let client;

  beforeEach(async () => {
    client = new Client(getConnectionConfig());
    await client.connect();
  });

  afterEach(async () => {
    await client.end();
  });

  test('should execute SELECT constant', async () => {
    // WHEN: Executing SELECT 1
    const result = await client.query('SELECT 1');

    // THEN: Should return 1
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0]['?column?']).toBe(1);
  });

  test('should execute multi-column SELECT', async () => {
    // WHEN: Executing multi-column SELECT
    const result = await client.query("SELECT 1 AS num, 'hello' AS text, 3.14 AS float_val");

    // THEN: Should return all columns correctly
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].num).toBe(1);
    expect(result.rows[0].text).toBe('hello');
    expect(result.rows[0].float_val).toBeCloseTo(3.14, 2);
  });

  test('should handle NULL values', async () => {
    // WHEN: Executing SELECT with NULL
    const result = await client.query('SELECT NULL AS null_col, 42 AS num_col');

    // THEN: NULL should be handled correctly
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].null_col).toBeNull();
    expect(result.rows[0].num_col).toBe(42);
  });

  test('should execute multiple queries sequentially', async () => {
    // WHEN: Executing multiple queries
    const result1 = await client.query('SELECT 1');
    const result2 = await client.query("SELECT 'second query'");

    // THEN: Both queries should succeed
    expect(result1.rows[0]['?column?']).toBe(1);
    expect(result2.rows[0]['?column?']).toBe('second query');
  });

  test('should handle empty result set', async () => {
    // GIVEN: Empty table
    await client.query('CREATE TABLE IF NOT EXISTS test_empty (id INT)');
    await client.query('DELETE FROM test_empty');

    try {
      // WHEN: Querying empty table
      const result = await client.query('SELECT * FROM test_empty');

      // THEN: Result set should be empty
      expect(result.rows).toHaveLength(0);
    } finally {
      // Cleanup
      await client.query('DROP TABLE IF EXISTS test_empty');
    }
  });

  test('should provide result metadata', async () => {
    // WHEN: Executing query
    const result = await client.query('SELECT 1 AS id, \'test\' AS name');

    // THEN: Metadata should be available
    expect(result.fields).toHaveLength(2);
    expect(result.fields[0].name).toBe('id');
    expect(result.fields[1].name).toBe('name');
    expect(result.rowCount).toBe(1);
  });

  test('should handle string with special characters', async () => {
    // GIVEN: String with special characters
    const testString = "O'Reilly's \"Book\"";

    // WHEN: Querying with parameterized query
    const result = await client.query('SELECT $1::text AS text', [testString]);

    // THEN: String should be returned correctly
    expect(result.rows[0].text).toBe(testString);
  });

  test('should support parameterized queries', async () => {
    // WHEN: Executing parameterized query
    const result = await client.query('SELECT $1::int AS num, $2::text AS text', [42, 'hello']);

    // THEN: Parameters should be bound correctly
    expect(result.rows[0].num).toBe(42);
    expect(result.rows[0].text).toBe('hello');
  });

  test('should handle array result', async () => {
    // WHEN: Executing query with multiple rows
    const result = await client.query(`
      SELECT 1 AS id, 'first' AS name
      UNION ALL
      SELECT 2, 'second'
      UNION ALL
      SELECT 3, 'third'
    `);

    console.log('UNION result columns:', result.fields.map(f => f.name));
    console.log('UNION result row:', JSON.stringify(result.rows[0], null, 2));

    // THEN: Should return all rows
    expect(result.rows).toHaveLength(3);
    expect(result.rows[0].id).toBe(1);
    expect(result.rows[1].id).toBe(2);
    expect(result.rows[2].id).toBe(3);
  });
});

describe('Transaction Tests', () => {
  let client;

  beforeEach(async () => {
    client = new Client(getConnectionConfig());
    await client.connect();
  });

  afterEach(async () => {
    await client.end();
  });

  test('should support basic commit', async () => {
    // GIVEN: Test table
    await client.query('CREATE TABLE IF NOT EXISTS test_commit (id INT, value VARCHAR(50))');

    try {
      await client.query('DELETE FROM test_commit');

      // WHEN: Transaction with commit
      await client.query('BEGIN');
      await client.query("INSERT INTO test_commit VALUES (1, 'committed')");
      await client.query('COMMIT');

      // THEN: Data should persist
      const result = await client.query('SELECT COUNT(*) FROM test_commit');
      expect(parseInt(result.rows[0].count)).toBe(1);
    } finally {
      // Cleanup
      await client.query('DROP TABLE IF EXISTS test_commit');
    }
  });

  test('should support basic rollback', async () => {
    // GIVEN: Test table
    await client.query('CREATE TABLE IF NOT EXISTS test_rollback (id INT, value VARCHAR(50))');

    try {
      await client.query('DELETE FROM test_rollback');

      // WHEN: Transaction with rollback
      await client.query('BEGIN');
      await client.query("INSERT INTO test_rollback VALUES (1, 'will rollback')");
      await client.query('ROLLBACK');

      // THEN: Data should NOT persist
      const result = await client.query('SELECT COUNT(*) FROM test_rollback');
      expect(parseInt(result.rows[0].count)).toBe(0);
    } finally {
      // Cleanup
      await client.query('DROP TABLE IF EXISTS test_rollback');
    }
  });
});
