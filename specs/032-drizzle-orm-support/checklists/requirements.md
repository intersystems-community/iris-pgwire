# Requirements Checklist: Drizzle ORM Support

**Feature**: 032-drizzle-orm-support
**Created**: 2025-12-25

## Drizzle-kit Introspection

- [ ] **FR-001**: information_schema queries return accurate table metadata
- [ ] **FR-002**: pg_catalog queries work (pg_class, pg_attribute, etc.)
- [ ] **FR-003**: Column types map to valid Drizzle types
- [ ] **FR-004**: Primary key information returned correctly
- [ ] **FR-005**: Index information returned for @@index generation

## CRUD Operations

- [x] **FR-006**: INSERT with .returning() works (implemented in 031)
- [x] **FR-007**: UPDATE with .returning() works (implemented in 031)
- [x] **FR-008**: DELETE with .returning() works (implemented in 031)
- [x] **FR-009**: Parameterized queries work ($1, $2 → ?)

## Transaction Support

- [ ] **FR-010**: BEGIN/COMMIT/ROLLBACK work for Drizzle transactions
- [ ] **FR-011**: Transaction isolation maintained

## Type Mapping

- [x] **FR-012**: INTEGER → int4 (OID 23)
- [x] **FR-013**: VARCHAR → varchar/text (OID 1043/25)
- [x] **FR-014**: TIMESTAMP → timestamp (OID 1114)
- [x] **FR-015**: BIGINT → int8 (OID 20)
- [ ] **FR-016**: BIT/BOOLEAN → boolean (OID 16)
- [ ] **FR-017**: DECIMAL/NUMERIC → numeric (OID 1700)

## Verification Tasks

- [ ] Create Drizzle demo project
- [ ] Run drizzle-kit introspect successfully
- [ ] Test INSERT with .returning()
- [ ] Test SELECT queries
- [ ] Test UPDATE with .returning()
- [ ] Test DELETE with .returning()
- [ ] Test transactions
- [ ] Document any gaps

## Success Criteria

- [ ] drizzle-kit introspect completes without errors
- [ ] Generated schema.ts matches IRIS tables
- [ ] All CRUD .returning() operations work
- [ ] Common types map correctly
- [ ] Transactions work correctly
