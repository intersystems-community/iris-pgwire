const { Client } = require('pg')

async function main() {
  const client = new Client({
    connectionString: process.env.DATABASE_URL,
  })

  try {
    console.log('Connecting...')
    await client.connect()
    console.log('Connected!')

    // Test SELECT
    console.log('\n1. Testing SELECT...')
    const result = await client.query('SELECT * FROM test_users LIMIT 5')
    console.log('SELECT succeeded!')
    console.log('Rows:', result.rows.length)
    console.log('Fields:', result.fields.map(f => f.name))
    console.log('Data:', result.rows)

    // Test INSERT with RETURNING
    console.log('\n2. Testing INSERT with RETURNING...')
    const insertResult = await client.query(
      "INSERT INTO test_users (name, email) VALUES ($1, $2) RETURNING id, name, email",
      ['PG Test User', 'pg-test@example.com']
    )
    console.log('INSERT succeeded!')
    console.log('Inserted:', insertResult.rows[0])

  } catch (err) {
    console.error('Error:', err.message)
    console.error('Stack:', err.stack)
  } finally {
    await client.end()
    console.log('\nDisconnected')
  }
}

main()
