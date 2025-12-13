
# Implementation Plan: Research and Implement Authentication Bridge

**Branch**: `024-research-and-implement` | **Date**: 2025-11-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/Users/tdyar/ws/iris-pgwire/specs/024-research-and-implement/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → If not found: ERROR "No feature spec at {path}"
2. Fill Technical Context (scan for NEEDS CLARIFICATION)
   → Detect Project Type from file system structure or context (web=frontend+backend, mobile=app+api)
   → Set Structure Decision based on project type
3. Fill the Constitution Check section based on the content of the constitution document.
4. Evaluate Constitution Check section below
   → If violations exist: Document in Complexity Tracking
   → If no justification possible: ERROR "Simplify approach first"
   → Update Progress Tracking: Initial Constitution Check
5. Execute Phase 0 → research.md
   → If NEEDS CLARIFICATION remain: ERROR "Resolve unknowns"
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, agent-specific template file (e.g., `CLAUDE.md` for Claude Code, `.github/copilot-instructions.md` for GitHub Copilot, `GEMINI.md` for Gemini CLI, `QWEN.md` for Qwen Code or `AGENTS.md` for opencode).
7. Re-evaluate Constitution Check section
   → If new violations: Refactor design, return to Phase 1
   → Update Progress Tracking: Post-Design Constitution Check
