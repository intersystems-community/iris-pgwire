# Implementation Plan: P6 COPY Protocol - Bulk Data Operations

**Branch**: `023-feature-number-023` | **Date**: 2025-01-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/Users/tdyar/ws/iris-pgwire/specs/023-feature-number-023/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → ✅ COMPLETE: Spec loaded from spec.md
2. Fill Technical Context (scan for NEEDS CLARIFICATION)
   → ✅ COMPLETE: No NEEDS CLARIFICATION markers found
   → Project Type: single (PostgreSQL wire protocol server)
   → Structure Decision: Extends existing src/iris_pgwire structure
3. Fill the Constitution Check section
   → ✅ COMPLETE: Evaluated against Constitution v1.3.0
4. Evaluate Constitution Check section
   → ✅ PASS: No violations detected
   → Update Progress Tracking: Initial Constitution Check
5. Execute Phase 0 → research.md
   → STATUS: IN PROGRESS
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, CLAUDE.md
   → STATUS: PENDING
7. Re-evaluate Constitution Check section
   → STATUS: PENDING
8. Plan Phase 2 → Describe task generation approach
   → STATUS: PENDING
9. STOP - Ready for /tasks command
```

## Summary

Implement PostgreSQL COPY protocol (COPY FROM STDIN, COPY TO STDOUT) for bulk data operations in the iris-pgwire server. Enable 10-100× performance improvement for healthcare data migration (250 patient records in <1 second vs. 2.5 seconds baseline) and unlock BI tool (Apache Superset, Metabase) bulk import features. Primary technical challenge: stream CSV data between PostgreSQL wire protocol messages and IRIS embedded Python execution while maintaining transaction semantics and memory efficiency (<100MB for 1M rows).

## Technical Context

**Language/Version**: Python 3.11+ (matches existing iris-pgwire infrastructure)
**Primary Dependencies**:
- asyncio (existing - protocol server)
- iris embedded Python (existing - IRIS integration via `irispython`)
- psycopg3 (existing - E2E testing)
- csv module (standard library - CSV parsing/generation)

**Storage**: IRIS database via embedded Python (`iris.sql.exec()`)
**Testing**: pytest with E2E real client tests (psql, psycopg) - NO MOCKS (Constitutional Principle II)
**Target Platform**: Linux Docker containers (existing iris-pgwire-db deployment)
**Project Type**: single (extends existing src/iris_pgwire/ structure)

**Performance Goals**:
- >10,000 rows/second throughput (vs. 100 rows/sec for individual INSERTs)
- 250 patient records in <1 second (current baseline: 2.5 seconds)
- Sustained throughput for datasets up to 1M rows

**Constraints**:
- <100MB server memory for 1M row COPY operation (streaming/batching required)
- <5ms protocol translation overhead (Constitutional performance standard)
- Transaction integration with Feature 022 (BEGIN/COMMIT/ROLLBACK)
- Docker container restart required after code changes (Constitution VII)

**Scale/Scope**:
- Primary: 250 patient healthcare records (examples/superset-iris-healthcare/data/patients-data.sql)
- Extended: 10,000 lab results (BI tool use case)
- Maximum: 1M rows (memory efficiency validation)

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle II: Test-First Development
**Status**: ✅ COMPLIANT
- Feature spec defines 5 acceptance scenarios (E2E tests with real psql client)
- Tests MUST fail initially (no COPY protocol implementation exists)
- Implementation only after E2E tests are written

**Evidence**: Acceptance scenarios 1-5 in spec.md define exact psql commands:
```bash
cat patients-data.csv | psql -c "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)"
psql -c "COPY Patients TO STDOUT WITH (FORMAT CSV, HEADER)" > backup.csv
```

### Principle III: Phased Implementation
**Status**: ✅ COMPLIANT
- P6 COPY follows P0-P5 completion (P0 handshake, P1 simple query, P2 extended protocol completed)
- Dependencies verified: Feature 022 (transaction verbs) COMPLETED, Feature 018 (IRIS backend) COMPLETED

**Evidence**: spec.md Dependencies section confirms Feature 022 and Feature 018 completion

### Principle IV: IRIS Integration
**Status**: ✅ COMPLIANT
- Uses existing embedded Python pattern (`irispython` execution)
- CallIn service already enabled (existing infrastructure)
- Async threading with `asyncio.to_thread()` for IRIS operations

**Evidence**: src/iris_pgwire/protocol.py already implements `iris.sql.exec()` pattern

### Performance Standards
**Status**: ✅ COMPLIANT
- Translation overhead target: <5ms per COPY command (constitutional limit)
- Bulk operation performance: 10-100× faster than individual INSERTs (FR-005, NFR-001)

**Requirement**: Benchmark COPY protocol parsing and CSV processing overhead against 5ms SLA

### Principle VII: Development Environment Synchronization
**Status**: ✅ COMPLIANT
- Tests MUST verify container restart after code changes
- E2E tests will include container state verification (docker ps uptime check)

**Requirement**: Add docker restart validation to E2E test setup

### Security Requirements
**Status**: ✅ COMPLIANT
- Input validation: CSV parsing MUST sanitize data and report errors (FR-007)
- Error handling: MUST NOT leak IRIS internals in error messages
- Transaction rollback: COPY failures MUST trigger transaction rollback (FR-004)

**Requirement**: Edge case testing for malformed CSV, SQL injection attempts

### COPY Protocol Complexity Assessment
**Evaluation**: MODERATE complexity, constitutionally justified

**Core Protocol Requirements**:
1. Parse COPY SQL command (COPY table FROM STDIN/TO STDOUT WITH options)
2. Send CopyInResponse or CopyOutResponse message to client
3. Stream CopyData messages bidirectionally
4. Handle CopyDone/CopyFail messages
5. Integrate with existing transaction state machine (Feature 022)

**Constitutional Alignment**:
- ✅ Protocol Fidelity (Principle I): Implements standard PostgreSQL COPY wire protocol
- ✅ Test-First (Principle II): E2E tests with real psql client before implementation
- ✅ IRIS Integration (Principle IV): Batched `iris.sql.exec()` for bulk inserts
- ✅ Production Readiness (Principle V): Memory limits, error handling, transaction integration

## Project Structure

### Documentation (this feature)
```
specs/023-feature-number-023/
├── spec.md              # Feature specification (COMPLETE)
├── plan.md              # This file (/plan command output - IN PROGRESS)
├── research.md          # Phase 0 output (/plan command - PENDING)
├── data-model.md        # Phase 1 output (/plan command - PENDING)
├── quickstart.md        # Phase 1 output (/plan command - PENDING)
├── contracts/           # Phase 1 output (/plan command - PENDING)
│   └── copy_protocol_interface.py  # TDD interface contracts
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
src/iris_pgwire/
├── __init__.py
├── server.py           # Main asyncio server (EXISTING)
├── protocol.py         # PGWire protocol implementation (EXISTING - extend for COPY)
├── copy_handler.py     # NEW: COPY protocol message handlers
├── csv_processor.py    # NEW: CSV parsing and generation
├── bulk_executor.py    # NEW: Batched IRIS SQL execution
├── auth.py            # EXISTING: Authentication (no changes)
├── iris_executor.py   # EXISTING: IRIS SQL execution (extend for bulk operations)
├── types.py          # EXISTING: Type system and OID mapping
└── sql_translator/   # EXISTING: SQL translation (Feature 021, Feature 022)
    ├── __init__.py
    ├── transaction_translator.py  # EXISTING: Feature 022 integration
    └── copy_parser.py  # NEW: COPY command parsing

