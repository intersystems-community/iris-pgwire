const { Client } = require('pg')

async function main() {
  const client = new Client({
    connectionString: process.env.DATABASE_URL,
  })

  try {
    console.log('Connecting...')
    await client.connect()
    console.log('Connected!')

    // Test exact Prisma query format
    console.log('\n1. Testing Prisma-style SELECT...')
    const query = `SELECT "public"."test_users"."id", "public"."test_users"."name", "public"."test_users"."email", "public"."test_users"."created_at" FROM "public"."test_users" WHERE 1=1 OFFSET $1`
    const result = await client.query(query, [0])
    console.log('SELECT succeeded!')
    console.log('Rows:', result.rows.length)
    console.log('Fields:', result.fields.map(f => `${f.name}(oid=${f.dataTypeID})`))
    console.log('First row:', result.rows[0])

  } catch (err) {
    console.error('Error:', err.message)
    console.error('Stack:', err.stack)
  } finally {
    await client.end()
    console.log('\nDisconnected')
  }
}

main()
