<?php

namespace IrisPGWire\Tests;

use PHPUnit\Framework\TestCase;
use PDO;
use DateTime;

class QueryTest extends TestCase
{
    private PDO $pdo;

    protected function setUp(): void
    {
        $config = [
            'host' => getenv('PGWIRE_HOST') ?: 'localhost',
            'port' => getenv('PGWIRE_PORT') ?: '5432',
            'dbname' => getenv('PGWIRE_DATABASE') ?: 'USER',
            'user' => getenv('PGWIRE_USERNAME') ?: 'test_user',
            'password' => getenv('PGWIRE_PASSWORD') ?: 'test'
        ];

        $dsn = sprintf(
            'pgsql:host=%s;port=%s;dbname=%s',
            $config['host'],
            $config['port'],
            $config['dbname']
        );

        $this->pdo = new PDO(
            $dsn,
            $config['user'],
            $config['password'],
            [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
            ]
        );
    }

    public function testSelectConstant(): void
    {
        // GIVEN: Connected client
        // WHEN: Executing SELECT with constant
        $stmt = $this->pdo->query('SELECT 42 as answer');
        $result = $stmt->fetch();

        // THEN: Should return constant value
        $this->assertEquals(42, $result['answer']);
    }

    public function testSelectMultipleColumns(): void
    {
        // GIVEN: Connected client
        // WHEN: Selecting multiple columns
        $stmt = $this->pdo->query("SELECT 1 as num, 'hello' as text, 3.14 as pi");
        $result = $stmt->fetch();

        // THEN: All columns should be returned
        $this->assertEquals(1, $result['num']);
        $this->assertEquals('hello', $result['text']);
        $this->assertEqualsWithDelta(3.14, (float)$result['pi'], 0.001);
    }

    public function testSelectCurrentTimestamp(): void
    {
        // GIVEN: Connected client
        // WHEN: Selecting CURRENT_TIMESTAMP
        $stmt = $this->pdo->query('SELECT CURRENT_TIMESTAMP as ts');
        $result = $stmt->fetch();

        // THEN: Should return timestamp string
        $this->assertIsString($result['ts']);
        $this->assertNotEmpty($result['ts']);

        // Verify timestamp is reasonable (within last hour)
        $timestamp = strtotime($result['ts']);
        $now = time();
        $diff = abs($now - $timestamp);
        $this->assertLessThan(3600, $diff, 'Timestamp should be within last hour');
    }

    public function testSelectWithNull(): void
    {
        // GIVEN: Connected client
        // WHEN: Selecting NULL in comparison
        $stmt = $this->pdo->query('SELECT 1 WHERE 1=0');
        $result = $stmt->fetch();

        // THEN: Empty result set
        $this->assertFalse($result, 'Empty result set should return false');
    }

    public function testPreparedStatementSingleParam(): void
    {
        // GIVEN: Connected client
        // WHEN: Using prepared statement with parameter
        $stmt = $this->pdo->prepare('SELECT :value as result');
        $stmt->execute(['value' => 99]);
        $result = $stmt->fetch();

        // THEN: Value should be returned correctly
        $this->assertEquals(99, $result['result']);
    }

    public function testPreparedStatementMultipleParams(): void
    {
        // GIVEN: Connected client
        // WHEN: Using prepared statement with multiple parameters
        $stmt = $this->pdo->prepare('SELECT :num as num, :text as text');
        $stmt->execute([
            'num' => 42,
            'text' => 'test'
        ]);
        $result = $stmt->fetch();

        // THEN: All parameters should be returned correctly
        $this->assertEquals(42, $result['num']);
        $this->assertEquals('test', $result['text']);
    }

    public function testPreparedStatementWithNull(): void
    {
        // GIVEN: Connected client
        // WHEN: Testing NULL in comparison
        $stmt = $this->pdo->query('SELECT 1 WHERE NULL IS NULL');
        $result = $stmt->fetch();

        // THEN: Should return one row (NULL IS NULL is true)
        $this->assertEquals(1, $result['?column?']);
    }

    public function testStringWithSpecialCharacters(): void
    {
        // GIVEN: Connected client
        // WHEN: Querying string with special characters
        $testString = "hello'world\"with\\special";
        $stmt = $this->pdo->prepare('SELECT :text as result');
        $stmt->execute(['text' => $testString]);
        $result = $stmt->fetch();

        // THEN: Special characters should be preserved
        $this->assertEquals($testString, $result['result']);
    }

    public function testMultipleRowsResult(): void
    {
        // GIVEN: Connected client
        // WHEN: Querying multiple rows (UNION ALL)
        $stmt = $this->pdo->query("SELECT 1 as num, 'first' as text UNION ALL SELECT 2, 'second'");
        $results = $stmt->fetchAll();

        // THEN: Should return multiple rows
        $this->assertCount(2, $results);

        $this->assertEquals(1, $results[0]['num']);
        $this->assertEquals('first', $results[0]['text']);

        $this->assertEquals(2, $results[1]['num']);
        $this->assertEquals('second', $results[1]['text']);
    }

    public function testEmptyResultSet(): void
    {
        // GIVEN: Connected client
        // WHEN: Executing query with no results
        $stmt = $this->pdo->query('SELECT 1 WHERE 1=0');
        $results = $stmt->fetchAll();

        // THEN: Should return empty array
        $this->assertCount(0, $results);
    }

    public function testSequentialQueries(): void
    {
        // GIVEN: Connected client
        // WHEN: Executing multiple queries sequentially
        $stmt1 = $this->pdo->query('SELECT 1 as value');
        $result1 = $stmt1->fetch();

        $stmt2 = $this->pdo->query('SELECT 2 as value');
        $result2 = $stmt2->fetch();

        $stmt3 = $this->pdo->query('SELECT 3 as value');
        $result3 = $stmt3->fetch();

        // THEN: All queries should succeed
        $this->assertEquals(1, $result1['value']);
        $this->assertEquals(2, $result2['value']);
        $this->assertEquals(3, $result3['value']);
    }

    public function testBlobHandling(): void
    {
        // GIVEN: Connected client with binary data
        $binaryData = "\x00\x01\x02\x03\x04\x05";

        // WHEN: Storing and retrieving binary data
        $stmt = $this->pdo->prepare('SELECT :data as result');
        $stmt->bindValue('data', $binaryData, PDO::PARAM_LOB);
        $stmt->execute();
        $result = $stmt->fetch();

        // THEN: Binary data should be preserved
        $this->assertEquals($binaryData, $result['result']);
    }
}