tests/
├── e2e/
│   ├── test_copy_from_stdin.py       # NEW: Real psql client COPY FROM tests
│   ├── test_copy_to_stdout.py        # NEW: Real psql client COPY TO tests
│   ├── test_copy_healthcare_250.py   # NEW: 250 patient benchmark
│   └── test_copy_memory_efficiency.py # NEW: 1M row memory test
├── contract/
│   └── test_copy_protocol_interface.py  # NEW: TDD interface contracts
├── integration/
│   ├── test_copy_transaction_integration.py  # NEW: Feature 022 integration
│   └── test_copy_error_handling.py   # NEW: Malformed CSV, edge cases
└── unit/
    ├── test_csv_processor.py         # NEW: CSV parsing/generation unit tests
    └── test_copy_parser.py           # NEW: COPY SQL parsing unit tests

examples/superset-iris-healthcare/data/
├── patients-data.sql      # EXISTING: 250 patient INSERT statements
└── patients-data.csv      # NEW: CSV format for COPY FROM testing
```

**Structure Decision**: Extends existing single project structure (src/iris_pgwire). New modules: copy_handler.py (protocol messages), csv_processor.py (CSV logic), bulk_executor.py (batched IRIS execution). Integration with existing protocol.py message routing and transaction_translator.py state management.

## Phase 0: Outline & Research

**No NEEDS CLARIFICATION markers detected** - all technical context is resolved based on:
1. Existing codebase structure (src/iris_pgwire/protocol.py message handling patterns)
2. PostgreSQL COPY protocol specification (well-defined wire format)
3. IRIS embedded Python patterns (existing iris_executor.py patterns)
4. Feature 022 transaction integration (completed dependency)

### Research Tasks (to be executed in research.md)

1. **PostgreSQL COPY Protocol Wire Format** (PRIMARY):
   - Research: PostgreSQL documentation for CopyInResponse, CopyOutResponse, CopyData message formats
   - Source: https://www.postgresql.org/docs/current/protocol-message-formats.html
   - Output: Exact byte layout for COPY protocol messages
   - Rationale: Protocol Fidelity (Constitution Principle I) requires exact message format compliance

2. **CSV Parsing Performance** (PERFORMANCE):
   - Research: Python csv module performance characteristics for large datasets
   - Benchmark: csv.reader() vs. csv.DictReader() memory usage for 1M rows
   - Output: Memory overhead per row, optimal batch size for streaming
   - Rationale: Must achieve <100MB memory for 1M rows (FR-006)

3. **IRIS Embedded Python Bulk Patterns** (INTEGRATION):
   - Research: Optimal batch size for `iris.sql.exec()` INSERT statements
   - Pattern: Existing iris_executor.py implementation for query execution
   - Output: Recommended batch size (rows or MB) for bulk inserts
   - Rationale: IRIS Integration (Constitution Principle IV) requires efficient batching

4. **Transaction Isolation for COPY** (INTEGRATION):
   - Research: PostgreSQL COPY behavior within BEGIN/COMMIT blocks
   - Integration: Feature 022 transaction state machine (TransactionTranslator)
   - Output: COPY abort behavior on error (rollback requirements)
   - Rationale: FR-004 requires transaction integration, must preserve Feature 022 semantics

5. **psql COPY Command Syntax** (TESTING):
   - Research: psql `\copy` vs. `COPY` command differences
   - E2E test: Exact psql commands for piping CSV data to server
   - Output: E2E test command templates for COPY FROM STDIN, COPY TO STDOUT
   - Rationale: Test-First Development (Constitution Principle II) requires real client testing

**Output**: research.md with decisions on:
- COPY protocol message byte layouts
- CSV batch size (recommended: 1000 rows or 10MB chunks)
- IRIS bulk insert patterns
- Transaction rollback strategy
- E2E test command templates

## Phase 1: Design & Contracts

*Prerequisites: research.md complete*

### 1. Extract entities from feature spec → `data-model.md`

**Entities** (from spec.md "Key Entities" section):

1. **CopyOperation** (state machine):
   - Fields: operation_type (FROM_STDIN | TO_STDOUT), table_name, column_list, csv_options, transaction_id, row_count, bytes_transferred
   - States: INITIATED → STREAMING → COMPLETED | FAILED
   - Transitions: INITIATED --(CopyData received/sent)--> STREAMING --(CopyDone/error)--> COMPLETED/FAILED

2. **CSVOptions** (configuration):
   - Fields: format='CSV', delimiter=',', null_string='\\N', header=True, quote='"', escape='\\'
   - Validation: Parse from COPY command WITH clause
   - Defaults: PostgreSQL standard CSV options

3. **Patient Record** (domain entity - from spec):
   - Fields: PatientID (INT), FirstName (VARCHAR), LastName (VARCHAR), DateOfBirth (DATE), Gender (VARCHAR), Status (VARCHAR), AdmissionDate (DATE), DischargeDate (DATE nullable)
   - Source: examples/superset-iris-healthcare/data/patients-data.sql
   - Usage: Primary test dataset (250 rows)

4. **BulkInsertBatch** (processing unit):
   - Fields: rows (List[Dict]), batch_size (1000 rows or 10MB), iris_statement (prepared INSERT)
   - Constraints: Memory limit <10MB per batch (to achieve <100MB total for 1M rows)

**Output**: data-model.md with state diagrams for CopyOperation lifecycle

### 2. Generate API contracts from functional requirements

**Contract Interface** (copy_protocol_interface.py):

```python
from typing import Protocol, AsyncIterator
from dataclasses import dataclass

