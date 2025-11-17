package com.intersystems.iris.pgwire;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.AfterAll;
import static org.junit.jupiter.api.Assertions.*;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Properties;

/**
 * Test basic PostgreSQL JDBC connection to IRIS PGWire server.
 *
 * Tests P0 Handshake Protocol:
 * - SSL negotiation
 * - StartupMessage processing
 * - Authentication
 * - ReadyForQuery state
 */
public class BasicConnectionTest {

    private static String host;
    private static int port;
    private static String database;
    private static String username;
    private static String password;

    @BeforeAll
    public static void setup() {
        host = System.getProperty("pgwire.host", "localhost");
        port = Integer.parseInt(System.getProperty("pgwire.port", "5432"));
        database = System.getProperty("pgwire.database", "USER");
        username = System.getProperty("pgwire.username", "test_user");
        password = System.getProperty("pgwire.password", "test");
    }

    @Test
    public void testBasicConnection() throws SQLException {
        // GIVEN: PGWire server is running
        String url = String.format("jdbc:postgresql://%s:%d/%s", host, port, database);

        // WHEN: Attempting to connect
        try (Connection conn = DriverManager.getConnection(url, username, password)) {
            // THEN: Connection should be established
            assertNotNull(conn, "Connection should not be null");
            assertFalse(conn.isClosed(), "Connection should be open");
            assertTrue(conn.isValid(5), "Connection should be valid within 5 seconds");
        }
    }

    @Test
    public void testConnectionWithProperties() throws SQLException {
        // GIVEN: Connection properties configured
        String url = String.format("jdbc:postgresql://%s:%d/%s", host, port, database);
        Properties props = new Properties();
        props.setProperty("user", username);
        props.setProperty("password", password);
        props.setProperty("ApplicationName", "JDBC-Compatibility-Test");
        props.setProperty("ssl", "false"); // Plain text for testing

        // WHEN: Connecting with properties
        try (Connection conn = DriverManager.getConnection(url, props)) {
            // THEN: Connection succeeds with properties
            assertNotNull(conn);
            assertFalse(conn.isClosed());
        }
    }

    @Test
    public void testConnectionMetadata() throws SQLException {
        // GIVEN: Active connection
        String url = String.format("jdbc:postgresql://%s:%d/%s", host, port, database);

        try (Connection conn = DriverManager.getConnection(url, username, password)) {
            // WHEN: Querying connection metadata
            var metadata = conn.getMetaData();

            // THEN: Metadata should be available
            assertNotNull(metadata, "Database metadata should not be null");
            assertTrue(metadata.getDatabaseProductName().contains("IRIS") ||
                      metadata.getDatabaseProductName().contains("PostgreSQL"),
                      "Database product should be IRIS or PostgreSQL-compatible");

            System.out.println("Database Product: " + metadata.getDatabaseProductName());
            System.out.println("Database Version: " + metadata.getDatabaseProductVersion());
            System.out.println("Driver Name: " + metadata.getDriverName());
            System.out.println("Driver Version: " + metadata.getDriverVersion());
        }
    }

    @Test
    public void testAutoCommitDefault() throws SQLException {
        // GIVEN: New connection
        String url = String.format("jdbc:postgresql://%s:%d/%s", host, port, database);

        try (Connection conn = DriverManager.getConnection(url, username, password)) {
            // THEN: Auto-commit should be enabled by default
            assertTrue(conn.getAutoCommit(), "Auto-commit should be enabled by default");
        }
    }

    @Test
    public void testReadOnlyMode() throws SQLException {
        // GIVEN: Active connection
        String url = String.format("jdbc:postgresql://%s:%d/%s", host, port, database);

        try (Connection conn = DriverManager.getConnection(url, username, password)) {
            // WHEN: Setting read-only mode
            conn.setReadOnly(false);

            // THEN: Read-only status should be queryable
            assertFalse(conn.isReadOnly(), "Connection should not be read-only");
        }
    }
}
