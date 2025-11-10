package com.intersystems.iris.pgwire;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeAll;
import static org.junit.jupiter.api.Assertions.*;

import java.sql.*;

/**
 * Test transaction management via PostgreSQL JDBC driver.
 *
 * Tests transaction commands:
 * - BEGIN (translated to START TRANSACTION by Feature 022)
 * - COMMIT
 * - ROLLBACK
 * - Auto-commit mode
 */
public class TransactionTest {

    private static String jdbcUrl;
    private static String username;
    private static String password;

    @BeforeAll
    public static void setup() {
        String host = System.getProperty("pgwire.host", "localhost");
        int port = Integer.parseInt(System.getProperty("pgwire.port", "5432"));
        String database = System.getProperty("pgwire.database", "USER");
        username = System.getProperty("pgwire.username", "test_user");
        password = System.getProperty("pgwire.password", "test");

        jdbcUrl = String.format("jdbc:postgresql://%s:%d/%s", host, port, database);
    }

    @Test
    public void testBasicCommit() throws SQLException {
        // GIVEN: Active connection with test table
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            stmt.execute("CREATE TABLE IF NOT EXISTS test_commit (id INT, value VARCHAR(50))");

            try {
                stmt.execute("DELETE FROM test_commit");
                conn.setAutoCommit(false);

                // WHEN: Inserting data and committing
                stmt.execute("INSERT INTO test_commit VALUES (1, 'committed')");
                conn.commit();

                // THEN: Data should persist
                ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM test_commit");
                assertTrue(rs.next());
                assertEquals(1, rs.getInt(1));

            } finally {
                conn.setAutoCommit(true);
                stmt.execute("DROP TABLE IF EXISTS test_commit");
            }
        }
    }

    @Test
    public void testBasicRollback() throws SQLException {
        // GIVEN: Active connection with test table
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            stmt.execute("CREATE TABLE IF NOT EXISTS test_rollback (id INT, value VARCHAR(50))");

            try {
                stmt.execute("DELETE FROM test_rollback");
                conn.setAutoCommit(false);

                // WHEN: Inserting data and rolling back
                stmt.execute("INSERT INTO test_rollback VALUES (1, 'will rollback')");
                conn.rollback();

                // THEN: Data should NOT persist
                ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM test_rollback");
                assertTrue(rs.next());
                assertEquals(0, rs.getInt(1), "Table should be empty after rollback");

            } finally {
                conn.setAutoCommit(true);
                stmt.execute("DROP TABLE IF EXISTS test_rollback");
            }
        }
    }

    @Test
    public void testMultipleOperationsInTransaction() throws SQLException {
        // GIVEN: Active connection with test table
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            stmt.execute("CREATE TABLE IF NOT EXISTS test_multi (id INT, value VARCHAR(50))");

            try {
                stmt.execute("DELETE FROM test_multi");
                conn.setAutoCommit(false);

                // WHEN: Multiple operations in single transaction
                stmt.execute("INSERT INTO test_multi VALUES (1, 'first')");
                stmt.execute("INSERT INTO test_multi VALUES (2, 'second')");
                stmt.execute("INSERT INTO test_multi VALUES (3, 'third')");
                conn.commit();

                // THEN: All operations should be committed
                ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM test_multi");
                assertTrue(rs.next());
                assertEquals(3, rs.getInt(1));

            } finally {
                conn.setAutoCommit(true);
                stmt.execute("DROP TABLE IF EXISTS test_multi");
            }
        }
    }

    @Test
    public void testAutoCommitMode() throws SQLException {
        // GIVEN: Active connection with test table
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            stmt.execute("CREATE TABLE IF NOT EXISTS test_autocommit (id INT, value VARCHAR(50))");

            try {
                stmt.execute("DELETE FROM test_autocommit");

                // Ensure auto-commit is enabled
                conn.setAutoCommit(true);
                assertTrue(conn.getAutoCommit());

                // WHEN: Inserting without explicit commit
                stmt.execute("INSERT INTO test_autocommit VALUES (1, 'auto-committed')");

                // THEN: Data should be immediately visible
                ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM test_autocommit");
                assertTrue(rs.next());
                assertEquals(1, rs.getInt(1), "Data should be auto-committed");

            } finally {
                stmt.execute("DROP TABLE IF EXISTS test_autocommit");
            }
        }
    }

    @Test
    public void testTransactionIsolation() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {

            // WHEN: Querying and setting transaction isolation
            int currentIsolation = conn.getTransactionIsolation();
            assertNotEquals(Connection.TRANSACTION_NONE, currentIsolation,
                           "Transaction isolation should be set");

            System.out.println("Current isolation level: " + getIsolationLevelName(currentIsolation));

            // Try setting isolation level (may not be fully supported)
            try {
                conn.setTransactionIsolation(Connection.TRANSACTION_READ_COMMITTED);
                System.out.println("Successfully set isolation to READ_COMMITTED");
            } catch (SQLException e) {
                System.out.println("Setting isolation level not supported: " + e.getMessage());
            }
        }
    }

    @Test
    public void testSavepointNotSupported() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {
            conn.setAutoCommit(false);

            try {
                // WHEN: Attempting to create savepoint
                // THEN: May throw SQLFeatureNotSupportedException
                Savepoint sp = conn.setSavepoint("test_savepoint");

                // If savepoints are supported, test rollback to savepoint
                conn.rollback(sp);
                System.out.println("Savepoints are supported");

            } catch (SQLFeatureNotSupportedException e) {
                // Expected if savepoints not implemented
                System.out.println("Savepoints not supported (expected): " + e.getMessage());
            } finally {
                conn.setAutoCommit(true);
            }
        }
    }

    @Test
    public void testRollbackOnError() throws SQLException {
        // GIVEN: Active connection with test table
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            stmt.execute("CREATE TABLE IF NOT EXISTS test_error (id INT PRIMARY KEY, value VARCHAR(50))");

            try {
                stmt.execute("DELETE FROM test_error");
                conn.setAutoCommit(false);

                // WHEN: Transaction with error
                stmt.execute("INSERT INTO test_error VALUES (1, 'first')");

                try {
                    // This should fail (duplicate primary key)
                    stmt.execute("INSERT INTO test_error VALUES (1, 'duplicate')");
                    fail("Should have thrown SQLException for duplicate key");
                } catch (SQLException e) {
                    // Expected error
                    System.out.println("Expected error: " + e.getMessage());
                    conn.rollback();
                }

                // THEN: After rollback, table should be empty
                ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM test_error");
                assertTrue(rs.next());
                assertEquals(0, rs.getInt(1), "Table should be empty after rollback");

            } finally {
                conn.setAutoCommit(true);
                stmt.execute("DROP TABLE IF EXISTS test_error");
            }
        }
    }

    private String getIsolationLevelName(int level) {
        switch (level) {
            case Connection.TRANSACTION_NONE:
                return "NONE";
            case Connection.TRANSACTION_READ_UNCOMMITTED:
                return "READ_UNCOMMITTED";
            case Connection.TRANSACTION_READ_COMMITTED:
                return "READ_COMMITTED";
            case Connection.TRANSACTION_REPEATABLE_READ:
                return "REPEATABLE_READ";
            case Connection.TRANSACTION_SERIALIZABLE:
                return "SERIALIZABLE";
            default:
                return "UNKNOWN (" + level + ")";
        }
    }
}
