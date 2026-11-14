"""Spec 052: the two server settings for transaction behaviour (FR-024, FR-025).

`PGWIRE_DEFAULT_ISOLATION` is the level a new session starts at; `PGWIRE_TXN_COMPAT` decides only
whether statement shapes with no exact emulation are refused (strict) or run as in 2.0
(permissive). A value outside the accepted ones must stop the server with a message that lists
them, not fall back to a default the operator did not choose.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from iris_pgwire.models.backend_config import BackendConfig


def _config(**kwargs) -> BackendConfig:
    return BackendConfig(backend_type="dbapi", iris_password="SYS", **kwargs)


class TestDefaultIsolation:
    def test_the_default_is_read_committed(self):
        assert _config().default_isolation == "read committed"

    @pytest.mark.parametrize(
        ("given", "stored"),
        [
            ("read committed", "read committed"),
            ("read uncommitted", "read uncommitted"),
            ("READ UNCOMMITTED", "read uncommitted"),
            ("  Read   Committed ", "read committed"),
        ],
    )
    def test_accepted_values_are_normalised(self, given, stored):
        assert _config(default_isolation=given).default_isolation == stored

    @pytest.mark.parametrize("bad", ["serializable", "repeatable read", "dirty", ""])
    def test_anything_else_is_refused_with_the_accepted_values(self, bad):
        with pytest.raises(ValidationError) as excinfo:
            _config(default_isolation=bad)
        message = str(excinfo.value)
        assert "read committed" in message and "read uncommitted" in message

    def test_read_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("PGWIRE_BACKEND_TYPE", "dbapi")
        monkeypatch.setenv("IRIS_PASSWORD", "SYS")
        monkeypatch.setenv("PGWIRE_DEFAULT_ISOLATION", "read uncommitted")
        assert BackendConfig.from_env().default_isolation == "read uncommitted"


class TestTxnCompat:
    def test_the_default_is_strict(self):
        assert _config().txn_compat == "strict"

    @pytest.mark.parametrize(
        ("given", "stored"),
        [("strict", "strict"), ("permissive", "permissive"), ("PERMISSIVE ", "permissive")],
    )
    def test_accepted_values_are_normalised(self, given, stored):
        assert _config(txn_compat=given).txn_compat == stored

    @pytest.mark.parametrize("bad", ["lenient", "off", ""])
    def test_anything_else_is_refused_with_the_accepted_values(self, bad):
        with pytest.raises(ValidationError) as excinfo:
            _config(txn_compat=bad)
        message = str(excinfo.value)
        assert "strict" in message and "permissive" in message

    def test_read_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("PGWIRE_BACKEND_TYPE", "dbapi")
        monkeypatch.setenv("IRIS_PASSWORD", "SYS")
        monkeypatch.setenv("PGWIRE_TXN_COMPAT", "permissive")
        assert BackendConfig.from_env().txn_compat == "permissive"
