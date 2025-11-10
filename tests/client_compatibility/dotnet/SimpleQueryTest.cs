using Npgsql;
using Xunit;

namespace PGWireCompatibility;

/// <summary>
/// Test simple query execution via Npgsql driver.
///
/// Tests P1 Simple Query Protocol:
/// - Query message handling
/// - IRIS SQL execution
/// - Row data encoding
/// - CommandComplete and ReadyForQuery
/// </summary>
public class SimpleQueryTest
{
    private readonly string connectionString;

    public SimpleQueryTest()
    {
        var host = Environment.GetEnvironmentVariable("PGWIRE_HOST") ?? "localhost";
        var port = Environment.GetEnvironmentVariable("PGWIRE_PORT") ?? "5432";
        var database = Environment.GetEnvironmentVariable("PGWIRE_DATABASE") ?? "USER";
        var username = Environment.GetEnvironmentVariable("PGWIRE_USERNAME") ?? "test_user";
        var password = Environment.GetEnvironmentVariable("PGWIRE_PASSWORD") ?? "test";

        connectionString = $"Host={host};Port={port};Database={database};Username={username};Password={password}";
    }

    [Fact]
    public async Task TestSelectConstant()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Executing SELECT 1
        await using var cmd = new NpgsqlCommand("SELECT 1", conn);
        var result = await cmd.ExecuteScalarAsync();

        // THEN: Should return 1
        Assert.NotNull(result);
        Assert.Equal(1, Convert.ToInt32(result));
    }

    [Fact]
    public async Task TestSelectMultipleColumns()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Executing multi-column SELECT
        await using var cmd = new NpgsqlCommand("SELECT 1 AS num, 'hello' AS text, 3.14 AS float_val", conn);
        await using var reader = await cmd.ExecuteReaderAsync();

        // THEN: Should return all columns correctly
        Assert.True(await reader.ReadAsync());
        Assert.Equal(1, reader.GetInt32(0));
        Assert.Equal("hello", reader.GetString(1));
        Assert.Equal(3.14, reader.GetDouble(2), precision: 2);
        Assert.False(await reader.ReadAsync());
    }

    [Fact]
    public async Task TestSelectCurrentTimestamp()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Executing SELECT CURRENT_TIMESTAMP
        await using var cmd = new NpgsqlCommand("SELECT CURRENT_TIMESTAMP", conn);
        var result = await cmd.ExecuteScalarAsync();

        // THEN: Should return a timestamp
        Assert.NotNull(result);
        Assert.IsType<DateTime>(result);
        Console.WriteLine($"Current Timestamp: {result}");
    }

    [Fact]
    public async Task TestSelectWithNullValue()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Executing SELECT with NULL
        await using var cmd = new NpgsqlCommand("SELECT NULL AS null_col, 42 AS num_col", conn);
        await using var reader = await cmd.ExecuteReaderAsync();

        // THEN: NULL should be handled correctly
        Assert.True(await reader.ReadAsync());
        Assert.True(reader.IsDBNull(0));
        Assert.Equal(42, reader.GetInt32(1));
    }

    [Fact]
    public async Task TestMultipleQueries()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Executing multiple queries sequentially
        await using var cmd1 = new NpgsqlCommand("SELECT 1", conn);
        var result1 = await cmd1.ExecuteScalarAsync();
        Assert.Equal(1, Convert.ToInt32(result1));

        await using var cmd2 = new NpgsqlCommand("SELECT 'second query'", conn);
        var result2 = await cmd2.ExecuteScalarAsync();
        Assert.Equal("second query", result2);

        // THEN: Both queries should succeed
        // (implicit assertion: no exceptions thrown)
    }

    [Fact]
    public async Task TestExecuteNonQuery()
    {
        // GIVEN: Active connection with test table
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        await using var createCmd = new NpgsqlCommand("CREATE TABLE IF NOT EXISTS test_nonquery (id INT)", conn);
        await createCmd.ExecuteNonQueryAsync();

        try
        {
            // WHEN: Executing DELETE
            await using var deleteCmd = new NpgsqlCommand("DELETE FROM test_nonquery", conn);
            var rowsAffected = await deleteCmd.ExecuteNonQueryAsync();

            // THEN: Should return number of rows affected (may be 0)
            Assert.True(rowsAffected >= 0);
        }
        finally
        {
            // Cleanup
            await using var dropCmd = new NpgsqlCommand("DROP TABLE IF EXISTS test_nonquery", conn);
            await dropCmd.ExecuteNonQueryAsync();
        }
    }

    [Fact]
    public async Task TestDataReaderColumnMetadata()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Executing query and examining metadata
        await using var cmd = new NpgsqlCommand("SELECT 1 AS id, 'test' AS name", conn);
        await using var reader = await cmd.ExecuteReaderAsync();

        // THEN: Metadata should describe result columns
        Assert.Equal(2, reader.FieldCount);
        Assert.Equal("id", reader.GetName(0).ToLower());
        Assert.Equal("name", reader.GetName(1).ToLower());

        Console.WriteLine($"Column 0: {reader.GetName(0)} (type: {reader.GetDataTypeName(0)})");
        Console.WriteLine($"Column 1: {reader.GetName(1)} (type: {reader.GetDataTypeName(1)})");
    }

    [Fact]
    public async Task TestEmptyResultSet()
    {
        // GIVEN: Active connection and a table with no rows
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        await using var createCmd = new NpgsqlCommand("CREATE TABLE IF NOT EXISTS test_empty (id INT)", conn);
        await createCmd.ExecuteNonQueryAsync();

        try
        {
            // Delete all rows to ensure empty
            await using var deleteCmd = new NpgsqlCommand("DELETE FROM test_empty", conn);
            await deleteCmd.ExecuteNonQueryAsync();

            // WHEN: Querying empty table
            await using var selectCmd = new NpgsqlCommand("SELECT * FROM test_empty", conn);
            await using var reader = await selectCmd.ExecuteReaderAsync();

            // THEN: Result set should be empty
            Assert.False(await reader.ReadAsync());
        }
        finally
        {
            // Cleanup
            await using var dropCmd = new NpgsqlCommand("DROP TABLE IF EXISTS test_empty", conn);
            await dropCmd.ExecuteNonQueryAsync();
        }
    }

    [Fact]
    public async Task TestStringWithSpecialCharacters()
    {
        // GIVEN: Active connection
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync();

        // WHEN: Selecting string with quotes and special characters
        var testString = "O'Reilly's \"Book\"";
        await using var cmd = new NpgsqlCommand($"SELECT '{testString.Replace("'", "''")}'", conn);
        var result = await cmd.ExecuteScalarAsync();

        // THEN: String should be returned correctly
        Assert.Equal(testString, result?.ToString());
    }
}
