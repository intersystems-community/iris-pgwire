package com.intersystems.iris.pgwire;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeAll;
import static org.junit.jupiter.api.Assertions.*;

import java.sql.*;

/**
 * Test simple query execution via PostgreSQL JDBC driver.
 *
 * Tests P1 Simple Query Protocol:
 * - Query message handling
 * - IRIS SQL execution
 * - Row data encoding
 * - CommandComplete and ReadyForQuery
 */
public class SimpleQueryTest {

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
    public void testSelectConstant() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            // WHEN: Executing SELECT 1
            ResultSet rs = stmt.executeQuery("SELECT 1");

            // THEN: Should return single row with value 1
            assertTrue(rs.next(), "Result set should have at least one row");
            assertEquals(1, rs.getInt(1), "First column should be 1");
            assertFalse(rs.next(), "Result set should have only one row");
        }
    }

    @Test
    public void testSelectMultipleColumns() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            // WHEN: Executing multi-column SELECT
            ResultSet rs = stmt.executeQuery("SELECT 1 AS num, 'hello' AS text, 3.14 AS float_val");

            // THEN: Should return all columns correctly
            assertTrue(rs.next());
            assertEquals(1, rs.getInt("num"));
            assertEquals("hello", rs.getString("text"));
            assertEquals(3.14, rs.getDouble("float_val"), 0.001);
        }
    }

    @Test
    public void testSelectCurrentTimestamp() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            // WHEN: Executing SELECT CURRENT_TIMESTAMP
            ResultSet rs = stmt.executeQuery("SELECT CURRENT_TIMESTAMP");

            // THEN: Should return a timestamp
            assertTrue(rs.next());
            Timestamp ts = rs.getTimestamp(1);
            assertNotNull(ts, "CURRENT_TIMESTAMP should return a value");
            System.out.println("Current Timestamp: " + ts);
        }
    }

    @Test
    public void testSelectWithNullValue() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            // WHEN: Executing SELECT with NULL
            ResultSet rs = stmt.executeQuery("SELECT NULL AS null_col, 42 AS num_col");

            // THEN: NULL should be handled correctly
            assertTrue(rs.next());
            assertNull(rs.getObject("null_col"), "null_col should be NULL");
            assertTrue(rs.wasNull(), "wasNull() should return true after reading NULL");
            assertEquals(42, rs.getInt("num_col"));
        }
    }

    @Test
    public void testMultipleQueries() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            // WHEN: Executing multiple queries sequentially
            ResultSet rs1 = stmt.executeQuery("SELECT 1");
            assertTrue(rs1.next());
            assertEquals(1, rs1.getInt(1));
            rs1.close();

            ResultSet rs2 = stmt.executeQuery("SELECT 'second query'");
            assertTrue(rs2.next());
            assertEquals("second query", rs2.getString(1));
            rs2.close();

            // THEN: Both queries should succeed
            // (implicit assertion: no exceptions thrown)
        }
    }

    @Test
    public void testResultSetMetadata() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            // WHEN: Executing query and examining metadata
            ResultSet rs = stmt.executeQuery("SELECT 1 AS id, 'test' AS name");
            ResultSetMetaData metadata = rs.getMetaData();

            // THEN: Metadata should describe result columns
            assertEquals(2, metadata.getColumnCount(), "Should have 2 columns");
            assertEquals("id", metadata.getColumnName(1).toLowerCase());
            assertEquals("name", metadata.getColumnName(2).toLowerCase());
            assertEquals(Types.INTEGER, metadata.getColumnType(1));
            assertEquals(Types.VARCHAR, metadata.getColumnType(2));

            System.out.println("Column 1: " + metadata.getColumnName(1) + " (type: " + metadata.getColumnTypeName(1) + ")");
            System.out.println("Column 2: " + metadata.getColumnName(2) + " (type: " + metadata.getColumnTypeName(2) + ")");
        }
    }

    @Test
    public void testEmptyResultSet() throws SQLException {
        // GIVEN: Active connection and a table with no rows
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            // Create temporary table
            stmt.execute("CREATE TABLE IF NOT EXISTS test_empty (id INT)");

            try {
                // Delete all rows to ensure empty
                stmt.execute("DELETE FROM test_empty");

                // WHEN: Querying empty table
                ResultSet rs = stmt.executeQuery("SELECT * FROM test_empty");

                // THEN: Result set should be empty
                assertFalse(rs.next(), "Result set should be empty");
            } finally {
                // Cleanup
                stmt.execute("DROP TABLE IF EXISTS test_empty");
            }
        }
    }
}