8. Plan Phase 2 → Describe task generation approach (DO NOT create tasks.md)
9. STOP - Ready for /tasks command
```

**IMPORTANT**: The /plan command STOPS at step 7. Phases 2-4 are executed by other commands:
- Phase 2: /tasks command creates tasks.md
- Phase 3-4: Implementation execution (manual or via tools)

## Summary

**Primary Requirement**: Enable PostgreSQL client applications to authenticate against InterSystems IRIS using enterprise identity infrastructure (OAuth 2.0, Kerberos, IRIS Wallet) instead of password-only authentication, providing single sign-on (SSO) capabilities and eliminating password management overhead.

**Technical Approach**: Bridge PostgreSQL wire protocol authentication (SCRAM-SHA-256, GSSAPI) to IRIS's existing OAuth 2.0, Kerberos, and Wallet capabilities. This leverages IRIS's native enterprise authentication infrastructure rather than reimplementing from scratch, reducing implementation timeline from 4+ weeks to 2-4 weeks.

**Key Innovation**: IRIS already has enterprise-grade OAuth 2.0 (RFC 6749, RFC 7636), Kerberos (%Service_Bindings), and encrypted credential storage (Wallet via IRISSECURITY database). The authentication bridge maps PostgreSQL protocols to these existing capabilities, enabling transparent SSO for all 8 PostgreSQL client drivers currently at 100% compatibility.

## Technical Context
**Language/Version**: Python 3.11+ (matching existing PGWire server implementation)
**Primary Dependencies**:
- python-gssapi>=1.8.0 (Kerberos GSSAPI authentication)
- cryptography>=41.0.0 (existing, for SCRAM-SHA-256)
- intersystems-irispython>=5.1.2 (IRIS embedded Python - existing)
- asyncio (existing event loop for concurrent connections)

**Storage**: IRIS IRISSECURITY database (for Wallet encrypted credentials), IRIS Security.Users table (user validation)
**Testing**: pytest with iris-devtester (isolated IRIS containers), E2E with psql/psycopg/JDBC clients, k5test (Kerberos test realms)
**Target Platform**: Linux server (Docker containers), macOS development (Homebrew Kerberos libraries)
**Project Type**: Single project (existing iris-pgwire codebase)
**Performance Goals**:
- Authentication latency <5 seconds (FR-028, constitutional requirement)
- Translation overhead <0.1ms per query (constitutional SLA)
- Support 1000 concurrent connections (constitutional requirement)

**Constraints**:
- MUST maintain backward compatibility with 8 existing PostgreSQL client drivers (FR-025)
- MUST use IRIS embedded Python (no external DBAPI) for auth API access
- OAuth 2.0 requires IRIS 2024.x+, Wallet requires IRIS 2025.3.0+ (FR-002, FR-003)
- Kerberos requires keytab file deployment and KDC availability (security constraint)

**Scale/Scope**:
- 28 functional requirements across 4 phases
- 3 authentication methods (OAuth, Kerberos, Wallet) + password fallback
- Integration with existing P3 authentication (SCRAM-SHA-256)
- 8 PostgreSQL client drivers regression testing (171 existing tests)

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**I. Protocol Fidelity** ✅ PASS
- Implements PostgreSQL GSSAPI authentication protocol (AuthenticationGSS, GSSResponse) per spec
- OAuth token exchange uses existing SCRAM-SHA-256 protocol (no protocol changes)
- Wallet integration transparent to clients (backend-only credential retrieval)
- No deviations from PostgreSQL wire protocol standards

**II. Test-First Development** ✅ PASS (with iris-devtester requirement)
- FR-004 requires E2E tests with psql, psycopg, JDBC clients before implementation
- FR-025 requires regression testing of all 8 existing client drivers
- Research phase (FR-001-FR-005) validates APIs before implementation
- MUST use iris-devtester for isolated IRIS containers (constitutional requirement)
- k5test library provides isolated Kerberos test realms (no shared KDC state)

**III. Phased Implementation** ✅ PASS
- Follows constitutional P0-P6 sequence: Authentication bridge extends P3 (existing SCRAM auth)
- Phase 1 (Research) validates IRIS APIs before Phase 2-4 implementation
- Each phase has clear success criteria (spec.md lines 237-265)
- No phase skipping: OAuth before Kerberos before Wallet

**IV. IRIS Integration** ✅ PASS
- Uses IRIS embedded Python (`import iris`) for OAuth/Kerberos/Wallet API access
- FR-001-FR-003 validate API accessibility from embedded Python
- FR-014 uses IRIS %Service_Bindings for Kerberos validation (not reimplementation)
- FR-009 uses IRIS Wallet for encrypted credential storage
- CallIn service already enabled (prerequisite for PGWire server operation)

**V. Production Readiness** ✅ PASS
- FR-026 requires audit trail for all authentication attempts
- FR-027 requires proper error surfacing to clients
- FR-009 requires secure storage of OAuth client credentials (preferably Wallet)
- Kerberos keytab protection via Docker secrets (documented in KERBEROS_GSSAPI_SUMMARY.md)
- TLS already enforced by existing PGWire implementation

**VI. Vector Performance Requirements** N/A
- Authentication bridge does not involve vector operations
- No HNSW index or vector query rewriting required

**VII. Development Environment Synchronization** ✅ PASS
- MUST restart Docker container after code changes (constitutional requirement)
- MUST validate container uptime vs code change timestamp before debugging
- iris-devtester provides fresh containers per test (automatic synchronization)

**Performance Standards** ✅ PASS (with clarification needed)
- FR-028 requires <5 second authentication latency (constitutional compliance)
- NEEDS CLARIFICATION: Is 5s acceptable for Kerberos multi-step handshake (2-3 round trips)?
- Query translation overhead <5ms maintained (no changes to query execution path)
- GSSAPI handshake overhead ~400ms (benchmark from KERBEROS_GSSAPI_OPTIONS.md:759)

**Security Requirements** ✅ PASS
- Extends existing SCRAM-SHA-256 implementation (no weakening)
- Kerberos ticket validation prevents replay attacks
- OAuth token validation against IRIS server (FR-008, not local verification)
- Wallet credentials encrypted in IRISSECURITY database
- FR-026 audit trail for compliance

**GATE STATUS**: ✅ **PASS** - Proceed to Phase 0 Research
- No constitutional violations detected
- 1 clarification needed (Kerberos timeout) - does not block research phase
- Complexity justified by enterprise SSO requirements

## Project Structure

### Documentation (this feature)
```
specs/[###-feature]/
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (/plan command)
├── data-model.md        # Phase 1 output (/plan command)
├── quickstart.md        # Phase 1 output (/plan command)
├── contracts/           # Phase 1 output (/plan command)
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
src/iris_pgwire/
├── auth/                         # Authentication components (NEW)
│   ├── __init__.py
│   ├── gssapi_auth.py           # Kerberos GSSAPI authentication (Phase 3)
│   ├── oauth_bridge.py          # OAuth 2.0 token exchange (Phase 2)
│   ├── wallet_credentials.py   # IRIS Wallet integration (Phase 4)
│   └── auth_selector.py         # Dual-mode authentication routing
├── protocol.py                   # Extend for AuthenticationGSS messages (EXISTING)
├── iris_executor.py             # Extend for IRIS auth API calls (EXISTING)
└── server.py                    # Main server (EXISTING)

tests/
├── contract/                     # API contract tests
│   ├── test_oauth_bridge_contract.py
│   ├── test_gssapi_auth_contract.py
│   └── test_wallet_credentials_contract.py
├── integration/                  # IRIS integration tests (with iris-devtester)
│   ├── test_oauth_token_exchange.py
│   ├── test_kerberos_validation.py
│   └── test_wallet_retrieval.py
├── unit/                        # Unit tests
│   ├── test_gssapi_token_parsing.py
│   ├── test_oauth_token_validation.py
│   └── test_principal_mapping.py
└── e2e/                         # E2E client tests
    ├── test_psql_kerberos.py
    ├── test_psycopg_oauth.py
    └── test_jdbc_wallet.py

examples/                         # Example configurations (NEW)
├── oauth-config.yml             # OAuth 2.0 client setup
├── kerberos-keytab/             # Keytab deployment example
└── wallet-secrets.py            # Wallet credential management scripts
```

**Structure Decision**: Single project structure (Option 1) with new `auth/` module added to existing `src/iris_pgwire/` codebase. Tests follow existing TDD pattern with contract/integration/unit/e2e separation. Authentication components are isolated in `auth/` module to maintain separation of concerns and enable independent testing of OAuth, Kerberos, and Wallet paths.

## Phase 0: Outline & Research
1. **Extract unknowns from Technical Context** above:
   - For each NEEDS CLARIFICATION → research task
   - For each dependency → best practices task
   - For each integration → patterns task

2. **Generate and dispatch research agents**:
   ```
   For each unknown in Technical Context:
     Task: "Research {unknown} for {feature context}"
   For each technology choice:
     Task: "Find best practices for {tech} in {domain}"
   ```

3. **Consolidate findings** in `research.md` using format:
   - Decision: [what was chosen]
   - Rationale: [why chosen]
   - Alternatives considered: [what else evaluated]

**Output**: ✅ research.md with all NEEDS CLARIFICATION resolved (9 research questions answered)

**Key Decisions**:
- OAuth → Kerberos → Wallet implementation sequence
- IRIS 2024.x+ required (2025.3.0+ for Wallet)
- 5-second authentication timeout (10× safety margin)
- Dual-purpose Wallet (OAuth secrets + user passwords)
- python-gssapi>=1.8.0 for Kerberos
- Strip realm + uppercase + validate for principal mapping

## Phase 1: Design & Contracts
*Prerequisites: research.md complete*

1. **Extract entities from feature spec** → `data-model.md`:
   - Entity name, fields, relationships
   - Validation rules from requirements
   - State transitions if applicable

2. **Generate API contracts** from functional requirements:
   - For each user action → endpoint
   - Use standard REST/GraphQL patterns
   - Output OpenAPI/GraphQL schema to `/contracts/`

3. **Generate contract tests** from contracts:
   - One test file per endpoint
   - Assert request/response schemas
   - Tests must fail (no implementation yet)

4. **Extract test scenarios** from user stories:
   - Each story → integration test scenario
   - Quickstart test = story validation steps

5. **Update agent file incrementally** (O(1) operation):
   - Run `.specify/scripts/bash/update-agent-context.sh claude`
     **IMPORTANT**: Execute it exactly as specified above. Do not add or remove any arguments.
   - If exists: Add only NEW tech from current plan
   - Preserve manual additions between markers
   - Update recent changes (keep last 3)
   - Keep under 150 lines for token efficiency
   - Output to repository root

**Output**: data-model.md, /contracts/*, failing tests, quickstart.md, agent-specific file

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Load `.specify/templates/tasks-template.md` as base
- Generate tasks from Phase 1 design docs (contracts, data model, quickstart)
- Each contract → contract test task [P]
- Each entity → model creation task [P]
- Each user story → integration test task
- Implementation tasks to make tests pass

**Ordering Strategy**:
- TDD order: Tests before implementation
- Dependency order: Models before services before UI
- Mark [P] for parallel execution (independent files)

**Phase-Specific Task Breakdown**:
1. **Research Phase Tasks** (T001-T009):
   - API validation tasks (FR-001, FR-002, FR-003)
   - Integration pattern documentation (FR-004)
   - Feasibility report generation (FR-005)

2. **OAuth Implementation Tasks** (T010-T024):
   - Contract tests for `OAuthBridgeProtocol` (6 tests from contract interface)
   - OAuth bridge implementation (`src/iris_pgwire/auth/oauth_bridge.py`)
   - Token exchange, validation, refresh flows
   - Client credential management (Wallet integration in Phase 4)
   - E2E tests with psql, psycopg, JDBC (Test Suite 1 from quickstart.md)

3. **Kerberos Implementation Tasks** (T025-T039):
   - Contract tests for `GSSAPIAuthenticatorProtocol` (4 tests from contract interface)
   - GSSAPI authentication implementation (`src/iris_pgwire/auth/gssapi_auth.py`)
   - Protocol message handling (AuthenticationGSS, GSSResponse, AuthenticationGSSContinue)
   - Principal extraction and mapping
   - Keytab deployment and KDC validation
   - E2E tests with psql GSSAPI, psycopg Kerberos (Test Suite 2 from quickstart.md)

4. **Wallet Implementation Tasks** (T040-T054):
   - Contract tests for `WalletCredentialsProtocol` (3 tests from contract interface)
   - Wallet integration implementation (`src/iris_pgwire/auth/wallet_credentials.py`)
   - Password retrieval with fallback
   - Credential rotation support
   - Audit trail implementation (FR-022)
   - E2E tests with Wallet-backed credentials (Test Suite 3 from quickstart.md)

5. **Dual-Mode Authentication Tasks** (T055-T064):
   - Authentication selector implementation (`src/iris_pgwire/auth/auth_selector.py`)
   - Multi-method routing (OAuth → Kerberos → Wallet → password)
   - Configuration management (environment variables)
   - Timeout enforcement (5-second limit)
   - Backward compatibility validation (8 existing client drivers)
   - E2E regression testing (FR-025)

6. **Production Readiness Tasks** (T065-T070):
   - Error handling and surfacing (FR-027)
   - Audit trail implementation (FR-026)
   - Performance benchmarking (FR-028 validation)
   - Documentation updates (CLAUDE.md, README.md)
   - Deployment guide (Docker secrets, keytab deployment)

**Estimated Output**: 65-70 numbered, ordered tasks in tasks.md

**Task Parallelization**:
- Contract tests can run in parallel [P] (independent files)
- OAuth, Kerberos, Wallet implementations can be developed in parallel after contracts complete
- Integration with existing `protocol.py` and `iris_executor.py` requires sequential execution

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)  
**Phase 4**: Implementation (execute tasks.md following constitutional principles)  
**Phase 5**: Validation (run tests, execute quickstart.md, performance validation)

## Complexity Tracking
*Fill ONLY if Constitution Check has violations that must be justified*

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |


## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command) ✅ **2025-11-15**
  - Created research.md with 9 research questions answered
  - All [NEEDS CLARIFICATION] markers resolved
  - Key decisions: OAuth → Kerberos → Wallet sequence, 5s timeout, dual-purpose Wallet
- [x] Phase 1: Design complete (/plan command) ✅ **2025-11-15**
  - Created data-model.md with 5 entities documented
  - Created 3 contract interfaces (OAuth, Kerberos, Wallet)
  - Created quickstart.md with E2E validation tests
  - Updated CLAUDE.md with authentication context
- [x] Phase 2: Task planning approach described (/plan command) ✅ **2025-11-15**
  - Estimated 65-70 tasks across 6 categories
  - Defined parallelization strategy
  - Mapped tasks to functional requirements
- [x] Phase 3: Tasks generated (/tasks command) ✅ **2025-11-15**
  - Created tasks.md with 70 ordered tasks (T001-T070)
  - 38 parallel tasks [P] (independent files)
  - 32 sequential tasks (shared files or dependencies)
  - All 28 functional requirements mapped to tasks
  - All 5 acceptance scenarios covered by E2E tests
  - TDD workflow: Tests before implementation (Phase 3.2 blocks 3.4)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS ✅
  - All 7 principles evaluated
  - No constitutional violations detected
  - 1 clarification needed (Kerberos timeout) - resolved in research.md
- [x] Post-Design Constitution Check: PASS ✅
  - Data model aligns with Protocol Fidelity (PostgreSQL GSSAPI protocol)
  - Contracts enable Test-First Development
  - IRIS Integration via embedded Python (`iris.cls()`)
  - No new constitutional violations introduced
- [x] All NEEDS CLARIFICATION resolved ✅
  - R1: Authentication priority order (OAuth first)
  - R2: IRIS version support (2024.x+ for OAuth, 2025.3.0+ for Wallet)
  - R3: Authentication timeout (5 seconds acceptable)
  - R4: Wallet integration scope (dual-purpose: OAuth secrets + user passwords)
  - Plus 5 additional research decisions documented in research.md
- [x] Complexity deviations documented ✅
  - No deviations from constitutional simplicity requirements
  - Complexity justified by enterprise SSO requirements
  - All requirements align with existing constitutional principles

---
*Based on Constitution v2.1.1 - See `/memory/constitution.md`*
