#!/usr/bin/env bash
# tests/e2e/test_adbc.py against one target on the pgwire-bench network.
exec docker run --rm --network pgwire-bench -v ~/ws/iris-pgwire:/repo:ro -e PGWIRE_E2E_TARGETS="$1" python:3.12-slim \
  sh -c 'pip install -q adbc-driver-postgresql==1.12.0 pyarrow pytest pytest-asyncio psycopg[binary] 2>&1 | grep -v WARN; cd /repo && python -m pytest -q -p no:cacheprovider --noconftest tests/e2e/test_adbc.py 2>&1 | tail -4'
