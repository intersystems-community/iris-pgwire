# Data Model: PostgreSQL Transaction Verb Compatibility

**Feature**: 022-postgresql-transaction-verb
**Date**: 2025-11-08
**Purpose**: Define entities and state machines for transaction verb translation

## Overview

This feature involves two primary entities: **TransactionCommand** (ephemeral value object) and **TransactionState** (session-scoped state machine). Transaction commands are translated before execution, and transaction state is managed by the PostgreSQL protocol session handler (outside this feature's scope).

## Entity: TransactionCommand

**Type**: Ephemeral Value Object
**Lifecycle**: Single-use, no persistence
**Purpose**: Represent a transaction control command sent by the client

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command_text` | str | Yes | Original SQL command as received from client |
| `command_type` | CommandType | Yes | Enum: BEGIN, COMMIT, ROLLBACK, START_TRANSACTION |
| `modifiers` | str | No | Optional transaction modifiers (e.g., "ISOLATION LEVEL READ COMMITTED") |
| `translated_text` | str | Yes | Translated SQL command for IRIS execution |

### Validation Rules

1. **Case Insensitivity** (FR-009):
   - `command_text` matching must be case-insensitive
   - `BEGIN`, `begin`, `Begin` all map to `CommandType.BEGIN`

2. **Modifier Preservation** (FR-005):
   - If modifiers present in original command, preserve in translation
   - Example: `BEGIN ISOLATION LEVEL READ COMMITTED` → modifiers = `"ISOLATION LEVEL READ COMMITTED"`

3. **String Literal Exclusion** (FR-006):
   - Commands inside string literals must NOT be translated
   - Example: `SELECT 'BEGIN'` → `command_type` = None (not a transaction command)

### Example Instances

```python
# Example 1: Simple BEGIN
TransactionCommand(
    command_text="BEGIN",
    command_type=CommandType.BEGIN,
    modifiers=None,
    translated_text="START TRANSACTION"
)

# Example 2: BEGIN with isolation level
TransactionCommand(
    command_text="BEGIN ISOLATION LEVEL READ COMMITTED",
    command_type=CommandType.BEGIN,
    modifiers="ISOLATION LEVEL READ COMMITTED",
    translated_text="START TRANSACTION ISOLATION LEVEL READ COMMITTED"
)

# Example 3: COMMIT (no translation needed)
TransactionCommand(
    command_text="COMMIT",
    command_type=CommandType.COMMIT,
    modifiers=None,
    translated_text="COMMIT"
)

# Example 4: Not a transaction command
TransactionCommand(
    command_text="SELECT 'BEGIN'",
    command_type=None,
    modifiers=None,
    translated_text="SELECT 'BEGIN'"  # Unchanged
)
```

## Entity: TransactionState

**Type**: Session-Scoped State Machine
**Lifecycle**: Exists for duration of PostgreSQL protocol session
**Purpose**: Track transaction state for proper protocol handling
**Scope**: Managed by protocol session handler (outside feature scope)

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | TransactionStatus | Yes | Current transaction state (enum) |
| `isolation_level` | str | No | Active isolation level for current transaction |
| `transaction_start_time` | float | No | Timestamp when transaction began (for monitoring) |

### State Machine

```
┌─────────────────────────────────────────────────────────────┐
│                    Transaction State Machine                 │
└─────────────────────────────────────────────────────────────┘

    ┌──────────┐
    │   IDLE   │  ◄──── Initial state (no active transaction)
    └──────────┘
         │
         │ BEGIN / START TRANSACTION
         ├──────────────────────────────────────┐
         │                                      │
         ▼                                      │
    ┌──────────────┐                           │
    │IN_TRANSACTION│                           │
    └──────────────┘                           │
         │                                      │
         │ COMMIT ───────────┐                 │
         │                   │                 │
         │ ROLLBACK ─────────┤                 │
         │                   │                 │
         ▼                   ▼                 │
    ┌──────────┐        ┌──────────┐          │
    │   IDLE   │        │   IDLE   │          │
    └──────────┘        └──────────┘          │
         ▲                                     │
         │                                     │
         └─────────────────────────────────────┘

    ┌──────────────┐
    │IN_TRANSACTION│
    └──────────────┘
         │
         │ BEGIN (nested attempt)
         ├──────────────────────────────
         │
         ▼
    ┌──────────┐
    │  ERROR   │  ◄──── IRIS error: nested transactions not supported
    └──────────┘
         │
         │ ROLLBACK (error recovery)
         ├──────────────────────────────
         │
         ▼
    ┌──────────┐
    │   IDLE   │
    └──────────┘
```

### State Transitions

| From State | Event | To State | Notes |
|------------|-------|----------|-------|
| IDLE | BEGIN | IN_TRANSACTION | Start new transaction |
| IDLE | START TRANSACTION | IN_TRANSACTION | Explicit start (already IRIS-compatible) |
| IN_TRANSACTION | COMMIT | IDLE | Successful commit |
| IN_TRANSACTION | ROLLBACK | IDLE | Explicit rollback |
| IN_TRANSACTION | BEGIN | ERROR | IRIS limitation: nested transactions not supported |
| ERROR | ROLLBACK | IDLE | Error recovery via rollback |

### Validation Rules

1. **Nested Transaction Detection**:
   - If `status = IN_TRANSACTION` and client sends `BEGIN`, transition to `ERROR`
   - Server should pass `BEGIN` to IRIS and let IRIS return error (constitutional Protocol Fidelity)

2. **Isolation Level Tracking**:
   - If `BEGIN ISOLATION LEVEL <level>`, store `isolation_level = <level>`
   - Reset to None on COMMIT or ROLLBACK

3. **Timing Metrics**:
   - Record `transaction_start_time` when entering IN_TRANSACTION
   - Calculate transaction duration for monitoring on COMMIT/ROLLBACK

## Enumerations

### CommandType

```python
from enum import Enum

class CommandType(Enum):
    """PostgreSQL transaction command types"""
    BEGIN = "BEGIN"
    START_TRANSACTION = "START TRANSACTION"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"
    NONE = None  # Not a transaction command
```

### TransactionStatus

```python
from enum import Enum

class TransactionStatus(Enum):
    """Session transaction state"""
    IDLE = "I"  # PostgreSQL protocol ReadyForQuery 'I' indicator
    IN_TRANSACTION = "T"  # PostgreSQL protocol ReadyForQuery 'T' indicator
    ERROR = "E"  # PostgreSQL protocol ReadyForQuery 'E' indicator
```

## Relationships

```
┌─────────────────────┐         ┌──────────────────────┐
│ PostgreSQL Client   │         │   TransactionState   │
│                     │         │   (Session-Scoped)   │
└─────────────────────┘         └──────────────────────┘
         │                                 ▲
         │ Sends SQL command               │
         ├─────────────────────────────────┘
         │                                 │
         ▼                                 │
┌─────────────────────┐                   │
│ TransactionCommand  │                   │
│ (Ephemeral)         │                   │
└─────────────────────┘                   │
         │                                 │
         │ translate()                     │
         ├─────────────────────────────────┘
         │                                 │
         ▼                                 │
┌─────────────────────┐                   │
│  IRIS SQL Executor  │                   │
│                     │                   │
└─────────────────────┘                   │
         │                                 │
         │ Result updates state            │
         └─────────────────────────────────┘
```

**Key Relationships**:
1. Client sends SQL → creates TransactionCommand (ephemeral)
2. TransactionCommand translates SQL before execution
3. IRIS execution result updates TransactionState (session-scoped)
4. TransactionState persists for session lifetime, TransactionCommand destroyed after translation

## Data Flow

```
1. Client → Server: "BEGIN ISOLATION LEVEL READ COMMITTED"
   ↓
2. Parse as TransactionCommand:
   command_text = "BEGIN ISOLATION LEVEL READ COMMITTED"
   command_type = CommandType.BEGIN
   modifiers = "ISOLATION LEVEL READ COMMITTED"
   ↓
3. Translate:
   translated_text = "START TRANSACTION ISOLATION LEVEL READ COMMITTED"
   ↓
4. Update TransactionState:
   status = TransactionStatus.IN_TRANSACTION
   isolation_level = "READ COMMITTED"
   transaction_start_time = time.perf_counter()
   ↓
5. Execute translated SQL against IRIS:
   iris.sql.exec("START TRANSACTION ISOLATION LEVEL READ COMMITTED")
   ↓
6. Return ReadyForQuery with 'T' indicator (IN_TRANSACTION)
```

## Implementation Notes

### Thread Safety

**Not Required**: Each PostgreSQL protocol session has its own TransactionState instance. Session handler is single-threaded per connection (asyncio coroutine), so no mutex needed.

### Performance Considerations

**TransactionCommand Creation**: <0.01ms (simple value object)
**State Transition Overhead**: <0.001ms (enum comparison)
**Total Translation Overhead**: <0.1ms (constitutional target)

### Error Handling

**Nested Transaction Detection**:
```python
if transaction_state.status == TransactionStatus.IN_TRANSACTION:
    if command.command_type == CommandType.BEGIN:
        # Don't block - let IRIS return error (Protocol Fidelity)
        logger.warning("Nested transaction attempt - IRIS will error")
        # Continue with translation and execution
```

**Rationale**: Constitutional Principle I (Protocol Fidelity) requires we pass commands to IRIS rather than blocking them ourselves. IRIS error handling is authoritative.

## Testing Validation

### Contract Tests

```python
def test_transaction_command_creation():
    """Validate TransactionCommand value object"""
    cmd = TransactionCommand(
        command_text="BEGIN ISOLATION LEVEL READ COMMITTED",
        command_type=CommandType.BEGIN,
        modifiers="ISOLATION LEVEL READ COMMITTED",
        translated_text="START TRANSACTION ISOLATION LEVEL READ COMMITTED"
    )
    assert cmd.translated_text == "START TRANSACTION ISOLATION LEVEL READ COMMITTED"

def test_transaction_state_machine():
    """Validate state transitions"""
    state = TransactionState(status=TransactionStatus.IDLE)

    # IDLE + BEGIN → IN_TRANSACTION
    state.handle_begin()
    assert state.status == TransactionStatus.IN_TRANSACTION

    # IN_TRANSACTION + COMMIT → IDLE
    state.handle_commit()
    assert state.status == TransactionStatus.IDLE
```

## References

1. **PostgreSQL Protocol**: ReadyForQuery message transaction status indicators
   https://www.postgresql.org/docs/16/protocol-message-formats.html

2. **IRIS Transaction Documentation**: Transaction management and isolation levels
   (InterSystems IRIS SQL Reference)

3. **Specification**: FR-001 through FR-010 functional requirements
   `/Users/tdyar/ws/iris-pgwire/specs/022-postgresql-transaction-verb/spec.md`

---

**Next Steps**: Generate contract tests based on these entity definitions (Phase 1, Step 3).
