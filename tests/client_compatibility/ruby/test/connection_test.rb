require 'minitest/autorun'
require 'pg'

class ConnectionTest < Minitest::Test
  def connection_config
    {
      host: ENV['PGWIRE_HOST'] || 'localhost',
      port: ENV['PGWIRE_PORT'] || 5432,
      dbname: ENV['PGWIRE_DATABASE'] || 'USER',
      user: ENV['PGWIRE_USERNAME'] || 'test_user',
      password: ENV['PGWIRE_PASSWORD'] || 'test'
    }
  end

  def create_connection
    PG.connect(connection_config)
  end

  def test_basic_connection
    # GIVEN: Connection configuration
    # WHEN: Establishing connection
    conn = create_connection

    # THEN: Should execute simple query
    result = conn.exec('SELECT 1 as value')
    assert_equal 1, result[0]['value'].to_i

    conn.close
  end

  def test_connection_with_connection_string
    # GIVEN: Connection string
    config = connection_config
    conn_string = "host=#{config[:host]} port=#{config[:port]} dbname=#{config[:dbname]} " \
                  "user=#{config[:user]} password=#{config[:password]}"

    # WHEN: Connecting with connection string
    conn = PG.connect(conn_string)

    # THEN: Connection should work
    result = conn.exec('SELECT 42 as answer')
    assert_equal 42, result[0]['answer'].to_i

    conn.close
  end

  def test_multiple_sequential_connections
    # GIVEN: Multiple connection attempts
    # WHEN: Creating sequential connections
    3.times do |i|
      conn = create_connection
      result = conn.exec("SELECT #{i + 1} as num")

      # THEN: Each connection should work
      assert_equal i + 1, result[0]['num'].to_i

      conn.close
    end
  end

  def test_server_version
    # GIVEN: Connected client
    conn = create_connection

    # WHEN: Querying server version
    version = conn.server_version

    # THEN: Should return version number
    assert_kind_of Integer, version
    assert version > 0

    conn.close
  end

  def test_connection_error_handling
    # GIVEN: Invalid connection parameters
    # WHEN: Attempting connection with wrong host
    # THEN: Should raise PG::Error
    assert_raises(PG::Error) do
      PG.connect(
        host: 'invalid-host',
        port: 9999,
        dbname: 'USER',
        user: 'test_user',
        password: 'test'
      )
    end
  end

  def test_multiple_queries_per_connection
    # GIVEN: Single connection
    conn = create_connection

    # WHEN: Executing multiple queries
    result1 = conn.exec('SELECT 1 as value')
    result2 = conn.exec('SELECT 2 as value')
    result3 = conn.exec('SELECT 3 as value')

    # THEN: All queries should succeed
    assert_equal 1, result1[0]['value'].to_i
    assert_equal 2, result2[0]['value'].to_i
    assert_equal 3, result3[0]['value'].to_i

    conn.close
  end
end
