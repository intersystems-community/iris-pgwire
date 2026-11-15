"""An isolation level asked for on BEGIN must be treated like one asked for on SET.

`SET TRANSACTION ISOLATION LEVEL ...` is not the only spelling, and it is not the one
psycopg3 sends by default: given `isolation_level` on the connection it emits
`BEGIN ISOLATION LEVEL READ COMMITTED` as a single statement. The original defect —
a level request that never reaches the code that knows which levels IRIS has — was
fixed for `SET` only, so the same request in the spelling clients actually use still
went straight past, unrecorded by `SHOW` and unrefused when unsupported.

Measured on IRIS 2026.1 CE in `iris-pgwire-db`, which is why only the verb is
rewritten and the transaction modes are passed through as the client wrote them:

    BEGIN ISOLATION LEVEL READ COMMITTED                        -> SQLCODE -51
    START TRANSACTION ISOLATION LEVEL READ COMMITTED            -> SQLCODE 0
    START TRANSACTION READ WRITE, ISOLATION LEVEL READ COMMITTED -> SQLCODE 0
    START TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE -> SQLCODE 0
    START TRANSACTION READ ONLY                                  -> SQLCODE 0

IRIS has no `BEGIN` statement at all: -51 is "SQL statement expected", so the
spelling psycopg3 sends cannot be forwarded untouched.
"""

from __future__ import annotations

import pytest

from iris_pgwire._isolation import IsolationMixin
from iris_pgwire.sql_translator.isolation import parse_begin_isolation

# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


class TestParseBeginIsolationSpellings:
    @pytest.mark.parametrize(
        "sql",
        [
            # What psycopg3 sends for a connection with isolation_level set.
            "BEGIN ISOLATION LEVEL READ COMMITTED",
            "BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "BEGIN WORK ISOLATION LEVEL READ COMMITTED",
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "begin isolation level read committed",
            "BEGIN ISOLATION LEVEL READ COMMITTED;",
            "BEGIN   ISOLATION   LEVEL   READ   COMMITTED",
            # Other transaction modes may precede or follow the level.
            "BEGIN READ WRITE, ISOLATION LEVEL READ COMMITTED",
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE",
            "BEGIN ISOLATION LEVEL READ COMMITTED READ WRITE",
        ],
    )
    def test_recognised(self, sql):
        req = parse_begin_isolation(sql)
        assert req is not None, sql
        assert req.level == "read committed"
        assert req.supported is True

    @pytest.mark.parametrize(
        "sql",
        [
            # No level named: these must keep their existing handling untouched.
            "BEGIN",
            "BEGIN TRANSACTION",
            "START TRANSACTION",
            "BEGIN READ WRITE",
            "BEGIN DEFERRABLE",
            "COMMIT",
            "ROLLBACK",
            "SELECT 1",
            "",
            # A SET is the other function's business, not this one's.
            "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
            # An ObjectScript BEGIN block in a statement body is not a transaction start.
            "CREATE PROCEDURE p() BEGIN ISOLATION LEVEL READ COMMITTED END",
        ],
    )
    def test_not_recognised(self, sql):
        assert parse_begin_isolation(sql) is None

    @pytest.mark.parametrize(
        "level_sql, level",
        [
            ("REPEATABLE READ", "repeatable read"),
            ("SERIALIZABLE", "serializable"),
        ],
    )
    def test_unsupported_levels_are_flagged(self, level_sql, level):
        req = parse_begin_isolation(f"BEGIN ISOLATION LEVEL {level_sql}")
        assert req is not None
        assert req.level == level
        assert req.supported is False
        assert req.sqlstate == "0A000"

    def test_read_uncommitted_is_supported(self):
        req = parse_begin_isolation("BEGIN ISOLATION LEVEL READ UNCOMMITTED")
        assert req.supported is True
        assert req.level == "read uncommitted"


