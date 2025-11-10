import pg from 'pg';
const { Client } = pg;

const client = new Client({
  host: 'localhost',
  port: 5432,
  database: 'USER',
  user: 'test_user',
  password: 'test',
  ssl: false
});

try {
  await client.connect();
  console.log('✅ Connected successfully');
  
  const result = await client.query('SELECT 1');
  console.log('✅ Query executed');
  console.log('Columns:', result.fields.map(f => f.name));
  console.log('Rows:', result.rows);
  
  await client.end();
  console.log('✅ Disconnected successfully');
} catch (err) {
  console.error('❌ Error:', err.message);
  process.exit(1);
}
