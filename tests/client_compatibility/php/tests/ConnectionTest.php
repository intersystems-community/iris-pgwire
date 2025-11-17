<?php

namespace IrisPGWire\Tests;

use PHPUnit\Framework\TestCase;
use PDO;
use PDOException;

class ConnectionTest extends TestCase
{
    private function getConnectionConfig(): array
    {
        return [
            'host' => getenv('PGWIRE_HOST') ?: 'localhost',
            'port' => getenv('PGWIRE_PORT') ?: '5432',
            'dbname' => getenv('PGWIRE_DATABASE') ?: 'USER',
            'user' => getenv('PGWIRE_USERNAME') ?: 'test_user',
            'password' => getenv('PGWIRE_PASSWORD') ?: 'test'
        ];
    }

    private function createConnection(): PDO
    {
        $config = $this->getConnectionConfig();
        $dsn = sprintf(
            'pgsql:host=%s;port=%s;dbname=%s',
            $config['host'],
            $config['port'],
            $config['dbname']
        );

        return new PDO(
            $dsn,
            $config['user'],
            $config['password'],
            [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
            ]
        );
    }

    public function testBasicConnection(): void
    {
        // GIVEN: Connection configuration
        // WHEN: Establishing connection
        $pdo = $this->createConnection();

        // THEN: Should execute simple query
        $stmt = $pdo->query('SELECT 1 as value');
        $result = $stmt->fetch();

        $this->assertEquals(1, $result['value'], 'Should return 1');
    }

    public function testConnectionWithDSN(): void
    {
        // GIVEN: DSN connection string
        $config = $this->getConnectionConfig();
        $dsn = sprintf(
            'pgsql:host=%s;port=%s;dbname=%s;user=%s;password=%s',
            $config['host'],
            $config['port'],
            $config['dbname'],
            $config['user'],
            $config['password']
        );

        // WHEN: Connecting with DSN
        $pdo = new PDO($dsn);

        // THEN: Connection should work
        $stmt = $pdo->query('SELECT 42 as answer');
        $result = $stmt->fetch(PDO::FETCH_ASSOC);

        $this->assertEquals(42, $result['answer']);
    }

    public function testMultipleSequentialConnections(): void
    {
        // GIVEN: Multiple connection attempts
        // WHEN: Creating sequential connections
        for ($i = 1; $i <= 3; $i++) {
            $pdo = $this->createConnection();
            $stmt = $pdo->query("SELECT {$i} as num");
            $result = $stmt->fetch();

            // THEN: Each connection should work
            $this->assertEquals($i, $result['num']);
            unset($pdo); // Close connection
        }
    }

    public function testServerVersion(): void
    {
        // GIVEN: Connected client
        $pdo = $this->createConnection();

        // WHEN: Querying server version
        $version = $pdo->getAttribute(PDO::ATTR_SERVER_VERSION);

        // THEN: Should return version string
        $this->assertIsString($version);
        $this->assertNotEmpty($version);
    }

    public function testConnectionErrorHandling(): void
    {
        // GIVEN: Invalid connection parameters
        // WHEN: Attempting connection with wrong host
        $this->expectException(PDOException::class);

        new PDO(
            'pgsql:host=invalid-host;port=9999;dbname=USER',
            'test_user',
            'test',
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );

        // THEN: Should throw PDOException
    }

    public function testMultipleQueriesPerConnection(): void
    {
        // GIVEN: Single connection
        $pdo = $this->createConnection();

        // WHEN: Executing multiple queries
        $stmt1 = $pdo->query('SELECT 1 as value');
        $result1 = $stmt1->fetch();

        $stmt2 = $pdo->query('SELECT 2 as value');
        $result2 = $stmt2->fetch();

        $stmt3 = $pdo->query('SELECT 3 as value');
        $result3 = $stmt3->fetch();

        // THEN: All queries should succeed
        $this->assertEquals(1, $result1['value']);
        $this->assertEquals(2, $result2['value']);
        $this->assertEquals(3, $result3['value']);
    }
}
