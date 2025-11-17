<?php

namespace IrisPGWire\Tests;

use PHPUnit\Framework\TestCase;
use PDO;

class TransactionTest extends TestCase
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

    public function testExplicitBegin(): void
    {
        // GIVEN: Connected client
        // WHEN: Issuing BEGIN command
        $result = $this->pdo->exec('BEGIN');

        // THEN: BEGIN should execute (translated to START TRANSACTION)
        // Note: exec() returns number of affected rows, 0 for DDL/transaction commands
        $this->assertIsInt($result);

        // Cleanup
        $this->pdo->exec('ROLLBACK');
    }

    public function testExplicitCommit(): void
    {
        // GIVEN: Connected client with transaction
        $this->pdo->exec('BEGIN');

        // WHEN: Issuing COMMIT command
        $result = $this->pdo->exec('COMMIT');

        // THEN: COMMIT should succeed
        $this->assertIsInt($result);
    }

    public function testExplicitRollback(): void
    {
        // GIVEN: Connected client with transaction
        $this->pdo->exec('BEGIN');

        // WHEN: Issuing ROLLBACK command
        $result = $this->pdo->exec('ROLLBACK');

        // THEN: ROLLBACK should succeed
        $this->assertIsInt($result);
    }

    public function testTransactionWithQuery(): void
    {
        // GIVEN: Connected client
        // WHEN: Running query in transaction
        $this->pdo->exec('BEGIN');

        $stmt = $this->pdo->query('SELECT 1 as value');
        $result = $stmt->fetch();

        $this->pdo->exec('COMMIT');

        // THEN: Query should succeed
        $this->assertEquals(1, $result['value']);
    }

    public function testMultipleQueriesInTransaction(): void
    {
        // GIVEN: Connected client in transaction
        $this->pdo->exec('BEGIN');

        // WHEN: Executing multiple queries
        $stmt1 = $this->pdo->query('SELECT 1 as value');
        $result1 = $stmt1->fetch();

        $stmt2 = $this->pdo->query('SELECT 2 as value');
        $result2 = $stmt2->fetch();

        $stmt3 = $this->pdo->query('SELECT 3 as value');
        $result3 = $stmt3->fetch();

        $this->pdo->exec('COMMIT');

        // THEN: All queries should succeed
        $this->assertEquals(1, $result1['value']);
        $this->assertEquals(2, $result2['value']);
        $this->assertEquals(3, $result3['value']);
    }

    public function testPDOTransactionMethods(): void
    {
        // GIVEN: Connected client
        // WHEN: Using PDO's transaction methods
        $this->assertTrue($this->pdo->beginTransaction());

        $stmt = $this->pdo->query('SELECT 42 as answer');
        $result = $stmt->fetch();

        $this->assertTrue($this->pdo->commit());

        // THEN: Transaction methods should work
        $this->assertEquals(42, $result['answer']);
    }

    public function testPDORollback(): void
    {
        // GIVEN: Connected client
        // WHEN: Using PDO's rollback method
        $this->assertTrue($this->pdo->beginTransaction());

        $stmt = $this->pdo->query('SELECT 100 as value');
        $result = $stmt->fetch();

        $this->assertTrue($this->pdo->rollback());

        // THEN: Rollback should succeed
        $this->assertEquals(100, $result['value']);
    }
}