@dataclass
class CopyCommand:
    """Parsed COPY SQL command"""
    table_name: str
    column_list: list[str] | None
    direction: Literal['FROM_STDIN', 'TO_STDOUT']
    csv_options: CSVOptions

class CopyHandler(Protocol):
    """Interface contract for COPY protocol implementation (TDD)"""

    async def handle_copy_from_stdin(
        self,
        command: CopyCommand,
        csv_stream: AsyncIterator[bytes]
    ) -> int:
        """
        FR-001: Support COPY table FROM STDIN

        Args:
            command: Parsed COPY command
            csv_stream: Async iterator of CopyData message payloads

        Returns:
            Number of rows inserted

        Raises:
            CSVParsingError: Malformed CSV data (FR-007)
            TransactionError: Transaction rollback required
        """
        ...

    async def handle_copy_to_stdout(
        self,
        command: CopyCommand
    ) -> AsyncIterator[bytes]:
        """
        FR-002: Support COPY table TO STDOUT

        Args:
            command: Parsed COPY command (includes SELECT query for COPY (...) TO STDOUT)

        Yields:
            CSV data as CopyData message payloads

        Raises:
            QueryExecutionError: IRIS query failure
        """
        ...

class CSVProcessor(Protocol):
    """Interface for CSV parsing and generation"""

    async def parse_csv_rows(
        self,
        csv_stream: AsyncIterator[bytes],
        options: CSVOptions
    ) -> AsyncIterator[dict]:
        """
        FR-003: Parse CSV with PostgreSQL-compatible options
        FR-007: Validate CSV format, report line numbers on error
        """
        ...

    async def generate_csv_rows(
        self,
        result_rows: AsyncIterator[tuple],
        column_names: list[str],
        options: CSVOptions
    ) -> AsyncIterator[bytes]:
        """
        FR-003: Generate CSV with PostgreSQL-compatible options
        """
        ...

