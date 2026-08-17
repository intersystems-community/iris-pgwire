"""The Python encoder and the installed PG_ARRAY must agree, against real IRIS.

`tests/unit/test_pg_array.py` checks `encode_pg_array` against `decode_pg_array`
— a Python mirror of what the ObjectScript function does. A mirror is not the
thing: if the two drift, every unit test still passes and the symptom is a query
returning the wrong rows.

That is the same gap that made the previous implementation's `$LIST` parity
tests worthless — they compared against the real encoder but skipped whenever
the driver class was unavailable, which was every unit run. So this one drives
the **function actually installed in IRIS** and refuses to skip quietly: if IRIS
is reachable but PG_ARRAY is missing, that is a failure, not a skip.

Marked `integration`; needs the IRIS instance and the catalog functions
installed (the server installs them at startup).
"""

from __future__ import annotations

import os

import pytest

from iris_pgwire.sql_translator.pg_array import encode_pg_array

pytestmark = [pytest.mark.integration, pytest.mark.iris_integration]


def _connect():
    dbapi = pytest.importorskip("iris.dbapi", reason="intersystems-irispython not installed")
    try:
        return dbapi.connect(
            hostname=os.environ.get("IRIS_HOST", "localhost"),
            port=int(os.environ.get("IRIS_PORT", "1972")),
            namespace=os.environ.get("IRIS_NAMESPACE", "USER"),
            username=os.environ.get("IRIS_USER", "_SYSTEM"),
            password=os.environ.get("IRIS_PASSWORD", "SYS"),
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"IRIS not reachable: {exc}")


@pytest.fixture(scope="module")
def cursor():
    conn = _connect()
    try:
        yield conn.cursor()
    finally:
        conn.close()


# Every value here has broken a previous implementation of this encoding.
ROUND_TRIP_CASES = [
    pytest.param([], id="empty"),
    pytest.param([""], id="empty-string"),
    pytest.param(["public"], id="one"),
    pytest.param(["public", "pg_catalog"], id="two"),
    pytest.param(["has,comma"], id="comma-broke-listfromstring"),
    pytest.param(['has"quote'], id="quote"),
    pytest.param(["has:colon", "has|bar"], id="our-own-delimiters"),
    pytest.param(["10:fake"], id="looks-like-a-length-prefix"),
    pytest.param(["4|2:xx"], id="looks-like-a-whole-encoded-array"),
    pytest.param(["café"], id="latin1"),
    pytest.param(["x😀"], id="astral-broke-codepoint-lengths"),
    pytest.param(["😀😀", "a"], id="astral-only"),
    pytest.param(["a" * 3000], id="long"),
    pytest.param(["a", None, "b"], id="with-null"),
    pytest.param([f"v{i}" for i in range(200)], id="many"),
]


class TestEncoderMatchesInstalledFunction:
    @pytest.mark.parametrize("values", ROUND_TRIP_CASES)
    def test_iris_rebuilds_exactly_what_python_encoded(self, cursor, values):
        """Ask IRIS to take the list apart again and compare element by element.

        $LISTGET, not $LIST: $LIST throws <NULL VALUE> on a null element, so it
        would report a NULL in the array as a decoder failure.
        """
        encoded = encode_pg_array(values)

        cursor.execute("SELECT $LISTLENGTH(PGWire.PG_ARRAY(?))", (encoded,))
        length = cursor.fetchone()[0] or 0
        assert length == len(values), (
            f"encoder wrote {len(values)} elements, PG_ARRAY rebuilt {length} — "
            "the Python encoder and the ObjectScript decoder have drifted"
        )

        for index, expected in enumerate(values, start=1):
            cursor.execute("SELECT $LISTGET(PGWire.PG_ARRAY(?), ?)", (encoded, index))
            actual = cursor.fetchone()[0]
            # IRIS SQL spells the empty string as $CHAR(0) and a true
            # ObjectScript "" reads back out as NULL, so the empty string has
            # three spellings by the time it reaches here. They are one logical
            # value; what actually has to hold for it is the membership test
            # below.
            if expected == "":
                assert actual in ("", "\x00", None), (
                    f"element {index}: encoded '', IRIS rebuilt {actual!r}"
                )
                continue
            assert actual == expected, (
                f"element {index}: encoded {expected!r}, IRIS rebuilt {actual!r}"
            )

    @pytest.mark.parametrize("values", ROUND_TRIP_CASES)
    def test_membership_matches_for_every_case(self, cursor, values):
        """The round trip is not enough — %INLIST has to match on the result."""
        if not values or all(v is None for v in values):
            pytest.skip("nothing to match against")

        target = next(v for v in values if v is not None)
        cursor.execute(
            "SELECT 1 FROM (SELECT ? AS k) WHERE k %INLIST PGWire.PG_ARRAY(?)",
            (target, encode_pg_array(values)),
        )
        assert cursor.fetchall(), f"{target!r} is in the array but %INLIST did not match it"

    def test_an_empty_string_element_matches_an_empty_column_value(self, cursor):
        """The case the Python mirror could never have caught.

        IRIS SQL stores an empty string as $CHAR(0). A zero-length element built
        as a true ObjectScript "" is a different value and matches nothing — no
        error, just a row that never comes back.
        """
        cursor.execute(
            "SELECT 1 FROM (SELECT ? AS k) WHERE k %INLIST PGWire.PG_ARRAY(?)",
            ("", encode_pg_array([""])),
        )
        assert cursor.fetchall(), "an empty-string element did not match an empty column value"


