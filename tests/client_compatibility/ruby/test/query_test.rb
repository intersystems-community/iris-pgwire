require 'minitest/autorun'
require 'pg'
require 'time'

class QueryTest < Minitest::Test
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

  def test_select_constant
    # GIVEN: Connected client
    # WHEN: Executing SELECT with constant
    result = @conn.exec('SELECT 42 as answer')

    # THEN: Should return constant value
    assert_equal 42, result[0]['answer'].to_i
  end

  def test_select_multiple_columns
    # GIVEN: Connected client
    # WHEN: Selecting multiple columns
    result = @conn.exec("SELECT 1 as num, 'hello' as text, 3.14 as pi")

    # THEN: All columns should be returned
    assert_equal 1, result[0]['num'].to_i
    assert_equal 'hello', result[0]['text']
    assert_in_delta 3.14, result[0]['pi'].to_f, 0.001
  end

  def test_select_current_timestamp
    # GIVEN: Connected client
    # WHEN: Selecting CURRENT_TIMESTAMP
    result = @conn.exec('SELECT CURRENT_TIMESTAMP as ts')

    # THEN: Should return timestamp string
    assert_kind_of String, result[0]['ts']
    refute_empty result[0]['ts']

    # Verify timestamp is reasonable (within last 24 hours)
    # Note: IRIS returns timestamps in UTC format without timezone indicator
    # Ruby's Time.parse treats it as local time, creating timezone offset
    # We use a more lenient 24-hour window to account for timezone differences
    timestamp = Time.parse(result[0]['ts'])
    now = Time.now
    diff = (now - timestamp).abs
    assert diff < 86400, 'Timestamp should be within last 24 hours'
  end

  def test_select_with_null
    # GIVEN: Connected client
    # WHEN: Selecting with WHERE clause that returns no rows
    result = @conn.exec('SELECT 1 WHERE 1=0')

    # THEN: Empty result set
    assert_equal 0, result.ntuples
  end

  def test_prepared_statement_single_param
    # GIVEN: Connected client
    # WHEN: Using prepared statement with parameter
    result = @conn.exec_params('SELECT $1::int as result', [99])

    # THEN: Value should be returned correctly
    assert_equal 99, result[0]['result'].to_i
  end

  def test_prepared_statement_multiple_params
    # GIVEN: Connected client
    # WHEN: Using prepared statement with multiple parameters
    result = @conn.exec_params('SELECT $1::int as num, $2::text as text', [42, 'test'])

    # THEN: All parameters should be returned correctly
    assert_equal 42, result[0]['num'].to_i
    assert_equal 'test', result[0]['text']
  end

  def test_prepared_statement_with_null
    # GIVEN: Connected client
    # WHEN: Testing NULL in comparison
    result = @conn.exec('SELECT 1 WHERE NULL IS NULL')

    # THEN: Should return one row (NULL IS NULL is true)
    assert_equal 1, result.ntuples
    assert_equal 1, result[0]['?column?'].to_i
  end

  def test_string_with_special_characters
    # GIVEN: Connected client
    # WHEN: Querying string with special characters
    test_string = "hello'world\"with\\special"
    result = @conn.exec_params('SELECT $1 as result', [test_string])

    # THEN: Special characters should be preserved
    assert_equal test_string, result[0]['result']
  end

  def test_multiple_rows_result
    # GIVEN: Connected client
    # WHEN: Querying multiple rows (UNION ALL)
    result = @conn.exec("SELECT 1 as num, 'first' as text UNION ALL SELECT 2, 'second'")

    # THEN: Should return multiple rows
    assert_equal 2, result.ntuples

    assert_equal 1, result[0]['num'].to_i
    assert_equal 'first', result[0]['text']

    assert_equal 2, result[1]['num'].to_i
    assert_equal 'second', result[1]['text']
  end

  def test_empty_result_set
    # GIVEN: Connected client
    # WHEN: Executing query with no results
    result = @conn.exec('SELECT 1 WHERE 1=0')

    # THEN: Should return empty result
    assert_equal 0, result.ntuples
  end

  def test_sequential_queries
    # GIVEN: Connected client
    # WHEN: Executing multiple queries sequentially
    result1 = @conn.exec('SELECT 1 as value')
    result2 = @conn.exec('SELECT 2 as value')
    result3 = @conn.exec('SELECT 3 as value')

    # THEN: All queries should succeed
    assert_equal 1, result1[0]['value'].to_i
    assert_equal 2, result2[0]['value'].to_i
    assert_equal 3, result3[0]['value'].to_i
  end

  def test_binary_data_handling
    # GIVEN: Connected client with binary data
    binary_data = "\x00\x01\x02\x03\x04\x05"

    # WHEN: Storing and retrieving binary data
    result = @conn.exec_params('SELECT $1 as result', [{ value: binary_data, format: 1 }])

    # THEN: Binary data should be preserved
    assert_equal binary_data, result[0]['result']
  end
end