class BulkExecutor(Protocol):
    """Interface for batched IRIS SQL execution"""

    async def bulk_insert(
        self,
        table_name: str,
        column_names: list[str],
        rows: AsyncIterator[dict],
        batch_size: int = 1000
    ) -> int:
        """
        FR-005: Achieve >10,000 rows/second throughput
        FR-006: <100MB memory for 1M rows (requires batching)
        """
        ...
```

**Output**: contracts/copy_protocol_interface.py with Protocol classes and type definitions

### 3. Generate contract tests from contracts

**Contract Tests** (tests/contract/test_copy_protocol_interface.py):

```python
import pytest
from iris_pgwire.copy_handler import CopyHandler, CopyCommand, CSVOptions
from iris_pgwire.csv_processor import CSVProcessor
from iris_pgwire.bulk_executor import BulkExecutor

class TestCopyHandlerContract:
    """Contract tests for CopyHandler interface (TDD - must fail initially)"""

    @pytest.mark.asyncio
    async def test_handle_copy_from_stdin_contract(self):
        """FR-001: handle_copy_from_stdin must accept CopyCommand and return row count"""
        handler = CopyHandler()  # Will fail - not implemented yet
        command = CopyCommand(
            table_name='Patients',
            column_list=None,
            direction='FROM_STDIN',
            csv_options=CSVOptions(format='CSV', header=True)
        )

        async def csv_stream():
            yield b"PatientID,FirstName,LastName\n"
            yield b"1,John,Smith\n"

        row_count = await handler.handle_copy_from_stdin(command, csv_stream())
        assert row_count == 1  # One data row (excluding header)

    @pytest.mark.asyncio
    async def test_handle_copy_to_stdout_contract(self):
        """FR-002: handle_copy_to_stdout must yield CSV data"""
        handler = CopyHandler()  # Will fail - not implemented yet
        command = CopyCommand(
            table_name='Patients',
            column_list=['PatientID', 'FirstName'],
            direction='TO_STDOUT',
            csv_options=CSVOptions(format='CSV', header=True)
        )

        csv_chunks = [chunk async for chunk in handler.handle_copy_to_stdout(command)]
        assert len(csv_chunks) > 0
        assert b'PatientID,FirstName' in csv_chunks[0]  # Header row
