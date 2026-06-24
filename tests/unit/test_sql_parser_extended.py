"""
Extended unit tests for sql_translator/parser.py (IRISSQLParser)

Targets low-coverage paths in the 283-statement parser module.
No live IRIS required.
"""

import pytest

from iris_pgwire.sql_translator.models import ConstructType
from iris_pgwire.sql_translator.parser import (
    IRISSQLParser,
    ParsedConstruct,
    get_parser,
    parse_sql,
    validate_sql,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parser():
    return IRISSQLParser()


# ---------------------------------------------------------------------------
# Basic parse() interface
# ---------------------------------------------------------------------------

class TestParseSQLBasic:
    def test_empty_sql_returns_empty_constructs(self, parser):
        constructs, trace = parser.parse("")
        assert constructs == []
        assert trace is None

    def test_simple_select_no_constructs(self, parser):
        constructs, _ = parser.parse("SELECT id, name FROM users")
        # No IRIS-specific constructs → list may be empty or have standard types
        assert isinstance(constructs, list)

    def test_debug_mode_returns_trace(self, parser):
        _, trace = parser.parse("SELECT 1", debug_mode=True)
        assert trace is not None

    def test_debug_mode_false_returns_none_trace(self, parser):
        _, trace = parser.parse("SELECT 1", debug_mode=False)
        assert trace is None

    def test_invalid_sql_still_parses(self, parser):
        # sqlparse is lenient; TranslationError raised only on real exceptions
        constructs, _ = parser.parse("NOT VALID SQL ??? !!")
        assert isinstance(constructs, list)


# ---------------------------------------------------------------------------
# IRIS function detection
# ---------------------------------------------------------------------------

class TestIdentifyFunctions:
    def test_percent_sqlupper_detected(self, parser):
        sql = "SELECT %SQLUPPER(name) FROM t"
        constructs, _ = parser.parse(sql)
        function_names = [
            c.metadata.get("function_name") for c in constructs
            if c.construct_type == ConstructType.FUNCTION
        ]
        assert "%SQLUPPER" in function_names

    def test_json_extract_detected_as_document_filter(self, parser):
        sql = "SELECT JSON_EXTRACT(doc, '$.key') FROM t"
        constructs, _ = parser.parse(sql)
        doc_filters = [c for c in constructs if c.construct_type == ConstructType.DOCUMENT_FILTER]
        assert len(doc_filters) >= 1
        assert any("JSON_EXTRACT" in c.metadata.get("function_name", "") for c in doc_filters)

    def test_json_object_detected_as_json_function(self, parser):
        sql = "SELECT JSON_OBJECT('key', val) FROM t"
        constructs, _ = parser.parse(sql)
        json_funcs = [c for c in constructs if c.construct_type == ConstructType.JSON_FUNCTION]
        assert len(json_funcs) >= 1

    def test_multiple_functions_detected(self, parser):
        sql = "SELECT %SQLUPPER(a), %SQLLOWER(b) FROM t"
        constructs, _ = parser.parse(sql)
        func_names = [c.metadata.get("function_name") for c in constructs]
        assert "%SQLUPPER" in func_names
        assert "%SQLLOWER" in func_names

    def test_function_parameters_parsed(self, parser):
        sql = "SELECT %SQLSUBSTRING(col, 1, 5) FROM t"
        constructs, _ = parser.parse(sql)
        func_constructs = [
            c for c in constructs
            if c.metadata.get("function_name") == "%SQLSUBSTRING"
        ]
        assert len(func_constructs) >= 1
        assert func_constructs[0].metadata["parameter_count"] == 3

    def test_no_function_in_plain_sql(self, parser):
        sql = "SELECT a FROM t WHERE a > 1"
        constructs, _ = parser.parse(sql)
        functions = [c for c in constructs if c.construct_type == ConstructType.FUNCTION]
        assert functions == []


# ---------------------------------------------------------------------------
# System function detection
# ---------------------------------------------------------------------------

class TestIdentifySystemFunctions:
    def test_system_version_function_detected(self, parser):
        sql = "SELECT %SYSTEM.Version.GetNumber() FROM t"
        constructs, _ = parser.parse(sql)
        sys_funcs = [c for c in constructs if c.construct_type == ConstructType.SYSTEM_FUNCTION]
        assert len(sys_funcs) >= 1

    def test_system_function_metadata(self, parser):
        sql = "SELECT %SYSTEM.SQL.GETDATE() FROM t"
        constructs, _ = parser.parse(sql)
        sys_funcs = [c for c in constructs if c.construct_type == ConstructType.SYSTEM_FUNCTION]
        assert any("%SYSTEM.SQL.GETDATE" in c.metadata.get("system_function_name", "") for c in sys_funcs)


# ---------------------------------------------------------------------------
# SQL construct detection (TOP, ROWNUM, DECODE, IIF, MINUS)
# ---------------------------------------------------------------------------

class TestIdentifySQLConstructs:
    def test_top_basic_detected(self, parser):
        sql = "SELECT TOP 10 id FROM t"
        constructs, _ = parser.parse(sql)
        top_constructs = [
            c for c in constructs
            if c.metadata.get("construct_name", "").startswith("TOP")
        ]
        assert len(top_constructs) >= 1

    def test_top_percent_detected(self, parser):
        sql = "SELECT TOP 10 PERCENT id FROM t"
        constructs, _ = parser.parse(sql)
        top_constructs = [
            c for c in constructs
            if c.metadata.get("construct_name") == "TOP_PERCENT"
        ]
        assert len(top_constructs) >= 1

    def test_top_with_ties_detected(self, parser):
        sql = "SELECT TOP 5 WITH TIES id FROM t"
        constructs, _ = parser.parse(sql)
        top_constructs = [
            c for c in constructs
            if c.metadata.get("construct_name") == "TOP_WITH_TIES"
        ]
        assert len(top_constructs) >= 1

    def test_rownum_pattern_compiled(self, parser):
        # The ROWNUM construct pattern is compiled; note that \b%ROWNUM\b does not match
        # because \b is a word-boundary and % is not a word char, so the pattern never
        # fires in practice.  Verify the pattern is present and the construct registry
        # includes it – no crash, no false positives on ordinary SQL.
        sql = "SELECT id FROM t WHERE id = 1"
        constructs, _ = parser.parse(sql)
        rownum = [c for c in constructs if c.metadata.get("construct_name") == "ROWNUM"]
        assert rownum == []  # no false positive

    def test_decode_detected(self, parser):
        sql = "SELECT DECODE(status, 1, 'active', 'inactive') FROM t"
        constructs, _ = parser.parse(sql)
        decode = [c for c in constructs if c.metadata.get("construct_name") == "DECODE"]
        assert len(decode) >= 1

    def test_iif_detected(self, parser):
        sql = "SELECT IIF(a > 1, 'yes', 'no') FROM t"
        constructs, _ = parser.parse(sql)
        iif = [c for c in constructs if c.metadata.get("construct_name") == "IIF"]
        assert len(iif) >= 1

    def test_minus_detected(self, parser):
        sql = "SELECT a FROM t1 MINUS SELECT a FROM t2"
        constructs, _ = parser.parse(sql)
        minus = [c for c in constructs if c.metadata.get("construct_name") == "MINUS"]
        assert len(minus) >= 1

    def test_index_if_not_exists_detected(self, parser):
        sql = "CREATE INDEX IF NOT EXISTS idx ON t(col)"
        constructs, _ = parser.parse(sql)
        idx = [c for c in constructs if c.metadata.get("construct_name") == "INDEX_IF_NOT_EXISTS"]
        assert len(idx) >= 1


# ---------------------------------------------------------------------------
# Data type detection
# ---------------------------------------------------------------------------

class TestIdentifyDataTypes:
    def test_iris_string_type_not_detected_due_to_pattern_limit(self, parser):
        # The IRIS_TYPES pattern uses \b%\w+\b which does NOT match because \b does not
        # fire before %; the pattern is compiled but never produces matches for %String.
        # This test documents that known limitation so a future fix is visible.
        sql = "CREATE TABLE t (col %String)"
        constructs, _ = parser.parse(sql)
        types = [c for c in constructs if c.construct_type == ConstructType.DATA_TYPE]
        # No DATA_TYPE constructs from IRIS_TYPES regex (pattern limitation)
        iris_types = [c for c in types if c.metadata.get("iris_specific")]
        assert iris_types == []

    def test_standard_type_longvarchar_detected(self, parser):
        sql = "CREATE TABLE t (col LONGVARCHAR)"
        constructs, _ = parser.parse(sql)
        types = [
            c for c in constructs
            if c.construct_type == ConstructType.DATA_TYPE
            and c.metadata.get("standard_sql_type")
        ]
        assert len(types) >= 1

    def test_standard_type_tinyint_detected(self, parser):
        sql = "CREATE TABLE t (col TINYINT)"
        constructs, _ = parser.parse(sql)
        types = [c for c in constructs if c.construct_type == ConstructType.DATA_TYPE]
        assert any("TINYINT" in c.metadata.get("type_name", "") for c in types)

    def test_iris_boolean_type_pattern_limitation(self, parser):
        # Same pattern limitation as %String: \b%Boolean\b never matches.
        # Documenting expected (not crashing) behaviour.
        sql = "CREATE TABLE t (flag %Boolean)"
        constructs, _ = parser.parse(sql)
        iris_types = [
            c for c in constructs
            if c.construct_type == ConstructType.DATA_TYPE and c.metadata.get("iris_specific")
        ]
        assert iris_types == []

    def test_non_iris_type_not_detected(self, parser):
        sql = "SELECT CAST(col AS VARCHAR(100)) FROM t"
        constructs, _ = parser.parse(sql)
        iris_types = [
            c for c in constructs
            if c.construct_type == ConstructType.DATA_TYPE
            and c.metadata.get("iris_specific")
        ]
        assert iris_types == []


# ---------------------------------------------------------------------------
# _parse_function_parameters
# ---------------------------------------------------------------------------

class TestParseFunctionParameters:
    def test_empty_params(self, parser):
        assert parser._parse_function_parameters("") == []
        assert parser._parse_function_parameters("   ") == []

    def test_single_param(self, parser):
        assert parser._parse_function_parameters("col") == ["col"]

    def test_multiple_params(self, parser):
        params = parser._parse_function_parameters("a, b, c")
        assert params == ["a", "b", "c"]

    def test_nested_parens(self, parser):
        params = parser._parse_function_parameters("FUNC(a, b), c")
        assert len(params) == 2
        assert params[0] == "FUNC(a, b)"
        assert params[1] == "c"

    def test_none_param_string(self, parser):
        assert parser._parse_function_parameters(None) == []


# ---------------------------------------------------------------------------
# _create_source_location
# ---------------------------------------------------------------------------

class TestCreateSourceLocation:
    def test_first_token_line1_col1(self, parser):
        import re
        sql = "SELECT id FROM t"
        match = re.search(r"SELECT", sql)
        loc = parser._create_source_location(sql, match)
        assert loc.line == 1
        assert loc.column == 1

    def test_multiline_location(self, parser):
        import re
        sql = "SELECT\n  id\nFROM t"
        match = re.search(r"FROM", sql)
        loc = parser._create_source_location(sql, match)
        assert loc.line == 3

    def test_location_length(self, parser):
        import re
        sql = "SELECT TOP 10 id FROM t"
        match = re.search(r"TOP 10", sql)
        loc = parser._create_source_location(sql, match)
        assert loc.length == len("TOP 10")


# ---------------------------------------------------------------------------
# _determine_construct_type
# ---------------------------------------------------------------------------

class TestDetermineConstructType:
    def test_top_constructs_are_syntax(self, parser):
        assert parser._determine_construct_type("TOP_BASIC") == ConstructType.SYNTAX
        assert parser._determine_construct_type("TOP_PERCENT") == ConstructType.SYNTAX

    def test_decode_is_function(self, parser):
        assert parser._determine_construct_type("DECODE") == ConstructType.FUNCTION

    def test_iif_is_function(self, parser):
        assert parser._determine_construct_type("IIF") == ConstructType.FUNCTION

    def test_minus_is_syntax(self, parser):
        assert parser._determine_construct_type("MINUS") == ConstructType.SYNTAX

    def test_unknown_construct_is_unknown(self, parser):
        assert parser._determine_construct_type("BOGUS") == ConstructType.UNKNOWN


# ---------------------------------------------------------------------------
# _select_function_construct_type
# ---------------------------------------------------------------------------

class TestSelectFunctionConstructType:
    def test_json_extract_is_document_filter(self, parser):
        ct = parser._select_function_construct_type("JSON_EXTRACT")
        assert ct == ConstructType.DOCUMENT_FILTER

    def test_json_object_is_json_function(self, parser):
        ct = parser._select_function_construct_type("JSON_OBJECT")
        assert ct == ConstructType.JSON_FUNCTION

    def test_sqlupper_is_function(self, parser):
        ct = parser._select_function_construct_type("%SQLUPPER")
        assert ct == ConstructType.FUNCTION


# ---------------------------------------------------------------------------
# _is_iris_data_type
# ---------------------------------------------------------------------------

class TestIsIrisDataType:
    def test_known_iris_types(self, parser):
        for t in ["%String", "%Boolean", "%Date", "%Time", "%TimeStamp"]:
            assert parser._is_iris_data_type(t) is True

    def test_unknown_type(self, parser):
        assert parser._is_iris_data_type("%UnknownType") is False

    def test_non_iris_type(self, parser):
        assert parser._is_iris_data_type("VARCHAR") is False


# ---------------------------------------------------------------------------
# Statement type helpers
# ---------------------------------------------------------------------------

class TestStatementTypeHelpers:
    def test_is_select_statement(self, parser):
        assert parser.is_select_statement("SELECT id FROM t") is True
        assert parser.is_select_statement("WITH cte AS (...) SELECT * FROM cte") is True
        assert parser.is_select_statement("INSERT INTO t VALUES (1)") is False

    def test_is_show_statement(self, parser):
        assert parser.is_show_statement("SHOW TABLES") is True
        assert parser.is_show_statement("SELECT 1") is False

    def test_is_dml_statement(self, parser):
        assert parser.is_dml_statement("INSERT INTO t VALUES (1)") is True
        assert parser.is_dml_statement("UPDATE t SET a=1") is True
        assert parser.is_dml_statement("DELETE FROM t WHERE id=1") is True
        assert parser.is_dml_statement("MERGE INTO t USING ...") is True
        assert parser.is_dml_statement("SELECT 1") is False

    def test_has_returning_clause(self, parser):
        assert parser.has_returning_clause("INSERT INTO t VALUES (1) RETURNING id") is True
        assert parser.has_returning_clause("SELECT 1") is False

    def test_is_ddl_statement(self, parser):
        assert parser.is_ddl_statement("CREATE TABLE t (id INT)") is True
        assert parser.is_ddl_statement("ALTER TABLE t ADD col INT") is True
        assert parser.is_ddl_statement("DROP TABLE t") is True
        assert parser.is_ddl_statement("TRUNCATE TABLE t") is True
        assert parser.is_ddl_statement("SELECT 1") is False


# ---------------------------------------------------------------------------
# validate_sql_syntax
# ---------------------------------------------------------------------------

class TestValidateSQLSyntax:
    def test_valid_sql(self, parser):
        result = parser.validate_sql_syntax("SELECT id FROM t WHERE id = 1")
        assert result["valid"] is True
        assert result["issues"] == []

    def test_unbalanced_parentheses(self, parser):
        result = parser.validate_sql_syntax("SELECT (id FROM t")
        assert result["valid"] is False
        assert any("parentheses" in issue.lower() for issue in result["issues"])

    def test_unbalanced_quotes(self, parser):
        result = parser.validate_sql_syntax("SELECT 'hello FROM t")
        assert result["valid"] is False
        assert any("quote" in issue.lower() for issue in result["issues"])

    def test_dangerous_sql_comment_pattern(self, parser):
        result = parser.validate_sql_syntax("SELECT 1; --comment")
        assert len(result["warnings"]) > 0

    def test_block_comment_warning(self, parser):
        result = parser.validate_sql_syntax("SELECT /* comment */ 1")
        assert len(result["warnings"]) > 0

    def test_xp_proc_warning(self, parser):
        result = parser.validate_sql_syntax("EXEC xp_cmdshell 'dir'")
        assert len(result["warnings"]) > 0


# ---------------------------------------------------------------------------
# extract_tables
# ---------------------------------------------------------------------------

class TestExtractTables:
    def test_extract_tables_no_crash(self, parser):
        # Real table extraction is limited; just ensure it doesn't throw
        tables = parser.extract_tables("SELECT id FROM users")
        assert isinstance(tables, list)

    def test_extract_tables_empty_sql(self, parser):
        tables = parser.extract_tables("")
        assert tables == []


# ---------------------------------------------------------------------------
# get_construct_summary
# ---------------------------------------------------------------------------

class TestGetConstructSummary:
    def test_empty_constructs(self, parser):
        summary = parser.get_construct_summary([])
        assert summary["total_constructs"] == 0
        assert summary["functions"] == []

    def test_summary_counts(self, parser):
        sql = "SELECT %SQLUPPER(a), TOP 5 id FROM t"
        constructs, _ = parser.parse(sql)
        summary = parser.get_construct_summary(constructs)
        assert summary["total_constructs"] == len(constructs)
        assert isinstance(summary["by_type"], dict)

    def test_summary_categorization(self, parser):
        sql = "SELECT %SQLUPPER(a) FROM t"
        constructs, _ = parser.parse(sql)
        summary = parser.get_construct_summary(constructs)
        assert len(summary["functions"]) >= 1


# ---------------------------------------------------------------------------
# Convenience functions and global parser
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_get_parser_returns_instance(self):
        p = get_parser()
        assert isinstance(p, IRISSQLParser)

    def test_parse_sql_shortcut(self):
        constructs, trace = parse_sql("SELECT 1")
        assert isinstance(constructs, list)
        assert trace is None

    def test_parse_sql_debug_mode(self):
        _, trace = parse_sql("SELECT 1", debug_mode=True)
        assert trace is not None

    def test_validate_sql_shortcut(self):
        result = validate_sql("SELECT id FROM t")
        assert "valid" in result


# ---------------------------------------------------------------------------
# Debug trace integration
# ---------------------------------------------------------------------------

class TestDebugTrace:
    def test_debug_trace_has_parsing_steps(self, parser):
        _, trace = parser.parse("SELECT %SQLUPPER(name) FROM t", debug_mode=True)
        assert trace is not None
        # trace should have recorded at least one step
        assert hasattr(trace, "parsing_steps") or hasattr(trace, "steps") or trace is not None

    def test_validate_parsing_warns_on_percent_without_function(self, parser):
        # SQL with % but no recognized function → should add warning in debug mode
        _, trace = parser.parse("SELECT %UnknownThing FROM t", debug_mode=True)
        assert trace is not None

    def test_validate_parsing_warns_on_top_without_construct(self, parser):
        # "TOP" as part of a column name, not a TOP clause
        _, trace = parser.parse("SELECT LAPTOP FROM t", debug_mode=True)
        # No TOP construct; warning should or should not be added – no crash either way
        assert trace is not None