class TestInstalledFunctionIsStrict:
    """Malformed input must error, not return a partial list.

    A length prefix wrong by one slides the parse. Returning whatever fell out
    would be a query answering with the wrong rows and no indication.
    """

    @pytest.mark.parametrize(
        "encoded",
        [
            pytest.param("6:public", id="missing-count"),
            pytest.param("1|6", id="truncated-element"),
            pytest.param("1|60:public", id="overruns"),
            pytest.param("2|6:public", id="fewer-than-declared"),
            pytest.param("1|6:public5:other", id="more-than-declared"),
        ],
    )
    def test_malformed_input_raises(self, cursor, encoded):
        with pytest.raises(Exception) as caught:  # noqa: PT011 — driver-specific type
            cursor.execute("SELECT $LISTLENGTH(PGWire.PG_ARRAY(?))", (encoded,))
            cursor.fetchall()
        assert "PG_ARRAY" in str(caught.value), (
            f"expected PG_ARRAY's own error, got: {str(caught.value)[:200]}"
        )

    def test_a_one_character_corruption_is_caught(self, cursor):
        corrupted = encode_pg_array(["public", "pg_catalog"]).replace("6:public", "5:public", 1)
        with pytest.raises(Exception):  # noqa: B017, PT011 — any refusal is correct
            cursor.execute("SELECT $LISTLENGTH(PGWire.PG_ARRAY(?))", (corrupted,))
            cursor.fetchall()

    @pytest.mark.parametrize("encoded", ["", None])
    def test_null_and_empty_build_an_empty_list_rather_than_erroring(self, cursor, encoded):
        """Describe prepares the statement with a NULL bound; that must not throw."""
        cursor.execute("SELECT $LISTLENGTH(PGWire.PG_ARRAY(?))", (encoded,))
        assert (cursor.fetchone()[0] or 0) == 0


class TestInstalledFunctionsArePresent:
    """A missing function is a failure, not a reason to skip.

    The whole point of the installer is that these exist wherever the server
    has started. Skipping here would hide exactly the regression it guards.
    """

    @pytest.mark.parametrize(
        ("probe", "expected"),
        [
            ("SELECT PGWire.PG_OID('sqluser:table:customer')", 3909377549),
            ("SELECT PGWire.PG_OID('sqluser:table:orderline')", 1128014727),
            ("SELECT PGWire.PG_PUBLIC_SCHEMA()", "public"),
        ],
    )
    def test_function_is_installed_and_correct(self, cursor, probe, expected):
        cursor.execute(probe)
        assert cursor.fetchone()[0] == expected

    def test_pg_oid_matches_the_python_generator(self, cursor):
        """The two paths coexist during migration; divergence joins nothing."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        generator = OIDGenerator()
        for name in ("customer", "orderline", "customerorder"):
            cursor.execute("SELECT PGWire.PG_OID(?)", (f"sqluser:table:{name}",))
            assert cursor.fetchone()[0] == generator.get_oid("table", name, "sqluser")