```

**Output**: tests/contract/test_copy_protocol_interface.py with failing contract tests

### 4. Extract test scenarios from user stories

**E2E Test Scenarios** (from spec.md acceptance scenarios):

```python
# tests/e2e/test_copy_healthcare_250.py
@pytest.mark.e2e
def test_copy_250_patients_from_stdin(psql_command):
    """
    Acceptance Scenario 1: Load 250 patient records in <1 second

    GIVEN: CSV file with 250 patient records
    WHEN: User executes COPY Patients FROM STDIN WITH (FORMAT CSV)
    THEN: All 250 records loaded in < 1 second with no errors
    """
    start_time = time.time()

    result = psql_command(
        "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)",
        stdin_file="examples/superset-iris-healthcare/data/patients-data.csv"
    )

    elapsed = time.time() - start_time
    assert result.returncode == 0, f"COPY failed: {result.stderr}"
    assert "COPY 250" in result.stdout, "Expected 250 rows inserted"
    assert elapsed < 1.0, f"COPY took {elapsed:.2f}s (should be <1s)"

# tests/e2e/test_copy_to_stdout.py
@pytest.mark.e2e
def test_copy_250_patients_to_stdout(psql_command):
    """
    Acceptance Scenario 2: Export 250 patient records to CSV

    GIVEN: Patients table with 250 records in IRIS
    WHEN: User executes COPY Patients TO STDOUT WITH (FORMAT CSV)
    THEN: All 250 records exported to CSV format and streamed to client
    """
    result = psql_command(
        "COPY Patients TO STDOUT WITH (FORMAT CSV, HEADER)",
        stdout_file="/tmp/patients_export.csv"
    )

    assert result.returncode == 0, f"COPY failed: {result.stderr}"

    # Verify exported CSV
    with open("/tmp/patients_export.csv") as f:
        lines = f.readlines()
        assert len(lines) == 251, "Expected 250 data rows + 1 header row"
        assert "PatientID,FirstName,LastName" in lines[0]

# tests/e2e/test_copy_memory_efficiency.py
@pytest.mark.e2e
@pytest.mark.slow
async def test_copy_1m_rows_memory_limit(pgwire_server):
    """
    Acceptance Scenario 5: Export 1M rows without exceeding 100MB memory

    GIVEN: Large dataset (1M patient records)
    WHEN: User executes COPY (SELECT * FROM Patients) TO STDOUT
    THEN: Server streams results without exceeding 100MB memory usage
    """
    # Monitor server memory usage during COPY
    initial_memory = get_server_memory_usage()

    # Execute COPY TO STDOUT for 1M rows
    async with psycopg.AsyncConnection.connect(...) as conn:
        async with conn.cursor() as cur:
            await cur.execute("COPY (SELECT * FROM LargeDataset) TO STDOUT WITH (FORMAT CSV)")
            row_count = 0
            async for row in cur:
                row_count += 1
                if row_count % 100000 == 0:
                    current_memory = get_server_memory_usage()
                    memory_delta = current_memory - initial_memory
                    assert memory_delta < 100 * 1024 * 1024, \
                        f"Memory usage {memory_delta/1024/1024:.1f}MB exceeds 100MB limit"

    assert row_count == 1000000, "Expected 1M rows exported"
