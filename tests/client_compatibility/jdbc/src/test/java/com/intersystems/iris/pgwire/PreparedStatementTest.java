package com.intersystems.iris.pgwire;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeAll;
import static org.junit.jupiter.api.Assertions.*;

import java.sql.*;

/**
 * Test prepared statement execution via PostgreSQL JDBC driver.
 *
 * Tests P2 Extended Protocol:
 * - Parse message (prepared statement creation)
 * - Bind message (parameter binding)
 * - Describe message (metadata)
 * - Execute message (query execution)
 */
public class PreparedStatementTest {

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
    public void testPreparedStatementWithSingleParameter() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {

            // WHEN: Creating and executing prepared statement
            String sql = "SELECT ? AS value";
            try (PreparedStatement pstmt = conn.prepareStatement(sql)) {
                pstmt.setInt(1, 42);
                ResultSet rs = pstmt.executeQuery();

                // THEN: Should return parameterized value
                assertTrue(rs.next());
                assertEquals(42, rs.getInt("value"));
                assertFalse(rs.next());
            }
        }
    }

    @Test
    public void testPreparedStatementWithMultipleParameters() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {

            // WHEN: Preparing statement with multiple parameters
            String sql = "SELECT ? AS num, ? AS text, ? AS flag";
            try (PreparedStatement pstmt = conn.prepareStatement(sql)) {
                pstmt.setInt(1, 123);
                pstmt.setString(2, "hello");
                pstmt.setBoolean(3, true);
                ResultSet rs = pstmt.executeQuery();

                // THEN: All parameters should be bound correctly
                assertTrue(rs.next());
                assertEquals(123, rs.getInt("num"));
                assertEquals("hello", rs.getString("text"));
                assertTrue(rs.getBoolean("flag"));
            }
        }
    }

    @Test
    public void testPreparedStatementReuse() throws SQLException {
        // GIVEN: Prepared statement
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {
            String sql = "SELECT ? * 2 AS doubled";
            try (PreparedStatement pstmt = conn.prepareStatement(sql)) {

                // WHEN: Executing same statement with different parameters
                pstmt.setInt(1, 5);
                ResultSet rs1 = pstmt.executeQuery();
                assertTrue(rs1.next());
                assertEquals(10, rs1.getInt("doubled"));

                pstmt.setInt(1, 7);
                ResultSet rs2 = pstmt.executeQuery();
                assertTrue(rs2.next());
                assertEquals(14, rs2.getInt("doubled"));

                // THEN: Statement should work correctly on reuse
                // (implicit assertion: no exceptions)
            }
        }
    }

    @Test
    public void testPreparedStatementWithNullParameter() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {

            // WHEN: Binding NULL parameter
            String sql = "SELECT ? AS null_val";
            try (PreparedStatement pstmt = conn.prepareStatement(sql)) {
                pstmt.setNull(1, Types.VARCHAR);
                ResultSet rs = pstmt.executeQuery();

                // THEN: NULL should be handled correctly
                assertTrue(rs.next());
                assertNull(rs.getObject("null_val"));
                assertTrue(rs.wasNull());
            }
        }
    }

    @Test
    public void testPreparedStatementMetadata() throws SQLException {
        // GIVEN: Prepared statement
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {
            String sql = "SELECT ? AS id, ? AS name";
            try (PreparedStatement pstmt = conn.prepareStatement(sql)) {

                // WHEN: Querying parameter metadata
                ParameterMetaData paramMeta = pstmt.getParameterMetaData();

                // THEN: Metadata should describe parameters
                assertEquals(2, paramMeta.getParameterCount(), "Should have 2 parameters");
                System.out.println("Parameter count: " + paramMeta.getParameterCount());

                // Note: Not all drivers fully support getParameterType/getParameterTypeName
                // Just verify metadata is accessible
                assertNotNull(paramMeta);
            }
        }
    }

    @Test
    public void testPreparedStatementWithStringParameter() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {

            // WHEN: Binding string with special characters
            String sql = "SELECT ? AS text";
            try (PreparedStatement pstmt = conn.prepareStatement(sql)) {
                String testString = "O'Reilly's \"Book\"";
                pstmt.setString(1, testString);
                ResultSet rs = pstmt.executeQuery();

                // THEN: String should be properly escaped and returned
                assertTrue(rs.next());
                assertEquals(testString, rs.getString("text"));
            }
        }
    }

    @Test
    public void testPreparedStatementWithDateParameter() throws SQLException {
        // GIVEN: Active connection
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password)) {

            // WHEN: Binding date parameter
            String sql = "SELECT ? AS test_date";
            try (PreparedStatement pstmt = conn.prepareStatement(sql)) {
                Date testDate = Date.valueOf("2024-01-15");
                pstmt.setDate(1, testDate);
                ResultSet rs = pstmt.executeQuery();

                // THEN: Date should be returned correctly
                assertTrue(rs.next());
                Date resultDate = rs.getDate("test_date");
                assertNotNull(resultDate);
                assertEquals(testDate, resultDate);
            }
        }
    }

    @Test
    public void testPreparedStatementBatch() throws SQLException {
        // GIVEN: Active connection and test table
        try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
             Statement stmt = conn.createStatement()) {

            stmt.execute("CREATE TABLE IF NOT EXISTS test_batch (id INT, value VARCHAR(50))");

            try {
                // Clear table
                stmt.execute("DELETE FROM test_batch");

                // WHEN: Executing batch insert
                String sql = "INSERT INTO test_batch (id, value) VALUES (?, ?)";
                try (PreparedStatement pstmt = conn.prepareStatement(sql)) {
                    pstmt.setInt(1, 1);
                    pstmt.setString(2, "first");
                    pstmt.addBatch();

                    pstmt.setInt(1, 2);
                    pstmt.setString(2, "second");
                    pstmt.addBatch();

                    int[] results = pstmt.executeBatch();

                    // THEN: Batch should execute successfully
                    assertEquals(2, results.length);
                    for (int result : results) {
                        assertTrue(result >= 0 || result == Statement.SUCCESS_NO_INFO);
                    }
                }

                // Verify data was inserted
                ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM test_batch");
                assertTrue(rs.next());
                assertEquals(2, rs.getInt(1));

            } finally {
                // Cleanup
                stmt.execute("DROP TABLE IF EXISTS test_batch");
            }
        }
    }
}
