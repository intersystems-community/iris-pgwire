# ADR-0003: Passwords are sent in the clear over TLS and verified by logging in to IRIS

- **Status**: Accepted
- **Date**: 2026-10-24
- **Deciders**: Thomas Dyar
- **Relates to**: ADR-0004, `CONTEXT.md` §Authentication, `src/iris_pgwire/password_auth.py`

## Context

Until this decision no version of iris-pgwire authenticated anyone. The default launch answered
`AuthenticationOk` before any credential was exchanged and ran every session as the configured IRIS
service account. The README, `DEPLOYMENT.md` and `KNOWN_LIMITATIONS.md` described SCRAM-SHA-256,
OAuth 2.0 and IRIS Wallet credentials as available, and said no password was ever sent in plain text.

Measured on 2026-10-24:

- The SCRAM exchange never examined the client's proof. It accepted "any well-formed client-final
  message", handed the next stage the literal password `"placeholder_password"`, and answered with a
  constant server signature.
- It could not have examined one. The salt was drawn at random for each connection and nothing in
  this codebase held a verifier. SCRAM needs the server to hold a salted hash of the password that
  it can derive keys from, and no supported way to get one from IRIS was found.
- `PGWIRE_ENABLE_SCRAM`, which the docs told operators to set, was read by no code.
- A libpq client with the right password could not log in under SCRAM at all: the parser required a
  non-empty `n=` username and libpq sends an empty one.
- The OAuth and Wallet code was reachable only through that SCRAM exchange.

So the choice was not "fix SCRAM". It was what to build in its place.

## Decision

The client sends its password (PostgreSQL's `AuthenticationCleartextPassword` exchange) and the
server checks it by logging in to IRIS with it. IRIS stays the only store of users and passwords;
pgwire keeps no verifier file and no copy.

Because the password crosses the wire, TLS is required. A server with neither TLS nor an explicit
choice refuses to start, and says why. The choices, all deliberate:

1. TLS (`PGWIRE_SSL_ENABLED` with a certificate).
2. `--allow-plaintext-password`, for a trusted network or a TLS-terminating proxy in front.
3. `--trust`, no authentication, for local development. Never the default.

Credentials are required by default, which is a breaking change.

How the check is made differs by backend, because the backends reach IRIS differently:

- **DBAPI**: open a one-off DBAPI connection with the client's credentials and confirm it with
  `SELECT 1`. The confirmation matters: `connect()` returning proves nothing when `iris.dbapi` is a
  stand-in, and this repository's own environment has two (the embedded wrapper hands out mocks, and
  other tests leave a fake in `sys.modules`). A verifier that trusted `connect()` would accept any
  password there.
- **Embedded**: `%SYSTEM.Security.Login` in a throwaway child process, with the password on stdin.
  It has to be a child. A successful `Login` switches the calling process to that IRIS user
  (measured: `irisowner` becomes `_SYSTEM`), which in the shared server would silently change the
  identity of every concurrent query. The DBAPI route is not callable under `irispython` at all.

A check has three answers: accepted, denied, and could not check. An unreachable IRIS is reported as
`57P03` and never as a wrong password. A wrong password, an unknown user and an empty password are
refused identically (`28P01`), so the answer does not reveal which accounts exist.

## Alternatives rejected

- **SCRAM-SHA-256 against a verifier file pgwire owns.** The standard answer, and it would keep the
  password off the wire. It means a second credential store, which drifts from IRIS the moment a
  password is changed there, and a new secret-handling surface to defend. IRIS is where users
  already live and are already audited.
- **MD5.** Deprecated, and it needs the same stored verifier.
- **Trust by default, as before.** Every release up to 1.7.3 did this. It is not a defensible
  default for a network service that proxies a database.
- **Keep OAuth 2.0 and Wallet.** Neither was reachable except through the SCRAM exchange that
  checked nothing. They were removed rather than left as code that fails open (see
  `src/iris_pgwire/auth/__init__.py`).
- **Kerberos/GSSAPI.** Deferred, as before.

## Consequences

**Costs.** The password is readable by anyone who can see an unencrypted connection, which is why TLS
is required and the opt-out is named for what it does. A password check costs one IRIS login, and a
failed one costs about two seconds because IRIS delays it. IRIS's own lockout policy applies, so
anyone who can reach the port can attempt logins and may lock an account out; the port belongs behind
a network boundary. A licence-limited IRIS spends a connection per check, transiently.

**This does not separate users.** It proves a client knows an IRIS user's password and nothing else.
Statements still run as the service account (ADR-0004).

**Before this change** a TLS client could not connect to a TLS-enabled server at all: the server
slept between answering `S` and upgrading, so the client's ClientHello was consumed as plain data and
the handshake hung. That was fixed in the same change, because "TLS is required" is not a rule
anyone can follow if TLS does not work.

## When to reopen

- A supported way to obtain a SCRAM verifier from IRIS, or to check a SCRAM proof against it, is
  found, so that the password need not be sent.
- A second credential store becomes acceptable for a reason that outweighs the drift.
- Connection volume makes a login per connection too expensive, in which case the answer is a
  bounded cache of recent successful checks, with its expiry stated, not a weaker check.