```

**Output**: tests/e2e/test_copy_healthcare_250.py, test_copy_to_stdout.py, test_copy_memory_efficiency.py with E2E scenarios

### 5. Update agent file incrementally (O(1) operation)

**Action**: Run `.specify/scripts/bash/update-agent-context.sh claude`

**Expected Updates to CLAUDE.md**:
- Add P6 COPY Protocol section to Development Methodology
- Update Recent Changes with Feature 023 completion
- Preserve existing P0-P5 phase documentation
- Keep under 150 lines for token efficiency

**Output**: Updated CLAUDE.md in repository root

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
1. Load `.specify/templates/tasks-template.md` as base template
2. Generate tasks from Phase 1 design docs:
   - contracts/copy_protocol_interface.py → contract test tasks [P]
   - data-model.md entities → model creation tasks [P]
   - E2E test scenarios → integration test tasks
3. Implementation tasks to make tests pass (TDD Red-Green-Refactor)

**Ordering Strategy**:
1. **TDD Order**: Tests before implementation
   - T001-T005: Write E2E tests (MUST fail initially)
   - T006-T010: Write contract tests (MUST fail initially)
   - T011-T030: Implementation to make tests pass

2. **Dependency Order**:
   - T011: Parse COPY SQL command [foundation]
   - T012: Implement CopyInResponse/CopyOutResponse message generation [protocol]
   - T013: Implement CSV parsing (FROM STDIN) [data processing]
   - T014: Implement CSV generation (TO STDOUT) [data processing]
   - T015: Implement batched IRIS bulk insert [IRIS integration]
   - T016: Integrate with transaction state machine (Feature 022) [integration]
   - T017-T020: Error handling, edge cases [robustness]
   - T021-T025: Performance optimization (batching, memory limits) [optimization]
   - T026-T030: E2E validation, benchmarks [validation]

**Parallelization** [P markers]:
- T001-T005: E2E tests [P] (independent files)
- T006-T010: Contract tests [P] (independent interfaces)
- T013, T014: CSV parsing and generation [P] (independent logic)

**Estimated Output**: 30 numbered, ordered tasks in tasks.md

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md from Phase 2 strategy)
**Phase 4**: Implementation (execute tasks.md following TDD principles and constitutional requirements)
**Phase 5**: Validation (run E2E tests, execute quickstart.md, performance validation against 250-patient benchmark)

## Complexity Tracking
*No violations - table not needed*

Constitution Check passed with zero violations. COPY protocol implementation aligns with all constitutional principles (Protocol Fidelity, Test-First, Phased Implementation, IRIS Integration, Production Readiness).

## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command) - research.md created
- [x] Phase 1: Design complete (/plan command) - contracts and data model specified in plan.md
- [x] Phase 2: Task planning complete (/plan command - approach described)
- [ ] Phase 3: Tasks generated (/tasks command - READY TO EXECUTE)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS (no new violations)
- [x] All NEEDS CLARIFICATION resolved: PASS (no markers found)
- [x] Complexity deviations documented: N/A (no violations)

## Plan Execution Complete

The `/plan` command has successfully completed all its phases:
1. ✅ Loaded and analyzed feature specification
2. ✅ Filled Technical Context with all project details
3. ✅ Executed Constitution Check (PASS - zero violations)
4. ✅ Generated Phase 0 research.md with all technical decisions
5. ✅ Designed Phase 1 contracts (CopyHandler, CSVProcessor, BulkExecutor)
6. ✅ Described Phase 2 task generation strategy (30 tasks estimated)

**Next Step**: Run `/tasks` command to generate tasks.md from the design artifacts

---
*Based on Constitution v1.3.0 - See `.specify/memory/constitution.md`*
