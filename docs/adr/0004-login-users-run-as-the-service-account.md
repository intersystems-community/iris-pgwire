# ADR-0004: Every login user runs as the service account, and only listed users may log in

- **Status**: Accepted
- **Date**: 2026-10-24
- **Deciders**: Thomas Dyar
- **Relates to**: ADR-0003, ADR-0001, `CONTEXT.md` §Authentication

## Context

ADR-0003 settles how a password is checked. It does not settle what a correct password grants.

The server executes every statement as one IRIS user, the service account (`IRIS_USERNAME`, default
`_SYSTEM`). The pool, and the embedded process, belong to that user. So a login user's own
privileges play no part. Scenario: `reporting_ro`, an IRIS user with read-only rights, connects with
its own correct password and runs `DROP TABLE`. The statement executes as `_SYSTEM` and succeeds.

Executing as the login user would fix that, but it is not available on both backends. The DBAPI
backend could open a connection per login user. The embedded backend cannot: the IRIS user is a
property of the process, so it has one identity at a time. This is the same cause as the
process-scoped transaction measured for ADR-0001, and it is why ADR-0003's embedded check has to run
in a child process.

## Decision

1. Every login user runs as the service account. Authentication proves a client knows a login user's
   password and grants the service account's privileges. This is stated in the README,
   `DEPLOYMENT.md` and `KNOWN_LIMITATIONS.md`, so nobody relies on it for separation they do not
   have.
2. Only listed login users may connect. If `PGWIRE_ALLOWED_USERS` is unset, the only login user is
   the service account. A list replaces that default rather than extending it. Names compare
   case-insensitively; IRIS still checks the real credentials.
3. A login user who is not listed is refused without any attempt to log in to IRIS. IRIS counts
   failed logins and locks accounts, so a stranger must not be able to spend another user's attempts.
   The refusal reads exactly like a wrong password and waits as long as a failed IRIS login does, so
   neither its text nor its timing reveals who is on the list.
4. Per-session identity is deferred. If it is built it is a declared capability, true on DBAPI and
   false on embedded, not a behaviour the core assumes.

## Alternatives rejected

- **Any IRIS user with a valid password may log in.** The simplest, and what "authentication" often
  means. Here it hands each of them the service account's privileges, which is a privilege-escalation
  path presented as access control.
- **Run each session as its login user.** The right end state for DBAPI. Not now: it needs a
  connection per login user, interacts with the pool and the licence ceiling (7 on Community Edition),
  and cannot exist on the embedded backend, so it cannot be the product's identity model yet.

## Consequences

An operator who wants several people connecting must list them, and must understand that listing a
user grants that person the service account's power. The safe use of the list is to name the people
or tools who would be trusted with that account anyway.

The service account is also the most exposed to IRIS's lockout, since it is the default login user
and the account the server's own pool uses. See ADR-0003 for the lockout cost.

## When to reopen

When per-session identity is wanted. It would arrive as a capability (`per_session_identity`), with
the embedded backend declared unable, and this ADR's first decision would then hold only for the
backend that cannot do it.
