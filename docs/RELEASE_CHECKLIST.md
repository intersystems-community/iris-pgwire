# Release Checklist

Companion to [RELEASING.md](RELEASING.md), which says _how_ to publish. This
says _whether to_. Every gate below names the command that decides it, so the
answer is measured rather than recalled.

Status column meaning: measured on **2026-11-13** for **2.0.0**, on branch `release/2.0`
(`0c45132` plus the IPM and SIGTERM fixes), against a throwaway IRIS 2026.2.0.221.0com lab
(`pgwire-release-lab`, Community Edition). The project container `iris-pgwire-db` could not be
started (OrbStack holds a stale reservation for its host port 52776), so nothing here was measured
on it.

## 1. Preconditions

| #   | Gate                                              | Command                                    | Status                                                                                                |
| --- | ------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| 1.1 | Working tree clean                                | `git status --short`                       | ✅ on `release/2.0`                                                                                   |
| 1.2 | `origin/main` contains what PyPI already has      | `git log --oneline origin/main..HEAD`      | ❌ `origin/main` is **v1.7.1** (`8783ba1`); PyPI is **1.7.3**. Pushing `release/2.0` fast-forwards it |
| 1.3 | Every push target in the release docs exists      | `git remote -v`                            | ❌ RELEASING.md pushes to `community`; only `origin` exists (it is the community repository)          |
| 1.4 | IRIS reachable for the container-backed gates     | `docker exec pgwire-release-lab iris list` | ✅ the lab; ❌ `iris-pgwire-db`                                                                       |
| 1.5 | One version source, and it is the one hatch reads | `grep -rn '__version__ =' src/`            | ✅ `src/iris_pgwire/__init__.py`, **2.0.0**                                                           |

## 2. Test gates

Run each in its **own** pytest process, one backend at a time. Container-backed suites contaminate
one another inside a single process, and a Community Edition licence pool (7 connections) is shared,
so two at once produce "Unable to allocate a license" rather than failures that mean anything.

| #   | Gate                     | Command                                                                    | Status                                                                                                                                       |
| --- | ------------------------ | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 2.1 | Whole tree **collects**  | `pytest tests/ --collect-only -q`                                          | ⚠️ 6782 collected, 18 errors, all missing test-only packages in the venv (`toml`, `numpy`, `asyncpg`, …). v1.7.3 in the same venv: 22 errors |
| 2.2 | Unit                     | `pytest tests/unit -q`                                                     | ✅ 5599 passed; the 4 failures are the flaky `test_sql_metrics.py` mocks, also red at the previous release                                   |
| 2.3 | Authentication, E2E      | `tests/e2e/test_auth_defaults.py` against four servers (see its docstring) | ✅ 15/15 on embedded, 15/15 on DBAPI: password, TLS, trust, allowlist                                                                        |
| 2.4 | Vector projection, E2E   | `tests/e2e/test_vector_projection.py`                                      | ✅ 5/5 on embedded, 5/5 on DBAPI                                                                                                             |
| 2.5 | IPM service, E2E         | `tests/ipm/test_service_start.py` under irispython, inside IRIS            | ✅ 17/17                                                                                                                                     |
| 2.6 | node-postgres            | `pg` 8 against the lab: right/wrong password, TLS on and off               | ✅ as designed; a client with SSL off is refused by a TLS server with `28000` and a message naming `sslmode=require`                         |
| 2.7 | Installed-artifact smoke | build, install the wheel in a clean venv, run `iris-pgwire`                | ✅ no flags: exit 2 with the reason; `--allow-plaintext-password`: right password in, wrong out; SIGTERM stops it                            |
| 2.8 | Container-backed suites  | `pytest tests/protocol tests/contract tests/e2e`                           | ⏭️ not run: their fixtures need `iris-devtester`, which this venv lacks, and its fixture loader errors in setup (051 `research.md` R6)       |

A suite that is red for a reason recorded in §5 is not a gate failure — it is a
known state. A suite that is red for any other reason blocks the tag.

## 3. Release artefacts

| #   | Gate                                              | Command                                         | Status                                                     |
| --- | ------------------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------- |
| 3.1 | CHANGELOG describes every shipped change          | read `CHANGELOG.md` `[2.0.0]`                   | ✅                                                         |
| 3.2 | Version bump matches the change classes           | —                                               | ✅ **2.0.0**: credentials are now required (BREAKING)      |
| 3.3 | Build is reproducible and metadata is valid       | `uv build && twine check dist/*`                | ✅ both artefacts PASSED                                   |
| 3.4 | Wheel contains only the package                   | inspect the wheel                               | ✅ `iris_pgwire/` + dist-info; no SCRAM/OAuth/Wallet files |
| 3.5 | Console script target is not a coroutine function | `pytest tests/unit/test_console_entry_point.py` | ✅                                                         |

## 4. Publish (Tom's action — never automated)

1. `git push origin release/2.0:main` — fast-forwards `origin/main` from v1.7.1 to the release, and
   carries the v1.7.2 and v1.7.3 commits with it.
2. `git push origin v1.7.2 v1.7.3 v2.0.0` — the two tags PyPI has and GitHub lacks, and the release.
3. `twine upload --repository testpypi dist/*`, install from TestPyPI in a clean venv, run
   `iris-pgwire`, then `twine upload dist/*`.
4. GitHub release from `v2.0.0`, with the `[2.0.0]` section as the body.
5. The security note, if and where Tom decides.

## 5. Known red, with cause

These are measured, reproduced at the v1.7.3 tag in a `git worktree`, and not
caused by the commits waiting to be released.

- **The DBAPI backend does no SQL translation.** `DBAPIExecutor.execute_query`
  applies targeted catalog rewrites (array literals, `= ANY`, boolean
  projections, `pg_*` function qualification) and `_translate_placeholders`, but
  never calls the SQL translator or `optimize_vector_query`. So on that backend
  `<=>`, `<#>`, `LIMIT`→`TOP` and identifier normalization do not happen and raw
  PostgreSQL reaches IRIS: SQLCODE -25, `Input ('>) encountered after end of
query`. `tests/conftest.py:692` defaults the test server to
  `PGWIRE_BACKEND_TYPE=dbapi` outside Docker, which is why 22 e2e tests fail,
  including `test_readme_vector_similarity_search` — the README's own example.
  The `IRISExecutor` path does optimize (`iris_executor.py:883`), and the
  optimizer itself is correct in isolation. **This is the release question worth
  answering before 1.8.0**: pgvector operator support is the headline feature,
  and it is absent from one of the two selectable backends.
- **`tests/contract/test_dbapi_executor_contract.py` hangs.** It drives ~100
  sequential queries; each acquires a connection, and once the 8-unit CE pool is
  exhausted every acquisition retries 2s apart, forever. Bound it with
  `--timeout` rather than waiting.
- **`test_code_quality_contract.py` cannot pass.** It asserts all of
  `src/iris_pgwire` is black-clean; `black --check` reports 136 files across the
  repo. Reformatting is its own change — it rewrites pre-existing code and
  swamps any release diff.
- **`tests/protocol/test_type_mapping_repro.py`** — 5 × SQLCODE -110, `Locking
conflict in filing`, reproduced with no locks held in the container.

## 6. CI is not a gate

`.github/workflows/package-quality.yml` runs pyroma, black, ruff, bandit and
pip-audit, and reports failures as `::warning::`. A green check mark there means
the workflow ran, not that the checks passed. `ruff check src/` currently
reports 19 findings. Treat §2 and §3 as the gate.