class TestTheIrisSpellingOfTheTransactionStart:
    """Only the verb changes. IRIS rejects BEGIN outright (SQLCODE -51).

    Everything after the verb is the client's, because IRIS accepts each mode
    combination measured above and this layer has no business reordering or
    dropping a mode it was not asked about.
    """

    @pytest.mark.parametrize(
        "sql, expected",
        [
            (
                "BEGIN ISOLATION LEVEL READ COMMITTED",
                "START TRANSACTION ISOLATION LEVEL READ COMMITTED",
            ),
            (
                "BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED",
                "START TRANSACTION ISOLATION LEVEL READ COMMITTED",
            ),
            (
                "BEGIN WORK ISOLATION LEVEL READ COMMITTED",
                "START TRANSACTION ISOLATION LEVEL READ COMMITTED",
            ),
            (
                "begin isolation level read committed",
                "START TRANSACTION isolation level read committed",
            ),
            (
                "BEGIN READ WRITE, ISOLATION LEVEL READ COMMITTED",
                "START TRANSACTION READ WRITE, ISOLATION LEVEL READ COMMITTED",
            ),
        ],
    )
    def test_the_begin_verb_becomes_start_transaction(self, sql, expected):
        assert parse_begin_isolation(sql).iris_sql == expected

    @pytest.mark.parametrize(
        "sql",
        [
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE",
        ],
    )
    def test_a_start_transaction_is_already_iris_sql(self, sql):
        """Nothing to rewrite, so nothing is rewritten — measured accepted as-is."""
        assert parse_begin_isolation(sql).iris_sql == sql

    def test_the_word_begin_later_in_the_statement_is_left_alone(self):
        """Only the leading verb is a transaction start; a later BEGIN is data."""
        req = parse_begin_isolation("START TRANSACTION ISOLATION LEVEL READ COMMITTED /* BEGIN */")
        assert req.iris_sql == "START TRANSACTION ISOLATION LEVEL READ COMMITTED /* BEGIN */"

    @pytest.mark.parametrize(
        "sql, tag",
        [
            ("BEGIN ISOLATION LEVEL READ COMMITTED", "BEGIN"),
            ("BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED", "BEGIN"),
            ("BEGIN WORK ISOLATION LEVEL READ COMMITTED", "BEGIN"),
            ("START TRANSACTION ISOLATION LEVEL READ COMMITTED", "START TRANSACTION"),
        ],
    )
    def test_the_tag_is_carried_alongside_the_rewrite(self, sql, tag):
        """Measured on PostgreSQL 16, which answers each verb with its own tag.

        The tag has to be decided here, because by the time the statement is sent
        it says START TRANSACTION whatever the client wrote.
        """
        assert parse_begin_isolation(sql).command_tag == tag


# ---------------------------------------------------------------------------
# The mixin
# ---------------------------------------------------------------------------


class _RecordingExecutor(IsolationMixin):
    """Records what the mixin forwards, and answers as IRIS would on success."""
    # These tests pin the override mechanics against IRIS's own default, READ UNCOMMITTED: the
    # server run with PGWIRE_DEFAULT_ISOLATION=read uncommitted. The READ COMMITTED default of spec
    # 052 US7 is tested in test_default_isolation_config.py.
    default_isolation_level = "read uncommitted"


    def __init__(self, succeed: bool = True):
        self.session_isolation: dict[str, str] = {}
        self.forwarded: list[tuple[str, dict]] = []
        self.succeed = succeed

    async def execute_query(self, sql, params=None, session_id=None, **kwargs):
        self.forwarded.append((sql, kwargs))
        return {
            "success": self.succeed,
            "rows": [],
            "columns": [],
            "row_count": 0,
            # What the normal pipeline answers for the statement actually sent,
            # which after the rewrite is IRIS's spelling rather than the client's.
            "command_tag": "START TRANSACTION",
        }


