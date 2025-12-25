const { PrismaClient } = require('@prisma/client')

const prisma = new PrismaClient({
  log: ['query', 'info', 'warn', 'error'],
})

async function main() {
  console.log('Connecting to IRIS via PGWire...')

  // Insert a test record (omit created_at to let DB generate it)
  console.log('\n1. Inserting a test user...')
  const newUser = await prisma.test_users.create({
    data: {
      name: 'Test User',
      email: 'test@example.com'
      // created_at omitted - let database default handle it
    },
    select: {
      id: true,
      name: true,
      email: true
      // Don't select created_at to avoid timestamp return issues
    }
  })
  console.log('Created user:', newUser)

  // Query all records
  console.log('\n2. Querying all users...')
  const users = await prisma.test_users.findMany()
  console.log('All users:', users)

  // Update the record
  console.log('\n3. Updating the user...')
  const updated = await prisma.test_users.update({
    where: { id: newUser.id },
    data: { name: 'Updated User' }
  })
  console.log('Updated user:', updated)

  // Delete the record
  console.log('\n4. Deleting the user...')
  await prisma.test_users.delete({
    where: { id: newUser.id }
  })
  console.log('User deleted')

  console.log('\n SUCCESS! Full CRUD operations completed via Prisma + IRIS PGWire!')
}

main()
  .catch((e) => {
    console.error('Error:', e)
    process.exit(1)
  })
  .finally(async () => {
    await prisma.$disconnect()
  })
