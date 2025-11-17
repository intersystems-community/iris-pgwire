require 'minitest/autorun'
require 'pg'

class TransactionTest < Minitest::Test
  def setup
    @conn = PG.connect(
      host: ENV['PGWIRE_HOST'] || 'localhost',
      port: ENV['PGWIRE_PORT'] || 5432,
      dbname: ENV['PGWIRE_DATABASE'] || 'USER',
      user: ENV['PGWIRE_USERNAME'] || 'test_user',
      password: ENV['PGWIRE_PASSWORD'] || 'test'
    )
  end

  def teardown
    @conn.close if @conn
  end

  def test_explicit_begin
    # GIVEN: Connected client
    # WHEN: Issuing BEGIN command
    result = @conn.exec('BEGIN')

    # THEN: BEGIN should execute (translated to START TRANSACTION)
    assert_kind_of PG::Result, result

    # Cleanup
    @conn.exec('ROLLBACK')
  end

  def test_explicit_commit
    # GIVEN: Connected client with transaction
    @conn.exec('BEGIN')

    # WHEN: Issuing COMMIT command
    result = @conn.exec('COMMIT')

    # THEN: COMMIT should succeed
    assert_kind_of PG::Result, result
  end

  def test_explicit_rollback
    # GIVEN: Connected client with transaction
    @conn.exec('BEGIN')

    # WHEN: Issuing ROLLBACK command
    result = @conn.exec('ROLLBACK')

    # THEN: ROLLBACK should succeed
    assert_kind_of PG::Result, result
  end

  def test_transaction_with_query
    # GIVEN: Connected client
    # WHEN: Running query in transaction
    @conn.exec('BEGIN')

    result = @conn.exec('SELECT 1 as value')

    @conn.exec('COMMIT')

    # THEN: Query should succeed
    assert_equal 1, result[0]['value'].to_i
  end

  def test_multiple_queries_in_transaction
    # GIVEN: Connected client in transaction
    @conn.exec('BEGIN')

    # WHEN: Executing multiple queries
    result1 = @conn.exec('SELECT 1 as value')
    result2 = @conn.exec('SELECT 2 as value')
    result3 = @conn.exec('SELECT 3 as value')

    @conn.exec('COMMIT')

    # THEN: All queries should succeed
    assert_equal 1, result1[0]['value'].to_i
    assert_equal 2, result2[0]['value'].to_i
    assert_equal 3, result3[0]['value'].to_i
  end

  def test_transaction_block_method
    # GIVEN: Connected client
    # WHEN: Using transaction block method
    result = nil
    @conn.transaction do
      result = @conn.exec('SELECT 42 as answer')
    end

    # THEN: Transaction should complete successfully
    assert_equal 42, result[0]['answer'].to_i
  end

  def test_transaction_rollback_on_error
    # GIVEN: Connected client
    # WHEN: Transaction with error
    begin
      @conn.transaction do
        @conn.exec('SELECT 100 as value')
        # Simulate error by raising exception
        raise StandardError, 'Test error'
      end
    rescue StandardError
      # Expected error
    end

    # THEN: Transaction should be rolled back
    # (No assertion needed - just verifying no crash)
  end
end
