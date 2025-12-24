/**
 * IRIS PGWire Demo - Node.js PostgreSQL Client
 *
 * This demo shows how standard PostgreSQL clients can connect to
 * InterSystems IRIS via PGWire with automatic schema mapping.
 *
 * The 'public' schema is automatically mapped to IRIS 'SQLUser' schema.
 */

const { Client } = require('pg');

async function main() {
    console.log('🔌 IRIS PGWire Demo - Node.js PostgreSQL Client\n');
    console.log('=' .repeat(60));

    // Connect using standard PostgreSQL connection string
    const client = new Client({
        host: 'localhost',
        port: 5432,
        database: 'USER',
        user: '_SYSTEM',
        password: 'SYS',
    });

    try {
        await client.connect();
        console.log('✅ Connected to IRIS via PostgreSQL wire protocol\n');

        // Demo 1: Schema mapping with information_schema
        console.log('📋 Demo 1: Schema Mapping (public → SQLUser)');
        console.log('-'.repeat(60));

        const tablesResult = await client.query(`
            SELECT table_name, table_schema
            FROM information_schema.tables
            WHERE table_schema = 'public'
            LIMIT 5
        `);

        console.log('Query: SELECT ... FROM information_schema.tables WHERE table_schema = \'public\'');
        console.log('Result (IRIS SQLUser tables shown as "public"):');
        tablesResult.rows.forEach(row => {
            console.log(`  - ${row.table_name} (schema: ${row.table_schema})`);
        });

        // Demo 2: Query using public.tablename syntax
        console.log('\n📋 Demo 2: Query with public.tablename Syntax');
        console.log('-'.repeat(60));

        // Check if demo table exists
        const demoTableExists = tablesResult.rows.some(r =>
            r.table_name.toUpperCase() === 'DEMO_VECTORS'
        );

        if (demoTableExists) {
            const vectorResult = await client.query(`
                SELECT COUNT(*) as row_count FROM public.DEMO_VECTORS
            `);
            console.log('Query: SELECT COUNT(*) FROM public.DEMO_VECTORS');
            console.log(`Result: ${vectorResult.rows[0].row_count} rows`);
        } else {
            console.log('(DEMO_VECTORS table not found, skipping)');
        }

        // Demo 3: Create and query a test table
        console.log('\n📋 Demo 3: Create Table & CRUD Operations');
        console.log('-'.repeat(60));

        // Create test table
        await client.query(`
            CREATE TABLE IF NOT EXISTS public.node_demo (
                id INT PRIMARY KEY,
                name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        `);
        console.log('✅ Created table: public.node_demo');

        // Insert data
        await client.query(`
            INSERT INTO public.node_demo (id, name) VALUES (1, 'Node.js Demo')
        `).catch(() => {}); // Ignore if exists

        await client.query(`
            INSERT INTO public.node_demo (id, name) VALUES (2, 'PostgreSQL Client')
        `).catch(() => {});

        console.log('✅ Inserted test records');

        // Query data
        const selectResult = await client.query(`
            SELECT id, name FROM public.node_demo ORDER BY id
        `);
        console.log('Query: SELECT id, name FROM public.node_demo');
        selectResult.rows.forEach(row => {
            // Handle both lowercase and uppercase column names from IRIS
            const id = row.id || row.ID || Object.values(row)[0];
            const name = row.name || row.NAME || Object.values(row)[1];
            console.log(`  - ID: ${id}, Name: ${name}`);
        });

        // Demo 4: Parameterized queries
        console.log('\n📋 Demo 4: Parameterized Query');
        console.log('-'.repeat(60));

        const paramResult = await client.query(
            'SELECT id, name FROM public.node_demo WHERE id = $1',
            [1]
        );
        console.log('Query: SELECT id, name FROM public.node_demo WHERE id = $1 (param: 1)');
        const row = paramResult.rows[0];
        const id = row.id || row.ID || Object.values(row)[0];
        const name = row.name || row.NAME || Object.values(row)[1];
        console.log(`Result: ID=${id}, Name="${name}"`);

        // Demo 5: Transaction
        console.log('\n📋 Demo 5: Transaction Support');
        console.log('-'.repeat(60));

        await client.query('BEGIN');
        await client.query(`
            INSERT INTO public.node_demo (id, name) VALUES (99, 'Transaction Test')
        `).catch(() => {});
        await client.query('ROLLBACK');
        console.log('✅ BEGIN → INSERT → ROLLBACK completed');

        // Cleanup
        await client.query('DELETE FROM public.node_demo WHERE id = 99').catch(() => {});

        console.log('\n' + '='.repeat(60));
        console.log('🎉 Demo Complete! IRIS is accessible via PostgreSQL protocol.');
        console.log('   Schema mapping: public ↔ SQLUser works seamlessly.');

    } catch (error) {
        console.error('❌ Error:', error.message);
    } finally {
        await client.end();
        console.log('\n🔌 Connection closed');
    }
}

main();