class TestBeginWithASupportedLevel:
    @pytest.mark.asyncio
    async def test_one_statement_is_forwarded_in_the_iris_spelling(self):
        """Still one statement: it both starts the transaction and sets the level.

        Splitting it into a SET plus a START TRANSACTION would change when the
        transaction begins, so only the verb IRIS does not have is replaced.
        """
        ex = _RecordingExecutor()

        await ex._handle_isolation_statement(
            "BEGIN ISOLATION LEVEL READ COMMITTED", session_id="s1"
        )

        assert [sql for sql, _ in ex.forwarded] == [
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED"
        ]

    @pytest.mark.asyncio
    async def test_the_level_is_recorded_so_show_agrees(self):
        ex = _RecordingExecutor()

        await ex._handle_isolation_statement(
            "BEGIN ISOLATION LEVEL READ COMMITTED", session_id="s1"
        )

        assert ex.get_isolation_level("s1") == "read committed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql, tag",
        [
            # Measured on PostgreSQL 16: the tag follows the verb the client used,
            # and `START TRANSACTION` is a tag PostgreSQL really does send.
            ("BEGIN ISOLATION LEVEL READ COMMITTED", "BEGIN"),
            ("BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED", "BEGIN"),
            ("BEGIN WORK ISOLATION LEVEL READ COMMITTED", "BEGIN"),
            ("START TRANSACTION ISOLATION LEVEL READ COMMITTED", "START TRANSACTION"),
        ],
    )
    async def test_the_tag_is_the_clients_own_verb(self, sql, tag):
        """The rewrite to IRIS's spelling must not be visible in the reply.

        A client that wrote BEGIN gets `BEGIN` even though IRIS was sent
        `START TRANSACTION`; a client that wrote `START TRANSACTION` gets that.
        """
        ex = _RecordingExecutor()

        result = await ex._handle_isolation_statement(sql, session_id="s1")

        assert result["command_tag"] == tag

    @pytest.mark.asyncio
    async def test_a_failed_begin_records_nothing(self):
        ex = _RecordingExecutor(succeed=False)

        await ex._handle_isolation_statement(
            "BEGIN ISOLATION LEVEL READ COMMITTED", session_id="s1"
        )

        assert ex.get_isolation_level("s1") == "read uncommitted"

    @pytest.mark.asyncio
    async def test_recursion_is_stopped(self):
        ex = _RecordingExecutor()

        await ex._handle_isolation_statement(
            "BEGIN ISOLATION LEVEL READ COMMITTED", session_id="s1"
        )

        assert ex.forwarded[0][1]["_skip_isolation"] is True


class TestBeginWithAnUnsupportedLevel:
    @pytest.mark.asyncio
    async def test_the_transaction_does_not_start(self):
        """Refusing after starting the transaction would leave the session mid-transaction."""
        ex = _RecordingExecutor()

        await ex._handle_isolation_statement("BEGIN ISOLATION LEVEL SERIALIZABLE", session_id="s1")

        assert ex.forwarded == []

    @pytest.mark.asyncio
    async def test_the_client_is_told_0a000(self):
        ex = _RecordingExecutor()

        result = await ex._handle_isolation_statement(
            "BEGIN ISOLATION LEVEL SERIALIZABLE", session_id="s1"
        )

        assert result["success"] is False
        assert result["sqlstate"] == "0A000"
        assert "serializable" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_the_refusal_matches_the_set_spelling(self):
        """Same request, two spellings, one answer — or a client can route around it."""
        ex = _RecordingExecutor()

        on_begin = await ex._handle_isolation_statement(
            "BEGIN ISOLATION LEVEL REPEATABLE READ", session_id="s1"
        )
        on_set = await ex._handle_isolation_statement(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ", session_id="s1"
        )

        assert on_begin["sqlstate"] == on_set["sqlstate"]
        assert on_begin["error"] == on_set["error"]


class TestPlainBeginIsUntouched:
    @pytest.mark.asyncio
    async def test_begin_without_a_level_passes_through(self):
        """None here means the existing transaction handling runs, unchanged."""
        ex = _RecordingExecutor()

        assert await ex._handle_isolation_statement("BEGIN", session_id="s1") is None
        assert await ex._handle_isolation_statement("START TRANSACTION", session_id="s1") is None
        assert ex.forwarded == []
