const { PrismaClient } = require('@prisma/client')

const prisma = new PrismaClient({
  log: ['query', 'info', 'warn', 'error'],
})

async function main() {
  console.log('Connecting to IRIS via PGWire...')

  // Insert a test record
  console.log('\n1. Inserting a test user...')
  const newUser = await prisma.test_users.create({
    data: {
      name: 'Prisma Test User',
      email: 'prisma-test@example.com'
    },
    select: {
      id: true,
      name: true,
      email: true
    }
  })
  console.log('✅ Created user:', newUser)

  // Insert another
  console.log('\n2. Inserting another test user...')
  const user2 = await prisma.test_users.create({
    data: {
      name: 'Second User',
      email: 'second@example.com'
    },
    select: {
      id: true,
      name: true,
      email: true
    }
  })
  console.log('✅ Created user:', user2)

  console.log('\n🎉 SUCCESS! Prisma INSERT operations work with IRIS PGWire!')
  console.log('(SELECT/findMany has known issues with binary format - work in progress)')
}

main()
  .catch((e) => {
    console.error('Error:', e)
    process.exit(1)
  })
  .finally(async () => {
    await prisma.$disconnect()
  })
