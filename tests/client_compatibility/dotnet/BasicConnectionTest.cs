using Npgsql;
using Xunit;

namespace PGWireCompatibility;

/// <summary>
/// Test basic Npgsql connection to IRIS PGWire server.
///
/// Tests P0 Handshake Protocol:
/// - SSL negotiation
/// - StartupMessage processing
/// - Authentication
/// - ReadyForQuery state
/// </summary>
public class BasicConnectionTest : IDisposable
{
    private readonly string connectionString;

    public BasicConnectionTest()
    {
        var host = Environment.GetEnvironmentVariable("PGWIRE_HOST") ?? "localhost";
        var port = Environment.GetEnvironmentVariable("PGWIRE_PORT") ?? "5432";
        var database = Environment.GetEnvironmentVariable("PGWIRE_DATABASE") ?? "USER";
        var username = Environment.GetEnvironmentVariable("PGWIRE_USERNAME") ?? "test_user";
        var password = Environment.GetEnvironmentVariable("PGWIRE_PASSWORD") ?? "test";

        connectionString = $"Host={host};Port={port};Database={database};Username={username};Password={password}";
    }

    public void Dispose()
    {
        // Cleanup if needed
    }

    [Fact]
    public async Task TestBasicConnection()
    {
        // GIVEN: PGWire server is running
        // WHEN: Attempting to connect
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // THEN: Connection should be established
        Assert.Equal(System.Data.ConnectionState.Open, conn.State);
        Assert.NotNull(conn.DataSource);
        Assert.NotNull(conn.Database);
    }

    [Fact]
    public async Task TestConnectionWithConnectionStringBuilder()
    {
        // GIVEN: Connection configured via builder
        var builder = new NpgsqlConnectionStringBuilder
        {
            Host = Environment.GetEnvironmentVariable("PGWIRE_HOST") ?? "localhost",
            Port = int.Parse(Environment.GetEnvironmentVariable("PGWIRE_PORT") ?? "5432"),
            Database = Environment.GetEnvironmentVariable("PGWIRE_DATABASE") ?? "USER",
            Username = Environment.GetEnvironmentVariable("PGWIRE_USERNAME") ?? "test_user",
            Password = Environment.GetEnvironmentVariable("PGWIRE_PASSWORD") ?? "test",
            SslMode = SslMode.Disable // Plain text for testing
        };

        // WHEN: Connecting with builder
        await using var conn = new NpgsqlConnection(builder.ConnectionString);
        await conn.OpenAsync();

        // THEN: Connection succeeds
        Assert.Equal(System.Data.ConnectionState.Open, conn.State);
    }

    [Fact]
    public async Task TestConnectionPooling()
    {
        // GIVEN: Connection string with pooling enabled
        var builder = new NpgsqlConnectionStringBuilder(connectionString)
        {
            Pooling = true,
            MinPoolSize = 1,
            MaxPoolSize = 10
        };

        // WHEN: Opening multiple connections
        await using var conn1 = new NpgsqlConnection(builder.ConnectionString);
        await using var conn2 = new NpgsqlConnection(builder.ConnectionString);

        await conn1.OpenAsync();
        await conn2.OpenAsync();

        // THEN: Both connections should be open
        Assert.Equal(System.Data.ConnectionState.Open, conn1.State);
        Assert.Equal(System.Data.ConnectionState.Open, conn2.State);
    }

    [Fact]
    public async Task TestServerVersion()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Querying server version
        var serverVersion = conn.ServerVersion;

        // THEN: Version should be available
        Assert.NotNull(serverVersion);
        Assert.NotEmpty(serverVersion);
        Console.WriteLine($"Server Version: {serverVersion}");
    }

    [Fact]
    public async Task TestConnectionInfo()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Querying connection info
        // THEN: Connection properties should be accessible
        Assert.NotNull(conn.Host);
        Assert.NotNull(conn.Database);
        Assert.True(conn.Port > 0);

        Console.WriteLine($"Host: {conn.Host}");
        Console.WriteLine($"Port: {conn.Port}");
        Console.WriteLine($"Database: {conn.Database}");
        Console.WriteLine($"Server Version: {conn.ServerVersion}");
    }

    [Fact]
    public async Task TestMultipleSequentialConnections()
    {
        // GIVEN: Connection string
        // WHEN: Opening and closing connections sequentially
        for (int i = 0; i < 3; i++)
        {
            await using var conn = new NpgsqlConnection(connectionString);
            await conn.OpenAsync();

            // THEN: Each connection should succeed
            Assert.Equal(System.Data.ConnectionState.Open, conn.State);
            await conn.CloseAsync();
            Assert.Equal(System.Data.ConnectionState.Closed, conn.State);
        }
    }
}
