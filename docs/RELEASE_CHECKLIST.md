# Release Checklist

Companion to [RELEASING.md](RELEASING.md), which says _how_ to publish. This
says _whether to_. Every gate below names the command that decides it, so the
answer is measured rather than recalled.

Status column meaning: measured on 2026-09-20 against HEAD `c73a167`
(5 commits past v1.7.3) with `iris-pgwire-db` (IRIS 2026.1 CE, 8 licence units)
running under `DOCKER_CONTEXT=orbstack`.

## 1. Preconditions

| #   | Gate                                              | Command                                                    | Status                                                                                |
| --- | ------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 1.1 | Working tree clean                                | `git status --short`                                       | ✅                                                                                    |
| 1.2 | `origin/main` contains what PyPI already has      | `git log --oneline origin/main..HEAD`                      | ❌ `origin/main` is **v1.7.1**; PyPI is **1.7.3**; 8 local commits unpushed           |
| 1.3 | Every push target in the release docs exists      | `git remote -v`                                            | ❌ RELEASING.md:25,34 and DEVELOPMENT.md:20 push to `community`; only `origin` exists |
| 1.4 | Container up (no skip-by-default)                 | `DOCKER_CONTEXT=orbstack docker ps \| grep iris-pgwire-db` | ✅                                                                                    |
| 1.5 | One version source, and it is the one hatch reads | `grep -rn "1\.7\." src/ pyproject.toml .github/`           | ✅ only `src/iris_pgwire/__init__.py:9`                                               |

## 2. Test gates

Run each in its **own** pytest process. Container-backed suites contaminate one
another inside a single process, and the CE licence pool (8 units) is shared, so
two suites at once produce "Unable to allocate a license" rather than failures
that mean anything.

| #   | Gate                     | Command                                                           | Status                                                                                                                            |
| --- | ------------------------ | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 2.1 | Whole tree **collects**  | `pytest tests/ --collect-only -q`                                 | ✅ 7128 collected, 0 errors (was 5 errors / 0 tests run before `c73a167`)                                                         |
| 2.2 | Unit                     | `pytest tests/unit -q`                                            | ✅ 5821 passed, 10 skipped                                                                                                        |
| 2.3 | Pinned limitations       | `pytest -m pinned_limitation tests/protocol tests/integration -q` | ✅ 4 passed                                                                                                                       |
| 2.4 | Protocol                 | `pytest tests/protocol -q`                                        | ⚠️ `test_isolation_e2e.py` 37 passed; `test_type_mapping_repro.py` 5 failures (`SQLCODE -110`), pre-existing at v1.7.3            |
| 2.5 | Contract                 | `pytest tests/contract -q --timeout=45`                           | ❌ cannot complete — 8 failures then a hang in `test_dbapi_executor_contract.py` on CE licence exhaustion. Pre-existing at v1.7.3 |
| 2.6 | E2E                      | `pytest tests/e2e -q --timeout=90`                                | ❌ 22 failures + 2 timeouts, no summary. Pre-existing at v1.7.3 — see §5                                                          |
| 2.7 | Installed-artifact smoke | build, install the wheel in a clean venv, run `iris-pgwire`       | ✅ as of `62d5b85`; broken in **published 1.7.3** (§5)                                                                            |

A suite that is red for a reason recorded in §5 is not a gate failure — it is a
known state. A suite that is red for any other reason blocks the tag.

## 3. Release artefacts

| #   | Gate                                                      | Command                                         | Status                              |
| --- | --------------------------------------------------------- | ----------------------------------------------- | ----------------------------------- |
| 3.1 | CHANGELOG `[Unreleased]` describes every shipped change   | read `CHANGELOG.md`                             | ✅                                  |
| 3.2 | Version bump matches the change classes in `[Unreleased]` | —                                               | ⏳ **1.8.0** — two BREAKING entries |
| 3.3 | Build is reproducible and metadata is valid               | `uv build && twine check dist/*`                | ✅ both artefacts PASSED            |
| 3.4 | Wheel contains only the package                           | inspect the wheel                               | ✅ `iris_pgwire/` + dist-info       |
| 3.5 | Console script target is not a coroutine function         | `pytest tests/unit/test_console_entry_point.py` | ✅                                  |

## 4. Publish (Tom's action — never automated)

1. `git push origin main` — resolves 1.2, and only then is the tag reachable.
2. `git push origin v1.8.0` after `git tag -a v1.8.0`.
3. Push the tags PyPI already has but GitHub does not: `v1.7.2`, `v1.7.3`.
4. `twine upload --repository testpypi dist/*`, install from TestPyPI in a clean
   venv, run `iris-pgwire`, then `twine upload dist/*`.
5. GitHub release from the tag, with the `[Unreleased]` section as the body.

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
