const { PrismaClient } = require('@prisma/client')

const prisma = new PrismaClient({
  log: ['query', 'info', 'warn', 'error'],
})

async function main() {
  console.log('Connecting to IRIS via PGWire...')

  // Query all records - just this, nothing else
  console.log('\n1. Querying all users...')
  const users = await prisma.test_users.findMany({
    take: 5  // Limit to 5 rows
  })
  console.log('Users:', users)
  console.log('\nSELECT worked!')
}

main()
  .catch((e) => {
    console.error('Error:', e)
    process.exit(1)
  })
  .finally(async () => {
    await prisma.$disconnect()
  })
