# Isolation suite (track 4): tests/e2e/isolation, against PGWire and PostgreSQL 16.
#
# `make isolation` starts a fresh PGWire server from this checkout (DBAPI backend, trust auth, on
# ISOLATION_PORT, against IRIS on IRIS_PORT), runs the suite in its own pytest process, stops the
# server, and prints the Hermitage table drawn from build/isolation-results.jsonl.
#
# A fresh server matters: some checks leave pooled IRIS connections damaged, which is part of what
# they measure, and a long-lived server carries that into the next run. Only one PGWire server at
# a time on a Community Edition IRIS; the target refuses to start if ISOLATION_PORT is taken.
#
# The reference PostgreSQL 16 must be up: iris-pgwire-pgref on 127.0.0.1:55433
# (`docker start iris-pgwire-pgref`).

PYTHON ?= .venv/bin/python
ISOLATION_PORT ?= 5442
IRIS_PORT ?= 2992
ISOLATION_RESULTS ?= build/isolation-results.jsonl
ISOLATION_LOG ?= build/isolation-server.log
# Extra environment for the server (e.g. PGWIRE_TXN_COMPAT=permissive), and a marker that selects
# only the checks written for that server. With a marker set, pytest's exit 5 ("no tests
# selected") counts as success, so a target whose checks do not exist yet still passes.
ISOLATION_SERVER_ENV ?=
ISOLATION_MARK ?=

.PHONY: isolation isolation-permissive isolation-read-uncommitted isolation-server isolation-table

isolation:
	@mkdir -p build
	@if nc -z 127.0.0.1 $(ISOLATION_PORT) 2>/dev/null; then \
		echo "port $(ISOLATION_PORT) is in use; stop that server first" >&2; exit 1; fi
	rm -f $(ISOLATION_RESULTS)
	$(ISOLATION_SERVER_ENV) IRIS_PORT=$(IRIS_PORT) PYTHONPATH=src $(PYTHON) tests/e2e/_auth_server.py $(ISOLATION_PORT) trust dbapi \
		> $(ISOLATION_LOG) 2>&1 & echo $$! > build/isolation-server.pid; \
	for i in $$(seq 1 60); do nc -z 127.0.0.1 $(ISOLATION_PORT) 2>/dev/null && break; sleep 1; done; \
	ISOLATION_SUITE=1 ISOLATION_RESULTS=$(ISOLATION_RESULTS) ISOLATION_MARK="$(ISOLATION_MARK)" ISOLATION_LOG=$(ISOLATION_LOG) \
	ISOLATION_PGWIRE_DSN="host=127.0.0.1 port=$(ISOLATION_PORT) user=_SYSTEM password=SYS dbname=USER sslmode=disable" \
		$(PYTHON) -m pytest tests/e2e/isolation -m "isolation$(if $(ISOLATION_MARK), and $(ISOLATION_MARK))" \
		-p no:cacheprovider -p no:randomly -q -rs; \
	status=$$?; kill $$(cat build/isolation-server.pid) 2>/dev/null; \
	if [ -n "$(ISOLATION_MARK)" ] && [ $$status -eq 5 ]; then status=0; fi; \
	$(PYTHON) scripts/render_hermitage_table.py $(ISOLATION_RESULTS); exit $$status

# The checks that need a server started with non-default settings (spec 052). Run after
# `make isolation`, never at the same time: one PGWire server at a time on a CE IRIS.
isolation-permissive:
	$(MAKE) isolation ISOLATION_SERVER_ENV="PGWIRE_TXN_COMPAT=permissive" ISOLATION_MARK=permissive \
		ISOLATION_RESULTS=build/isolation-results-permissive.jsonl ISOLATION_LOG=build/isolation-server-permissive.log

isolation-read-uncommitted:
	$(MAKE) isolation ISOLATION_SERVER_ENV="PGWIRE_DEFAULT_ISOLATION='read uncommitted'" ISOLATION_MARK=default_isolation \
		ISOLATION_RESULTS=build/isolation-results-read-uncommitted.jsonl ISOLATION_LOG=build/isolation-server-read-uncommitted.log

isolation-table:
	$(PYTHON) scripts/render_hermitage_table.py $(ISOLATION_RESULTS)

# A server on its own, for running single test modules by hand.
isolation-server:
	IRIS_PORT=$(IRIS_PORT) PYTHONPATH=src $(PYTHON) tests/e2e/_auth_server.py $(ISOLATION_PORT) trust dbapi
