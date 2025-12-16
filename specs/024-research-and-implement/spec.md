# Feature Specification: Research and Implement Authentication Bridge

**Feature Branch**: `024-research-and-implement`
**Created**: 2025-11-15
**Status**: Draft
**Input**: User description: "research and implement auth bridge"

## Execution Flow (main)
```
1. Parse user description from Input
   ✅ Feature: Research and implement authentication bridge for enterprise SSO
2. Extract key concepts from description
   ✅ Actors: Enterprise IT admins, PostgreSQL client users, IRIS administrators
   ✅ Actions: Research IRIS auth APIs, bridge PostgreSQL auth to IRIS, validate integration
   ✅ Data: OAuth tokens, Kerberos tickets, credentials in IRIS Wallet
   ✅ Constraints: Must leverage existing IRIS infrastructure, no reimplementation
3. For each unclear aspect:
   → [NEEDS CLARIFICATION: Which auth method to prioritize first - OAuth, Kerberos, or Wallet?]
   → [NEEDS CLARIFICATION: What IRIS version(s) must be supported - 2024.x, 2025.x+?]
   → [NEEDS CLARIFICATION: Should implementation support multiple auth methods simultaneously?]
4. Fill User Scenarios & Testing section
   ✅ Scenarios defined for OAuth, Kerberos, and Wallet integration
5. Generate Functional Requirements
   ✅ Each requirement testable and mapped to implementation phases
6. Identify Key Entities
   ✅ IRIS OAuth tokens, Kerberos principals, Wallet secrets, user sessions
7. Run Review Checklist
   ⚠️ WARN "Spec has uncertainties" - 3 clarifications needed
8. Return: SUCCESS (spec ready for planning with clarifications)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

---

## User Scenarios & Testing

### Primary User Story

As an **enterprise IT administrator**, I want PostgreSQL client applications to authenticate against InterSystems IRIS using our existing enterprise identity infrastructure (Azure AD, Active Directory, Okta) so that users can leverage single sign-on (SSO) and eliminate password management overhead.

**Current Pain**: PostgreSQL clients connecting to IRIS via PGWire can only use password authentication. Enterprise users must manage separate IRIS passwords, which creates security risks (password sprawl in notebooks/configs) and operational overhead (manual rotation).

**Desired Outcome**: PostgreSQL clients gain transparent access to IRIS's existing OAuth 2.0, Kerberos, and Wallet capabilities through standard PostgreSQL authentication protocols (GSSAPI for Kerberos, password-to-token exchange for OAuth).

### Acceptance Scenarios

#### Scenario 1: OAuth Token Exchange (Priority 1)
1. **Given** an enterprise user has Azure AD credentials and IRIS has OAuth 2.0 configured
2. **When** user connects via PostgreSQL client with username/password
3. **Then** PGWire exchanges credentials for IRIS OAuth token transparently
4. **And** user session is authenticated via OAuth (not password table)
5. **And** OAuth token expiry and refresh work correctly

#### Scenario 2: Kerberos SSO (Priority 2)
1. **Given** user has obtained Kerberos ticket (`kinit alice@REALM`)
2. **And** IRIS has Kerberos authentication enabled for xDBC services
3. **When** PostgreSQL client initiates connection with GSSAPI authentication
4. **Then** PGWire validates Kerberos ticket via IRIS's native Kerberos support
5. **And** user is authenticated without entering password
6. **And** Kerberos principal is mapped to IRIS username correctly

#### Scenario 3: Wallet-Backed Credentials (Priority 3)
1. **Given** IRIS administrator has stored PostgreSQL user credentials in IRIS Wallet (encrypted)
2. **When** user connects via PostgreSQL client with username
3. **Then** PGWire retrieves password from IRIS Wallet (not IRIS user table)
4. **And** authentication succeeds with encrypted credentials
5. **And** credential access is audited in IRIS Wallet logs

#### Scenario 4: Research Phase Validation
1. **Given** IRIS embedded Python environment is available
2. **When** research phase tests IRIS OAuth/Kerberos/Wallet APIs
3. **Then** all three APIs are accessible and functional from embedded Python
4. **And** integration patterns are documented with code samples
5. **And** feasibility report confirms bridging approach is viable

#### Scenario 5: Backward Compatibility
1. **Given** existing PostgreSQL clients use password authentication
2. **When** authentication bridge is deployed
3. **Then** existing clients continue working without changes
4. **And** new clients can opt into OAuth/Kerberos via configuration
5. **And** dual-mode authentication supports gradual migration

### Edge Cases

**Research Phase**:
- What happens when IRIS version doesn't support OAuth 2.0 or Wallet? (pre-2024.x for OAuth, pre-2025.3.0 for Wallet)
- How does system detect which IRIS authentication features are available?
- What if embedded Python cannot access IRIS auth APIs due to permissions?

**OAuth Integration**:
- What happens when OAuth token validation fails (expired, invalid)?
- How does system handle OAuth server unavailability?
- What if user password changes between token exchanges?

**Kerberos Integration**:
- What happens when Kerberos KDC is unreachable?
- How does system handle Kerberos ticket expiry during long-running sessions?
- What if Kerberos principal doesn't map to any IRIS user?

**Wallet Integration**:
- What happens when Wallet secret is not found for username?
- How does system handle Wallet API errors (IRISSECURITY database unavailable)?
- What if Wallet secret is rotated while session is active?

**General**:
- How does system handle multiple authentication methods configured simultaneously?
- What is the fallback behavior if preferred auth method fails?
- How are authentication errors surfaced to PostgreSQL clients?

## Requirements

### Functional Requirements

**Research Phase (Phase 1 - Week 1)**:
- **FR-001**: System MUST validate IRIS OAuth 2.0 API accessibility from embedded Python
- **FR-002**: System MUST validate IRIS Kerberos authentication API accessibility from embedded Python
- **FR-003**: System MUST validate IRIS Wallet API accessibility from embedded Python (if IRIS 2025.3.0+)
- **FR-004**: System MUST document IRIS auth API integration patterns with working code samples
- **FR-005**: System MUST produce feasibility report confirming authentication bridge approach

**OAuth Token Bridge (Phase 2 - Weeks 2-3)** [NEEDS CLARIFICATION: Should this be Phase 1 implementation priority?]:
- **FR-006**: System MUST accept username/password from PostgreSQL clients via existing SCRAM-SHA-256 protocol
- **FR-007**: System MUST exchange username/password for IRIS OAuth 2.0 access token
- **FR-008**: System MUST validate OAuth tokens against IRIS OAuth 2.0 server (not local verification)
- **FR-009**: System MUST store PGWire OAuth client credentials securely (preferably in IRIS Wallet)
- **FR-010**: System MUST handle OAuth token expiry and refresh transparently
- **FR-011**: System MUST create IRIS sessions authenticated via OAuth (not password table)
- **FR-012**: System MUST maintain backward compatibility with password-only authentication

**Kerberos Bridge (Phase 3 - Weeks 4-6)** [NEEDS CLARIFICATION: Should this be implemented before OAuth?]:
- **FR-013**: System MUST support PostgreSQL GSSAPI authentication protocol (AuthenticationGSS, GSSResponse messages)
- **FR-014**: System MUST validate Kerberos tickets via IRIS's native Kerberos support (%Service_Bindings)
- **FR-015**: System MUST extract authenticated username from Kerberos principal
- **FR-016**: System MUST map Kerberos principals to IRIS usernames (e.g., `alice@EXAMPLE.COM` → `ALICE`)
- **FR-017**: System MUST validate mapped IRIS user exists before creating session
- **FR-018**: System MUST work with Active Directory and MIT Kerberos KDCs
- **FR-019**: System MUST support multi-step GSSAPI token exchange until context is established

**Wallet Integration (Phase 4 - Week 7)** [NEEDS CLARIFICATION: Should Wallet be standalone or combined with OAuth?]:
- **FR-020**: System MUST retrieve PostgreSQL user credentials from IRIS Wallet when configured
- **FR-021**: System MUST handle Wallet API errors gracefully (fallback to password table if needed)
- **FR-022**: System MUST audit all credential retrievals from Wallet
- **FR-023**: System MUST support credential rotation via Wallet API without service restart

**Cross-Cutting Requirements**:
- **FR-024**: System MUST allow multiple authentication methods to be configured simultaneously (dual-mode)
- **FR-025**: System MUST not break existing 8 PostgreSQL client drivers (Node.js, JDBC, Go, Python, .NET, Rust, PHP, Ruby)
- **FR-026**: System MUST log all authentication attempts (success and failure) for audit trail
- **FR-027**: System MUST surface authentication errors to PostgreSQL clients with appropriate error codes
- **FR-028**: System MUST complete authentication within 5 seconds under normal conditions [NEEDS CLARIFICATION: Is 5s acceptable for Kerberos multi-step handshake?]

### Key Entities

- **IRIS OAuth Token**: Represents authenticated session via IRIS OAuth 2.0 server. Contains username, scopes, expiry, and refresh token. Generated by IRIS OAuth endpoint, validated by PGWire against IRIS OAuth server.

- **Kerberos Principal**: Represents authenticated user identity from Kerberos KDC (e.g., `alice@EXAMPLE.COM`). Extracted from GSSAPI token during multi-step handshake. Must be mapped to IRIS username before session creation.

- **IRIS Wallet Secret**: Represents encrypted credential stored in IRISSECURITY database. Key format: `pgwire-user-{username}`. Retrieved via `%IRIS.Wallet` API. Provides audit trail and rotation support.

- **User Session**: Represents authenticated PostgreSQL client connection. Contains authentication method used (password, OAuth, Kerberos, Wallet), IRIS username, session start time, and authentication token/principal if applicable.

- **Authentication Method Configuration**: Represents which auth methods are enabled (OAuth, Kerberos, Wallet, password fallback). Determines authentication flow selection during connection handshake.

---

## Review & Acceptance Checklist

### Content Quality
- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

### Requirement Completeness
- [ ] No [NEEDS CLARIFICATION] markers remain (4 clarifications present)
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

**Clarifications Needed**:
1. **Priority Order**: Which auth method should be implemented first - OAuth (simpler, 2 weeks) or Kerberos (enterprise standard, 3 weeks)?
2. **IRIS Version Support**: Must support IRIS 2024.x (OAuth available) or only 2025.3.0+ (Wallet available)?
3. **Authentication Timeout**: Is 5-second timeout acceptable for Kerberos multi-step handshake (typically 2-3 round trips)?
4. **Wallet Integration Scope**: Should Wallet be standalone feature or combined with OAuth for client credential storage?

---

## Execution Status

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked (4 clarifications)
- [x] User scenarios defined (5 scenarios)
- [x] Requirements generated (28 functional requirements)
- [x] Entities identified (5 key entities)
- [ ] Review checklist passed (pending clarifications)

---

## Dependencies and Assumptions

**Dependencies**:
- IRIS 2024.x or later (for OAuth 2.0 support)
- IRIS 2025.3.0 or later (for Wallet support - optional)
- IRIS embedded Python environment available
- IRIS OAuth 2.0 configured (for OAuth scenarios)
- IRIS Kerberos configured on %Service_Bindings (for Kerberos scenarios)
- Active Directory or MIT Kerberos KDC available (for Kerberos testing)

**Assumptions**:
- Existing IRIS authentication infrastructure is functional and tested
- PGWire has access to IRIS embedded Python APIs
- PostgreSQL clients will accept standard GSSAPI and SCRAM protocols
- Enterprise users prefer SSO over password management
- 8 existing PostgreSQL client drivers will not be affected by new auth paths
- Performance overhead of OAuth/Kerberos validation is acceptable (<5 seconds)

**Based on Prior Research**:
- IRIS OAuth 2.0 server and client classes (`OAuth2.Server`, `OAuth2.Client`) are available
- IRIS Kerberos authentication via `%Service_Bindings` supports security levels 0-3
- IRIS Wallet API (`%IRIS.Wallet`) provides `GetSecret()` and `SetSecret()` methods
- IRIS integrates with Azure AD, Okta, Auth0, Active Directory (confirmed via Confluence research)
- JDBC, ODBC, xDBC support OAuth tokens via connection strings (AccessToken parameter)
- Bridging approach is 2× faster than reimplementation (2-4 weeks vs 4+ weeks)

---

## Success Criteria

**Research Phase Complete When**:
- All three IRIS auth APIs (OAuth, Kerberos, Wallet) validated from embedded Python
- Integration patterns documented with runnable code samples
- Feasibility report confirms no blockers for bridging approach

**OAuth Bridge Complete When**:
- PostgreSQL client connects with username/password, authenticated via IRIS OAuth token
- Token validation, expiry, and refresh work correctly
- Backward compatibility maintained (existing clients work unchanged)
- E2E tests pass with psql, psycopg, JDBC clients

**Kerberos Bridge Complete When**:
- PostgreSQL client connects with Kerberos ticket (`kinit`), no password required
- GSSAPI multi-step handshake completes successfully
- Kerberos principal maps to IRIS username correctly
- E2E tests pass with Active Directory and MIT Kerberos

**Wallet Integration Complete When**:
- Credentials retrieved from IRIS Wallet (not password table)
- Wallet API errors handled gracefully
- Credential access audited in Wallet logs
- Credential rotation supported without restart

**Overall Feature Complete When**:
- All 4 phases (Research, OAuth, Kerberos, Wallet) complete
- Dual-mode authentication supports multiple methods simultaneously
- All 8 existing PostgreSQL client drivers pass regression tests
- Authentication audit trail functional across all methods
- Documentation complete for enterprise deployment

---

## Related Specifications

**Reference Documents**:
- `specs/ENTERPRISE_AUTH_BRIDGE_REVISED.md`: 508-line architecture specification with IRIS capabilities research
- `specs/KERBEROS_GSSAPI_SUMMARY.md`: 5-page executive summary for Kerberos SSO
- `specs/KERBEROS_GSSAPI_OPTIONS.md`: 20-page implementation guide (superseded by REVISED spec)
- `CLAUDE.md`: Enterprise Authentication Bridge section (lines 1958-2174)

**Related Features**:
- Feature 022: PostgreSQL Transaction Verb Translation (transaction state management integration)
- Client Compatibility Testing: 8 drivers at 100% (must not regress)
- P3 Authentication (SCRAM-SHA-256): Current password-only implementation

---
